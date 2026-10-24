"""Home Assistant MQTT Bridge for Generac PWRcell (v3).

Connects to the external Home Assistant MQTT broker, publishes MQTT Discovery
configurations for user-selected entities with modern HA standards, streams state
updates, and handles incoming commands for writable controls.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from .client import PwrcellClient
from .config import AppConfig, MqttConfig
from .ha import (
    generate_discovery_payload,
    get_default_ha_config_path,
    get_recommended_field_keys,
    is_field_selected,
    load_ha_config,
    qualify_legacy_ha_config,
)
from .state import StateField, SUNSPEC_SENTINELS

logger = logging.getLogger(__name__)

DEFAULT_HA_PUBLISHED_TOPICS_FILE = ".ha_published_topics.json"


def get_default_published_topics_path() -> Path:
    ha_cfg_path = get_default_ha_config_path()
    return ha_cfg_path.parent / DEFAULT_HA_PUBLISHED_TOPICS_FILE


def format_state_value(value: Any, precision: Optional[int] = None) -> str:
    """Format a state value for MQTT publishing, ensuring float precision is clean and avoiding scientific notation."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        try:
            if "e" in value.lower():
                val_float = float(value)
                return format_state_value(val_float, precision)
        except ValueError:
            pass
        return value
    if isinstance(value, (int, float)):
        import math
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return "nan"
        if abs(value) > 1e12 or int(value) in SUNSPEC_SENTINELS:
            return ""
        if precision is not None:
            if precision == 0:
                return str(int(round(value)))
            return f"{value:.{precision}f}"
        if isinstance(value, float):
            rounded = round(value, 4)
            if rounded == int(rounded):
                return str(int(rounded))
            return f"{rounded:.4f}".rstrip("0").rstrip(".")
        return str(value)
    return str(value)


class HomeAssistantBridge:
    """Bridges the PWRcell StateStore to Home Assistant via MQTT Discovery."""

    def __init__(
        self,
        client: PwrcellClient,
        mqtt_config: Optional[MqttConfig] = None,
        discovery_prefix: str = "homeassistant",
        base_topic: str = "pwrcell",
        published_topics_path: Optional[Path] = None,
    ):
        self.client = client
        self.mqtt_config = mqtt_config or (client.config.mqtt if client.config else MqttConfig())
        self.discovery_prefix = discovery_prefix
        self.base_topic = base_topic
        self.published_topics_path = (
            published_topics_path if published_topics_path is not None else get_default_published_topics_path()
        )
        self.selected_field_keys: List[str] = []
        self._selected_set: set[str] = set()
        self._command_topic_to_field: Dict[str, Any] = {}
        self._published_discovery_topics: set[str] = set()
        self._active_compound_keys: set[str] = set()
        self._mqttc: Optional[mqtt.Client] = None
        self._lock = threading.RLock()
        self._running = False

    def start(self):
        """Connect to external Home Assistant MQTT broker and publish discovery."""
        with self._lock:
            if self._running:
                return

            # Load selected entities from ha_config.yaml (or default seed), fallback to recommended
            raw_keys = load_ha_config()
            self.selected_field_keys = qualify_legacy_ha_config(raw_keys, self.client.state)
            if not self.selected_field_keys:
                logger.info("No ha_config.yaml found, using recommended default entities")
                self.selected_field_keys = get_recommended_field_keys(self.client.state)
            self._selected_set = set(self.selected_field_keys)
            if hasattr(self.client, "poller") and self.client.poller:
                self.client.poller.sync_ha_selected_fields(self.selected_field_keys)

            if not self.mqtt_config or not self.mqtt_config.host:
                logger.warning("No Home Assistant MQTT broker configured in config.yaml")
                return

            client_id = self.mqtt_config.client_name or os.environ.get("HOSTNAME") or "pwrcell_ha_bridge"
            self._mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            if self.mqtt_config.username:
                self._mqttc.username_pw_set(self.mqtt_config.username, self.mqtt_config.password)

            # Set Last Will and Testament (LWT) for automatic offline status in HA
            status_topic = f"{self.base_topic}/status"
            self._mqttc.will_set(status_topic, payload="offline", qos=1, retain=True)

            self._mqttc.on_connect = self._on_connect
            self._mqttc.on_message = self._on_message
            self._mqttc.on_disconnect = self._on_disconnect

            logger.info("Connecting to Home Assistant MQTT broker on %s:%d as client '%s'", self.mqtt_config.host, self.mqtt_config.port, client_id)
            self._mqttc.loop_start()
            try:
                self._mqttc.connect(self.mqtt_config.host, self.mqtt_config.port)
            except Exception as e:
                logger.warning("Initial connection to Home Assistant MQTT broker failed (%s); client loop will retry", e)

            # Subscribe to StateStore updates and compound view updates
            self.client.state.subscribe(self._on_field_update)
            self.client.state.subscribe_compound(self._on_compound_update)
            self._running = True

    def stop(self):
        """Disconnect from Home Assistant MQTT broker and publish offline status."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            mqttc = self._mqttc
            self._mqttc = None

        if mqttc:
            try:
                # Publish graceful offline status
                mqttc.publish(f"{self.base_topic}/status", "offline", qos=1, retain=True)
                mqttc.loop_stop()
                mqttc.disconnect()
            except Exception as e:
                logger.debug("Error disconnecting HA MQTT: %s", e)
            logger.info("Home Assistant bridge stopped")

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: ReasonCode,
        properties: Properties,
    ):
        logger.info("Connected to Home Assistant MQTT broker: %s", reason_code)
        # Publish bridge online status
        client.publish(f"{self.base_topic}/status", "online", qos=1, retain=True)
        self.publish_discovery()

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.DisconnectFlags,
        reason_code: ReasonCode,
        properties: Properties,
    ):
        logger.warning("Disconnected from Home Assistant MQTT broker: %s", reason_code)

    def reload_config_and_republish(self):
        """Reload selected entities from ha_config.yaml and republish discovery."""
        raw_keys = load_ha_config()
        self.selected_field_keys = qualify_legacy_ha_config(raw_keys, self.client.state)
        self._selected_set = set(self.selected_field_keys)
        if hasattr(self.client, "poller") and self.client.poller:
            self.client.poller.sync_ha_selected_fields(self.selected_field_keys)
        self.publish_discovery()

    def _load_persisted_published_topics(self) -> set[str]:
        """Load previously published discovery topics from disk."""
        if not self.published_topics_path or not self.published_topics_path.exists():
            return set()
        try:
            with open(self.published_topics_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
                if isinstance(data, dict) and "published_topics" in data:
                    return set(data["published_topics"])
        except Exception as e:
            logger.warning("Could not read persisted published topics from %s: %s", self.published_topics_path, e)
        return set()

    def _save_persisted_published_topics(self, topics: set[str]):
        """Save currently published discovery topics to disk."""
        if not self.published_topics_path:
            return
        try:
            self.published_topics_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.published_topics_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(sorted(list(topics)), f, indent=2)
            temp_path.replace(self.published_topics_path)
        except Exception as e:
            logger.warning("Could not write persisted published topics to %s: %s", self.published_topics_path, e)

    def publish_discovery(self):
        """Publish discovery configurations for all selected entities."""
        if not self._mqttc:
            return

        if not self.selected_field_keys:
            raw_keys = load_ha_config()
            self.selected_field_keys = qualify_legacy_ha_config(raw_keys, self.client.state)
            if not self.selected_field_keys:
                self.selected_field_keys = get_recommended_field_keys(self.client.state)
            self._selected_set = set(self.selected_field_keys)

        gateway = self.client.state.get_beacon() or self.client.state.get_inverter()
        published_count = 0

        with self._lock:
            self._command_topic_to_field.clear()
            self._active_compound_keys.clear()
            current_discovery_topics: set[str] = set()

            for dev in self.client.state.devices.values():
                sn_clean = dev.serial_number.strip().upper()
                # 1. Publish selected compound fields
                for c_view in self.client.state.get_compound_views(dev.serial_number):
                    if is_field_selected(c_view.key, dev.serial_number, self.selected_field_keys, c_view.mqtt_key):
                        self._active_compound_keys.add(f"{sn_clean}:{c_view.key}")
                        payload_info = generate_discovery_payload(
                            c_view,
                            dev,
                            gateway_device=gateway,
                            base_topic=self.base_topic,
                            ha_prefix=self.discovery_prefix,
                        )
                        config_topic = payload_info["config_topic"]
                        config_payload = json.dumps(payload_info["payload"])
                        self._mqttc.publish(config_topic, config_payload, retain=True)
                        current_discovery_topics.add(config_topic)
                        published_count += 1

                        if payload_info.get("old_sensor_topic"):
                            self._mqttc.publish(payload_info["old_sensor_topic"], "", retain=True)

                        cmd_topic = payload_info.get("command_topic")
                        if cmd_topic:
                            self._command_topic_to_field[cmd_topic] = c_view
                            self._mqttc.subscribe(cmd_topic)

                        if c_view.latest_value is not None:
                            val_str = format_state_value(c_view.latest_value, payload_info.get("suggested_display_precision"))
                            self._mqttc.publish(payload_info["state_topic"], val_str, retain=True)

                # 2. Publish selected raw fields
                # Pre-populate metadata for any selected fields not yet polled
                for sel_key in self.selected_field_keys:
                    if ":" in sel_key:
                        target_sn, f_path = sel_key.split(":", 1)
                        if target_sn.strip().upper() != sn_clean:
                            continue
                    else:
                        f_path = sel_key
                        if not f_path.startswith(f"{dev.device_type}."):
                            continue

                    if f_path not in dev.fields and not f_path.startswith(f"{dev.device_type}.compound."):
                        self.client.state.ensure_field_definition(dev.serial_number, f_path)

                for f_key, field in list(dev.fields.items()):
                    if field.compound_key and f"{sn_clean}:{field.compound_key}" in self._active_compound_keys:
                        # Suppress duplicate raw field because its compound view is active.
                        # Clear any previously retained discovery and state topics for this suppressed field.
                        payload_info = generate_discovery_payload(
                            field,
                            dev,
                            gateway_device=gateway,
                            base_topic=self.base_topic,
                            ha_prefix=self.discovery_prefix,
                        )
                        self._mqttc.publish(payload_info["config_topic"], "", retain=True)
                        if payload_info.get("state_topic"):
                            self._mqttc.publish(payload_info["state_topic"], "", retain=True)
                        continue

                    if is_field_selected(f_key, dev.serial_number, self.selected_field_keys):
                        payload_info = generate_discovery_payload(
                            field,
                            dev,
                            gateway_device=gateway,
                            base_topic=self.base_topic,
                            ha_prefix=self.discovery_prefix,
                        )

                        config_topic = payload_info["config_topic"]
                        config_payload = json.dumps(payload_info["payload"])

                        # Publish discovery configuration (retained)
                        self._mqttc.publish(config_topic, config_payload, retain=True)
                        current_discovery_topics.add(config_topic)
                        published_count += 1

                        if payload_info.get("old_sensor_topic"):
                            self._mqttc.publish(payload_info["old_sensor_topic"], "", retain=True)

                        # If field is writable, subscribe to its command topic
                        cmd_topic = payload_info.get("command_topic")
                        if cmd_topic:
                            self._command_topic_to_field[cmd_topic] = field
                            self._mqttc.subscribe(cmd_topic)

                        # Publish initial state if value exists
                        if field.value is not None:
                            self._publish_field_state(field, payload_info, retain=True)

            # Unpublish deselected entities by sending empty retained payload to remove from Home Assistant
            previously_published = self._published_discovery_topics | self._load_persisted_published_topics()
            removed_topics = previously_published - current_discovery_topics
            for rem_topic in removed_topics:
                logger.info("Removing deselected/orphaned HA MQTT Discovery entity at %s", rem_topic)
                self._mqttc.publish(rem_topic, "", retain=True)

            self._published_discovery_topics = current_discovery_topics
            self._save_persisted_published_topics(current_discovery_topics)

        logger.info("Published %d Home Assistant MQTT Discovery entities (removed %d)", published_count, len(removed_topics))

    def _publish_field_state(self, field: StateField, payload_info: Dict[str, Any], retain: bool = False):
        """Publish state and optional JSON attributes for a field."""
        if field.value is None:
            return

        state_topic = payload_info["state_topic"]
        if getattr(field, "is_bitfield", False):
            flags = field.active_flags if hasattr(field, "active_flags") else (field.value if isinstance(field.value, list) else [])
            state_str = ", ".join(flags) if flags else "NONE"
            self._mqttc.publish(state_topic, state_str, retain=retain)
            attr_topic = payload_info.get("attributes_topic")
            if attr_topic:
                attr_payload = {
                    "raw_value": field.raw_value,
                    "hex_value": f"0x{field.raw_value:04X}" if isinstance(field.raw_value, int) else None,
                    "active_flags": flags,
                    "flag_count": len(flags),
                    "flags": field.flags_dict or {},
                }
                self._mqttc.publish(attr_topic, json.dumps(attr_payload), retain=retain)
        else:
            precision = payload_info.get("suggested_display_precision")
            self._mqttc.publish(state_topic, format_state_value(field.value, precision), retain=retain)

    def _is_field_suppressed_by_compound(self, field: StateField) -> bool:
        """Check if a raw field is suppressed because its unified compound view is active."""
        if not field.compound_key or not field.device_sn:
            return False
        clean_sn = field.device_sn.strip().upper()
        comp_id = f"{clean_sn}:{field.compound_key}"
        with self._lock:
            if comp_id in self._active_compound_keys:
                return True
        c_views = self.client.state.get_compound_views(field.device_sn)
        for c_view in c_views:
            if c_view.key == field.compound_key:
                if is_field_selected(c_view.key, field.device_sn, self.selected_field_keys, getattr(c_view, "mqtt_key", None)):
                    with self._lock:
                        self._active_compound_keys.add(comp_id)
                    return True
        return False

    def _on_field_update(self, field: StateField):
        """Called when a field value updates in the StateStore."""
        if not self._mqttc or field.value is None:
            return
        if not is_field_selected(field.key, field.device_sn, self.selected_field_keys):
            return
        if self._is_field_suppressed_by_compound(field):
            return

        dev = self.client.state.devices.get(field.device_sn)
        if not dev:
            return

        gateway = self.client.state.get_beacon() or self.client.state.get_inverter()
        payload_info = generate_discovery_payload(
            field,
            dev,
            gateway_device=gateway,
            base_topic=self.base_topic,
            ha_prefix=self.discovery_prefix,
        )

        config_topic = payload_info["config_topic"]
        if config_topic not in self._published_discovery_topics:
            config_payload = json.dumps(payload_info["payload"])
            self._mqttc.publish(config_topic, config_payload, retain=True)
            self._published_discovery_topics.add(config_topic)
            if payload_info.get("old_sensor_topic"):
                self._mqttc.publish(payload_info["old_sensor_topic"], "", retain=True)
            cmd_topic = payload_info.get("command_topic")
            if cmd_topic:
                with self._lock:
                    self._command_topic_to_field[cmd_topic] = field
                self._mqttc.subscribe(cmd_topic)

        self._publish_field_state(field, payload_info, retain=False)

    def _on_compound_update(self, c_view: Any):
        """Called when a compound view updates from either MQTT push or Modbus poll."""
        if not self._mqttc or c_view.latest_value is None:
            return
        if not is_field_selected(c_view.key, c_view.device_sn, self.selected_field_keys, getattr(c_view, "mqtt_key", None)):
            return
        clean_sn = c_view.device_sn.strip().upper()
        with self._lock:
            self._active_compound_keys.add(f"{clean_sn}:{c_view.key}")
        dev = self.client.state.devices.get(c_view.device_sn)
        if not dev:
            return
        gateway = self.client.state.get_beacon() or self.client.state.get_inverter()
        payload_info = generate_discovery_payload(
            c_view,
            dev,
            gateway_device=gateway,
            base_topic=self.base_topic,
            ha_prefix=self.discovery_prefix,
        )

        config_topic = payload_info["config_topic"]
        if config_topic not in self._published_discovery_topics:
            config_payload = json.dumps(payload_info["payload"])
            self._mqttc.publish(config_topic, config_payload, retain=True)
            self._published_discovery_topics.add(config_topic)
            if payload_info.get("old_sensor_topic"):
                self._mqttc.publish(payload_info["old_sensor_topic"], "", retain=True)
            cmd_topic = payload_info.get("command_topic")
            if cmd_topic:
                with self._lock:
                    self._command_topic_to_field[cmd_topic] = c_view
                self._mqttc.subscribe(cmd_topic)

        state_topic = payload_info["state_topic"]
        precision = payload_info.get("suggested_display_precision")
        self._mqttc.publish(state_topic, format_state_value(c_view.latest_value, precision))

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage):
        """Handle incoming command messages on subscribed command topics."""
        topic = msg.topic
        payload_str = msg.payload.decode("utf-8").strip()
        logger.info("Received command on %s: %s", topic, payload_str)

        with self._lock:
            target_field = self._command_topic_to_field.get(topic)

        if not target_field:
            logger.warning("No registered field for command topic %s", topic)
            return

        # Offload blocking Modbus write operation to worker thread to prevent freezing Paho's network loop
        threading.Thread(
            target=self._execute_command_async,
            args=(target_field.key, payload_str),
            daemon=True,
            name=f"HACommand_{target_field.key}",
        ).start()

    def _execute_command_async(self, field_key: str, payload_str: str):
        try:
            confirmed_val = self.client.controls.write_field(field_key, payload_str)
            logger.info("Executed command for %s: confirmed=%s", field_key, confirmed_val)
        except Exception as e:
            logger.error("Failed executing command for %s: %s", field_key, e)

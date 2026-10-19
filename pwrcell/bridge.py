"""Home Assistant MQTT Bridge for Generac PWRcell (v3).

Connects to the external Home Assistant MQTT broker, publishes MQTT Discovery
configurations for user-selected entities with modern HA standards, streams state
updates, and handles incoming commands for writable controls.
"""

from __future__ import annotations

import json
import logging
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
    get_recommended_field_keys,
    load_ha_config,
)
from .state import StateField

logger = logging.getLogger(__name__)


class HomeAssistantBridge:
    """Bridges the PWRcell StateStore to Home Assistant via MQTT Discovery."""

    def __init__(
        self,
        client: PwrcellClient,
        mqtt_config: Optional[MqttConfig] = None,
        discovery_prefix: str = "homeassistant",
        base_topic: str = "pwrcell",
    ):
        self.client = client
        self.mqtt_config = mqtt_config or (client.config.mqtt if client.config else MqttConfig())
        self.discovery_prefix = discovery_prefix
        self.base_topic = base_topic
        self.selected_field_keys: List[str] = []
        self._selected_set: set[str] = set()
        self._command_topic_to_field: Dict[str, Any] = {}
        self._published_discovery_topics: set[str] = set()
        self._mqttc: Optional[mqtt.Client] = None
        self._lock = threading.Lock()
        self._running = False

    def start(self):
        """Connect to external Home Assistant MQTT broker and publish discovery."""
        with self._lock:
            if self._running:
                return
            self._running = True

            # Load selected entities from ha_config.yaml, fallback to recommended
            self.selected_field_keys = load_ha_config()
            if not self.selected_field_keys:
                logger.info("No ha_config.yaml found, using recommended default entities")
                self.selected_field_keys = get_recommended_field_keys(self.client.state)
            self._selected_set = set(self.selected_field_keys)

            if not self.mqtt_config or not self.mqtt_config.host:
                logger.warning("No Home Assistant MQTT broker configured in config.yaml")
                return

            client_id = self.mqtt_config.client_name or "pwrcell_ha_bridge"
            self._mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            if self.mqtt_config.username:
                self._mqttc.username_pw_set(self.mqtt_config.username, self.mqtt_config.password)

            # Set Last Will and Testament (LWT) for automatic offline status in HA
            status_topic = f"{self.base_topic}/status"
            self._mqttc.will_set(status_topic, payload="offline", qos=1, retain=True)

            self._mqttc.on_connect = self._on_connect
            self._mqttc.on_message = self._on_message
            self._mqttc.on_disconnect = self._on_disconnect

            logger.info("Connecting to Home Assistant MQTT broker on %s:%d", self.mqtt_config.host, self.mqtt_config.port)
            self._mqttc.loop_start()
            try:
                self._mqttc.connect(self.mqtt_config.host, self.mqtt_config.port)
            except Exception as e:
                logger.warning("Initial connection to Home Assistant MQTT broker failed (%s); client loop will retry", e)

            # Subscribe to StateStore updates and compound view updates
            self.client.state.subscribe(self._on_field_update)
            self.client.state.subscribe_compound(self._on_compound_update)

    def stop(self):
        """Disconnect from Home Assistant MQTT broker and publish offline status."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._mqttc:
                try:
                    # Publish graceful offline status
                    self._mqttc.publish(f"{self.base_topic}/status", "offline", qos=1, retain=True)
                    self._mqttc.loop_stop()
                    self._mqttc.disconnect()
                except Exception as e:
                    logger.debug("Error disconnecting HA MQTT: %s", e)
                self._mqttc = None
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
        self.selected_field_keys = load_ha_config()
        self._selected_set = set(self.selected_field_keys)
        self.publish_discovery()

    def publish_discovery(self):
        """Publish discovery configurations for all selected entities."""
        if not self._mqttc:
            return

        gateway = self.client.state.get_beacon() or self.client.state.get_inverter()
        published_count = 0

        with self._lock:
            self._command_topic_to_field.clear()
            current_discovery_topics: set[str] = set()

            for dev in self.client.state.devices.values():
                # 1. Publish selected compound fields
                for c_view in self.client.state.get_compound_views(dev.serial_number):
                    if c_view.key in self.selected_field_keys:
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

                        cmd_topic = payload_info.get("command_topic")
                        if cmd_topic:
                            self._command_topic_to_field[cmd_topic] = c_view
                            self._mqttc.subscribe(cmd_topic)

                        if c_view.latest_value is not None:
                            self._mqttc.publish(payload_info["state_topic"], str(c_view.latest_value), retain=True)

                # 2. Publish selected raw fields
                for f_key, field in dev.fields.items():
                    if f_key in self.selected_field_keys:
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

                        # If field is writable, subscribe to its command topic
                        cmd_topic = payload_info.get("command_topic")
                        if cmd_topic:
                            self._command_topic_to_field[cmd_topic] = field
                            self._mqttc.subscribe(cmd_topic)

                        # Publish initial state if value exists
                        if field.value is not None:
                            self._publish_field_state(field, payload_info, retain=True)

            # Unpublish deselected entities by sending empty retained payload to remove from Home Assistant
            removed_topics = self._published_discovery_topics - current_discovery_topics
            for rem_topic in removed_topics:
                logger.debug("Removing deselected HA MQTT Discovery entity at %s", rem_topic)
                self._mqttc.publish(rem_topic, "", retain=True)

            self._published_discovery_topics = current_discovery_topics

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
            self._mqttc.publish(state_topic, str(field.value), retain=retain)

    def _on_field_update(self, field: StateField):
        """Called when a field value updates in the StateStore."""
        if not self._mqttc or field.value is None or field.key not in self._selected_set:
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
        self._publish_field_state(field, payload_info, retain=False)

    def _on_compound_update(self, c_view: Any):
        """Called when a compound view updates from either MQTT push or Modbus poll."""
        if not self._mqttc:
            return
        if c_view.key in self._selected_set and c_view.latest_value is not None:
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
            state_topic = payload_info["state_topic"]
            self._mqttc.publish(state_topic, str(c_view.latest_value))

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

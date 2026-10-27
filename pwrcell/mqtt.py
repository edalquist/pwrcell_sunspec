"""Push MQTT Telemetry Engine for Generac PWRcell.

Connects to the PWRcell internal MQTT broker (typically port 1883 over SSH tunnel),
subscribes to `/energy_recordset_live`, decodes Protocol Buffer telemetry, and
dispatches live channel updates without any Modbus polling overhead.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

try:
    import paho.mqtt.client as mqtt
    from paho.mqtt.properties import Properties
    from paho.mqtt.reasoncodes import ReasonCode
except ImportError:
    mqtt = None
    Properties = None
    ReasonCode = None

try:
    from google.protobuf import text_format
    from google.protobuf.unknown_fields import UnknownFieldSet
    from .protos import energy_record_set_pb2
except ImportError:
    text_format = None
    UnknownFieldSet = None
    energy_record_set_pb2 = None

from .tunnel import TunnelConfig

logger = logging.getLogger(__name__)


@dataclass
class ChannelTelemetry:
    """Parsed real-time metric from a ChannelSample protobuf."""
    channel: int
    channel_type: int
    channel_type_name: str
    real_power_w: float
    voltage_v: float
    imported_energy_ws: int
    exported_energy_ws: int
    device_id: str
    device_type: int
    soc: Optional[float] = None
    soh: Optional[float] = None
    real_power_source_max_w: float = 0.0
    real_power_sink_max_w: float = 0.0


@dataclass
class LiveTelemetrySnapshot:
    """High-frequency telemetry snapshot from EnergyRecordSet."""
    timestamp: float
    system_mode: int
    system_mode_name: str
    inverter_state: int
    inverter_state_name: str = "UNKNOWN"
    grid_power_w: float = 0.0
    solar_power_w: float = 0.0
    load_power_w: float = 0.0
    battery_power_w: float = 0.0
    battery_soc: Optional[float] = None
    battery_soh: Optional[float] = None
    inverter_id: str = ""
    system_family: str = ""
    gateway_id: str = ""
    gateway_type: str = ""
    channels: Dict[int, ChannelTelemetry] = field(default_factory=dict)


if energy_record_set_pb2 is not None:
    _CH_ALIAS = {
        "NET": "NET_GRID",
        "GENERATION": "GENERATION_SOLAR",
        "CONSUMPTION": "CONSUMPTION_LOAD",
        "STORAGE": "STORAGE_BATTERY",
        "UNKNOWN_CHANNEL": "UNKNOWN",
    }
    CHANNEL_TYPE_NAMES = {
        v.number: _CH_ALIAS.get(v.name, v.name)
        for v in energy_record_set_pb2.ChannelType.DESCRIPTOR.values
    }
    PROTO_SYSTEM_MODE_NAMES = {
        v.number: ("UNKNOWN" if v.name == "UNKNOWN_SYSTEM_MODE" else v.name)
        for v in energy_record_set_pb2.SystemMode.DESCRIPTOR.values
    }
    INVERTER_STATE_NAMES = {
        v.number: (v.name[15:] if v.name.startswith("INVERTER_STATE_") else v.name)
        for v in energy_record_set_pb2.InverterState.DESCRIPTOR.values
    }
else:
    CHANNEL_TYPE_NAMES = {}
    PROTO_SYSTEM_MODE_NAMES = {}
    INVERTER_STATE_NAMES = {}

SYSTEM_MODE_NAMES = PROTO_SYSTEM_MODE_NAMES


class MqttClient:
    """Internal MQTT push client for PWRcell high-frequency telemetry."""

    def __init__(self, tunnel_config: TunnelConfig):
        self.__tunnel_ip = tunnel_config.host or "127.0.0.1"
        self.__tunnel_port = tunnel_config.mqtt_port or 1883
        self.__tunnel_manager = getattr(tunnel_config, "manager", None)
        self.__callbacks: List[Callable[[energy_record_set_pb2.EnergyRecordSet], None]] = []
        self.__snapshot_callbacks: List[Callable[[LiveTelemetrySnapshot], None]] = []
        self.__energy_recordset_live: Optional[energy_record_set_pb2.EnergyRecordSet] = None
        self.__latest_snapshot: Optional[LiveTelemetrySnapshot] = None
        self.__unrecognized_topics: Dict[str, int] = {}
        self.__mqttc: Optional[mqtt.Client] = None
        self._connected_port: Optional[int] = None
        self._reconnecting: bool = False
        self._stopping: bool = False
        self.__lock = threading.RLock()

    @property
    def port(self) -> int:
        if self.__tunnel_manager:
            if hasattr(self.__tunnel_manager, "get_config"):
                cfg = self.__tunnel_manager.get_config()
                if cfg and getattr(cfg, "mqtt_port", None):
                    return cfg.mqtt_port
            if getattr(self.__tunnel_manager, "mqtt_port", None):
                return self.__tunnel_manager.mqtt_port
        return self.__tunnel_port

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    def start(self):
        with self.__lock:
            if self.__mqttc is not None:
                return
            self._stopping = False
            self.__mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            self.__mqttc.on_connect = self.__mqtt_on_connect
            self.__mqttc.on_message = self.__mqtt_on_message
            self.__mqttc.on_disconnect = self.__mqtt_disconnect

            self.__mqttc.loop_start()
            target_port = self.port
            self._connected_port = target_port
            logger.info("Connecting to internal PWRcell MQTT on %s:%s", self.__tunnel_ip, target_port)
            try:
                self.__mqttc.connect(self.__tunnel_ip, target_port)
            except Exception as e:
                logger.warning("Initial connection to internal PWRcell MQTT failed (%s); client loop will retry", e)
                try:
                    self.__mqttc.connect_async(self.__tunnel_ip, target_port)
                except Exception:
                    pass

    def stop(self):
        with self.__lock:
            if self.__mqttc is None:
                return
            mqttc = self.__mqttc
            self.__mqttc = None
            self._stopping = True

        try:
            mqttc.loop_stop()
            mqttc.disconnect()
        except Exception as e:
            logger.debug("Error disconnecting MQTT: %s", e)

    def register_callback(self, callback: Callable[[energy_record_set_pb2.EnergyRecordSet], None]):
        """Register a callback for raw protobuf record sets."""
        with self.__lock:
            self.__callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[energy_record_set_pb2.EnergyRecordSet], None]):
        """Unregister a callback for raw protobuf record sets."""
        with self.__lock:
            if callback in self.__callbacks:
                self.__callbacks.remove(callback)

    def register_snapshot_callback(self, callback: Callable[[LiveTelemetrySnapshot], None]):
        """Register a callback for parsed telemetry snapshots."""
        with self.__lock:
            self.__snapshot_callbacks.append(callback)

    def unregister_snapshot_callback(self, callback: Callable[[LiveTelemetrySnapshot], None]):
        """Unregister a callback for parsed telemetry snapshots."""
        with self.__lock:
            if callback in self.__snapshot_callbacks:
                self.__snapshot_callbacks.remove(callback)

    def get_energy_record_set_live(self) -> Optional[energy_record_set_pb2.EnergyRecordSet]:
        with self.__lock:
            return self.__energy_recordset_live

    def get_latest_snapshot(self) -> Optional[LiveTelemetrySnapshot]:
        with self.__lock:
            return self.__latest_snapshot

    def get_unrecognized_topics(self) -> List[str]:
        with self.__lock:
            return list(self.__unrecognized_topics.keys())

    def get_unrecognized_proto_fields(self) -> List[Dict[str, Any]]:
        with self.__lock:
            erl = self.__energy_recordset_live
            topics = list(self.__unrecognized_topics.keys())
        return inspect_unrecognized_proto_fields(erl, topics)

    def __mqtt_on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: ReasonCode,
        properties: Properties,
    ):
        logger.info("PWRcell internal MQTT connected: %s", reason_code)
        # Subscribe only to live protobuf telemetry recordset topics
        client.subscribe([("+/energy_recordset_live", 0), ("/energy_recordset_live", 0)])

    def __mqtt_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.DisconnectFlags,
        reason_code: ReasonCode,
        properties: Properties,
    ):
        logger.warning("PWRcell internal MQTT disconnected: %s", reason_code)
        if getattr(self, "_stopping", False) or self.__mqttc is None:
            return

        if self.__tunnel_manager:
            with self.__lock:
                if self._reconnecting:
                    return
                self._reconnecting = True
                old_port = self._connected_port or self.__tunnel_port

            def _reconnect_bg():
                try:
                    reconnected = self.__tunnel_manager.ensure_active()
                    if reconnected:
                        new_port = self.port
                        with self.__lock:
                            if self.__mqttc and not getattr(self, "_stopping", False) and new_port != old_port:
                                logger.info(
                                    "Tunnel port changed (%s -> %s); pointing internal MQTT client to port %s",
                                    old_port,
                                    new_port,
                                    new_port,
                                )
                                self._connected_port = new_port
                                try:
                                    self.__mqttc.disconnect()
                                except Exception:
                                    pass
                                try:
                                    self.__mqttc.connect_async(self.__tunnel_ip, new_port)
                                except Exception as e:
                                    logger.warning("Failed reconnecting internal MQTT to %s:%s: %s", self.__tunnel_ip, new_port, e)
                finally:
                    with self.__lock:
                        self._reconnecting = False

            threading.Thread(target=_reconnect_bg, daemon=True, name="MqttTunnelReconnect").start()

    def __mqtt_on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage):
        logger.debug("PWRcell MQTT msg on %s (%d bytes)", msg.topic, len(msg.payload))

        if msg.topic.endswith("/energy_recordset_live"):
            try:
                erl = energy_record_set_pb2.EnergyRecordSet()
                erl.ParseFromString(msg.payload)

                unknown_fields = UnknownFieldSet(erl)
                if unknown_fields:
                    logger.debug("Unknown fields in EnergyRecordSet: %s", unknown_fields)

                snapshot = self._parse_snapshot(erl)

                with self.__lock:
                    self.__energy_recordset_live = erl
                    self.__latest_snapshot = snapshot
                    callbacks = list(self.__callbacks)
                    snapshot_cbs = list(self.__snapshot_callbacks)

                for cb in callbacks:
                    try:
                        cb(erl)
                    except Exception as e:
                        logger.error("Error in MQTT record callback: %s", e)

                for cb in snapshot_cbs:
                    try:
                        cb(snapshot)
                    except Exception as e:
                        logger.error("Error in MQTT snapshot callback: %s", e)

            except Exception as e:
                logger.error("Failed to parse EnergyRecordSet from %s: %s", msg.topic, e)
        else:
            with self.__lock:
                if len(self.__unrecognized_topics) < 500 or msg.topic in self.__unrecognized_topics:
                    self.__unrecognized_topics[msg.topic] = len(msg.payload)
            logger.debug("Received unhandled PWRcell topic: %s", msg.topic)

    @classmethod
    def _parse_snapshot(cls, erl: energy_record_set_pb2.EnergyRecordSet) -> LiveTelemetrySnapshot:
        """Extract a structured LiveTelemetrySnapshot from an EnergyRecordSet protobuf."""
        rec = erl.energyRecord[0] if erl.energyRecord else None
        ts = rec.currentTimestamp if rec else 0.0
        sys_mode = rec.sysMode if rec else 0
        inverter_state = int(rec.inverterState) if rec else 0

        inverter_id = erl.inverterId or ""
        fam_name = ""
        if erl.systemFamily != energy_record_set_pb2.SYSTEM_FAMILY_UNSPECIFIED:
            fam_name = energy_record_set_pb2.SystemFamily.Name(erl.systemFamily) if hasattr(energy_record_set_pb2, "SystemFamily") else str(erl.systemFamily)
        gw_id = ""
        gw_type = ""
        if erl.HasField("gatewayInfo"):
            gw_id = erl.gatewayInfo.gateway_id
            gw_type = energy_record_set_pb2.GatewayType.Name(erl.gatewayInfo.gateway_type) if hasattr(energy_record_set_pb2, "GatewayType") else str(erl.gatewayInfo.gateway_type)

        snapshot = LiveTelemetrySnapshot(
            timestamp=ts,
            system_mode=sys_mode,
            system_mode_name=SYSTEM_MODE_NAMES.get(sys_mode, f"MODE_{sys_mode}"),
            inverter_state=inverter_state,
            inverter_state_name=INVERTER_STATE_NAMES.get(inverter_state, f"STATE_{inverter_state}"),
            inverter_id=inverter_id,
            system_family=fam_name,
            gateway_id=gw_id,
            gateway_type=gw_type,
            channels={},
        )

        if not rec:
            return snapshot

        for ch in rec.channel:
            ch_type_name = CHANNEL_TYPE_NAMES.get(ch.channelType, f"TYPE_{ch.channelType}")
            power_w = float(ch.realPower_Wf) if ch.realPower_Wf != 0 else float(ch.realPower_W)
            is_storage = (
                (energy_record_set_pb2 is not None and (
                    ch.deviceType == energy_record_set_pb2.BATTERY
                    or ch.channelType in (energy_record_set_pb2.STORAGE, energy_record_set_pb2.STORAGE_AC)
                ))
                or ch.channelType == 4
            )
            soc_val = float(ch.soc) if (is_storage or ch.soc != 0) else None
            soh_val = float(ch.soh) if ch.soh > 0.0 else None

            ch_telemetry = ChannelTelemetry(
                channel=ch.channel,
                channel_type=ch.channelType,
                channel_type_name=ch_type_name,
                real_power_w=power_w,
                voltage_v=float(ch.voltage_V),
                imported_energy_ws=ch.importedEnergy_Ws,
                exported_energy_ws=ch.exportedEnergy_Ws,
                device_id=ch.deviceId,
                device_type=ch.deviceType,
                soc=soc_val,
                soh=soh_val,
                real_power_source_max_w=float(ch.realPowerSourceMax_W),
                real_power_sink_max_w=float(ch.realPowerSinkMax_W),
            )
            snapshot.channels[ch.channel] = ch_telemetry

            if ch.channelType == energy_record_set_pb2.NET:
                snapshot.grid_power_w = power_w
            elif ch.channelType == energy_record_set_pb2.GENERATION:
                snapshot.solar_power_w = power_w
            elif ch.channelType == energy_record_set_pb2.CONSUMPTION:
                snapshot.load_power_w = power_w
            elif ch.channelType == energy_record_set_pb2.STORAGE:
                snapshot.battery_power_w = power_w
                if soc_val is not None:
                    snapshot.battery_soc = soc_val
                if soh_val is not None:
                    snapshot.battery_soh = soh_val

        return snapshot


def inspect_unrecognized_proto_fields(
    erl: Optional[energy_record_set_pb2.EnergyRecordSet],
    unrecognized_topics: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Scan raw protobuf message from MQTT for unknown fields, unmapped channels, and unhandled fields.
    
    Used during the compare operation to ensure full visibility into any data on the MQTT bus
    that has not been correlated or recognized.
    """
    findings: List[Dict[str, Any]] = []
    if not erl:
        return findings

    # 1. Protobuf Unknown Fields (present on wire but not defined in .proto schema)
    def _scan_unknown_fields(msg, location: str):
        try:
            ufs = UnknownFieldSet(msg)
            for f in ufs:
                findings.append({
                    "category": "WIRE_UNKNOWN_FIELD",
                    "location": location,
                    "field_number": f.field_number,
                    "wire_type": f.wire_type,
                    "value": f.data,
                    "description": f"Wire field #{f.field_number} (wire type {f.wire_type}) not defined in proto schema",
                })
        except Exception as e:
            logger.debug("Error checking unknown fields on %s: %s", location, e)

    _scan_unknown_fields(erl, "EnergyRecordSet")
    if erl.HasField("gatewayInfo"):
        _scan_unknown_fields(erl.gatewayInfo, "EnergyRecordSet.gatewayInfo")

    # Standard mapped channel types across all Generac configurations
    STANDARD_MAPPED_CHANNELS = {
        energy_record_set_pb2.NET,
        energy_record_set_pb2.GENERATION,
        energy_record_set_pb2.CONSUMPTION,
        energy_record_set_pb2.STORAGE,
        energy_record_set_pb2.INVERTER_OUTPUT,
        energy_record_set_pb2.STORAGE_AC,
        energy_record_set_pb2.GENERATION_AC,
    }

    # 2. Check records and channel samples
    for r_idx, rec in enumerate(erl.energyRecord):
        loc_rec = f"EnergyRecord[{r_idx}]"
        _scan_unknown_fields(rec, loc_rec)

        if rec.acConversionChecksum != 0:
            findings.append({
                "category": "UNMAPPED_FIELD",
                "location": loc_rec,
                "field_name": "acConversionChecksum",
                "value": rec.acConversionChecksum,
                "description": f"AC conversion integrity checksum: {rec.acConversionChecksum}",
            })

        for ch in rec.channel:
            ch_type_name = CHANNEL_TYPE_NAMES.get(ch.channelType, f"TYPE_{ch.channelType}")
            loc_ch = f"Channel {ch.channel} ({ch_type_name})"
            _scan_unknown_fields(ch, f"{loc_rec}.channel[{ch.channel}]")

            # Check if non-standard or unmapped channel type
            if ch.channelType not in STANDARD_MAPPED_CHANNELS:
                findings.append({
                    "category": "UNMAPPED_CHANNEL",
                    "location": loc_ch,
                    "field_name": "channelType",
                    "value": f"{ch_type_name} ({ch.channelType})",
                    "description": f"Unmapped channel {ch.channel} ({ch_type_name}): realPower={ch.realPower_W} W, voltage={ch.voltage_V} V, deviceId={ch.deviceId}",
                })

            # Check unmapped point fields on channels
            if ch.reactivePower_VAR != 0:
                findings.append({
                    "category": "UNMAPPED_FIELD",
                    "location": loc_ch,
                    "field_name": "reactivePower_VAR",
                    "value": f"{ch.reactivePower_VAR} VAR",
                    "description": f"Reactive power: {ch.reactivePower_VAR} VAR",
                })
            if ch.isRevenueGrade:
                findings.append({
                    "category": "UNMAPPED_FIELD",
                    "location": loc_ch,
                    "field_name": "isRevenueGrade",
                    "value": True,
                    "description": "Revenue grade metering flag enabled",
                })
            if ch.deltaExportedEnergy_Ws != 0:
                findings.append({
                    "category": "UNMAPPED_FIELD",
                    "location": loc_ch,
                    "field_name": "deltaExportedEnergy_Ws",
                    "value": f"{ch.deltaExportedEnergy_Ws} Ws",
                    "description": f"Delta exported energy: {ch.deltaExportedEnergy_Ws} Ws",
                })
            if ch.deltaImportedEnergy_Ws != 0:
                findings.append({
                    "category": "UNMAPPED_FIELD",
                    "location": loc_ch,
                    "field_name": "deltaImportedEnergy_Ws",
                    "value": f"{ch.deltaImportedEnergy_Ws} Ws",
                    "description": f"Delta imported energy: {ch.deltaImportedEnergy_Ws} Ws",
                })
            if len(ch.anomalyCodeList) > 0:
                anomalies = [str(a) for a in ch.anomalyCodeList if a != 0]
                if anomalies:
                    findings.append({
                        "category": "ANOMALY_CODE",
                        "location": loc_ch,
                        "field_name": "anomalyCodeList",
                        "value": ", ".join(anomalies),
                        "description": f"Anomaly code list: {', '.join(anomalies)}",
                    })

    # 4. Unrecognized MQTT topics
    if unrecognized_topics:
        for top in unrecognized_topics:
            findings.append({
                "category": "UNRECOGNIZED_TOPIC",
                "location": "MQTT Bus",
                "field_name": "topic",
                "value": top,
                "description": f"Non-standard telemetry topic on internal broker: {top}",
            })

    return findings


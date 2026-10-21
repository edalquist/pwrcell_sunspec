"""Utility to purge Home Assistant MQTT discovery topics published by PWRcell SunSpec."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import paho.mqtt.client as mqtt

from .bridge import get_default_published_topics_path
from .config import AppConfig, MqttConfig
from .ha import ORIGIN_INFO

logger = logging.getLogger(__name__)


def is_pwrcell_origin(payload_data: Dict[str, Any], match_exact: bool = False) -> bool:
    """Check if the payload origin matches PWRcell SunSpec."""
    origin = payload_data.get("origin")
    if not isinstance(origin, dict):
        return False

    if match_exact:
        return origin == ORIGIN_INFO

    # Matches name 'PWRcell SunSpec'
    return origin.get("name") == ORIGIN_INFO["name"]


def purge_pwrcell_discovery_topics(
    broker_host: str = "127.0.0.1",
    broker_port: int = 1883,
    username: Optional[str] = None,
    password: Optional[str] = None,
    discovery_prefix: str = "homeassistant",
    timeout: float = 4.0,
    dry_run: bool = False,
    match_exact_origin: bool = False,
    clear_cache: bool = True,
) -> List[str]:
    """Scan and delete all retained MQTT discovery topics from PWRcell SunSpec."""
    discovered_entries: List[Tuple[str, Dict[str, Any]]] = []
    purged_topics: List[str] = []

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="pwrcell_discovery_cleaner",
    )
    if username:
        client.username_pw_set(username=username, password=password)

    last_msg_time = time.time()

    def on_message(_client, _userdata, msg):
        nonlocal last_msg_time
        last_msg_time = time.time()
        topic = msg.topic
        if not topic.endswith("/config"):
            return
        if not msg.payload:
            return
        try:
            payload_str = msg.payload.decode("utf-8")
            data = json.loads(payload_str)
        except Exception:
            return

        if is_pwrcell_origin(data, match_exact=match_exact_origin):
            discovered_entries.append((topic, data))

    client.on_message = on_message

    print(f"Connecting to MQTT broker at {broker_host}:{broker_port}...")
    try:
        client.connect(broker_host, broker_port, keepalive=30)
    except Exception as e:
        print(f"Failed to connect to MQTT broker {broker_host}:{broker_port}: {e}", file=sys.stderr)
        return []

    client.loop_start()

    sub_pattern = f"{discovery_prefix}/#"
    print(f"Subscribing to {sub_pattern} to discover retained configuration topics...")
    client.subscribe(sub_pattern, qos=1)

    # Allow time to collect retained discovery messages
    start_time = time.time()
    quiet_threshold = 1.0  # seconds of silence after at least one message
    while time.time() - start_time < timeout:
        time.sleep(0.2)
        if discovered_entries and (time.time() - last_msg_time > quiet_threshold):
            break

    print(f"Scan complete. Found {len(discovered_entries)} PWRcell SunSpec discovery topics.")

    for topic, data in discovered_entries:
        purged_topics.append(topic)
        state_topic = data.get("state_topic")
        if dry_run:
            print(f"[DRY RUN] Would delete: {topic}")
            if state_topic:
                print(f"          State topic: {state_topic}")
        else:
            # Publish empty payload with retain=True to delete from HA & broker
            client.publish(topic, "", retain=True)
            if state_topic:
                client.publish(state_topic, "", retain=True)
            print(f"[DELETED] {topic}")

    if not dry_run:
        # Give broker a moment to process the empty publications
        time.sleep(0.5)

        if clear_cache:
            cache_path = get_default_published_topics_path()
            if cache_path.exists():
                try:
                    cache_path.unlink()
                    print(f"Cleared published topics cache at {cache_path}")
                except Exception as e:
                    logger.warning("Could not delete cache file %s: %s", cache_path, e)

    client.loop_stop()
    client.disconnect()
    return purged_topics


def main():
    parser = argparse.ArgumentParser(
        prog="pwrcell-clean-discovery",
        description="Delete all Home Assistant MQTT Discovery topics created by PWRcell SunSpec.",
    )
    parser.add_argument("--host", type=str, default=None, help="MQTT broker host")
    parser.add_argument("--port", type=int, default=None, help="MQTT broker port")
    parser.add_argument("--username", "-u", type=str, default=None, help="MQTT broker username")
    parser.add_argument("--password", "-p", type=str, default=None, help="MQTT broker password")
    parser.add_argument("--prefix", type=str, default="homeassistant", help="HA discovery prefix (default: homeassistant)")
    parser.add_argument("--timeout", type=float, default=4.0, help="Wait timeout in seconds for retained messages")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Show topics without deleting")
    parser.add_argument(
        "--exact-origin",
        action="store_true",
        default=False,
        help="Match exact origin dict instead of matching origin name 'PWRcell SunSpec'",
    )
    parser.add_argument(
        "--no-clear-cache",
        action="store_true",
        default=False,
        help="Do not delete .ha_published_topics.json cache file",
    )

    args = parser.parse_args()

    # Load configuration defaults if available
    try:
        app_cfg = AppConfig.read()
        mqtt_cfg = app_cfg.mqtt or MqttConfig()
    except Exception:
        mqtt_cfg = MqttConfig()

    host = args.host or mqtt_cfg.host or "127.0.0.1"
    port = args.port or mqtt_cfg.port or 1883
    username = args.username or mqtt_cfg.username
    password = args.password or mqtt_cfg.password

    purged = purge_pwrcell_discovery_topics(
        broker_host=host,
        broker_port=port,
        username=username,
        password=password,
        discovery_prefix=args.prefix,
        timeout=args.timeout,
        dry_run=args.dry_run,
        match_exact_origin=args.exact_origin,
        clear_cache=not args.no_clear_cache,
    )

    action = "Identified" if args.dry_run else "Purged"
    print(f"\nFinished: {action} {len(purged)} entities.")


if __name__ == "__main__":
    main()

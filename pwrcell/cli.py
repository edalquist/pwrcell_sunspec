"""Unified CLI Entrypoint for Generac PWRcell (v3).

Subcommands:
  pwrcell explore    - Launch the companion Web Explorer (UI)
  pwrcell run        - Run the Home Assistant bridge daemon
  pwrcell scan       - Scan and discover Modbus devices
  pwrcell set-mode   - Change system operating mode
  pwrcell status     - Show current live status
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from .bridge import HomeAssistantBridge
from .client import create_client
from .config import AppConfig
from .ui.server import run_explorer


def cmd_explore(args, config: AppConfig):
    publish = getattr(args, "publish", False)
    print(f"Starting PWRcell Web Explorer (mock={args.mock}, publish={publish}) at http://{args.host}:{args.port}")
    with create_client(config=config, mock=args.mock) as client:
        bridge = None
        if publish:
            bridge = HomeAssistantBridge(client=client)
            client.bridge = bridge
            bridge.start()
            print("PWRcell Home Assistant MQTT Bridge started.")
        try:
            run_explorer(client, host=args.host, port=args.port, debug=args.debug)
        finally:
            if bridge:
                bridge.stop()


def cmd_run(args, config: AppConfig):
    print(f"Starting PWRcell Home Assistant Bridge (mock={args.mock})...")
    with create_client(config=config, mock=args.mock) as client:
        bridge = HomeAssistantBridge(client=client)
        bridge.start()
        print("PWRcell HA Bridge running. Press Ctrl+C to exit.")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\nShutting down bridge...")
        finally:
            bridge.stop()


def cmd_service(args, config: AppConfig):
    print(f"Starting PWRcell Combined Service (mock={args.mock})...")
    with create_client(config=config, mock=args.mock) as client:
        bridge = HomeAssistantBridge(client=client)
        client.bridge = bridge
        bridge.start()
        print("PWRcell Home Assistant MQTT Bridge started.")
        try:
            if not getattr(args, "no_ui", False):
                print(f"Starting Web Explorer on http://{args.host}:{args.port}...")
                run_explorer(client, host=args.host, port=args.port, debug=args.debug)
            else:
                while True:
                    time.sleep(1.0)
        except KeyboardInterrupt:
            print("\nShutting down service...")
        finally:
            bridge.stop()


def cmd_scan(args, config: AppConfig):
    print(f"Scanning Modbus slave IDs {args.start}..{args.end}...")
    with create_client(config=config, mock=False) as client:
        if not client.modbus:
            print("Error: Modbus client not available")
            return
        discovered = client.modbus.scan_range(args.start, args.end)
        client._save_scanned_devices(discovered)
        print(f"Discovered and saved {len(discovered)} devices into devices.yaml")


def cmd_set_mode(args, config: AppConfig):
    mode = args.mode.upper()
    print(f"Setting PWRcell system operating mode to '{mode}'...")
    with create_client(config=config, mock=args.mock) as client:
        try:
            confirmed = client.controls.set_system_mode(mode)
            print(f"Successfully set system mode to: {mode} ({confirmed})")
        except Exception as e:
            print(f"Error setting mode: {e}")


def cmd_status(args, config: AppConfig):
    with create_client(config=config, mock=args.mock) as client:
        time.sleep(1.5)  # Let initial telemetry populate
        print("\n=== Generac PWRcell Live Status ===")
        print(f"Mode: {'MOCK/SIMULATION' if client.is_mock else 'LIVE HARDWARE'}")
        print(f"Total Discovered Devices: {len(client.state.devices)}")
        for sn, dev in client.state.devices.items():
            print(f"  • [{dev.device_type.upper()}] {dev.model_name} (SN: {sn}, Slave ID: {dev.slave_id})")

        inv = client.state.get_inverter()
        if inv:
            grid = inv.fields.get("inverter.live.grid_power_w")
            solar = inv.fields.get("inverter.live.solar_power_w")
            load = inv.fields.get("inverter.live.load_power_w")
            mode = inv.fields.get("inverter.live.system_mode")
            print("\n--- Inverter Telemetry ---")
            print(f"  Solar Power: {solar.value if solar else '--'} W")
            print(f"  Grid Power:  {grid.value if grid else '--'} W")
            print(f"  Home Load:   {load.value if load else '--'} W")
            print(f"  Operating Mode: {mode.value if mode else '--'}")

        bat = client.state.get_battery()
        if bat:
            soc = bat.fields.get("battery.live.state_of_charge")
            pwr = bat.fields.get("battery.live.battery_power_w")
            print("\n--- Battery Telemetry ---")
            print(f"  State of Charge: {soc.value if soc else '--'} %")
            print(f"  Battery Power:   {pwr.value if pwr else '--'} W")
        print("===================================\n")


def cmd_compare(args, config: AppConfig):
    from .correlator import evaluate_comparisons, format_comparison_table, log_unrecognized_proto_fields
    print(f"Connecting to PWRcell (mock={args.mock}) for telemetry comparison...")
    with create_client(config=config, mock=args.mock) as client:
        start_wait = time.time()
        while time.time() - start_wait < 5.0:
            if client.get_latest_record_set() is not None:
                break
            time.sleep(0.5)
        try:
            while True:
                if not client.is_mock:
                    client.poll_telemetry_models_live()
                results = evaluate_comparisons(client.state)
                unrecognized = client.get_unrecognized_proto_fields()
                log_unrecognized_proto_fields(unrecognized)
                if not args.once:
                    print("\033[H\033[J", end="")  # ANSI clear screen
                print(f"=== Generac PWRcell Telemetry vs Modbus Correlation [{time.strftime('%H:%M:%S')}] ===")
                print(format_comparison_table(results, unrecognized_fields=unrecognized))
                print("\nPress Ctrl+C to exit.\n")
                if args.once:
                    break
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nExiting comparison monitor.")


def cmd_export_default_config(args):
    from .ha import export_default_config
    try:
        keys = export_default_config(source_path=args.source, target_path=args.target)
        target_name = args.target or "ha_default_config.yaml"
        print(f"Successfully exported {len(keys)} generic field IDs to {target_name}")
    except Exception as e:
        print(f"Error exporting default config: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_clean_discovery(args, config: AppConfig):
    from .clean_discovery import purge_pwrcell_discovery_topics
    from .config import MqttConfig
    mqtt_cfg = config.mqtt or MqttConfig()
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


def main():
    parser = argparse.ArgumentParser(prog="pwrcell", description="Generac PWRcell v3 Client & Explorer")
    parser.add_argument("--mock", action="store_true", default=False, help="Run in mock/simulation mode")
    parser.add_argument("--log-level", type=str, default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # explore
    sub_explore = subparsers.add_parser("explore", help="Launch companion Web Explorer")
    sub_explore.add_argument("--host", type=str, default="0.0.0.0", help="HTTP bind host")
    sub_explore.add_argument("--port", type=int, default=5555, help="HTTP bind port")
    sub_explore.add_argument("--debug", action="store_true", default=False, help="Enable Flask debug")
    sub_explore.add_argument("--mock", action="store_true", default=False, help="Run in mock/simulation mode")
    sub_explore.add_argument("--publish", action="store_true", default=False, help="Also start and publish to Home Assistant MQTT bridge")

    # compare
    sub_compare = subparsers.add_parser("compare", help="Compare live MQTT telemetry with candidate Modbus registers")
    sub_compare.add_argument("--interval", type=float, default=1.0, help="Refresh interval in seconds (default: 1.0)")
    sub_compare.add_argument("--once", action="store_true", default=False, help="Print snapshot once and exit")
    sub_compare.add_argument("--mock", action="store_true", default=False, help="Run in mock/simulation mode")

    # run
    sub_run = subparsers.add_parser("run", help="Run Home Assistant MQTT bridge daemon")
    sub_run.add_argument("--mock", action="store_true", default=False, help="Run in mock/simulation mode")

    # service (Bridge + Web Explorer for HA Add-on / Systemd)
    sub_service = subparsers.add_parser("service", help="Run Home Assistant MQTT bridge and Web Explorer together")
    sub_service.add_argument("--host", type=str, default="0.0.0.0", help="HTTP bind host")
    sub_service.add_argument("--port", type=int, default=5555, help="HTTP bind port")
    sub_service.add_argument("--no-ui", action="store_true", default=False, help="Disable Web Explorer UI")
    sub_service.add_argument("--debug", action="store_true", default=False, help="Enable Flask debug")
    sub_service.add_argument("--mock", action="store_true", default=False, help="Run in mock/simulation mode")
    sub_service.add_argument("--log-level", dest="sub_log_level", type=str, default=None, help="Logging level (DEBUG, INFO, WARNING, ERROR)")

    # scan
    sub_scan = subparsers.add_parser("scan", help="Scan Modbus slave IDs")
    sub_scan.add_argument("--start", type=int, default=1, help="Start slave ID")
    sub_scan.add_argument("--end", type=int, default=100, help="End slave ID")

    # set-mode
    sub_mode = subparsers.add_parser("set-mode", help="Set system operating mode")
    sub_mode.add_argument("mode", type=str, help="Operating mode (e.g. CLEAN_BACKUP, SELF_SUPPLY, GRID_TIE)")
    sub_mode.add_argument("--mock", action="store_true", default=False, help="Run in mock/simulation mode")

    # status
    sub_status = subparsers.add_parser("status", help="Display live status summary")
    sub_status.add_argument("--mock", action="store_true", default=False, help="Run in mock/simulation mode")

    # export-default-config
    sub_export = subparsers.add_parser(
        "export-default-config",
        help="Convert ha_config.yaml to generic ha_default_config.yaml by stripping serial numbers",
    )
    sub_export.add_argument("--source", type=str, default=None, help="Source config path (default: ha_config.yaml)")
    sub_export.add_argument("--target", type=str, default=None, help="Target default config path (default: ha_default_config.yaml)")

    # clean-discovery
    sub_clean = subparsers.add_parser(
        "clean-discovery",
        help="Purge all Home Assistant MQTT discovery topics matching PWRcell SunSpec",
    )
    sub_clean.add_argument("--host", type=str, default=None, help="MQTT broker host")
    sub_clean.add_argument("--port", type=int, default=None, help="MQTT broker port")
    sub_clean.add_argument("--username", "-u", type=str, default=None, help="MQTT broker username")
    sub_clean.add_argument("--password", "-p", type=str, default=None, help="MQTT broker password")
    sub_clean.add_argument("--prefix", type=str, default="homeassistant", help="HA discovery prefix (default: homeassistant)")
    sub_clean.add_argument("--timeout", type=float, default=4.0, help="Wait timeout in seconds for retained messages")
    sub_clean.add_argument("--dry-run", action="store_true", default=False, help="Show topics without deleting")
    sub_clean.add_argument(
        "--exact-origin",
        action="store_true",
        default=False,
        help="Match exact origin dict instead of matching origin name 'PWRcell SunSpec'",
    )
    sub_clean.add_argument(
        "--no-clear-cache",
        action="store_true",
        default=False,
        help="Do not delete .ha_published_topics.json cache file",
    )

    args = parser.parse_args()

    effective_log_level = getattr(args, "sub_log_level", None) or getattr(args, "log_level", "INFO")
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s",
        level=getattr(logging, effective_log_level.upper(), logging.INFO),
    )

    try:
        config = AppConfig.read()
    except Exception:
        config = AppConfig()

    if args.subcommand == "explore" or args.subcommand is None:
        cmd_explore(args if hasattr(args, "port") else argparse.Namespace(host="0.0.0.0", port=5555, debug=False, mock=args.mock), config)
    elif args.subcommand == "service":
        cmd_service(args, config)
    elif args.subcommand == "compare":
        cmd_compare(args, config)
    elif args.subcommand == "run":
        cmd_run(args, config)
    elif args.subcommand == "scan":
        cmd_scan(args, config)
    elif args.subcommand == "set-mode":
        cmd_set_mode(args, config)
    elif args.subcommand == "status":
        cmd_status(args, config)
    elif args.subcommand == "export-default-config":
        cmd_export_default_config(args)
    elif args.subcommand == "clean-discovery":
        cmd_clean_discovery(args, config)


if __name__ == "__main__":
    main()

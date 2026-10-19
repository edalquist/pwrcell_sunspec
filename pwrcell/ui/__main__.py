"""CLI runner for PWRcell Web Explorer (`python -m pwrcell.ui`)."""

import argparse
import logging
import sys

from ..client import create_client
from ..config import AppConfig
from .server import run_explorer


def main():
    parser = argparse.ArgumentParser(description="PWRcell Companion Web Explorer")
    parser.add_argument("--mock", action="store_true", default=False, help="Run in mock/simulation mode using recorded dumps")
    parser.add_argument("--port", type=int, default=5555, help="HTTP port to bind (default: 5555)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="HTTP host to bind (default: 0.0.0.0)")
    parser.add_argument("--debug", action="store_true", default=False, help="Enable Flask debug mode")

    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s",
        level=logging.DEBUG if args.debug else logging.INFO,
    )

    try:
        config = AppConfig.read()
    except Exception:
        config = AppConfig()

    print(f"Starting PWRcell Web Explorer (mock={args.mock}) on http://{args.host}:{args.port}")
    with create_client(config=config, mock=args.mock) as client:
        run_explorer(client, host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()

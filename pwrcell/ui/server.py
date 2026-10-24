"""Web Explorer API Server for Generac PWRcell (v3).

Provides REST APIs and Server-Sent Events (SSE) for the companion Web Explorer,
enabling real-time device inspection, field exploration, and Home Assistant entity configuration.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from ..client import PwrcellClient, create_client
from ..ha import (
    generate_discovery_payload,
    get_recommended_field_keys,
    is_field_selected,
    load_ha_config,
    qualify_legacy_ha_config,
    save_ha_config,
)
from ..state import StateField
from .routes import control, devices, grouping, ha

logger = logging.getLogger(__name__)


def create_app(client: PwrcellClient) -> Flask:
    """Create and configure the Flask Web Explorer application."""
    static_dir = Path(__file__).resolve().parent / "static"
    app = Flask(__name__, static_folder=str(static_dir), static_url_path="")

    # Event subscribers queue list for Server-Sent Events
    sse_queues: list[queue.Queue] = []
    sse_lock = threading.Lock()
    app.sse_queues = sse_queues  # type: ignore[attr-defined]
    app.sse_lock = sse_lock      # type: ignore[attr-defined]

    def on_field_change(field: StateField):
        event_data = {
            "type": "field_update",
            "field": field.to_dict(),
        }
        with sse_lock:
            for q in list(sse_queues):
                try:
                    q.put_nowait(event_data)
                except queue.Full:
                    pass

    def on_compound_change(c_view):
        event_data = {
            "type": "compound_update",
            "field": c_view.to_dict(),
        }
        with sse_lock:
            for q in list(sse_queues):
                try:
                    q.put_nowait(event_data)
                except queue.Full:
                    pass

    # Subscribe to state store changes and compound view updates
    client.state.subscribe(on_field_change)
    client.state.subscribe_compound(on_compound_change)

    for module in (devices, grouping, control, ha):
        app.register_blueprint(module.create_blueprint(client))

    @app.route("/")
    def index():
        return send_from_directory(str(static_dir), "index.html")

    @app.route("/api/stream")
    def sse_stream():
        """Server-Sent Events endpoint streaming live state updates to the browser."""
        client_queue: queue.Queue = queue.Queue(maxsize=100)
        with sse_lock:
            sse_queues.append(client_queue)

        def event_generator():
            try:
                # Initial connect ping
                yield f"data: {json.dumps({'type': 'connected'})}\n\n"
                while True:
                    try:
                        event_data = client_queue.get(timeout=15.0)
                        yield f"data: {json.dumps(event_data)}\n\n"
                    except queue.Empty:
                        # Keepalive ping
                        yield ": keepalive\n\n"
            finally:
                with sse_lock:
                    if client_queue in sse_queues:
                        sse_queues.remove(client_queue)

        return Response(
            event_generator(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return app


def run_explorer(
    client: PwrcellClient,
    host: str = "0.0.0.0",
    port: int = 5555,
    debug: bool = False,
):
    """Run the Web Explorer HTTP server."""
    app = create_app(client)
    logger.info("Starting PWRcell Web Explorer at http://%s:%d", "localhost" if host == "0.0.0.0" else host, port)
    app.run(host=host, port=port, debug=debug, use_reloader=False)

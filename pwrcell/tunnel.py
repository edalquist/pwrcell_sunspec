import dataclasses
import logging
import threading
import time
from contextlib import contextmanager
from typing import Generator, Optional

try:
    from sshtunnel import SSHTunnelForwarder
except ImportError:
    SSHTunnelForwarder = None

try:
    from .config import AppConfig
except ImportError:
    AppConfig = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class TunnelConfig:
    host: str = "127.0.0.1"
    mqtt_port: Optional[int] = None
    modbus_port: Optional[int] = None
    manager: Optional["PwrCellTunnel"] = None


class PwrCellTunnel:
    """Manages an SSH tunnel to the PWRcell hardware with automatic health checking and reconnection."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.host: str = "127.0.0.1"
        self.mqtt_port: Optional[int] = None
        self.modbus_port: Optional[int] = None
        self._server: Optional[SSHTunnelForwarder] = None
        self._lock = threading.Lock()
        self._reconnect_lock = threading.Lock()
        self._running = False
        self._watchdog_thread: Optional[threading.Thread] = None

    @property
    def is_active(self) -> bool:
        """Return True if the underlying SSH transport is alive and connected."""
        with self._lock:
            return bool(self._server and self._server.is_active)

    def start(self) -> TunnelConfig:
        """Start the SSH tunnel, establishing forwarded ports and launching the watchdog."""
        with self._lock:
            if self._running:
                return self.get_config()
            self._running = True

        server, host, mod_port, mqtt_port = self._create_and_start_server(None, None)
        with self._lock:
            self._server = server
            self.host = host
            self.modbus_port = mod_port
            self.mqtt_port = mqtt_port

            # Start background watchdog to automatically heal tunnel drops
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop,
                name="PwrCellTunnelWatchdog",
                daemon=True,
            )
            self._watchdog_thread.start()

            return self.get_config()

    def get_config(self) -> TunnelConfig:
        with self._lock:
            return TunnelConfig(
                host=self.host,
                mqtt_port=self.mqtt_port,
                modbus_port=self.modbus_port,
                manager=self,
            )

    def _create_and_start_server(self, target_modbus_port: Optional[int], target_mqtt_port: Optional[int]):
        ssh_cfg = self.config.pwrcell.ssh_tunnel
        logger.info("Opening PWRcell SSH tunnel to %s:%s", ssh_cfg.host, ssh_cfg.port)

        if target_modbus_port and target_mqtt_port:
            local_binds = [
                (self.host, target_modbus_port),
                (self.host, target_mqtt_port),
            ]
        else:
            local_binds = [
                (self.host, ),  # Modbus - random free port
                (self.host, ),  # MQTT - random free port
            ]

        server = SSHTunnelForwarder(
            (ssh_cfg.host, ssh_cfg.port),
            ssh_username=ssh_cfg.username,
            ssh_pkey=ssh_cfg.identity_file,
            local_bind_addresses=local_binds,
            remote_bind_addresses=[
                ("127.0.0.1", 502),   # ModBus
                ("127.0.0.1", 1883),  # MQTT
            ],
            set_keepalive=15.0,
            mute_exceptions=True,
        )
        server.start()

        host = server.local_bind_hosts[0]
        mod_port = server.local_bind_ports[0]
        mqtt_port = server.local_bind_ports[1]
        logger.info(
            "PWRcell tunnel listening: TunnelConfig(host=%r, mqtt_port=%s, modbus_port=%s)",
            host,
            mqtt_port,
            mod_port,
        )
        return server, host, mod_port, mqtt_port

    def ensure_active(self) -> bool:
        """Verify tunnel health and re-establish connection if dropped."""
        with self._lock:
            if not self._running:
                return False
            if self._server and self._server.is_active:
                return True

        with self._reconnect_lock:
            with self._lock:
                if not self._running:
                    return False
                if self._server and self._server.is_active:
                    return True
                old_server = self._server
                self._server = None
                old_mod_port = self.modbus_port
                old_mqtt_port = self.mqtt_port

            if old_server:
                try:
                    old_server.stop(force=True)
                except Exception as e:
                    logger.debug("Error stopping dead SSH tunnel: %s", e)

            logger.warning("SSH tunnel session dropped; re-establishing connection to PWRcell...")
            time.sleep(0.5)

            for attempt in range(1, 4):
                with self._lock:
                    if not self._running:
                        return False
                try:
                    server, host, mod_port, mqtt_port = self._create_and_start_server(old_mod_port, old_mqtt_port)
                    with self._lock:
                        self._server = server
                        self.host = host
                        self.modbus_port = mod_port
                        self.mqtt_port = mqtt_port
                    logger.info("SSH tunnel successfully reconnected (attempt %d/3)", attempt)
                    return True
                except Exception as e:
                    logger.warning("Failed to reconnect SSH tunnel (attempt %d/3): %s", attempt, e)
                    time.sleep(1.0 * attempt)

            return False

    def _watchdog_loop(self):
        """Background thread checking tunnel health every 2 seconds."""
        while True:
            time.sleep(2.0)
            with self._lock:
                if not self._running:
                    break
                is_down = not (self._server and self._server.is_active)
            if is_down:
                self.ensure_active()

    def stop(self):
        """Stop tunnel and watchdog."""
        with self._lock:
            self._running = False
            old_server = self._server
            self._server = None

        if old_server:
            try:
                old_server.stop(force=True)
            except Exception as e:
                logger.debug("Error closing tunnel: %s", e)
        logger.info("PWRcell SSH tunnel closed")


@contextmanager
def pwrcell_tunnel(config: AppConfig) -> Generator[TunnelConfig, None, None]:
    tunnel = PwrCellTunnel(config)
    tunnel_cfg = tunnel.start()
    try:
        yield tunnel_cfg
    finally:
        tunnel.stop()
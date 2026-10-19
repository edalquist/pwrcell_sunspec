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
            self._start_server_locked()

            # Start background watchdog to automatically heal tunnel drops
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop,
                name="PwrCellTunnelWatchdog",
                daemon=True,
            )
            self._watchdog_thread.start()

            return self.get_config()

    def get_config(self) -> TunnelConfig:
        return TunnelConfig(
            host=self.host,
            mqtt_port=self.mqtt_port,
            modbus_port=self.modbus_port,
            manager=self,
        )

    def _start_server_locked(self):
        ssh_cfg = self.config.pwrcell.ssh_tunnel
        logger.info("Opening PWRcell SSH tunnel to %s:%s", ssh_cfg.host, ssh_cfg.port)

        # If ports are already assigned, reuse them across reconnects so clients don't break
        if self.modbus_port and self.mqtt_port:
            local_binds = [
                (self.host, self.modbus_port),
                (self.host, self.mqtt_port),
            ]
        else:
            local_binds = [
                (self.host, ),  # Modbus - random free port
                (self.host, ),  # MQTT - random free port
            ]

        self._server = SSHTunnelForwarder(
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
        self._server.start()

        self.host = self._server.local_bind_hosts[0]
        self.modbus_port = self._server.local_bind_ports[0]
        self.mqtt_port = self._server.local_bind_ports[1]
        logger.info(
            "PWRcell tunnel listening: TunnelConfig(host=%r, mqtt_port=%s, modbus_port=%s)",
            self.host,
            self.mqtt_port,
            self.modbus_port,
        )

    def ensure_active(self) -> bool:
        """Verify tunnel health and re-establish connection if dropped."""
        with self._lock:
            if not self._running:
                return False
            if self._server and self._server.is_active:
                return True

            logger.warning("SSH tunnel session dropped; re-establishing connection to PWRcell...")
            return self._reconnect_locked()

    def _reconnect_locked(self) -> bool:
        if self._server:
            try:
                self._server.stop(force=True)
            except Exception as e:
                logger.debug("Error stopping dead SSH tunnel: %s", e)
            self._server = None

        time.sleep(0.5)

        for attempt in range(1, 4):
            try:
                self._start_server_locked()
                logger.info("SSH tunnel successfully reconnected (attempt %d/3)", attempt)
                return True
            except Exception as e:
                logger.warning("Failed to reconnect SSH tunnel (attempt %d/3): %s", attempt, e)
                time.sleep(1.0 * attempt)

        return False

    def _watchdog_loop(self):
        """Background thread checking tunnel health every 2 seconds."""
        while self._running:
            time.sleep(2.0)
            if not self._running:
                break
            try:
                with self._lock:
                    is_down = not (self._server and self._server.is_active)
                if is_down and self._running:
                    self.ensure_active()
            except Exception as e:
                logger.debug("Tunnel watchdog error: %s", e)

    def stop(self):
        """Stop tunnel and watchdog."""
        with self._lock:
            self._running = False
            if self._server:
                try:
                    self._server.stop(force=True)
                except Exception as e:
                    logger.debug("Error closing tunnel: %s", e)
                self._server = None
            logger.info("PWRcell SSH tunnel closed")


@contextmanager
def pwrcell_tunnel(config: AppConfig) -> Generator[TunnelConfig, None, None]:
    tunnel = PwrCellTunnel(config)
    tunnel_cfg = tunnel.start()
    try:
        yield tunnel_cfg
    finally:
        tunnel.stop()
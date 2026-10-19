"""Serialized Modbus TCP Client for Generac PWRcell.

This module enforces strictly serialized Modbus transactions through a dedicated
worker thread and FIFO queue, preventing packet collisions, gateway timeouts,
and cascading reconnection deadlocks.
"""

from __future__ import annotations

import concurrent.futures
import logging
import queue
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

try:
    import sunspec2.device as ss2_device
    import sunspec2.modbus.client as ss2_client
    import sunspec2.modbus.modbus as mb
except ImportError:
    ss2_device = None  # type: ignore
    ss2_client = None  # type: ignore
    mb = None  # type: ignore

logger = logging.getLogger(__name__)

T = TypeVar("T")


def configure_sunspec_model_paths(models_dir: Optional[Path | str] = None):
    """Configure pysunspec2 to include custom PWRcell SunSpec model definitions."""
    repo_root = Path(__file__).resolve().parent.parent
    target = Path(models_dir) if models_dir else (repo_root / "sunspec-models")
    if target.exists() and target.is_dir():
        current = ss2_device.get_model_defs_path()
        target_str = str(target.resolve())
        if target_str not in current:
            ss2_device.set_model_defs_path([target_str] + current)
            logger.info("Configured pysunspec2 model defs path: %s", target_str)


@dataclass
class ModbusJob:
    """Represents a queued Modbus operation."""
    func: Callable[[], Any]
    future: concurrent.futures.Future
    retries: int = 3
    base_backoff_sec: float = 0.25
    description: str = ""


class SerializedModbusWorker:
    """A dedicated worker thread processing Modbus requests sequentially."""

    def __init__(self):
        self._queue: queue.Queue[Optional[ModbusJob]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="PwrCellModbusWorker",
                daemon=True,
            )
            self._thread.start()
            logger.info("Started Serialized Modbus Worker thread")

    def stop(self, timeout: float = 3.0):
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._queue.put(None)  # Sentinel to terminate thread
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=timeout)
            logger.info("Stopped Serialized Modbus Worker thread")

    def submit(
        self,
        func: Callable[[], T],
        description: str = "",
        retries: int = 3,
        backoff_sec: float = 0.25,
    ) -> concurrent.futures.Future[T]:
        """Submit a Modbus operation to the serialized queue."""
        if not self._running:
            self.start()

        future: concurrent.futures.Future[T] = concurrent.futures.Future()
        job = ModbusJob(
            func=func,
            future=future,
            retries=retries,
            base_backoff_sec=backoff_sec,
            description=description,
        )
        self._queue.put(job)
        return future

    def execute_sync(
        self,
        func: Callable[[], T],
        description: str = "",
        retries: int = 3,
        timeout: float = 30.0,
    ) -> T:
        """Execute a Modbus operation synchronously with strict serialization."""
        future = self.submit(func, description=description, retries=retries)
        return future.result(timeout=timeout)

    def _worker_loop(self):
        logger.debug("Serialized Modbus worker loop running")
        while self._running:
            try:
                job = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if job is None:
                break

            try:
                self._execute_job(job)
            finally:
                self._queue.task_done()

    def _execute_job(self, job: ModbusJob):
        last_exception: Optional[Exception] = None
        for attempt in range(1, job.retries + 1):
            try:
                if job.description:
                    logger.debug(
                        "Executing Modbus op: %s (attempt %d/%d)",
                        job.description,
                        attempt,
                        job.retries,
                    )
                result = job.func()
                job.future.set_result(result)
                return
            except Exception as exc:
                last_exception = exc
                err_msg = str(exc)
                if attempt < job.retries:
                    logger.info(
                        "Transient Modbus error on '%s' (attempt %d/%d, retrying): %s",
                        job.description,
                        attempt,
                        job.retries,
                        err_msg,
                    )
                    delay = job.base_backoff_sec * (2 ** (attempt - 1))
                    time.sleep(delay)
                else:
                    logger.warning(
                        "Modbus error on '%s' (attempt %d/%d): %s",
                        job.description,
                        attempt,
                        job.retries,
                        err_msg,
                    )

        if last_exception:
            job.future.set_exception(last_exception)


class SerializedModbusClient:
    """High-level client managing SunSpec Modbus TCP devices through the serialized worker."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 502,
        timeout: float = 60.0,
        tunnel: Optional[Any] = None,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.tunnel = tunnel
        self.worker = SerializedModbusWorker()
        self._devices: Dict[int, ss2_client.SunSpecModbusClientDeviceTCP] = {}
        self._shared_client: Optional[mb.ModbusClientTCP] = None
        self._lock = threading.Lock()
        configure_sunspec_model_paths()

    def __enter__(self):
        self.worker.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        """Disconnect all devices and stop worker thread."""
        with self._lock:
            if self._shared_client:
                try:
                    self.worker.execute_sync(self._shared_client.disconnect, description="Disconnect shared Modbus client", timeout=2.0)
                except Exception as e:
                    logger.debug("Error closing shared Modbus client: %s", e)
                self._shared_client = None
            self._devices.clear()
        self.worker.stop()

    def _get_shared_client(self) -> mb.ModbusClientTCP:
        if self._shared_client is None:
            self._shared_client = mb.ModbusClientTCP(
                slave_id=1,
                ipaddr=self.host,
                ipport=self.port,
                timeout=int(self.timeout),
            )
        return self._shared_client

    def _ensure_device_connected(self, device: ss2_client.SunSpecModbusClientDeviceTCP):
        """Ensure SSH tunnel is healthy, point shared client to slave_id, and connect socket."""
        if self.tunnel:
            self.tunnel.ensure_active()
        shared = self._get_shared_client()
        shared.slave_id = device.slave_id
        if not shared.is_connected():
            shared.connect()

    def _handle_socket_error(self, exc: Exception):
        """Disconnect dead socket on broken pipe or network drop so next retry starts fresh."""
        err_str = str(exc)
        is_sock_err = any(
            x in err_str
            for x in (
                "Broken pipe",
                "Socket write error",
                "Connection reset",
                "Connection refused",
                "Response timeout",
                "Bad file descriptor",
            )
        ) or isinstance(exc, (OSError, socket.error))

        if is_sock_err:
            logger.debug("Socket error encountered (%s); closing Modbus socket and verifying tunnel", exc)
            if self._shared_client:
                try:
                    self._shared_client.disconnect()
                except Exception:
                    pass
            if self.tunnel:
                try:
                    self.tunnel.ensure_active()
                except Exception as te:
                    logger.debug("Error checking tunnel on socket error: %s", te)

    def get_or_create_device(self, slave_id: int) -> ss2_client.SunSpecModbusClientDeviceTCP:
        with self._lock:
            if slave_id in self._devices:
                return self._devices[slave_id]

            shared_client = self._get_shared_client()
            device = ss2_client.SunSpecModbusClientDeviceTCP(
                slave_id=slave_id,
                ipaddr=self.host,
                ipport=self.port,
                timeout=int(self.timeout),
            )
            # Multiplex all devices over the single shared Modbus TCP connection
            device.client = shared_client
            self._devices[slave_id] = device
            return device

    def scan_device(self, slave_id: int, full_model_read: bool = False) -> Optional[ss2_client.SunSpecModbusClientDeviceTCP]:
        """Scan a slave ID to detect SunSpec device models."""
        device = self.get_or_create_device(slave_id)

        def _scan():
            self._ensure_device_connected(device)
            try:
                device.scan(full_model_read=full_model_read)
                if "common" in device.models or 1 in device.models:
                    return device
                return None
            except Exception as e:
                self._handle_socket_error(e)
                if "Error scanning SunSpec base addresses" in str(e):
                    return None
                raise e

        try:
            return self.worker.execute_sync(_scan, description=f"Scan device {slave_id}", retries=3)
        except Exception as e:
            logger.debug("Device %d scan failed: %s", slave_id, e)
            return None

    def scan_range(
        self,
        start_id: int = 1,
        end_id: int = 100,
        stop_on_duplicate_serial: bool = True,
    ) -> Dict[int, ss2_client.SunSpecModbusClientDeviceTCP]:
        """Scan a range of slave IDs sequentially, returning discovered devices."""
        discovered: Dict[int, ss2_client.SunSpecModbusClientDeviceTCP] = {}
        found_serials: Dict[str, List[int]] = {}

        logger.info("Scanning Modbus slave IDs %d..%d on %s:%d", start_id, end_id, self.host, self.port)

        for slave_id in range(start_id, end_id + 1):
            dev = self.scan_device(slave_id, full_model_read=False)
            if not dev:
                continue

            # Read common model to get serial number and model name
            common_model = dev.models.get(1) or dev.models.get("common")
            if not common_model:
                continue

            try:
                self.read_model_block(dev, 1)
                sn = str(dev.common[0].SN.value).strip() if hasattr(dev, "common") else ""
                md = str(dev.common[0].Md.value).strip() if hasattr(dev, "common") else ""
            except Exception as e:
                logger.debug("Could not read common model on slave %d: %s", slave_id, e)
                continue

            if sn:
                ids = found_serials.setdefault(sn, [])
                ids.append(slave_id)
                if len(ids) > 1 and stop_on_duplicate_serial:
                    logger.info("Found duplicate serial %s at ID %d, stopping scan", sn, slave_id)
                    break

            discovered[slave_id] = dev
            logger.info("Discovered device at ID %d: %s (SN: %s)", slave_id, md, sn)

        return discovered

    def read_model_block(
        self,
        device: ss2_client.SunSpecModbusClientDeviceTCP,
        model_id: int,
        index: int = 0,
    ) -> Optional[ss2_client.SunSpecModbusClientModel]:
        """Read an entire model block in a single Modbus transaction."""
        models_list = device.models.get(model_id)
        if not models_list or index >= len(models_list):
            return None

        model = models_list[index]

        def _read():
            self._ensure_device_connected(device)
            try:
                model.read()
                return model
            except Exception as e:
                self._handle_socket_error(e)
                raise e

        desc = f"Read model {model_id}[{index}] on slave {device.slave_id}"
        return self.worker.execute_sync(_read, description=desc, retries=3)

    def write_point_value(
        self,
        device: ss2_client.SunSpecModbusClientDeviceTCP,
        model_id: int,
        point_name: str,
        value: Any,
        index: int = 0,
    ) -> Any:
        """Write a value to a writable register point and verify by re-reading the block."""
        models_list = device.models.get(model_id)
        if not models_list or index >= len(models_list):
            raise ValueError(f"Model {model_id}[{index}] not found on slave {device.slave_id}")

        model = models_list[index]
        point = model.points.get(point_name)
        if not point:
            raise ValueError(f"Point {point_name} not found in model {model_id}")

        def _write():
            self._ensure_device_connected(device)
            try:
                point.cvalue = value
                point.write()
                # Immediately re-read model block to confirm
                model.read()
                return point.cvalue
            except Exception as e:
                self._handle_socket_error(e)
                raise e

        desc = f"Write {point_name}={value} in model {model_id} on slave {device.slave_id}"
        return self.worker.execute_sync(_write, description=desc, retries=3)

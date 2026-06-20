from __future__ import annotations

import logging
import struct
import time
from typing import Any, NamedTuple

logger = logging.getLogger("open-aio-agent.usb")

VID = 0x303A
PID = 0x4004
OUT_ENDPOINT = 0x01
IN_ENDPOINT = 0x81
CHUNK_SIZE = 4 * 1024
TIMEOUT_MS = 250
READ_TIMEOUT_MS = 20

MAGIC = b"CAPP"
SIGNALRGB_MAGIC = b"SRGB"
EVENT_MAGIC_REVIEW = b"CREV"
EVENT_MAGIC_TOUCH = b"CTCH"
CMD_STATE_JSON = 0x01
CMD_SIGNALRGB_RGB565_SCALED = 0x03
CMD_SIGNALRGB_JPEG = 0x05


class ReviewTouchDiagnostic(NamedTuple):
    result: str
    raw_x: int
    raw_y: int
    logical_x: int
    logical_y: int


class SignalDeviceStatus(NamedTuple):
    status: int
    command: int
    detail: int
    millis: int
    rx_ms: int | None
    decode_ms: int | None
    flush_ms: int | None


def _checksum16(data: bytes) -> int:
    return sum(data) & 0xFFFF


class UsbStateSender:
    def __init__(self) -> None:
        self._device: Any | None = None
        self._backend: Any | None = None
        self._warned = False
        self.last_status = "unknown"
        self.last_error: str | None = None
        self.last_write_seconds = 0.0
        self.last_device_status: int | None = None
        self.last_device_timing: SignalDeviceStatus | None = None

    def send_state(self, state: dict[str, Any]) -> bool:
        import json

        payload = json.dumps(state, separators=(",", ":"), default=str).encode("utf-8")
        if not payload or len(payload) > 8192:
            self.last_status = "payload_rejected"
            self.last_error = f"payload length {len(payload)}"
            return False

        header = MAGIC + bytes([CMD_STATE_JSON, 0]) + struct.pack(
            "<H8sI", _checksum16(payload), b"\x00" * 8, len(payload)
        )
        return self._write(header, payload)

    def send_signalrgb_jpeg(self, jpeg: bytes, scale: int = 0, wait_status: bool = False) -> bool:
        if not jpeg:
            self.last_status = "payload_rejected"
            self.last_error = "empty jpeg frame"
            return False
        flags = (scale & 0x7F) | (0x80 if wait_status else 0)
        header = SIGNALRGB_MAGIC + bytes([CMD_SIGNALRGB_JPEG, flags]) + struct.pack(
            "<H8sI", _checksum16(jpeg), b"\x00" * 8, len(jpeg)
        )
        return self._write(header, jpeg, wait_status=wait_status, status_command=CMD_SIGNALRGB_JPEG)

    def send_signalrgb_rgb565_scaled(
        self,
        pixels: bytes,
        width: int,
        height: int,
        scale: int,
        x: int = 0,
        y: int = 0,
        wait_status: bool = False,
    ) -> bool:
        if not pixels or width <= 0 or height <= 0 or scale <= 0:
            self.last_status = "payload_rejected"
            self.last_error = "invalid rgb565 frame"
            return False
        if len(pixels) != width * height * 2:
            self.last_status = "payload_rejected"
            self.last_error = f"rgb565 length {len(pixels)} != {width * height * 2}"
            return False
        flags = (scale & 0x7F) | (0x80 if wait_status else 0)
        header = SIGNALRGB_MAGIC + bytes([CMD_SIGNALRGB_RGB565_SCALED, flags]) + struct.pack(
            "<HHHHHI", _checksum16(pixels), x, y, width, height, len(pixels)
        )
        return self._write(header, pixels, wait_status=wait_status, status_command=CMD_SIGNALRGB_RGB565_SCALED)

    def read_review_events(self) -> list[str]:
        events, _ = self.read_review_usb_events()
        return events

    def read_review_usb_events(self) -> tuple[list[str], list[ReviewTouchDiagnostic]]:
        device = self._connect()
        if device is None:
            return [], []

        events: list[str] = []
        touch_events: list[ReviewTouchDiagnostic] = []
        for _ in range(64):
            try:
                data = bytes(device.read(IN_ENDPOINT, 64, READ_TIMEOUT_MS))
            except Exception as exc:
                message = str(exc).lower()
                if "timed out" not in message and "timeout" not in message:
                    logger.info("USB app read failed: %s", exc)
                break
            if len(data) < 5:
                continue
            if data[:4] == EVENT_MAGIC_REVIEW:
                if data[4] == 0x01:
                    logger.info("USB review event received: approve")
                    events.append("approve")
                elif data[4] == 0x02:
                    logger.info("USB review event received: reject")
                    events.append("reject")
            elif data[:4] == EVENT_MAGIC_TOUCH and len(data) >= 14:
                result = {
                    0: "miss",
                    1: "approve",
                    2: "reject",
                    3: "no_review",
                    4: "no_touch",
                    5: "pressed_no_point",
                }.get(data[4], f"unknown:{data[4]}")
                raw_x = struct.unpack_from("<h", data, 6)[0]
                raw_y = struct.unpack_from("<h", data, 8)[0]
                logical_x = struct.unpack_from("<h", data, 10)[0]
                logical_y = struct.unpack_from("<h", data, 12)[0]
                diagnostic = ReviewTouchDiagnostic(result, raw_x, raw_y, logical_x, logical_y)
                logger.info(
                    "USB review touch: result=%s raw=%d,%d logical=%d,%d",
                    result,
                    raw_x,
                    raw_y,
                    logical_x,
                    logical_y,
                )
                touch_events.append(diagnostic)
            elif data[:4] == b"SRSP":
                logger.debug("USB status packet received: %s", data.hex())
            else:
                logger.info("USB IN packet received: %s", data.hex())
        return events, touch_events

    def close(self) -> None:
        if self._device is None:
            return
        try:
            import usb.util

            usb.util.dispose_resources(self._device)
        except Exception:
            pass
        self._device = None

    def _connect(self) -> Any | None:
        if self._device is not None:
            return self._device

        try:
            import usb.backend.libusb1
            import usb.core
            from libusb_package import find_library

            self._backend = usb.backend.libusb1.get_backend(find_library=find_library)
            self._device = usb.core.find(idVendor=VID, idProduct=PID, backend=self._backend)
            if self._device is None:
                self.last_status = "missing"
                self.last_error = None
                return None
            try:
                self._device.set_configuration()
            except Exception:
                pass
            self.last_status = "connected"
            self.last_error = None
            return self._device
        except Exception as exc:
            if not self._warned:
                logger.info("USB app transport unavailable: %s", exc)
                self._warned = True
            self._device = None
            self.last_status = "unavailable"
            self.last_error = str(exc)
            return None

    def _read_signal_status(self, timeout_seconds: float, command: int) -> int | None:
        device = self._connect()
        if device is None:
            return None

        deadline = time.perf_counter() + timeout_seconds
        while time.perf_counter() < deadline:
            remaining_ms = max(1, min(READ_TIMEOUT_MS, int((deadline - time.perf_counter()) * 1000)))
            try:
                data = bytes(device.read(IN_ENDPOINT, 64, remaining_ms))
            except Exception as exc:
                message = str(exc).lower()
                if "timed out" in message or "timeout" in message:
                    continue
                raise
            if len(data) >= 6 and data[:4] == b"SRSP" and data[5] == command:
                detail = struct.unpack_from("<H", data, 6)[0] if len(data) >= 8 else 0
                device_ms = struct.unpack_from("<I", data, 8)[0] if len(data) >= 12 else 0
                rx_ms = struct.unpack_from("<H", data, 12)[0] if len(data) >= 14 else None
                decode_ms = struct.unpack_from("<H", data, 14)[0] if len(data) >= 16 else None
                flush_ms = struct.unpack_from("<H", data, 16)[0] if len(data) >= 18 else None
                self.last_device_timing = SignalDeviceStatus(
                    data[4],
                    data[5],
                    detail,
                    device_ms,
                    rx_ms,
                    decode_ms,
                    flush_ms,
                )
                return data[4]
        return None

    def _drain_signal_status(self) -> None:
        device = self._connect()
        if device is None:
            return
        for _ in range(128):
            try:
                data = bytes(device.read(IN_ENDPOINT, 64, 1))
            except Exception:
                break
            if len(data) < 4 or data[:4] != b"SRSP":
                break

    def _write(self, header: bytes, payload: bytes, wait_status: bool = False, status_command: int = CMD_SIGNALRGB_JPEG) -> bool:
        device = self._connect()
        if device is None:
            return False

        try:
            started = time.perf_counter()
            if wait_status:
                self._drain_signal_status()
            device.write(OUT_ENDPOINT, header, TIMEOUT_MS)
            for offset in range(0, len(payload), CHUNK_SIZE):
                device.write(OUT_ENDPOINT, payload[offset : offset + CHUNK_SIZE], TIMEOUT_MS)
            if wait_status:
                self.last_device_status = self._read_signal_status(0.25, status_command)
                if self.last_device_status != 0:
                    self.last_write_seconds = time.perf_counter() - started
                    self.last_status = "device_rejected" if self.last_device_status is not None else "device_timeout"
                    self.last_error = f"device status {self.last_device_status}"
                    return False
            self.last_write_seconds = time.perf_counter() - started
            self.last_status = "ok"
            self.last_error = None
            return True
        except Exception as exc:
            if not self._warned:
                logger.info("USB app write failed: %s", exc)
                self._warned = True
            self._device = None
            self.last_status = "write_failed"
            self.last_error = str(exc)
            return False

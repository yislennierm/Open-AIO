from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock


@dataclass
class DesignerFrame:
    sequence: int
    content_type: str
    data: bytes
    updated_at: float


_LOCK = Lock()
_FRAME: DesignerFrame | None = None
_SEQUENCE = 0
_ACTIVE_TIMEOUT_SECONDS = 2.5
_PREVIEW_HEARTBEAT_TIMEOUT_SECONDS = 5.0
_MAX_FRAME_BYTES = 256 * 1024
_PREVIEW_ACTIVE_UNTIL = 0.0
_PREVIEW_OWNER_ID: str | None = None


def _normalize_client_id(client_id: str | None) -> str:
    cleaned = (client_id or "").strip()
    return cleaned[:96] if cleaned else "legacy"


def _owner_is_available(now: float) -> bool:
    return _PREVIEW_OWNER_ID is None or now > _PREVIEW_ACTIVE_UNTIL


def _claim_owner(client_id: str, now: float) -> bool:
    global _PREVIEW_OWNER_ID
    if client_id.startswith(("edge-renderer-", "direct-media-")):
        _PREVIEW_OWNER_ID = client_id
        return True
    if _owner_is_available(now) or _PREVIEW_OWNER_ID == client_id:
        _PREVIEW_OWNER_ID = client_id
        return True
    return False


def put_frame(data: bytes, content_type: str, client_id: str | None = None) -> DesignerFrame:
    global _FRAME, _SEQUENCE, _PREVIEW_ACTIVE_UNTIL
    if content_type not in {"image/jpeg", "image/png"}:
        raise ValueError("frame must be image/jpeg or image/png")
    if not data:
        raise ValueError("frame is empty")
    if len(data) > _MAX_FRAME_BYTES:
        raise ValueError(f"frame is too large: {len(data)} bytes")
    with _LOCK:
        now = time.monotonic()
        owner_id = _normalize_client_id(client_id)
        if not _claim_owner(owner_id, now):
            raise PermissionError("designer preview is already owned by another tab")
        _SEQUENCE += 1
        _FRAME = DesignerFrame(
            sequence=_SEQUENCE,
            content_type=content_type,
            data=data,
            updated_at=now,
        )
        _PREVIEW_ACTIVE_UNTIL = now + _PREVIEW_HEARTBEAT_TIMEOUT_SECONDS
        return _FRAME


def get_frame_after(sequence: int = 0) -> DesignerFrame | None:
    with _LOCK:
        frame = _FRAME
        if frame is None:
            return None
        if time.monotonic() - frame.updated_at > _ACTIVE_TIMEOUT_SECONDS:
            return None
        if frame.sequence <= sequence:
            return None
        return frame


def is_active() -> bool:
    with _LOCK:
        now = time.monotonic()
        frame_active = _FRAME is not None and now - _FRAME.updated_at <= _ACTIVE_TIMEOUT_SECONDS
        return frame_active or now <= _PREVIEW_ACTIVE_UNTIL


def set_preview_active(active: bool, client_id: str | None = None) -> bool:
    global _PREVIEW_ACTIVE_UNTIL, _PREVIEW_OWNER_ID
    with _LOCK:
        now = time.monotonic()
        owner_id = _normalize_client_id(client_id)
        if active:
            if not _claim_owner(owner_id, now):
                raise PermissionError("designer preview is already owned by another tab")
            _PREVIEW_ACTIVE_UNTIL = now + _PREVIEW_HEARTBEAT_TIMEOUT_SECONDS
        else:
            if _PREVIEW_OWNER_ID in {None, owner_id}:
                _PREVIEW_ACTIVE_UNTIL = 0.0
                _PREVIEW_OWNER_ID = None
        frame_active = _FRAME is not None and now - _FRAME.updated_at <= _ACTIVE_TIMEOUT_SECONDS
        return frame_active or now <= _PREVIEW_ACTIVE_UNTIL

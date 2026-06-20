from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class TelemetryRequest(BaseModel):
    active_process: str = Field(default="unknown.exe", max_length=260)
    active_window_title: str = Field(default="", max_length=260)
    cpu_temp: Optional[float] = None
    gpu_temp: Optional[float] = None
    cpu_load: float = Field(ge=0.0, le=100.0)
    gpu_load: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    ram_used_percent: float = Field(ge=0.0, le=100.0)
    ram_total_mb: Optional[float] = None
    ssd_temp: Optional[float] = None
    cpu_frequency: Optional[float] = None
    gpu_frequency: Optional[float] = None
    cpu_power: Optional[float] = None
    gpu_power: Optional[float] = None
    gpu_fan_speed: Optional[float] = None


class TelemetryRecord(TelemetryRequest):
    device_id: str
    app_id: str
    updated_at: datetime


class StateResponse(BaseModel):
    device_id: str
    app_id: str
    display_name: str
    asset_type: str
    asset_url: str
    asset_hash: str
    asset_width: int
    asset_height: int
    cpu_temp: Optional[float]
    gpu_temp: Optional[float]
    cpu_load: float
    gpu_load: Optional[float]
    ram_used_percent: float
    ram_total_mb: Optional[float]
    ssd_temp: Optional[float]
    cpu_frequency: Optional[float]
    gpu_frequency: Optional[float]
    cpu_power: Optional[float]
    gpu_power: Optional[float]
    gpu_fan_speed: Optional[float]
    updated_at: datetime
    local_time: str
    local_date: str
    review_available: bool = False
    review_process_name: Optional[str] = None
    review_app_id: Optional[str] = None
    review_display_name: Optional[str] = None
    review_status: Optional[str] = None


class TelemetryAck(BaseModel):
    ok: bool
    device_id: str
    app_id: str


class UnknownApp(BaseModel):
    process_name: str
    app_id: str
    display_name: str
    status: str
    source_icon: Optional[str] = None
    updated_at: str


class CandidateDecision(BaseModel):
    process_name: str
    app_id: Optional[str] = None


class LogoFetchRequest(BaseModel):
    process_name: str
    query: Optional[str] = None


class LogoUrlImportRequest(BaseModel):
    process_name: str
    url: str
    display_name: Optional[str] = None


class LayoutSummary(BaseModel):
    id: str
    name: str
    updated_at: Optional[str] = None
    element_count: int


class LayoutSaveRequest(BaseModel):
    layout: dict[str, Any]

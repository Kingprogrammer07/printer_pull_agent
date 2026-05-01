from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class JobStatus(str, Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    QUEUED = "QUEUED"
    PRINTING = "PRINTING"
    PRINTED = "PRINTED"
    PRINTER_OFFLINE = "PRINTER_OFFLINE"
    FAILED = "FAILED"
    FAILED_PERM = "FAILED_PERM"


class PrinterStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    PAUSED = "PAUSED"
    UNKNOWN = "UNKNOWN"


class CreateJobRequest(BaseModel):
    order_number: str = Field(min_length=1, max_length=128)
    user_code: str = Field(min_length=1, max_length=128)
    pdf_url: HttpUrl
    agent_id: Optional[str] = Field(default=None, max_length=128)


class JobResponse(BaseModel):
    id: int
    order_number: str
    user_code: str
    pdf_url: str
    status: JobStatus
    agent_id: Optional[str] = None
    retry_count: int
    error_message: Optional[str] = None
    file_size_bytes: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    downloaded_at: Optional[datetime] = None
    printed_at: Optional[datetime] = None
    claimed_at: Optional[datetime] = None
    locked_until: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PaginatedJobsResponse(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    limit: int
    total_pages: int


class StatsResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    today_printed: int
    today_failed: int
    queue_depth: int
    printer_status: str
    agents_online: int
    uptime_seconds: int


class HealthResponse(BaseModel):
    status: str
    db: str
    printer: str
    agents_online: int
    connected_agents: int
    queue_depth: int
    uptime_seconds: int


class PrinterStatusResponse(BaseModel):
    name: str
    status: PrinterStatus
    details: dict[str, object]


class AgentResponse(BaseModel):
    agent_id: str
    printer_name: Optional[str] = None
    printer_status: str
    details: dict[str, object]
    is_online: bool
    last_seen_at: Optional[datetime] = None
    updated_at: datetime

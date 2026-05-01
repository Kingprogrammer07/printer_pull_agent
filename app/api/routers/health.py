import time

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_agent_manager, get_repo
from app.models.job import HealthResponse, StatsResponse
from app.repositories.job_repository import JobRepository
from app.services.agent_connection_manager import AgentConnectionManager


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    repo: JobRepository = Depends(get_repo),
    manager: AgentConnectionManager = Depends(get_agent_manager),
) -> dict:
    stats = await repo.get_stats()
    printer_status = (await repo.get_latest_printer_status())["status"]
    uptime = int(time.monotonic() - request.app.state.started_at)
    return {
        "status": "healthy",
        "db": "connected",
        "printer": printer_status,
        "agents_online": stats["agents_online"],
        "connected_agents": manager.connected_count(),
        "queue_depth": stats["queue_depth"],
        "uptime_seconds": uptime,
    }


@router.get("/stats", response_model=StatsResponse)
async def stats(
    request: Request,
    repo: JobRepository = Depends(get_repo),
) -> dict:
    data = await repo.get_stats()
    data["printer_status"] = (await repo.get_latest_printer_status())["status"]
    data["uptime_seconds"] = int(time.monotonic() - request.app.state.started_at)
    return data

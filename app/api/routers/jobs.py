from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import get_agent_manager, get_repo
from app.models.job import CreateJobRequest, JobResponse, JobStatus, PaginatedJobsResponse
from app.repositories.job_repository import JobRepository
from app.services.agent_connection_manager import AgentConnectionManager


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: CreateJobRequest,
    response: Response,
    repo: JobRepository = Depends(get_repo),
    manager: AgentConnectionManager = Depends(get_agent_manager),
) -> dict:
    job = await repo.create(payload.model_dump())
    response.status_code = status.HTTP_201_CREATED if job.pop("_created", False) else status.HTTP_200_OK
    await manager.broadcast({"type": "job_available"})
    return job


@router.get("", response_model=PaginatedJobsResponse)
async def list_jobs(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    order_number: str | None = None,
    user_code: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    repo: JobRepository = Depends(get_repo),
) -> dict:
    return await repo.get_paginated(
        page=page,
        limit=limit,
        status=status_filter.value if status_filter else None,
        order_number=order_number,
        user_code=user_code,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: int, repo: JobRepository = Depends(get_repo)) -> dict:
    job = await repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry_job(
    job_id: int,
    repo: JobRepository = Depends(get_repo),
    manager: AgentConnectionManager = Depends(get_agent_manager),
) -> dict:
    job = await repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job["status"] not in {"FAILED", "FAILED_PERM", "PRINTER_OFFLINE"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job cannot be retried")
    updated = await repo.update_status(
        job_id,
        "PENDING",
        retry_count=0,
        next_retry_at=None,
        error_message=None,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    await manager.broadcast({"type": "job_available"})
    return updated


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: int, repo: JobRepository = Depends(get_repo)) -> dict:
    job = await repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job["status"] not in {"PENDING", "FAILED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only PENDING or FAILED jobs can be canceled")
    updated = await repo.update_status(
        job_id,
        "FAILED_PERM",
        next_retry_at=None,
        error_message="Canceled manually",
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return updated

from fastapi import APIRouter, Depends

from app.api.deps import get_repo
from app.models.job import PrinterStatusResponse
from app.repositories.job_repository import JobRepository


router = APIRouter(prefix="/printer", tags=["printer"])


@router.get("/status", response_model=PrinterStatusResponse)
async def get_printer_status(repo: JobRepository = Depends(get_repo)) -> dict:
    return await repo.get_latest_printer_status()

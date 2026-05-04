import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.logger import get_logger
from app.repositories.job_repository import JobRepository, utc_now
from app.services.download_service import DownloadService

TASHKENT_TZ = ZoneInfo("Asia/Tashkent")


logger = get_logger(__name__)


class DownloadWorker:
    def __init__(self, repo: JobRepository, download_service: DownloadService, settings: Settings):
        self.repo = repo
        self.download_service = download_service
        self.settings = settings
        self._running = True

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        logger.info("download_worker_started")
        while self._running:
            try:
                jobs = await self.repo.get_pending_for_download(limit=self.settings.max_concurrent_downloads)
                retry_jobs = await self.repo.get_failed_ready_for_retry()
                all_jobs = jobs + retry_jobs
                if all_jobs:
                    semaphore = asyncio.Semaphore(self.settings.max_concurrent_downloads)
                    await asyncio.gather(
                        *(self._process_guarded(job, semaphore) for job in all_jobs),
                        return_exceptions=True,
                    )
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("download_worker_loop_error", error=str(exc))
                await asyncio.sleep(2)
        logger.info("download_worker_stopped")

    async def _process_guarded(self, job: dict, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            await self._process_job(job)

    async def _process_job(self, job: dict) -> None:
        job_id = int(job["id"])
        started = datetime.now(TASHKENT_TZ)
        await self.repo.update_status(job_id, "DOWNLOADING", error_message=None)
        logger.info("download_started", job_id=job_id, order_number=job["order_number"], user_code=job["user_code"])

        try:
            file_path, file_size = await self.download_service.download(job)
            duration_ms = int((datetime.now(TASHKENT_TZ) - started).total_seconds() * 1000)
            await self.repo.update_status(
                job_id,
                "DOWNLOADED",
                file_path=file_path,
                file_size_bytes=file_size,
                downloaded_at=utc_now(),
                error_message=None,
                next_retry_at=None,
            )
            logger.info("download_complete", job_id=job_id, duration_ms=duration_ms, size_bytes=file_size)
        except Exception as exc:
            await self._mark_failed(job, str(exc))

    async def _mark_failed(self, job: dict, error_message: str) -> None:
        job_id = int(job["id"])
        retry_count = int(job.get("retry_count") or 0) + 1
        if retry_count >= self.settings.max_retry_count:
            await self.repo.update_status(
                job_id,
                "FAILED_PERM",
                retry_count=retry_count,
                next_retry_at=None,
                error_message=error_message,
            )
            logger.error("download_failed_permanent", job_id=job_id, retry_count=retry_count, error=error_message)
            return

        delay = self._retry_delay(retry_count)
        next_retry = datetime.now(TASHKENT_TZ) + timedelta(seconds=delay)
        await self.repo.update_status(
            job_id,
            "FAILED",
            retry_count=retry_count,
            next_retry_at=next_retry.replace(microsecond=0).isoformat(),
            error_message=error_message,
        )
        logger.warning(
            "download_failed_retry_scheduled",
            job_id=job_id,
            retry_count=retry_count,
            next_retry_seconds=delay,
            error=error_message,
        )

    def _retry_delay(self, retry_count: int) -> int:
        index = min(max(retry_count - 1, 0), len(self.settings.retry_delays_seconds) - 1)
        return int(self.settings.retry_delays_seconds[index])


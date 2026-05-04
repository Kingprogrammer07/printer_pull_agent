import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.logger import get_logger
from app.repositories.job_repository import JobRepository, utc_now
from app.services.archive_service import archive_printed_file
from app.services.print_service import PrintService

TASHKENT_TZ = ZoneInfo("Asia/Tashkent")


logger = get_logger(__name__)


class PrintWorker:
    def __init__(
        self,
        repo: JobRepository,
        print_service: PrintService,
        printer_ready_event: asyncio.Event,
        settings: Settings,
    ):
        self.repo = repo
        self.print_service = print_service
        self.printer_ready_event = printer_ready_event
        self.settings = settings
        self._running = True
        self._current_job: asyncio.Task | None = None

    def stop(self) -> None:
        self._running = False
        self.printer_ready_event.set()

    async def wait_current_job_finish(self) -> None:
        if self._current_job is not None and not self._current_job.done():
            await self._current_job

    async def run(self) -> None:
        logger.info("print_worker_started")
        while self._running:
            try:
                if not self.print_service.is_online():
                    self.printer_ready_event.clear()
                    await self._wait_for_printer()
                    continue

                job = await self.repo.get_downloaded_for_print()
                if not job:
                    await asyncio.sleep(3)
                    continue

                self._current_job = asyncio.create_task(self._print_job(job))
                await self._current_job
                self._current_job = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("print_worker_loop_error", error=str(exc))
                await asyncio.sleep(3)
        logger.info("print_worker_stopped")

    async def _wait_for_printer(self) -> None:
        try:
            await asyncio.wait_for(self.printer_ready_event.wait(), timeout=self.settings.printer_poll_interval)
        except asyncio.TimeoutError:
            pass

    async def _print_job(self, job: dict) -> None:
        job_id = int(job["id"])
        started = datetime.now(TASHKENT_TZ)
        await self.repo.update_status(job_id, "PRINTING", error_message=None)
        logger.info("print_started", job_id=job_id, order_number=job["order_number"], user_code=job["user_code"])

        try:
            await self.print_service.print_pdf(str(job["file_path"]))
            printed_at = datetime.now(TASHKENT_TZ)
            archived_path = await asyncio.to_thread(
                archive_printed_file,
                str(job["file_path"]),
                self.settings.archive_dir,
                printed_at,
            )
            duration_ms = int((printed_at - started).total_seconds() * 1000)
            await self.repo.update_status(
                job_id,
                "PRINTED",
                printed_at=printed_at.replace(microsecond=0).isoformat(),
                file_path=archived_path,
                error_message=None,
            )
            logger.info("print_complete", job_id=job_id, duration_ms=duration_ms)
        except Exception as exc:
            await self.repo.update_status(job_id, "PRINTER_OFFLINE", error_message=str(exc))
            self.printer_ready_event.clear()
            logger.error("print_failed_printer_offline", job_id=job_id, error=str(exc))


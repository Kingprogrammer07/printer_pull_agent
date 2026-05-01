import asyncio

from app.core.config import Settings
from app.core.logger import get_logger
from app.repositories.job_repository import JobRepository
from app.services.print_service import PrintService


logger = get_logger(__name__)


class PrinterMonitor:
    def __init__(
        self,
        print_service: PrintService,
        repo: JobRepository,
        printer_ready_event: asyncio.Event,
        settings: Settings,
    ):
        self.print_service = print_service
        self.repo = repo
        self.printer_ready_event = printer_ready_event
        self.settings = settings
        self._running = True
        self._last_online: bool | None = None

    def stop(self) -> None:
        self._running = False
        self.printer_ready_event.set()

    async def run(self) -> None:
        logger.info("printer_monitor_started")
        while self._running:
            try:
                current_online = await asyncio.to_thread(self.print_service.is_online)
                if current_online and not self._last_online:
                    count = await self.repo.requeue_printer_offline_jobs()
                    self.printer_ready_event.set()
                    logger.info("printer_online", requeued=count)

                if not current_online and self._last_online:
                    count = await self.repo.pause_printing_jobs()
                    self.printer_ready_event.clear()
                    logger.warning("printer_offline", paused=count)

                self._last_online = current_online
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_online = False
                self.printer_ready_event.clear()
                logger.error("printer_monitor_error", error=str(exc))

            await asyncio.sleep(self.settings.printer_poll_interval)
        logger.info("printer_monitor_stopped")


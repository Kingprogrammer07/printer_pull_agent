import asyncio
import time
from urllib.parse import urlparse, urlunparse

import aiohttp

from app.core.config import settings
from app.core.logger import get_logger
from app.repositories.job_repository import utc_now
from app.services.download_service import DownloadService
from app.services.local_file_cleanup import LocalFileCleanup
from app.services.print_service import PrintService


logger = get_logger(__name__)


class LocalPrintAgent:
    def __init__(self) -> None:
        self.agent_id = settings.agent_id
        self.server_url = settings.server_url.rstrip("/")
        self.poll_interval = settings.agent_poll_interval
        self.download_service = DownloadService(settings)
        self.print_service = PrintService(settings.printer_name)
        self.file_cleanup = LocalFileCleanup(settings)
        self.cleanup_after_print = settings.local_pdf_cleanup_after_print
        self.cleanup_interval = max(settings.local_pdf_cleanup_interval_seconds, 0)
        self._last_cleanup_at = 0.0

    async def run_forever(self) -> None:
        while True:
            try:
                await self._run_session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("agent_session_error", error=str(exc))
                await asyncio.sleep(self.poll_interval)

    async def _run_session(self) -> None:
        ws_url = self._websocket_url()
        logger.info("agent_connecting", agent_id=self.agent_id, server=ws_url)
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, heartbeat=20) as ws:
                logger.info("agent_connected", agent_id=self.agent_id)
                await self._send_heartbeat(ws)
                while True:
                    await self._send_heartbeat(ws)
                    await self._cleanup_local_files_if_due()
                    await ws.send_json({"type": "claim_next"})
                    message = await self._wait_for_job_message(ws)

                    if message is None or message.get("type") == "no_job":
                        await asyncio.sleep(self.poll_interval)
                        continue

                    if message.get("type") == "job":
                        await self._process_job(ws, message["job"])

    async def _wait_for_job_message(self, ws) -> dict | None:
        deadline = asyncio.get_running_loop().time() + self.poll_interval
        while True:
            timeout = max(0.1, deadline - asyncio.get_running_loop().time())
            try:
                message = await ws.receive_json(timeout=timeout)
            except asyncio.TimeoutError:
                return None

            if message.get("type") in {"job", "no_job"}:
                return message
            if message.get("type") == "job_available":
                await ws.send_json({"type": "claim_next"})
            if message.get("type") == "cleanup_local_files":
                deleted = await self.file_cleanup.cleanup_all_files()
                await ws.send_json({"type": "local_cleanup_done", "deleted": deleted})

    async def _process_job(self, ws, job: dict) -> None:
        job_id = int(job["id"])
        local_path: str | None = None
        logger.info("agent_job_received", job_id=job_id, order_number=job["order_number"])
        try:
            await self._send_job_status(ws, job_id, "DOWNLOADING")
            local_path, file_size = await self.download_service.download(job)

            if not self.print_service.is_online():
                await self._send_job_status(
                    ws,
                    job_id,
                    "PRINTER_OFFLINE",
                    error_message="Printer is offline",
                    file_size_bytes=file_size,
                )
                return

            await self._send_job_status(ws, job_id, "PRINTING", file_size_bytes=file_size)
            await self.print_service.print_pdf(local_path)
            await self._send_job_status(ws, job_id, "PRINTED", file_size_bytes=file_size)
            if self.cleanup_after_print and local_path:
                await self.file_cleanup.delete_downloaded_pdf(local_path)
            logger.info("agent_job_printed", job_id=job_id)
        except Exception as exc:
            logger.error("agent_job_failed", job_id=job_id, error=str(exc))
            await self._send_job_status(
                ws,
                job_id,
                "FAILED",
                error_message=str(exc),
                retryable=True,
            )

    async def _cleanup_local_files_if_due(self) -> None:
        if self.cleanup_interval <= 0:
            return
        now = time.monotonic()
        if now - self._last_cleanup_at < self.cleanup_interval:
            return
        self._last_cleanup_at = now
        await self.file_cleanup.cleanup_old_files()

    async def _send_heartbeat(self, ws) -> None:
        status = "UNKNOWN"
        details = {"checked_at": utc_now()}
        printer_name = self.print_service.printer_name
        try:
            status = self.print_service.get_printer_status().value
            details.update(self.print_service.get_detailed_status())
        except Exception as exc:
            details["error"] = str(exc)
        await ws.send_json(
            {
                "type": "heartbeat",
                "printer_name": printer_name,
                "printer_status": status,
                "details": details,
            }
        )

    async def _send_job_status(
        self,
        ws,
        job_id: int,
        status: str,
        *,
        error_message: str | None = None,
        file_size_bytes: int | None = None,
        retryable: bool = True,
    ) -> None:
        await ws.send_json(
            {
                "type": "job_status",
                "job_id": job_id,
                "status": status,
                "error_message": error_message,
                "file_size_bytes": file_size_bytes,
                "retryable": retryable,
            }
        )

    def _websocket_url(self) -> str:
        parsed = urlparse(self.server_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        base = urlunparse((scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
        return f"{base}/api/v1/agents/{self.agent_id}/ws"


async def main() -> None:
    await LocalPrintAgent().run_forever()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import os
import re
import shutil
from pathlib import Path
from uuid import uuid4

import aiohttp

from app.core.config import Settings
from app.core.exceptions import DownloadError


SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_part(value: str) -> str:
    return SAFE_NAME_PATTERN.sub("_", value).strip("_") or "unknown"


class DownloadService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pending_dir = Path(settings.pending_dir)
        self.ready_dir = Path(settings.ready_dir)

    async def download(self, job: dict) -> tuple[str, int]:
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.ready_dir.mkdir(parents=True, exist_ok=True)

        order_number = safe_part(str(job["order_number"]))
        user_code = safe_part(str(job["user_code"]))
        temp_path = self.pending_dir / f"{order_number}_{user_code}_{uuid4().hex}.pdf.tmp"
        final_name = f"{order_number}_{user_code}.pdf"
        pdf_url = str(job["pdf_url"])

        try:
            await self._download_to_temp(pdf_url, temp_path)
            await self._validate_pdf(temp_path)
            final_path = await self._atomic_move(temp_path, final_name)
            file_size = await asyncio.to_thread(os.path.getsize, final_path)
            return str(final_path), int(file_size)
        except Exception as exc:
            await asyncio.to_thread(self._safe_unlink, temp_path)
            if isinstance(exc, DownloadError):
                raise
            raise DownloadError(str(exc)) from exc

    async def _download_to_temp(self, url: str, path: Path) -> None:
        timeout = aiohttp.ClientTimeout(
            connect=self.settings.download_timeout_connect,
            sock_read=self.settings.download_timeout_read,
        )
        max_bytes = self.settings.max_pdf_size_mb * 1024 * 1024
        bytes_written = 0

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise DownloadError(f"PDF is larger than {self.settings.max_pdf_size_mb} MB")

                with path.open("wb") as file:
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        bytes_written += len(chunk)
                        if bytes_written > max_bytes:
                            raise DownloadError(f"PDF is larger than {self.settings.max_pdf_size_mb} MB")
                        await asyncio.to_thread(file.write, chunk)

        if bytes_written == 0:
            raise DownloadError("Downloaded file is empty")

    async def _validate_pdf(self, path: Path) -> None:
        def validate() -> None:
            try:
                import fitz

                with fitz.open(path) as document:
                    if document.page_count <= 0:
                        raise DownloadError("PDF has no pages")
            except DownloadError:
                raise
            except Exception as exc:
                raise DownloadError(f"Invalid PDF: {exc}") from exc

        await asyncio.to_thread(validate)

    async def _atomic_move(self, src: Path, final_name: str) -> Path:
        dst = self.ready_dir / final_name

        def move() -> Path:
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))
            return dst

        return await asyncio.to_thread(move)

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


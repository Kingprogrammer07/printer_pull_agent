import asyncio
import time
from pathlib import Path

from app.core.config import Settings
from app.core.logger import get_logger


logger = get_logger(__name__)


class LocalFileCleanup:
    def __init__(self, settings: Settings):
        self.pending_dir = Path(settings.pending_dir)
        self.ready_dir = Path(settings.ready_dir)
        self.retention_hours = max(settings.local_pdf_retention_hours, 0)

    async def cleanup_old_files(self) -> int:
        return await asyncio.to_thread(self._cleanup_old_files)

    async def cleanup_all_files(self) -> int:
        return await asyncio.to_thread(self._cleanup_files, None)

    async def delete_downloaded_pdf(self, path: str) -> bool:
        return await asyncio.to_thread(self._delete_downloaded_pdf, Path(path))

    def _cleanup_old_files(self) -> int:
        cutoff = time.time() - self.retention_hours * 3600
        return self._cleanup_files(cutoff)

    def _cleanup_files(self, cutoff: float | None) -> int:
        deleted = 0
        for directory in (self.pending_dir, self.ready_dir):
            if not directory.exists():
                continue
            for path in directory.iterdir():
                if not path.is_file() or path.suffix.lower() not in {".pdf", ".tmp"}:
                    continue
                try:
                    if cutoff is None or self.retention_hours == 0 or path.stat().st_mtime <= cutoff:
                        path.unlink()
                        deleted += 1
                except OSError as exc:
                    logger.warning("local_pdf_cleanup_failed", path=str(path), error=str(exc))
        if deleted:
            logger.info("local_pdf_cleanup_done", deleted=deleted)
        return deleted

    def _delete_downloaded_pdf(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            allowed_roots = [self.pending_dir.resolve(), self.ready_dir.resolve()]
            if not any(self._is_inside(resolved, root) for root in allowed_roots):
                logger.warning("local_pdf_delete_skipped", path=str(path), reason="outside_download_dirs")
                return False
            if resolved.exists() and resolved.is_file():
                resolved.unlink()
                logger.info("local_pdf_deleted_after_print", path=str(resolved))
                return True
        except OSError as exc:
            logger.warning("local_pdf_delete_failed", path=str(path), error=str(exc))
        return False

    @staticmethod
    def _is_inside(path: Path, root: Path) -> bool:
        return path == root or root in path.parents

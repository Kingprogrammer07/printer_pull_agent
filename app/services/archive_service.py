import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.logger import get_logger

TASHKENT_TZ = ZoneInfo("Asia/Tashkent")


logger = get_logger(__name__)


def cleanup_archive(archive_dir: str, retention_days: int) -> int:
    base = Path(archive_dir)
    if not base.exists():
        return 0

    cutoff = datetime.now(TASHKENT_TZ) - timedelta(days=retention_days)
    deleted = 0
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=TASHKENT_TZ)
        if modified < cutoff:
            path.unlink(missing_ok=True)
            deleted += 1

    for directory in sorted((p for p in base.rglob("*") if p.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass

    logger.info("archive_cleanup_complete", deleted=deleted)
    return deleted


def archive_printed_file(file_path: str, archive_dir: str, printed_at: datetime) -> str:
    src = Path(file_path)
    if not src.exists():
        return file_path
    target_dir = Path(archive_dir) / printed_at.strftime("%Y-%m-%d")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / src.name
    if target.exists():
        target.unlink()
    shutil.move(str(src), str(target))
    return str(target)


import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path


async def create_database_backup(db_path: str, backup_path: str) -> Path:
    source = Path(db_path)
    destination = Path(backup_path)
    if not source.exists():
        raise FileNotFoundError(f"Database topilmadi: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")

    def backup() -> None:
        if temporary.exists():
            temporary.unlink()
        with closing(sqlite3.connect(source)) as source_db, closing(sqlite3.connect(temporary)) as backup_db:
            source_db.backup(backup_db)
        if destination.exists():
            destination.unlink()
        temporary.replace(destination)

    await asyncio.to_thread(backup)
    return destination

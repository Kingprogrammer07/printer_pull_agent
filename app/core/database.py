from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from app.models.db_schema import (
    CREATE_AGENTS_TABLE,
    CREATE_PRINT_JOBS_INDEXES,
    CREATE_PRINT_JOBS_TABLE,
    PRINT_JOBS_MIGRATIONS,
)


PRAGMAS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA synchronous=NORMAL;",
    "PRAGMA foreign_keys=ON;",
    "PRAGMA cache_size=10000;",
)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def initialize(self) -> None:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            for pragma in PRAGMAS:
                await db.execute(pragma)
            await db.execute(CREATE_PRINT_JOBS_TABLE)
            await db.execute(CREATE_AGENTS_TABLE)
            await self._run_migrations(db)
            for statement in CREATE_PRINT_JOBS_INDEXES:
                await db.execute(statement)
            await db.commit()

    async def _run_migrations(self, db: aiosqlite.Connection) -> None:
        cursor = await db.execute("PRAGMA table_info(print_jobs)")
        columns = {row[1] for row in await cursor.fetchall()}
        for column, statement in PRINT_JOBS_MIGRATIONS.items():
            if column not in columns:
                await db.execute(statement)

    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        try:
            await db.execute("PRAGMA foreign_keys=ON;")
            yield db
        finally:
            await db.close()


async def initialize_database(db_path: str) -> Database:
    database = Database(db_path)
    await database.initialize()
    return database

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from app.core.database import initialize_database
from app.repositories.job_repository import JobRepository


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def repo(tmp_path: Path):
    database = await initialize_database(str(tmp_path / "test.db"))
    return JobRepository(database)

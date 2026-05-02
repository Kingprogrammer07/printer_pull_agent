import pytest

from app.services.database_maintenance import create_database_backup


@pytest.mark.asyncio
async def test_create_is_idempotent(repo):
    first = await repo.create(
        {
            "order_number": "ORD-1",
            "user_code": "USR-1",
            "pdf_url": "https://example.com/a.pdf",
        }
    )
    second = await repo.create(
        {
            "order_number": "ORD-1",
            "user_code": "USR-1",
            "pdf_url": "https://example.com/a.pdf",
        }
    )

    assert first["id"] == second["id"]
    assert first["_created"] is True
    assert second["_created"] is False


@pytest.mark.asyncio
async def test_stale_jobs_are_recovered(repo):
    job = await repo.create(
        {
            "order_number": "ORD-2",
            "user_code": "USR-2",
            "pdf_url": "https://example.com/b.pdf",
        }
    )
    await repo.update_status(job["id"], "DOWNLOADING")
    await repo.mark_stale_jobs_pending()

    recovered = await repo.get_by_id(job["id"])
    assert recovered["status"] == "PENDING"


@pytest.mark.asyncio
async def test_retry_failed_job_for_print(repo):
    job = await repo.create(
        {
            "order_number": "ORD-3",
            "user_code": "USR-3",
            "pdf_url": "https://example.com/c.pdf",
        }
    )
    await repo.update_status(job["id"], "FAILED_PERM", retry_count=3, error_message="bad")

    retried = await repo.retry_job_for_print(job["id"])

    assert retried["status"] == "PENDING"
    assert retried["retry_count"] == 0
    assert retried["error_message"] is None


@pytest.mark.asyncio
async def test_cleanup_jobs_by_status(repo):
    failed = await repo.create(
        {
            "order_number": "ORD-4",
            "user_code": "USR-4",
            "pdf_url": "https://example.com/d.pdf",
        }
    )
    pending = await repo.create(
        {
            "order_number": "ORD-5",
            "user_code": "USR-5",
            "pdf_url": "https://example.com/e.pdf",
        }
    )
    await repo.update_status(failed["id"], "FAILED_PERM")

    deleted = await repo.cleanup_jobs(["FAILED_PERM"], older_than_days=0)

    assert deleted == 1
    assert await repo.get_by_id(failed["id"]) is None
    assert await repo.get_by_id(pending["id"]) is not None


@pytest.mark.asyncio
async def test_delete_all_data_removes_jobs_and_agents(repo):
    job = await repo.create(
        {
            "order_number": "ORD-6",
            "user_code": "USR-6",
            "pdf_url": "https://example.com/f.pdf",
            "agent_id": "agent-1",
        }
    )
    await repo.heartbeat_agent("agent-1", printer_name="Xprinter XP-D481B")

    deleted = await repo.delete_all_data()

    assert deleted == {"jobs": 1, "agents": 1}
    assert await repo.get_by_id(job["id"]) is None
    assert await repo.list_agents() == []


@pytest.mark.asyncio
async def test_database_backup_replaces_previous_backup(repo, tmp_path):
    await repo.create(
        {
            "order_number": "ORD-7",
            "user_code": "USR-7",
            "pdf_url": "https://example.com/g.pdf",
        }
    )
    backup_path = tmp_path / "backups" / "latest.db"

    first_backup = await create_database_backup(repo.database.db_path, str(backup_path))
    backup_path.write_text("old backup", encoding="utf-8")
    second_backup = await create_database_backup(repo.database.db_path, str(backup_path))

    assert first_backup == second_backup
    assert backup_path.read_bytes() != b"old backup"

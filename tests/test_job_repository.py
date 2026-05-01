import pytest


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


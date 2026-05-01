import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any, AsyncIterator

import aiosqlite

from app.core.database import Database
from app.repositories.base import BaseRepository


RETRY_DELAYS_SECONDS = [5, 15, 45]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


class JobRepository(BaseRepository):
    def __init__(self, database: Database):
        self.database = database

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async for db in self.database.connect():
            yield db

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        order_number = data["order_number"]
        user_code = data["user_code"]
        pdf_url = str(data["pdf_url"])
        agent_id = data.get("agent_id")
        async with self._connect() as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO print_jobs (order_number, user_code, pdf_url, agent_id)
                VALUES (?, ?, ?, ?)
                """,
                (order_number, user_code, pdf_url, agent_id),
            )
            created = cursor.rowcount == 1
            await db.commit()
            row = await self._get_by_order_user(db, order_number, user_code)
            result = row_to_dict(row)
            if result is None:
                raise RuntimeError("Job insert/select failed")
            result["_created"] = created
            return result

    async def get_by_id(self, id: int) -> dict[str, Any] | None:
        async with self._connect() as db:
            row = await self._get_by_id(db, id)
            return row_to_dict(row)

    async def get_pending_for_download(self, limit: int = 5) -> list[dict[str, Any]]:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM print_jobs
                WHERE status = 'PENDING'
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_failed_ready_for_retry(self) -> list[dict[str, Any]]:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM print_jobs
                WHERE status = 'FAILED'
                  AND next_retry_at IS NOT NULL
                  AND next_retry_at <= ?
                ORDER BY next_retry_at ASC, id ASC
                """,
                (utc_now(),),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_downloaded_for_print(self) -> dict[str, Any] | None:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM print_jobs
                WHERE status IN ('DOWNLOADED', 'QUEUED')
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """
            )
            return row_to_dict(await cursor.fetchone())

    async def update_status(self, id: int, status: str, **kwargs: Any) -> dict[str, Any] | None:
        data = dict(kwargs)
        data["status"] = status
        data["updated_at"] = utc_now()
        return await self.update_fields(id, **data)

    async def update_fields(self, id: int, **kwargs: Any) -> dict[str, Any] | None:
        allowed = {
            "status",
            "agent_id",
            "claimed_at",
            "locked_until",
            "retry_count",
            "next_retry_at",
            "error_message",
            "file_path",
            "file_size_bytes",
            "updated_at",
            "downloaded_at",
            "printed_at",
        }
        fields = {key: value for key, value in kwargs.items() if key in allowed}
        if "updated_at" not in fields:
            fields["updated_at"] = utc_now()
        if not fields:
            return await self.get_by_id(id)

        assignments = ", ".join(f"{field} = ?" for field in fields)
        values = list(fields.values()) + [id]
        async with self._connect() as db:
            await db.execute(f"UPDATE print_jobs SET {assignments} WHERE id = ?", values)
            await db.commit()
            return row_to_dict(await self._get_by_id(db, id))

    async def get_paginated(
        self,
        page: int,
        limit: int,
        status: str | None = None,
        order_number: str | None = None,
        user_code: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        page = max(page, 1)
        limit = min(max(limit, 1), 100)
        offset = (page - 1) * limit
        clauses: list[str] = []
        params: list[Any] = []

        if status:
            clauses.append("status = ?")
            params.append(status)
        if order_number:
            clauses.append("order_number = ?")
            params.append(order_number)
        if user_code:
            clauses.append("user_code = ?")
            params.append(user_code)
        if date_from:
            clauses.append("date(created_at) >= date(?)")
            params.append(date_from)
        if date_to:
            clauses.append("date(created_at) <= date(?)")
            params.append(date_to)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._connect() as db:
            count_cursor = await db.execute(f"SELECT COUNT(*) AS total FROM print_jobs {where}", params)
            total = int((await count_cursor.fetchone())["total"])
            cursor = await db.execute(
                f"""
                SELECT * FROM print_jobs
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            )
            rows = await cursor.fetchall()

        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": ceil(total / limit) if total else 0,
        }

    async def recent_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM print_jobs
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def get_stats(self) -> dict[str, Any]:
        async with self._connect() as db:
            total_cursor = await db.execute("SELECT COUNT(*) AS total FROM print_jobs")
            total = int((await total_cursor.fetchone())["total"])

            status_cursor = await db.execute(
                "SELECT status, COUNT(*) AS count FROM print_jobs GROUP BY status"
            )
            by_status = {row["status"]: int(row["count"]) for row in await status_cursor.fetchall()}

            printed_cursor = await db.execute(
                """
                SELECT COUNT(*) AS count FROM print_jobs
                WHERE status = 'PRINTED' AND date(printed_at) = date('now')
                """
            )
            today_printed = int((await printed_cursor.fetchone())["count"])

            failed_cursor = await db.execute(
                """
                SELECT COUNT(*) AS count FROM print_jobs
                WHERE status IN ('FAILED', 'FAILED_PERM') AND date(updated_at) = date('now')
                """
            )
            today_failed = int((await failed_cursor.fetchone())["count"])

            queue_cursor = await db.execute(
                """
                SELECT COUNT(*) AS count FROM print_jobs
                WHERE status IN ('PENDING', 'CLAIMED', 'DOWNLOADING', 'PRINTING', 'PRINTER_OFFLINE', 'FAILED')
                """
            )
            queue_depth = int((await queue_cursor.fetchone())["count"])

            agents_cursor = await db.execute(
                """
                SELECT COUNT(*) AS count FROM print_agents
                WHERE is_online = 1
                """
            )
            agents_online = int((await agents_cursor.fetchone())["count"])

        return {
            "total": total,
            "by_status": by_status,
            "today_printed": today_printed,
            "today_failed": today_failed,
            "queue_depth": queue_depth,
            "agents_online": agents_online,
        }

    async def mark_stale_jobs_pending(self) -> None:
        now = utc_now()
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE print_jobs
                SET status = 'PENDING',
                    updated_at = ?,
                    error_message = NULL,
                    locked_until = NULL
                WHERE status IN ('CLAIMED', 'DOWNLOADING')
                  AND (locked_until IS NULL OR locked_until <= ?)
                """,
                (now, now),
            )
            await db.execute(
                """
                UPDATE print_jobs
                SET status = 'PENDING',
                    updated_at = ?,
                    locked_until = NULL
                WHERE status = 'PRINTING'
                  AND (locked_until IS NULL OR locked_until <= ?)
                """,
                (now, now),
            )
            await db.execute(
                """
                UPDATE print_agents
                SET is_online = 0, updated_at = ?
                WHERE last_seen_at IS NOT NULL
                  AND last_seen_at <= datetime('now', '-30 seconds')
                """,
                (now,),
            )
            await db.commit()

    async def claim_next_for_agent(self, agent_id: str, lease_seconds: int = 90) -> dict[str, Any] | None:
        now = utc_now()
        locked_until = self._timestamp_after(lease_seconds)
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT * FROM print_jobs
                WHERE status IN ('PENDING', 'FAILED')
                  AND (agent_id IS NULL OR agent_id = ?)
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
                  AND (locked_until IS NULL OR locked_until <= ?)
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (agent_id, now, now),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.commit()
                return None

            await db.execute(
                """
                UPDATE print_jobs
                SET status = 'CLAIMED',
                    agent_id = ?,
                    claimed_at = ?,
                    locked_until = ?,
                    updated_at = ?,
                    error_message = NULL
                WHERE id = ?
                """,
                (agent_id, now, locked_until, now, row["id"]),
            )
            await db.commit()
            return row_to_dict(await self._get_by_id(db, int(row["id"])))

    async def update_agent_job_status(
        self,
        agent_id: str,
        job_id: int,
        status: str,
        *,
        error_message: str | None = None,
        file_size_bytes: int | None = None,
        retryable: bool = True,
    ) -> dict[str, Any] | None:
        now = utc_now()
        async with self._connect() as db:
            row = await self._get_by_id(db, job_id)
            if row is None or row["agent_id"] != agent_id:
                return None

            values: dict[str, Any] = {
                "status": status,
                "updated_at": now,
                "error_message": error_message,
            }
            if file_size_bytes is not None:
                values["file_size_bytes"] = file_size_bytes

            if status == "DOWNLOADING":
                values["locked_until"] = self._timestamp_after(120)
            elif status == "PRINTING":
                values["locked_until"] = self._timestamp_after(180)
            elif status == "PRINTED":
                values["printed_at"] = now
                values["locked_until"] = None
                values["next_retry_at"] = None
            elif status == "PRINTER_OFFLINE":
                values["locked_until"] = None
            elif status == "FAILED":
                retry_count = int(row["retry_count"] or 0) + 1
                values["retry_count"] = retry_count
                values["locked_until"] = None
                if retryable and retry_count < len(RETRY_DELAYS_SECONDS) + 1:
                    values["next_retry_at"] = self._retry_timestamp(retry_count)
                    values["status"] = "FAILED"
                else:
                    values["next_retry_at"] = None
                    values["status"] = "FAILED_PERM"

            assignments = ", ".join(f"{key} = ?" for key in values)
            await db.execute(
                f"UPDATE print_jobs SET {assignments} WHERE id = ?",
                list(values.values()) + [job_id],
            )
            await db.commit()
            return row_to_dict(await self._get_by_id(db, job_id))

    async def heartbeat_agent(
        self,
        agent_id: str,
        *,
        printer_name: str | None = None,
        printer_status: str = "UNKNOWN",
        details: dict[str, Any] | None = None,
        is_online: bool = True,
    ) -> dict[str, Any]:
        now = utc_now()
        details_json = json.dumps(details or {}, ensure_ascii=True)
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO print_agents (
                    agent_id, printer_name, printer_status, details_json,
                    is_online, last_seen_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    printer_name = excluded.printer_name,
                    printer_status = excluded.printer_status,
                    details_json = excluded.details_json,
                    is_online = excluded.is_online,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (agent_id, printer_name, printer_status, details_json, int(is_online), now, now),
            )
            await db.commit()
            row = await self._get_agent(db, agent_id)
            result = self._agent_row_to_dict(row)
            if result is None:
                raise RuntimeError("Agent heartbeat failed")
            return result

    async def mark_agent_offline(self, agent_id: str) -> None:
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE print_agents
                SET is_online = 0, updated_at = ?
                WHERE agent_id = ?
                """,
                (utc_now(), agent_id),
            )
            await db.commit()

    async def list_agents(self) -> list[dict[str, Any]]:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM print_agents
                ORDER BY is_online DESC, updated_at DESC
                """
            )
            return [self._agent_row_to_dict(row) for row in await cursor.fetchall()]

    async def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        async with self._connect() as db:
            return self._agent_row_to_dict(await self._get_agent(db, agent_id))

    async def get_latest_printer_status(self) -> dict[str, Any]:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM print_agents
                ORDER BY is_online DESC, last_seen_at DESC
                LIMIT 1
                """
            )
            agent = self._agent_row_to_dict(await cursor.fetchone())
            if agent is None:
                return {"name": "No agent connected", "status": "UNKNOWN", "details": {}}
            return {
                "name": agent.get("printer_name") or agent["agent_id"],
                "status": agent.get("printer_status") or "UNKNOWN",
                "details": {
                    **(agent.get("details") or {}),
                    "agent_id": agent["agent_id"],
                    "is_online": agent["is_online"],
                    "last_seen_at": agent["last_seen_at"],
                },
            }

    async def requeue_printer_offline_jobs(self) -> int:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                UPDATE print_jobs
                SET status = 'PENDING', updated_at = ?, locked_until = NULL
                WHERE status = 'PRINTER_OFFLINE'
                """,
                (utc_now(),),
            )
            await db.commit()
            return cursor.rowcount

    async def pause_printing_jobs(self) -> int:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                UPDATE print_jobs
                SET status = 'PRINTER_OFFLINE', updated_at = ?, locked_until = NULL
                WHERE status = 'PRINTING'
                """,
                (utc_now(),),
            )
            await db.commit()
            return cursor.rowcount

    async def _get_by_id(self, db: aiosqlite.Connection, id: int) -> aiosqlite.Row | None:
        cursor = await db.execute("SELECT * FROM print_jobs WHERE id = ?", (id,))
        return await cursor.fetchone()

    async def _get_by_order_user(
        self, db: aiosqlite.Connection, order_number: str, user_code: str
    ) -> aiosqlite.Row | None:
        cursor = await db.execute(
            "SELECT * FROM print_jobs WHERE order_number = ? AND user_code = ?",
            (order_number, user_code),
        )
        return await cursor.fetchone()

    async def _get_agent(self, db: aiosqlite.Connection, agent_id: str) -> aiosqlite.Row | None:
        cursor = await db.execute("SELECT * FROM print_agents WHERE agent_id = ?", (agent_id,))
        return await cursor.fetchone()

    @staticmethod
    def _agent_row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["is_online"] = bool(data["is_online"])
        try:
            data["details"] = json.loads(data.pop("details_json") or "{}")
        except json.JSONDecodeError:
            data["details"] = {}
        return data

    @staticmethod
    def _timestamp_after(seconds: int) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()

    @staticmethod
    def _retry_timestamp(retry_count: int) -> str:
        delay = RETRY_DELAYS_SECONDS[min(max(retry_count - 1, 0), len(RETRY_DELAYS_SECONDS) - 1)]
        return (datetime.now(timezone.utc) + timedelta(seconds=delay)).replace(microsecond=0).isoformat()

# type: ignore
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskPayload(BaseModel):
    id: str | None = None
    title: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    is_flexible: bool = False
    done: bool = False
    createdAt: int | None = Field(default=None)


class TaskPatchPayload(BaseModel):
    title: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    is_flexible: bool | None = None
    done: bool | None = None


class TaskSyncPayload(BaseModel):
    tasks: list[TaskPayload] = Field(default_factory=list)
    replace_existing: bool = False


def _millis_to_datetime(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _task_uuid(raw_id: str | None) -> UUID:
    if not raw_id:
        return uuid4()
    try:
        return UUID(raw_id)
    except ValueError:
        # Keep deterministic mapping for non-UUID legacy task identifiers.
        return uuid5(NAMESPACE_URL, f"saidi-task:{raw_id}")


def _parse_task_uuid(raw_id: str) -> UUID:
    try:
        return UUID(raw_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Task id must be a valid UUID.") from exc


def _serialize_task(row: Any) -> dict[str, Any]:
    created_at = row["created_at"]
    created_ms = int(created_at.timestamp() * 1000) if created_at else int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    start_time = row["start_time"]
    end_time = row["end_time"]

    return {
        "id": str(row["id"]),
        "title": row["title"],
        "text": row["title"],
        "start_time": start_time.isoformat() if start_time else None,
        "end_time": end_time.isoformat() if end_time else None,
        "is_flexible": bool(row["is_flexible"]),
        "done": bool(row["done"]),
        "createdAt": created_ms,
    }


def _db_pool_or_503(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="Database is not configured. Set DATABASE_URL to enable task sync.",
        )
    return pool


async def _fetch_all_tasks(pool) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, start_time, end_time, is_flexible, done, created_at
            FROM Tasks
            ORDER BY COALESCE(start_time, created_at) DESC NULLS LAST, created_at DESC
            """
        )
    return [_serialize_task(row) for row in rows]


@router.get("")
async def list_tasks(request: Request):
    pool = _db_pool_or_503(request)
    return await _fetch_all_tasks(pool)


@router.post("")
async def create_task(payload: TaskPayload, request: Request):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Task title is required.")

    pool = _db_pool_or_503(request)
    task_id = _task_uuid(payload.id)
    created_at = _millis_to_datetime(payload.createdAt)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO Tasks (id, title, start_time, end_time, is_flexible, done, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, NOW()))
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time,
                is_flexible = EXCLUDED.is_flexible,
                done = EXCLUDED.done
            RETURNING id, title, start_time, end_time, is_flexible, done, created_at
            """,
            task_id,
            title,
            payload.start_time,
            payload.end_time,
            payload.is_flexible,
            payload.done,
            created_at,
        )

    return _serialize_task(row)


@router.patch("/{task_id}")
async def update_task(task_id: str, payload: TaskPatchPayload, request: Request):
    pool = _db_pool_or_503(request)
    parsed_task_id = _parse_task_uuid(task_id)

    updates: list[str] = []
    values: list[Any] = [parsed_task_id]

    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Task title cannot be empty.")
        updates.append(f"title = ${len(values) + 1}")
        values.append(title)

    if payload.start_time is not None:
        updates.append(f"start_time = ${len(values) + 1}")
        values.append(payload.start_time)

    if payload.end_time is not None:
        updates.append(f"end_time = ${len(values) + 1}")
        values.append(payload.end_time)

    if payload.is_flexible is not None:
        updates.append(f"is_flexible = ${len(values) + 1}")
        values.append(payload.is_flexible)

    if payload.done is not None:
        updates.append(f"done = ${len(values) + 1}")
        values.append(payload.done)

    if not updates:
        raise HTTPException(status_code=400, detail="No task fields provided for update.")

    query = f"""
        UPDATE Tasks
        SET {", ".join(updates)}
        WHERE id = $1
        RETURNING id, title, start_time, end_time, is_flexible, done, created_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *values)

    if row is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    return _serialize_task(row)


@router.delete("/{task_id}")
async def delete_task(task_id: str, request: Request):
    pool = _db_pool_or_503(request)
    parsed_task_id = _parse_task_uuid(task_id)

    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM Tasks WHERE id = $1", parsed_task_id)

    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Task not found.")

    return {"deleted": True, "id": str(parsed_task_id)}


@router.post("/sync")
async def sync_tasks(payload: TaskSyncPayload, request: Request):
    pool = _db_pool_or_503(request)

    normalized_ids: list[UUID] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for task in payload.tasks:
                title = task.title.strip()
                if not title:
                    continue

                task_id = _task_uuid(task.id)
                normalized_ids.append(task_id)

                await conn.execute(
                    """
                    INSERT INTO Tasks (id, title, start_time, end_time, is_flexible, done, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, NOW()))
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        start_time = EXCLUDED.start_time,
                        end_time = EXCLUDED.end_time,
                        is_flexible = EXCLUDED.is_flexible,
                        done = EXCLUDED.done
                    """,
                    task_id,
                    title,
                    task.start_time,
                    task.end_time,
                    task.is_flexible,
                    task.done,
                    _millis_to_datetime(task.createdAt),
                )

            if payload.replace_existing:
                if normalized_ids:
                    await conn.execute("DELETE FROM Tasks WHERE id <> ALL($1::uuid[])", normalized_ids)
                else:
                    await conn.execute("DELETE FROM Tasks")

    return await _fetch_all_tasks(pool)
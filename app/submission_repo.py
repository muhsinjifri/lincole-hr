from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Submission


def parse_jotform_datetime(val: Any) -> datetime | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    s_norm = s.replace(" ", "T", 1)
    try:
        if s_norm.endswith("Z"):
            dt = datetime.fromisoformat(s_norm.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s_norm)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def upsert_submission(session: AsyncSession, form_id: str, payload: dict[str, Any]) -> None:
    sid = str(payload.get("id") or "").strip()
    if not sid:
        return
    created_at = parse_jotform_datetime(payload.get("created_at"))
    insert_stmt = pg_insert(Submission).values(
        jotform_submission_id=sid,
        form_id=form_id,
        created_at=created_at,
        payload=payload,
    )
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[Submission.jotform_submission_id],
        set_={
            "payload": insert_stmt.excluded.payload,
            "form_id": insert_stmt.excluded.form_id,
            "created_at": insert_stmt.excluded.created_at,
        },
    )
    await session.execute(upsert_stmt)


async def upsert_many(session: AsyncSession, form_id: str, payloads: list[dict[str, Any]]) -> None:
    for p in payloads:
        await upsert_submission(session, form_id, p)


async def list_submission_payloads(session: AsyncSession, form_id: str) -> list[dict[str, Any]]:
    q = (
        select(Submission.payload)
        .where(Submission.form_id == form_id)
        .order_by(Submission.created_at.desc().nulls_last(), Submission.jotform_submission_id.desc())
    )
    rows = (await session.execute(q)).all()
    return [row[0] for row in rows]

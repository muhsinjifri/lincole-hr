from __future__ import annotations

import asyncio
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.jotform_service import fetch_all_submissions, fetch_form_questions, fetch_form_title
from app.submission_repo import upsert_many, list_submission_payloads


async def load_dashboard_bundle(
    session: AsyncSession, settings: Settings
) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        questions, submissions_api = await asyncio.gather(
            fetch_form_questions(client, settings),
            fetch_all_submissions(client, settings),
        )
        form_title: str | None = None
        try:
            form_title = await fetch_form_title(client, settings)
        except (httpx.HTTPError, RuntimeError, KeyError, TypeError, ValueError):
            form_title = None

    await upsert_many(session, settings.jotform_form_id, submissions_api)
    await session.commit()
    stored = await list_submission_payloads(session, settings.jotform_form_id)
    return questions, stored, form_title

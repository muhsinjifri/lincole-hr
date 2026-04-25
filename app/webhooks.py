# DEAD MODULE: webhook ingestion is off while the app runs DB-less.
# Re-register this router in main.py when Postgres + event bus come back.
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.event_bus import publish
from app.jotform_service import fetch_submission_by_id
from app.submission_repo import upsert_submission

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/jotform")
async def jotform_webhook(request: Request, session: AsyncSession = Depends(get_session)) -> PlainTextResponse:
    settings = get_settings()
    token = settings.webhook_token
    if token and request.query_params.get("token") != token:
        raise HTTPException(status_code=403, detail="invalid webhook token")

    submission_id: str | None = None
    form_body: str | None = None
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="expected JSON object")
        submission_id = str(body.get("submissionID") or body.get("submission_id") or "").strip() or None
        form_body = str(body.get("formID") or body.get("form_id") or "").strip() or None
    else:
        form_data = await request.form()
        submission_id = str(form_data.get("submissionID") or form_data.get("submission_id") or "").strip() or None
        form_body = str(form_data.get("formID") or form_data.get("form_id") or "").strip() or None

    if form_body and form_body != settings.jotform_form_id:
        raise HTTPException(status_code=400, detail="form mismatch")

    if not submission_id:
        return PlainTextResponse("missing submissionID", status_code=400)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            payload = await fetch_submission_by_id(client, settings, submission_id)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Could not load submission from Jotform: HTTP {e.response.status_code}",
        ) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Jotform request failed: {e}") from e

    await upsert_submission(session, settings.jotform_form_id, payload)
    await session.commit()
    publish({"type": "submission"})
    return PlainTextResponse("ok")

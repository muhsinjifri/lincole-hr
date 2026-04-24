from contextlib import asynccontextmanager
import secrets
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import (
    department_breakdown,
    department_field_candidate,
    resolve_department_field_id,
)
from app.config import Settings, get_settings
from app.dashboard_bundle import load_dashboard_bundle
from app.db import close_db, get_session, init_db
from app.jotform_errors import format_generic_error, format_jotform_http_error
from app.event_bus import publish
from app.jotform_service import (
    build_table,
    extract_upload_files,
    filename_from_upload_url,
    fetch_form_questions,
    fetch_submission_by_id,
    is_safe_jotform_file_url,
    list_form_column_fields,
    list_form_section_fields,
    sniff_media_type,
    update_submission_answer,
    upload_body_looks_like_html,
)
from app.submission_repo import get_payload_by_jotform_id, upsert_submission
from app import realtime as realtime_routes
from app import webhooks as webhooks_routes

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

_HINTS = (
    "Check JOTFORM_API_KEY and JOTFORM_FORM_ID in .env. "
    "If your Jotform account is EU/GDPR, set JOTFORM_API_BASE=https://eu-api.jotform.com/v1 . "
    "Regenerate the API key if it was ever shared or pasted into chat."
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(title="Jotform Admin", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(webhooks_routes.router)
app.include_router(realtime_routes.router)


async def _build_dashboard_context(session: AsyncSession, settings: Settings) -> dict[str, Any]:
    questions, submissions, form_title = await load_dashboard_bundle(session, settings)
    note_editor_enabled = bool(settings.notes_field_id and settings.notes_api_token)
    dept_candidate = department_field_candidate(questions, settings.department_field_id)
    nq = settings.notes_field_id
    if nq and dept_candidate and nq == dept_candidate:
        dept_candidate = None
    department_editor_enabled = bool(settings.notes_api_token and dept_candidate)
    headers, rows = build_table(
        questions,
        submissions,
        settings.field_id_allowlist,
        resume_field_id=settings.resume_field_id,
        upload_proxy=settings.use_upload_proxy,
        append_note_editor_column=note_editor_enabled,
        notes_field_id=settings.notes_field_id,
        append_department_editor_column=department_editor_enabled,
        department_editor_field_id=dept_candidate,
    )
    dept_field = (
        "_dept_ui"
        if department_editor_enabled and dept_candidate
        else resolve_department_field_id(headers, settings.department_field_id)
    )
    dept_stats = department_breakdown(rows, dept_field)
    dept_label = next((lbl for key, lbl in headers if key == dept_field), "Department") if dept_field else ""
    max_dept = max((c for _, c in dept_stats), default=0)
    form_sections = list_form_section_fields(questions)
    form_columns = list_form_column_fields(questions)
    return {
        "headers": headers,
        "rows": rows,
        "form_id": settings.jotform_form_id,
        "form_title": form_title,
        "submission_count": len(rows),
        "dept_stats": dept_stats,
        "dept_field": dept_field,
        "dept_label": dept_label,
        "max_dept": max_dept,
        "form_sections": form_sections,
        "form_columns": form_columns,
        "note_editor_enabled": note_editor_enabled,
        "department_editor_enabled": department_editor_enabled,
    }


@app.get("/", response_class=HTMLResponse)
async def admin_ui(request: Request, session: AsyncSession = Depends(get_session)):
    settings = get_settings()
    try:
        ctx = await _build_dashboard_context(session, settings)
    except httpx.HTTPStatusError as e:
        message = format_jotform_http_error(e)
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": message, "hints": _HINTS},
            status_code=502,
        )
    except (SQLAlchemyError, OSError, RuntimeError) as e:
        message = format_generic_error(e)
        hints = _HINTS + " Also ensure Docker Postgres is running (docker compose up -d) and DATABASE_URL is correct."
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": message, "hints": hints},
            status_code=502,
        )
    except Exception as e:
        message = format_generic_error(e)
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": message, "hints": _HINTS},
            status_code=502,
        )

    note_ed = bool(ctx.get("note_editor_enabled"))
    dept_ed = bool(ctx.get("department_editor_enabled"))
    token = (settings.notes_api_token or "") if (note_ed or dept_ed) else ""
    ctx["note_post_client"] = {
        "enabled": bool(token and (note_ed or dept_ed)),
        "token": token,
        "notes": note_ed,
        "department": dept_ed,
    }
    return templates.TemplateResponse(request, "admin.html", ctx)


@app.get("/api/files/submission/{jotform_submission_id}/{qid}/{file_index:int}")
async def proxy_jotform_upload(
    jotform_submission_id: str,
    qid: str,
    file_index: int,
    disposition: Literal["inline", "attachment"] = Query("inline"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Stream an uploaded file through this app using the Jotform API key (no Jotform web login in the browser)."""
    settings = get_settings()
    payload = await get_payload_by_jotform_id(
        session, settings.jotform_form_id, jotform_submission_id
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="submission not found")
    answers = payload.get("answers") or {}
    files = extract_upload_files(answers.get(str(qid)))
    if file_index < 0 or file_index >= len(files):
        raise HTTPException(status_code=404, detail="file not found")
    url = files[file_index]["url"]
    name = (files[file_index].get("name") or "").strip() or filename_from_upload_url(url)
    name = name.replace('"', "").replace("\\", "")[:200] or "file"
    if not is_safe_jotform_file_url(url):
        raise HTTPException(status_code=400, detail="URL is not an allowed Jotform upload link")
    browser_headers = {
        "APIKEY": settings.jotform_api_key,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/pdf,application/octet-stream,image/*,*/*;q=0.8",
        "Referer": "https://www.jotform.com/",
    }
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        r = await client.get(
            url,
            headers=browser_headers,
            params={"apiKey": settings.jotform_api_key},
        )
    if not r.is_success:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Could not fetch file from Jotform (HTTP {r.status_code}). "
                "If uploads require Jotform login, try turning off that form security option "
                "or set JOTFORM_UPLOAD_PROXY=false to use direct links."
            ),
        )
    body = r.content
    if upload_body_looks_like_html(body):
        raise HTTPException(
            status_code=502,
            detail=(
                "Jotform returned a web page instead of the file (often a login or consent screen). "
                "Try opening the form’s file-upload security settings, or use direct file URLs with "
                "JOTFORM_UPLOAD_PROXY=false while logged into Jotform."
            ),
        )
    ct = sniff_media_type(body, url, r.headers.get("content-type"))
    disp_type = "attachment" if disposition == "attachment" else "inline"
    disp = f'{disp_type}; filename="{name}"'
    out_headers = {
        "Content-Disposition": disp,
        "Cache-Control": "private, max-age=300",
    }
    if ct == "application/pdf":
        out_headers["Accept-Ranges"] = "bytes"
    return Response(content=body, media_type=ct, headers=out_headers)


@app.get("/api/submissions")
async def submissions_json(session: AsyncSession = Depends(get_session)):
    settings = get_settings()
    try:
        ctx = await _build_dashboard_context(session, settings)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=format_jotform_http_error(e)) from e
    except (SQLAlchemyError, OSError, RuntimeError) as e:
        raise HTTPException(status_code=502, detail=format_generic_error(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=format_generic_error(e)) from e

    dept_stats = ctx["dept_stats"]
    return {
        "form_id": ctx["form_id"],
        "form_title": ctx["form_title"],
        "columns": ctx["headers"],
        "rows": ctx["rows"],
        "submission_count": ctx["submission_count"],
        "department_field_id": ctx["dept_field"],
        "department_breakdown": [{"name": n, "count": c} for n, c in dept_stats],
        "form_sections": ctx["form_sections"],
        "form_columns": ctx["form_columns"],
        "note_editor_enabled": ctx["note_editor_enabled"],
        "department_editor_enabled": ctx["department_editor_enabled"],
    }


class SubmissionNoteBody(BaseModel):
    text: str = Field(default="", max_length=8000)


class SubmissionDepartmentBody(BaseModel):
    text: str = Field(default="", max_length=2000)


def _require_dashboard_write_auth(request: Request, settings: Settings) -> None:
    expected = settings.notes_api_token
    if not expected:
        raise HTTPException(
            status_code=501,
            detail="Dashboard write API disabled: set NOTES_API_SECRET in the environment.",
        )
    token = ""
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = (request.query_params.get("token") or "").strip()
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid or missing token for dashboard write endpoint.")


@app.post("/api/submissions/{jotform_submission_id}/notes")
async def post_submission_note(
    jotform_submission_id: str,
    request: Request,
    body: SubmissionNoteBody,
    session: AsyncSession = Depends(get_session),
):
    """Write text into a Jotform field (e.g. a Short Text column named Test) and refresh the local copy."""
    settings = get_settings()
    _require_dashboard_write_auth(request, settings)
    field_id = settings.notes_field_id
    if not field_id:
        raise HTTPException(
            status_code=501,
            detail="Set JOTFORM_NOTES_FIELD_ID to the numeric question id for your notes column (see Form columns tab).",
        )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            current = await fetch_submission_by_id(client, settings, jotform_submission_id)
            form_id = str(current.get("form_id") or "").strip()
            if form_id and form_id != str(settings.jotform_form_id).strip():
                raise HTTPException(status_code=400, detail="Submission does not belong to this form")
            await update_submission_answer(client, settings, jotform_submission_id, field_id, body.text)
            updated = await fetch_submission_by_id(client, settings, jotform_submission_id)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=format_jotform_http_error(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=format_generic_error(e)) from e

    await upsert_submission(session, settings.jotform_form_id, updated)
    await session.commit()
    publish({"type": "submission"})
    return {"ok": True, "jotform_submission_id": str(jotform_submission_id)}


@app.post("/api/submissions/{jotform_submission_id}/department")
async def post_submission_department(
    jotform_submission_id: str,
    request: Request,
    body: SubmissionDepartmentBody,
    session: AsyncSession = Depends(get_session),
):
    """Update the Department answer on Jotform and refresh the local copy (same auth as notes)."""
    settings = get_settings()
    _require_dashboard_write_auth(request, settings)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            questions = await fetch_form_questions(client, settings)
            dept_qid = department_field_candidate(questions, settings.department_field_id)
            if not dept_qid:
                raise HTTPException(
                    status_code=501,
                    detail='No department field found on the form (label containing "Department" or JOTFORM_DEPARTMENT_FIELD_ID).',
                )
            current = await fetch_submission_by_id(client, settings, jotform_submission_id)
            form_id = str(current.get("form_id") or "").strip()
            if form_id and form_id != str(settings.jotform_form_id).strip():
                raise HTTPException(status_code=400, detail="Submission does not belong to this form")
            await update_submission_answer(client, settings, jotform_submission_id, dept_qid, body.text)
            updated = await fetch_submission_by_id(client, settings, jotform_submission_id)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=format_jotform_http_error(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=format_generic_error(e)) from e

    await upsert_submission(session, settings.jotform_form_id, updated)
    await session.commit()
    publish({"type": "submission"})
    return {"ok": True, "jotform_submission_id": str(jotform_submission_id)}

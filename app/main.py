from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import department_breakdown, resolve_department_field_id
from app.config import Settings, get_settings
from app.dashboard_bundle import load_dashboard_bundle
from app.db import close_db, get_session, init_db
from app.jotform_errors import format_generic_error, format_jotform_http_error
from app.jotform_service import build_table
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
    headers, rows = build_table(questions, submissions, settings.field_id_allowlist)
    dept_field = resolve_department_field_id(headers, settings.department_field_id)
    dept_stats = department_breakdown(rows, dept_field)
    dept_label = next((lbl for key, lbl in headers if key == dept_field), "Department") if dept_field else ""
    max_dept = max((c for _, c in dept_stats), default=0)
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

    return templates.TemplateResponse(request, "admin.html", ctx)


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
    }

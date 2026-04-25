from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.jotform_errors import format_generic_error, format_jotform_http_error
from app.jotform_service import (
    extract_upload_files,
    fetch_all_submissions,
    fetch_form_questions,
    fetch_form_title,
    fetch_submission_by_id,
    filename_from_upload_url,
    format_answer_display,
    is_safe_jotform_file_url,
    list_form_column_fields,
    sniff_media_type,
    upload_body_looks_like_html,
)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

_HINTS = (
    "Check JOTFORM_API_KEY and JOTFORM_FORM_ID in .env. "
    "If your Jotform account is EU/GDPR, set JOTFORM_API_BASE=https://eu-api.jotform.com/v1 . "
    "Regenerate the API key if it was ever shared or pasted into chat."
)

_LAYOUT_WIDGETS = {"control_head", "control_collapse", "control_pagebreak"}

app = FastAPI(title="Jotform Admin")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _build_submission_table(
    questions: dict[str, dict[str, Any]],
    submissions: list[dict[str, Any]],
    settings: Settings,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    ordered: list[tuple[int, str]] = []
    for qid, meta in questions.items():
        qtype = str(meta.get("type") or "").lower()
        if qtype in _LAYOUT_WIDGETS:
            continue
        try:
            order = int(meta.get("order", 0))
        except (TypeError, ValueError):
            order = 0
        ordered.append((order, str(qid)))
    ordered.sort(key=lambda t: (t[0], t[1]))

    headers: list[dict[str, str]] = []
    for _, qid in ordered:
        meta = questions.get(qid) or {}
        label = (meta.get("text") or meta.get("name") or f"Field {qid}").strip()
        qtype = str(meta.get("type") or "").lower()
        kind = qtype.removeprefix("control_").replace("_", " ") if qtype.startswith("control_") else qtype
        headers.append({"qid": qid, "label": label, "kind": kind})

    rows: list[dict[str, Any]] = []
    for sub in submissions:
        answers = sub.get("answers") or {}
        sub_id = str(sub.get("id", ""))
        cells: list[dict[str, Any]] = []
        for h in headers:
            qid = h["qid"]
            blob = answers.get(qid)
            files: list[dict[str, str]] = []
            value = ""
            for i, f in enumerate(extract_upload_files(blob)):
                if not is_safe_jotform_file_url(f["url"]):
                    continue
                if settings.use_upload_proxy and sub_id:
                    base = f"/api/files/submission/{sub_id}/{qid}/{i}"
                    files.append(
                        {
                            "name": f["name"],
                            "view_url": f"{base}?disposition=inline",
                            "download_url": f"{base}?disposition=attachment",
                        }
                    )
                else:
                    files.append({"name": f["name"], "view_url": f["url"], "download_url": f["url"]})
            if not files:
                value = format_answer_display(blob)
            cells.append({"value": value, "files": files})
        rows.append(
            {
                "id": sub_id,
                "created_at": str(sub.get("created_at") or ""),
                "cells": cells,
            }
        )
    return headers, rows


async def _load_one_form(
    client: httpx.AsyncClient, settings: Settings, form_id: str
) -> dict[str, Any]:
    questions = await fetch_form_questions(client, settings, form_id)
    submissions = await fetch_all_submissions(client, settings, form_id)
    try:
        form_title = await fetch_form_title(client, settings, form_id)
    except (httpx.HTTPError, RuntimeError, KeyError, TypeError, ValueError):
        form_title = None

    columns = list_form_column_fields(questions)
    sub_headers, sub_rows = _build_submission_table(questions, submissions, settings)
    return {
        "form_id": form_id,
        "form_title": form_title,
        "columns": columns,
        "submission_headers": sub_headers,
        "submission_rows": sub_rows,
        "submission_count": len(sub_rows),
    }


async def _load_form_data(settings: Settings) -> dict[str, Any]:
    form_ids = settings.form_ids
    if not form_ids:
        raise RuntimeError("No JOTFORM_FORM_ID configured")
    async with httpx.AsyncClient(timeout=60.0) as client:
        forms = [await _load_one_form(client, settings, fid) for fid in form_ids]
    return {"forms": forms}


@app.get("/", response_class=HTMLResponse)
async def admin_ui(request: Request):
    settings = get_settings()
    try:
        ctx = await _load_form_data(settings)
    except httpx.HTTPStatusError as e:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": format_jotform_http_error(e), "hints": _HINTS},
            status_code=502,
        )
    except (OSError, RuntimeError) as e:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": format_generic_error(e), "hints": _HINTS},
            status_code=502,
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": format_generic_error(e), "hints": _HINTS},
            status_code=502,
        )
    return templates.TemplateResponse(request, "admin.html", ctx)


@app.get("/api/files/submission/{jotform_submission_id}/{qid}/{file_index:int}")
async def proxy_jotform_upload(
    jotform_submission_id: str,
    qid: str,
    file_index: int,
    disposition: Literal["inline", "attachment"] = Query("inline"),
) -> Response:
    """Stream an uploaded file through this app using the Jotform API key (no Jotform web login in the browser)."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        try:
            payload = await fetch_submission_by_id(client, settings, jotform_submission_id)
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=404, detail="submission not found") from e
        form_id = str(payload.get("form_id") or "").strip()
        if form_id and form_id not in settings.form_ids:
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

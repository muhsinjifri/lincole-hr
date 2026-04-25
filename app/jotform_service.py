from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from app.config import Settings


def _extract_answer_value(answer_blob: Any) -> Any:
    if answer_blob is None:
        return None
    if isinstance(answer_blob, dict) and "answer" in answer_blob:
        return answer_blob.get("answer")
    if isinstance(answer_blob, dict):
        return None
    return answer_blob


def _maybe_parse_json_string(val: Any) -> Any:
    if not isinstance(val, str):
        return val
    s = val.strip()
    if not s or s[0] not in "{[":
        return val
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return val


def filename_from_upload_url(url: str) -> str:
    """Last path segment of an upload URL, for display and download filename."""
    try:
        path = (urlparse(url).path or "").rstrip("/")
        seg = path.split("/")[-1] if path else ""
        seg = unquote(seg).strip()
        return seg if seg else "file"
    except (ValueError, TypeError, AttributeError):
        return "file"


def sniff_media_type(body: bytes, url: str, upstream_content_type: str | None) -> str:
    """Prefer magic bytes / URL extension over Jotform Content-Type (often wrong for inline PDF)."""
    if body.startswith(b"%PDF"):
        return "application/pdf"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"GIF87a") or body.startswith(b"GIF89a"):
        return "image/gif"

    raw = (upstream_content_type or "").split(";")[0].strip()
    rl = raw.lower()
    if raw and rl not in ("text/html", "text/plain", "application/octet-stream"):
        return raw

    path = urlparse(url).path.lower()
    for ext, mime in (
        (".pdf", "application/pdf"),
        (".png", "image/png"),
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".gif", "image/gif"),
        (".webp", "image/webp"),
        (".doc", "application/msword"),
        (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ):
        if path.endswith(ext):
            return mime
    if raw:
        return raw
    return "application/octet-stream"


def upload_body_looks_like_html(body: bytes) -> bool:
    probe = body[:1000].lstrip().lower()
    return probe.startswith(b"<!doctype html") or probe.startswith(b"<html") or probe.startswith(b"<head")


def extract_upload_files(answer_blob: Any) -> list[dict[str, str]]:
    """Jotform file upload answers: list of {name, url} or a single URL/dict."""
    val = _extract_answer_value(answer_blob)
    if val is None:
        return []
    val = _maybe_parse_json_string(val)

    def one_file(obj: Any) -> dict[str, str] | None:
        if isinstance(obj, dict):
            url = obj.get("url") or obj.get("link")
            if isinstance(url, str) and url.strip():
                u = url.strip()
                name = (obj.get("name") or obj.get("fileName") or "").strip()
                if not name:
                    name = filename_from_upload_url(u)
                return {"name": name, "url": u}
        if isinstance(obj, str):
            u = obj.strip()
            if u.lower().startswith(("http://", "https://")):
                return {"name": filename_from_upload_url(u), "url": u}
        return None

    if isinstance(val, list):
        out: list[dict[str, str]] = []
        for item in val:
            f = one_file(item)
            if f:
                out.append(f)
        return out
    f = one_file(val)
    return [f] if f else []


def is_safe_jotform_file_url(url: str) -> bool:
    """Only allow proxying Jotform-hosted upload paths (SSRF guard)."""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if not host or not (host == "jotform.com" or host.endswith(".jotform.com")):
        return False
    path = (p.path or "").lower()
    return "/uploads/" in path or path.startswith("/uploads/")


def detect_resume_field_id(
    questions: dict[str, dict[str, Any]],
    submissions: list[dict[str, Any]],
) -> str | None:
    """Pick the file-upload question without opening Jotform (metadata first, then submission answers)."""
    ranked: list[tuple[int, str]] = []
    for qid, meta in (questions or {}).items():
        t = str(meta.get("type") or "").lower()
        if t != "control_fileupload":
            continue
        try:
            order = int(meta.get("order", 0))
        except (TypeError, ValueError):
            order = 0
        ranked.append((order, str(qid)))
    if ranked:
        ranked.sort(key=lambda t: (t[0], t[1]))
        qids_ordered = [q for _, q in ranked]
        if len(qids_ordered) == 1:
            return qids_ordered[0]
        for _, qid in ranked:
            meta = questions.get(qid) or {}
            label = f"{meta.get('text') or ''} {meta.get('name') or ''}".lower()
            if "resume" in label or " cv" in label or label.strip().startswith("cv"):
                return qid
        return qids_ordered[0]

    counts: dict[str, int] = {}
    for sub in submissions:
        answers = sub.get("answers") or {}
        for qid, blob in answers.items():
            if extract_upload_files(blob):
                qs = str(qid)
                counts[qs] = counts.get(qs, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _resume_file_cells(
    sub_id: str,
    resume_q: str,
    answer_blob: Any,
    *,
    upload_proxy: bool,
) -> list[dict[str, str]]:
    raw = extract_upload_files(answer_blob)
    out: list[dict[str, str]] = []
    for i, f in enumerate(raw):
        if upload_proxy and resume_q and sub_id:
            base = f"/api/files/submission/{sub_id}/{resume_q}/{i}"
            out.append(
                {
                    "name": f["name"],
                    "view_url": f"{base}?disposition=inline",
                    "download_url": f"{base}?disposition=attachment",
                }
            )
        else:
            u = f["url"]
            out.append({"name": f["name"], "view_url": u, "download_url": u})
    return out


def format_answer_display(answer_blob: Any) -> str:
    """Human-readable cell text (names, phones, lists) for the admin UI."""
    val = _extract_answer_value(answer_blob)
    if val is None:
        return ""
    val = _maybe_parse_json_string(val)
    if val is None:
        return ""

    if isinstance(val, dict):
        # Full name widget
        if "first" in val or "last" in val:
            parts = [str(val.get("first") or "").strip(), str(val.get("last") or "").strip()]
            joined = " ".join(p for p in parts if p).strip()
            if joined:
                return joined
        # Phone widget (Jotform often stores {"full": "..."} )
        if isinstance(val.get("full"), str) and val.get("full", "").strip():
            return str(val["full"]).strip()
        if isinstance(val.get("prettyFormat"), str) and val.get("prettyFormat", "").strip():
            return str(val["prettyFormat"]).strip()
        # Address-style pretty lines
        if isinstance(val.get("addr_line1"), str):
            lines = [
                val.get("addr_line1"),
                val.get("addr_line2"),
                val.get("city"),
                val.get("state"),
                val.get("postal"),
            ]
            pretty = ", ".join(str(x).strip() for x in lines if x and str(x).strip())
            if pretty:
                return pretty
        return json.dumps(val, ensure_ascii=False)

    if isinstance(val, list):
        pieces: list[str] = []
        for item in val:
            if isinstance(item, dict) and "text" in item:
                pieces.append(str(item.get("text") or "").strip())
            else:
                pieces.append(format_answer_display({"answer": item}))
        return ", ".join(p for p in pieces if p)

    return str(val).strip()


async def fetch_form_questions(
    client: httpx.AsyncClient, settings: Settings, form_id: str | None = None
) -> dict[str, dict[str, Any]]:
    fid = (form_id or settings.jotform_form_id).strip()
    url = f"{settings.api_base}/form/{fid}/questions"
    r = await client.get(url, params={"apiKey": settings.jotform_api_key})
    r.raise_for_status()
    data = r.json()
    if data.get("responseCode") != 200:
        raise RuntimeError(data.get("message") or "Jotform questions request failed")
    return data.get("content") or {}


async def fetch_all_submissions(
    client: httpx.AsyncClient, settings: Settings, form_id: str | None = None
) -> list[dict[str, Any]]:
    fid = (form_id or settings.jotform_form_id).strip()
    out: list[dict[str, Any]] = []
    offset = 0
    limit = 1000
    while True:
        url = f"{settings.api_base}/form/{fid}/submissions"
        r = await client.get(
            url,
            params={"apiKey": settings.jotform_api_key, "limit": limit, "offset": offset},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("responseCode") != 200:
            raise RuntimeError(data.get("message") or "Jotform submissions request failed")
        chunk = data.get("content") or []
        out.extend(chunk)
        if len(chunk) < limit:
            break
        offset += limit
    return out


def _ordered_question_ids(questions: dict[str, dict[str, Any]]) -> list[str]:
    ranked: list[tuple[int, str]] = []
    for qid, meta in questions.items():
        try:
            order = int(meta.get("order", 0))
        except (TypeError, ValueError):
            order = 0
        ranked.append((order, qid))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [qid for _, qid in ranked]


# Jotform widgets that act as visible section boundaries in the form builder.
_SECTION_WIDGET_LABELS: dict[str, str] = {
    "control_head": "Heading",
    "control_collapse": "Section collapse",
    "control_pagebreak": "Page break",
}


def list_form_section_fields(questions: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Headings, section collapse headers, and page breaks in form order (name + qid for mapping)."""
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for qid, meta in questions.items():
        qtype = str(meta.get("type") or "").lower()
        if qtype not in _SECTION_WIDGET_LABELS:
            continue
        try:
            order = int(meta.get("order", 0))
        except (TypeError, ValueError):
            order = 0
        ranked.append((order, str(qid), meta))
    ranked.sort(key=lambda t: (t[0], t[1]))
    out: list[dict[str, str]] = []
    for _order, qid, meta in ranked:
        qtype = str(meta.get("type") or "").lower()
        kind = _SECTION_WIDGET_LABELS.get(qtype, qtype)
        title = (meta.get("text") or meta.get("name") or "").strip()
        if not title:
            title = kind
        out.append({"qid": qid, "name": title, "kind": kind})
    return out


def list_form_column_fields(questions: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """All form fields in builder order: display label, Jotform qid, and widget type (for .env / API mapping)."""
    out: list[dict[str, str]] = []
    for qid in _ordered_question_ids(questions):
        meta = questions.get(qid) or {}
        label = (meta.get("text") or meta.get("name") or f"Field {qid}").strip()
        raw_type = str(meta.get("type") or "").strip().lower()
        if raw_type.startswith("control_"):
            kind = raw_type.removeprefix("control_").replace("_", " ")
        else:
            kind = raw_type.replace("_", " ") if raw_type else "field"
        out.append({"qid": str(qid), "name": label, "kind": kind})
    return out


def resolve_column_ids(
    questions: dict[str, dict[str, Any]],
    submissions: list[dict[str, Any]],
    allowlist: set[str] | None,
) -> list[str]:
    if allowlist is not None:
        return sorted(allowlist, key=lambda x: int(x) if x.isdigit() else x)

    if questions:
        return _ordered_question_ids(questions)

    # Fallback: keys from first submission
    if not submissions:
        return []
    answers = submissions[0].get("answers") or {}
    return sorted(answers.keys(), key=lambda x: int(x) if str(x).isdigit() else x)


def build_table(
    questions: dict[str, dict[str, Any]],
    submissions: list[dict[str, Any]],
    allowlist: set[str] | None,
    resume_field_id: str | None = None,
    upload_proxy: bool = True,
    *,
    append_note_editor_column: bool = False,
    notes_field_id: str | None = None,
    append_department_editor_column: bool = False,
    department_editor_field_id: str | None = None,
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    column_ids = resolve_column_ids(questions, submissions, allowlist)
    resume_q = (resume_field_id or "").strip() or None
    if not resume_q:
        resume_q = detect_resume_field_id(questions, submissions)
    if resume_q and resume_q in column_ids:
        column_ids = [q for q in column_ids if q != resume_q]

    note_q = (notes_field_id or "").strip() or None
    dept_edit_q = (department_editor_field_id or "").strip() or None
    if append_department_editor_column and dept_edit_q and dept_edit_q in column_ids:
        column_ids = [q for q in column_ids if q != dept_edit_q]
    if append_note_editor_column and note_q and note_q in column_ids:
        column_ids = [q for q in column_ids if q != note_q]

    headers: list[tuple[str, str]] = [
        ("_id", "Submission ID"),
        ("created_at", "Submitted"),
    ]
    if resume_q:
        meta_r = questions.get(resume_q) or {}
        resume_label = (meta_r.get("text") or meta_r.get("name") or "Resume").strip() or "Resume"
        headers.append(("_resume", resume_label))

    for qid in column_ids:
        meta = questions.get(qid) or {}
        label = (meta.get("text") or meta.get("name") or f"Field {qid}").strip()
        headers.append((qid, label))

    if append_department_editor_column and dept_edit_q:
        meta_d = questions.get(dept_edit_q) or {}
        dept_hdr = (meta_d.get("text") or meta_d.get("name") or "Department").strip() or "Department"
        headers.append(("_dept_ui", dept_hdr))
    if append_note_editor_column and note_q:
        meta_n = questions.get(note_q) or {}
        note_label = (meta_n.get("text") or meta_n.get("name") or "Note").strip() or "Note"
        headers.append(("_note_ui", note_label))

    rows: list[dict[str, Any]] = []
    for sub in submissions:
        answers = sub.get("answers") or {}
        row: dict[str, Any] = {
            "_id": str(sub.get("id", "")),
            "created_at": str(sub.get("created_at", "") or ""),
        }
        if resume_q:
            row["_resume"] = _resume_file_cells(
                str(sub.get("id", "")),
                resume_q,
                answers.get(resume_q),
                upload_proxy=upload_proxy,
            )
        for qid in column_ids:
            row[qid] = format_answer_display(answers.get(qid))
        if append_department_editor_column and dept_edit_q:
            row["_dept_ui"] = format_answer_display(answers.get(str(dept_edit_q)))
        if append_note_editor_column and note_q:
            row["_note_ui"] = format_answer_display(answers.get(str(note_q)))
        rows.append(row)

    return headers, rows


async def fetch_submission_by_id(
    client: httpx.AsyncClient, settings: Settings, submission_id: str
) -> dict[str, Any]:
    url = f"{settings.api_base}/submission/{submission_id}"
    r = await client.get(url, params={"apiKey": settings.jotform_api_key})
    r.raise_for_status()
    data = r.json()
    if data.get("responseCode") != 200:
        raise RuntimeError(data.get("message") or "Jotform submission request failed")
    content = data.get("content")
    if not isinstance(content, dict):
        raise RuntimeError("Unexpected submission response shape")
    return content


async def update_submission_answer(
    client: httpx.AsyncClient,
    settings: Settings,
    submission_id: str,
    field_qid: str,
    text: str,
) -> None:
    """Set a single answer on an existing submission (syncs to Jotform Tables if the column maps to this field)."""
    qid = str(field_qid).strip()
    if not qid.isdigit():
        raise ValueError("field_qid must be a numeric Jotform question id")
    sid = str(submission_id).strip()
    if not sid:
        raise ValueError("submission_id is required")
    url = f"{settings.api_base}/submission/{sid}"
    r = await client.post(
        url,
        params={"apiKey": settings.jotform_api_key},
        data={f"submission[{qid}]": text},
    )
    r.raise_for_status()
    try:
        data = r.json()
    except (json.JSONDecodeError, TypeError, ValueError):
        data = {}
    if isinstance(data, dict) and data.get("responseCode") not in (200, None):
        raise RuntimeError(data.get("message") or "Jotform rejected submission update")


async def fetch_form_title(
    client: httpx.AsyncClient, settings: Settings, form_id: str | None = None
) -> str | None:
    fid = (form_id or settings.jotform_form_id).strip()
    url = f"{settings.api_base}/form/{fid}"
    r = await client.get(url, params={"apiKey": settings.jotform_api_key})
    r.raise_for_status()
    data = r.json()
    if data.get("responseCode") != 200:
        return None
    content = data.get("content") or {}
    title = (content.get("title") or "").strip()
    return title or None

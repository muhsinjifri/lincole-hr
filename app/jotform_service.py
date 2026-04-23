from __future__ import annotations

import json
from typing import Any

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


async def fetch_form_questions(client: httpx.AsyncClient, settings: Settings) -> dict[str, dict[str, Any]]:
    url = f"{settings.api_base}/form/{settings.jotform_form_id}/questions"
    r = await client.get(url, params={"apiKey": settings.jotform_api_key})
    r.raise_for_status()
    data = r.json()
    if data.get("responseCode") != 200:
        raise RuntimeError(data.get("message") or "Jotform questions request failed")
    return data.get("content") or {}


async def fetch_all_submissions(client: httpx.AsyncClient, settings: Settings) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    limit = 1000
    while True:
        url = f"{settings.api_base}/form/{settings.jotform_form_id}/submissions"
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
) -> tuple[list[tuple[str, str]], list[dict[str, str]]]:
    column_ids = resolve_column_ids(questions, submissions, allowlist)

    headers: list[tuple[str, str]] = [
        ("_id", "Submission ID"),
        ("created_at", "Submitted"),
    ]
    for qid in column_ids:
        meta = questions.get(qid) or {}
        label = (meta.get("text") or meta.get("name") or f"Field {qid}").strip()
        headers.append((qid, label))

    rows: list[dict[str, str]] = []
    for sub in submissions:
        answers = sub.get("answers") or {}
        row: dict[str, str] = {
            "_id": str(sub.get("id", "")),
            "created_at": str(sub.get("created_at", "") or ""),
        }
        for qid in column_ids:
            row[qid] = format_answer_display(answers.get(qid))
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


async def fetch_form_title(client: httpx.AsyncClient, settings: Settings) -> str | None:
    url = f"{settings.api_base}/form/{settings.jotform_form_id}"
    r = await client.get(url, params={"apiKey": settings.jotform_api_key})
    r.raise_for_status()
    data = r.json()
    if data.get("responseCode") != 200:
        return None
    content = data.get("content") or {}
    title = (content.get("title") or "").strip()
    return title or None

from __future__ import annotations

from collections import Counter
from typing import Any


def department_field_candidate(
    questions: dict[str, dict[str, Any]],
    explicit_id: str | None,
) -> str | None:
    """Pick department question id from form metadata (works even if JOTFORM_FIELD_IDS hides the column)."""
    if explicit_id:
        e = explicit_id.strip()
        if e in questions:
            return e
    for qid, meta in questions.items():
        label = f"{meta.get('text') or ''} {meta.get('name') or ''}".lower()
        if "department" in label:
            return str(qid)
    return None


def resolve_department_field_id(
    headers: list[tuple[str, str]],
    explicit_id: str | None,
) -> str | None:
    if explicit_id:
        e = explicit_id.strip()
        keys = {k for k, _ in headers}
        if e in keys:
            return e
    for key, label in headers:
        if key in ("_id", "created_at", "_resume", "_note_ui"):
            continue
        if "department" in label.lower():
            return key
    return None


def department_breakdown(rows: list[dict[str, str]], dept_field: str | None) -> list[tuple[str, int]]:
    if not dept_field or not rows:
        return []
    counts: Counter[str] = Counter()
    for row in rows:
        cell = row.get(dept_field)
        raw = cell.strip() if isinstance(cell, str) else ""
        key = raw if raw else "— Unspecified —"
        counts[key] += 1
    return sorted(counts.items(), key=lambda t: (-t[1], t[0].lower()))

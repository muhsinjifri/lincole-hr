from __future__ import annotations

from collections import Counter


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
        if key in ("_id", "created_at"):
            continue
        if "department" in label.lower():
            return key
    return None


def department_breakdown(rows: list[dict[str, str]], dept_field: str | None) -> list[tuple[str, int]]:
    if not dept_field or not rows:
        return []
    counts: Counter[str] = Counter()
    for row in rows:
        raw = (row.get(dept_field) or "").strip()
        key = raw if raw else "— Unspecified —"
        counts[key] += 1
    return sorted(counts.items(), key=lambda t: (-t[1], t[0].lower()))

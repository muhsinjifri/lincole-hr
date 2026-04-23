from __future__ import annotations

import json

import httpx


def format_jotform_http_error(exc: httpx.HTTPStatusError) -> str:
    r = exc.response
    body = (r.text or "")[:4000]
    try:
        data = r.json()
        msg = data.get("message") or data.get("error")
        if msg:
            return f"Jotform HTTP {r.status_code}: {msg}"
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return f"Jotform HTTP {r.status_code}: {body or '(empty body)'}"


def format_generic_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"

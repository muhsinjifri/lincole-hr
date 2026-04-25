# DEAD MODULE: in-process pub/sub for the SSE stream — orphaned while realtime.py and webhooks.py are dead.
from __future__ import annotations

import asyncio
import json
from typing import Any

_queues: list[asyncio.Queue[str]] = []


def subscribe() -> asyncio.Queue[str]:
    q: asyncio.Queue[str] = asyncio.Queue()
    _queues.append(q)
    return q


def unsubscribe(q: asyncio.Queue[str]) -> None:
    if q in _queues:
        _queues.remove(q)


def publish(data: dict[str, Any]) -> None:
    text = json.dumps(data)
    for q in list(_queues):
        try:
            q.put_nowait(text)
        except Exception:
            pass

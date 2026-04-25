# DEAD MODULE: SSE stream is unused now that the dashboard renders server-side on each page load.
# Re-include the router in main.py if live updates come back.
from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.event_bus import subscribe, unsubscribe

router = APIRouter(tags=["realtime"])


@router.get("/api/events/stream")
async def submission_events() -> StreamingResponse:
    async def gen():
        q = subscribe()
        try:
            yield f"data: {json.dumps({'type': 'ready'})}\n\n"
            while True:
                msg = await q.get()
                yield f"data: {msg}\n\n"
        finally:
            unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

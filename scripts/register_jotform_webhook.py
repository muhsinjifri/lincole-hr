from __future__ import annotations

import asyncio
import os
import sys

import httpx

from app.config import get_settings


def _build_target_url(public_base: str, token: str | None) -> str:
    base = public_base.strip().rstrip("/")
    if not base.startswith("http://") and not base.startswith("https://"):
        raise SystemExit("PUBLIC_BASE_URL must start with http:// or https://")
    url = f"{base}/webhooks/jotform"
    if token:
        url = f"{url}?token={token}"
    return url


async def _run() -> int:
    settings = get_settings()
    public_base = (os.getenv("PUBLIC_BASE_URL") or "").strip()
    if not public_base:
        raise SystemExit("Missing PUBLIC_BASE_URL (example: https://xxxx.ngrok-free.app)")

    webhook_url = _build_target_url(public_base, settings.webhook_token)
    api_url = f"{settings.api_base}/form/{settings.jotform_form_id}/webhooks"

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(api_url, data={"webhookURL": webhook_url, "apiKey": settings.jotform_api_key})
        r.raise_for_status()
        data = r.json()

    if data.get("responseCode") != 200:
        msg = data.get("message") or f"Unexpected response: {data}"
        raise SystemExit(f"Jotform API error: {msg}")

    print("Webhook created/updated:")
    print(f"- Jotform form: {settings.jotform_form_id}")
    print(f"- Webhook URL:  {webhook_url}")
    return 0


def main() -> None:
    try:
        raise SystemExit(asyncio.run(_run()))
    except httpx.HTTPStatusError as e:
        body = e.response.text
        raise SystemExit(f"HTTP {e.response.status_code} from Jotform API: {body}") from e


if __name__ == "__main__":
    main()

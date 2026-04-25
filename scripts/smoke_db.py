# DEAD SCRIPT: Postgres smoke test — unused while the app runs without a database.
import asyncio
import os

# Allow running without a populated .env (CI / smoke).
os.environ.setdefault("JOTFORM_API_KEY", "dummy")
os.environ.setdefault("JOTFORM_FORM_ID", "dummy")

from app.db import close_db, get_session, init_db
from app.submission_repo import list_submission_payloads, upsert_submission


async def main() -> None:
    await init_db()
    async for session in get_session():
        await upsert_submission(
            session,
            "testform",
            {"id": "1", "created_at": "2026-04-23 12:00:00", "answers": {}},
        )
        await session.commit()
        rows = await list_submission_payloads(session, "testform")
        print("rows", len(rows), rows[0].get("id"))
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())

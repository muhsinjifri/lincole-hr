# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this app is

A single-form Jotform read-only admin dashboard. The root page fetches one form's questions and submissions from the Jotform REST API on every page load and renders them server-side with Jinja2. There is no user auth — protect the URL at the network layer.

## Run / develop

```bash
# deps
pip install -r requirements.txt

# start the dev server (SSR, no build step)
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000/. There is no test suite, no linter config, and no frontend toolchain — static assets in `static/` are served as-is.

Required env vars (see `.env.example` for the full list, but the app currently only reads these):
- `JOTFORM_API_KEY` — Jotform API key (Read scope is enough)
- `JOTFORM_FORM_ID` — the form to display
- `JOTFORM_API_BASE` *(optional)* — default `https://api.jotform.com/v1`; use `https://eu-api.jotform.com/v1` for EU/GDPR accounts
- `JOTFORM_UPLOAD_PROXY` *(optional, default true)* — when true, file links go through `/api/files/...` so the API key stays server-side

Other vars in `.env.example` (`DATABASE_URL`, `WEBHOOK_SECRET`, `NOTES_API_SECRET`, `JOTFORM_*_FIELD_ID`, etc.) are still declared in `app/config.py` but **not read anywhere** — they belong to the dead modules described below.

## Architecture (what actually runs)

Request flow for `GET /`:

1. `app/main.py::admin_ui` calls `_load_form_data()`
2. `_load_form_data` makes three Jotform API calls via `app/jotform_service.py`:
   - `fetch_form_questions` → `/form/{id}/questions` (field metadata, keyed by QID)
   - `fetch_all_submissions` → paginated `/form/{id}/submissions`
   - `fetch_form_title` → `/form/{id}` (best-effort, swallowed on failure)
3. `list_form_column_fields(questions)` produces the **Form columns** view model (label + QID + widget type)
4. `_build_submission_cards` walks each submission, skips layout widgets (`control_head`, `control_collapse`, `control_pagebreak`), formats values via `format_answer_display`, and expands `control_fileupload` answers into proxied view/download URLs
5. `templates/admin.html` renders two sections (columns table, submission cards); CSS in `static/admin.css`

The only other live route is `GET /api/files/submission/{submission_id}/{qid}/{file_index}`, which re-fetches the submission from Jotform, validates the URL is a real Jotform upload (`is_safe_jotform_file_url` SSRF guard), and streams the bytes through with a sniffed Content-Type. `upload_body_looks_like_html` catches the "Jotform returned a login page" failure mode.

## Dead modules (do not import from main.py)

These files exist on disk with a `# DEAD MODULE` header comment. They are the remnants of an earlier DB-backed + webhook + write-endpoint design. Re-enable by wiring them back into `app/main.py`; do not quietly resurrect them.

- `app/db.py`, `app/models.py`, `app/submission_repo.py`, `app/dashboard_bundle.py` — Postgres mirror of submissions (SQLAlchemy async + asyncpg)
- `app/webhooks.py`, `app/realtime.py`, `app/event_bus.py` — Jotform webhook ingestion + SSE stream for live updates
- `app/analytics.py` — department field detection / breakdown counts
- `scripts/register_jotform_webhook.py`, `scripts/smoke_db.py` — companion scripts
- `static/dashboard.js` — client-side SSE consumer and note/department save wiring; no longer referenced from `admin.html`

`docker-compose.yml` (Postgres 16) is also only relevant if the DB layer is revived.

## Conventions worth knowing

- **Everything keys off Jotform QIDs (numeric strings).** `questions` is `dict[qid_str, meta_dict]`; submission `answers` is `dict[qid_str, answer_blob]`. Ordering comes from `meta["order"]`. When you need "form builder order", sort by `(int(order), qid)`.
- **Answer shapes vary by widget.** `format_answer_display` handles name/phone/address widgets and stringified JSON lists. For file uploads, use `extract_upload_files` — it tolerates dicts, JSON strings, and plain URLs.
- **Errors route through `templates/error.html`.** `format_jotform_http_error` pulls Jotform's own `message` out of 4xx/5xx response bodies; keep that helper in sync with any new Jotform endpoints you call.
- **Settings access.** Always go through `get_settings()` (it's `@lru_cache`d); don't instantiate `Settings()` directly or read `os.environ` in request handlers.

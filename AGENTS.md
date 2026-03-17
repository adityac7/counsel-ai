# CounselAI Architecture Guide

This file is the shortest path to the real architecture.

Use it to answer 4 questions before editing anything:
- what flow am I changing
- which file actually owns that flow
- which files are legacy, fallback, or dead ends
- what is the smallest test that proves the contract

If you skip this, you will patch the wrong layer.

## Read This First

1. Websocket lifecycle is the source of truth for live session creation, `started_at`, `ended_at`, `duration_seconds`, `turn_count`, and final transcript persistence.
2. `/api/analyze-session` enriches an existing session. It must not create sessions and must not repair core timing.
3. Transcript-first is the real fallback path. Missing or empty video is allowed if transcript data exists.
4. The live browser client uses [`state.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/state.js) as the shared source of truth. Do not create parallel runtime state unless you are deliberately refactoring toward it.
5. Counsellor dashboards can fall back from `Profile` rows to `SessionRecord.report`. Student and school dashboards cannot. They read `Profile` tables, not legacy report blobs.
6. [`profile_views.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/profile_views.py) is the adapter that makes raw or legacy profile data safe for counsellor dashboard rendering. Fix it before touching counsellor templates.
7. Do not add another writer format to `SessionRecord.report`. It is already overloaded by incompatible schemas.
8. Debug JSON and service output before HTML. Template edits are the last step, not the first.
9. Do not trust [`api/schemas.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/schemas.py) as the exact source of truth for dashboard payloads. Some dashboard endpoints return richer raw dicts than the schema implies.
10. Prefer the smallest targeted test lane first. Do not default to `pytest` for the whole repo.

## Product Surfaces

CounselAI has 4 practical surfaces:
- live counselling session: browser + media capture + Gemini websocket
- post-session enrichment: transcript/video upload + profile synthesis
- dashboard read models: counsellor, student, school
- report API: transcript-derived session report under `/api/v1/sessions/{id}/report`

The first 3 share data, but they do not share the same write path.

## Route Map

These are the entrypoints that matter:

| Surface | Route | Owner |
| --- | --- | --- |
| Live page | `/` | [`api/app.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/app.py) -> [`templates/live.html`](/Users/admin_vtion/Desktop/CounselAi/templates/live.html) |
| Legacy overview page | `/dashboard` | [`api/app.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/app.py) -> [`templates/dashboard.html`](/Users/admin_vtion/Desktop/CounselAi/templates/dashboard.html) |
| Live websocket | `/api/gemini-ws` | [`api/routes/gemini_ws.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/gemini_ws.py) |
| Transcript upload | `/api/gemini-transcribe` | [`api/routes/analysis.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/analysis.py) |
| Post-session enrichment | `/api/analyze-session` | [`api/routes/analysis.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/analysis.py) |
| Counsellor dashboards | `/api/v1/dashboard/counsellor...` | [`api/routes/dashboard.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/dashboard.py) + [`dashboard/counsellor_queue.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/counsellor_queue.py) + [`dashboard/counsellor_review.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/counsellor_review.py) |
| Student dashboards | `/api/v1/dashboard/students...` | [`api/routes/dashboard.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/dashboard.py) + [`dashboard/student.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/student.py) |
| School dashboards | `/api/v1/dashboard/schools...` | [`api/routes/dashboard.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/dashboard.py) + [`dashboard/school.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/school.py) |
| Session detail/report APIs | `/api/v1/sessions/{id}...` | [`api/routes/sessions.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/sessions.py) |

## Actual Runtime Flow

### 1. Live Session Flow

1. Browser loads [`templates/live.html`](/Users/admin_vtion/Desktop/CounselAi/templates/live.html).
2. [`static/live/app.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/app.js) loads case studies, gates start on consent, resets shared state, and switches to the live screen.
3. [`static/live/media-capture.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/media-capture.js) requests mic/camera, falls back to audio-only if needed, and starts `MediaRecorder`.
4. [`static/live/gemini-session.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/gemini-session.js) opens `/api/gemini-ws` with student metadata.
5. [`api/routes/gemini_ws.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/gemini_ws.py) validates metadata, initializes Gemini, and immediately creates a `SessionRecord` through [`storage/repositories/live_sessions.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/storage/repositories/live_sessions.py).
6. The server emits `session_started` before Gemini setup completes. The frontend must preserve this `session_id`.
7. [`api/websocket_handler.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/websocket_handler.py) handles browser-to-Gemini forwarding, Gemini-to-browser forwarding, transcript collection, keepalive, wrap-up warnings, and GoAway reconnection.
8. Student transcript comes from 2 places today:
- frontend sidecar transcript batches posted to `/api/gemini-transcribe` and then relayed over websocket
- Gemini input transcription returned over the live session
9. On End Session, [`static/live/analysis.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/analysis.js) finalizes the recorder, flushes pending transcript, tears down media/websocket resources, and POSTs `/api/analyze-session` with the existing `session_id`.
10. When the websocket closes, [`api/routes/gemini_ws.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/gemini_ws.py) finalizes `ended_at`, `duration_seconds`, `status`, `turn_count`, and persisted `Turn` rows through [`storage/repositories/live_sessions.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/storage/repositories/live_sessions.py).

### 2. Post-Session Enrichment Flow

1. `/api/analyze-session` lives in [`api/routes/analysis.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/analysis.py).
2. It accepts optional video, transcript JSON, and session metadata.
3. If transcript payload is empty but `session_id` exists, it falls back to stored `Turn` rows.
4. If video is present, it extracts frames and audio through [`api/media_utils.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/media_utils.py).
5. Face analysis runs in [`analysis/face_analyzer.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/face_analyzer.py).
6. Voice analysis runs in [`analysis/voice_analyzer.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/voice_analyzer.py).
7. Profile synthesis runs in [`analysis/profile_generator.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/profile_generator.py).
8. Raw output is normalized for counsellor dashboards by [`analysis/profile_views.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/profile_views.py).
9. The route writes a report blob back to `SessionRecord.report` and upserts analysis-owned `Profile` plus construct-level `Hypothesis` rows for dashboard consumers.

Important:
- this route now creates or updates `Profile` and construct-level `Hypothesis` rows for the analyzed session
- this route still does not create `SignalWindow` or `SignalObservation` rows
- this route should not own session timing
- transcript-only analysis is expected behavior

### 3. Session Report Flow

1. `/api/v1/sessions/{id}/report` lives in [`api/routes/sessions.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/sessions.py).
2. It uses [`analysis/report_generator.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/report_generator.py).
3. This is a separate transcript-derived report path with a different JSON contract from `/api/analyze-session`.
4. It also writes back into `SessionRecord.report`.

This means `SessionRecord.report` currently has 2 incompatible writer shapes:
- legacy analyze-session blob: `profile`, `profile_raw`, `face_data`, `voice_data`, `duration_seconds`
- session report blob: `session_summary`, `student_engagement_score`, and related report fields

Do not assume those shapes are interchangeable.

### 4. Dashboard Flow

Counsellor flow:
- route layer is [`api/routes/dashboard.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/dashboard.py)
- queue read model is [`dashboard/counsellor_queue.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/counsellor_queue.py)
- session review and evidence read models are [`dashboard/counsellor_review.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/counsellor_review.py)
- HTML templates are [`templates/dashboard/counsellor.html`](/Users/admin_vtion/Desktop/CounselAi/templates/dashboard/counsellor.html) and [`templates/dashboard/counsellor_session.html`](/Users/admin_vtion/Desktop/CounselAi/templates/dashboard/counsellor_session.html)

Student flow:
- route layer is [`api/routes/dashboard.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/dashboard.py)
- read model is [`dashboard/student.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/student.py)
- template is [`templates/dashboard/student.html`](/Users/admin_vtion/Desktop/CounselAi/templates/dashboard/student.html)

School flow:
- route layer is [`api/routes/dashboard.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/dashboard.py)
- read model is [`dashboard/school.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/school.py)
- template is [`templates/dashboard/school.html`](/Users/admin_vtion/Desktop/CounselAi/templates/dashboard/school.html)

Legacy overview flow:
- `/dashboard` is not owned by `dashboard.py`
- it is served directly from [`api/app.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/app.py)
- [`templates/dashboard.html`](/Users/admin_vtion/Desktop/CounselAi/templates/dashboard.html) builds a client-side read model by calling counsellor queue and review APIs

## What Really Persists

The aggregate root is [`SessionRecord`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/storage/models.py).

Important persistence facts:
- live websocket persistence uses [`storage/repositories/live_sessions.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/storage/repositories/live_sessions.py), not `SessionRepository`
- generic CRUD and report-oriented writes use [`storage/repositories/sessions.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/storage/repositories/sessions.py)
- `ProfileRepository` exists in [`storage/repositories/profiles.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/storage/repositories/profiles.py) but the active `/api/analyze-session` write path currently uses a sync persistence helper instead
- default live enrichment now writes `Profile` rows and construct-level `Hypothesis` rows, but `signal_windows` and `signal_observations` still mainly come from seed data or targeted flows
- `finalize_live_session()` writes `Turn` rows with `start_ms=0` and `end_ms=0` for every turn today

## Ownership Table

| Concern | First Owner | Then Check | Do Not Fix First |
| --- | --- | --- | --- |
| App startup, route registration, `/health` | [`api/app.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/app.py) | [`settings.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/settings.py), [`storage/db.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/storage/db.py) | random route files |
| Live DOM contract | [`templates/live.html`](/Users/admin_vtion/Desktop/CounselAi/templates/live.html) | [`static/live/screens.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/screens.js) | backend files |
| Live shared state | [`static/live/state.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/state.js) | callers in `static/live/*` | new module-local state |
| Camera, mic, recorder | [`static/live/media-capture.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/media-capture.js) | [`static/live/analysis.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/analysis.js) | backend upload logic |
| Websocket handshake and browser streaming | [`static/live/gemini-session.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/gemini-session.js) | [`api/routes/gemini_ws.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/gemini_ws.py) | dashboard code |
| Browser <-> Gemini translation | [`api/websocket_handler.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/websocket_handler.py) | [`api/gemini_client.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/gemini_client.py) | templates |
| Live session row timing/status | [`storage/repositories/live_sessions.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/storage/repositories/live_sessions.py) | [`api/routes/gemini_ws.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/gemini_ws.py) | `/api/analyze-session` |
| Post-session enrichment | [`api/routes/analysis.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/analysis.py) | `face_analyzer.py`, `voice_analyzer.py`, `profile_generator.py` | dashboard templates |
| Counsellor profile normalization | [`analysis/profile_views.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/profile_views.py) | [`dashboard/counsellor_review.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/counsellor_review.py) | counsellor templates |
| Counsellor queue data | [`dashboard/counsellor_queue.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/counsellor_queue.py) | [`api/routes/dashboard.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/dashboard.py) | queue template JS |
| Counsellor review data | [`dashboard/counsellor_review.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/counsellor_review.py) | [`analysis/profile_views.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/profile_views.py) | template hacks |
| Student dashboard data | [`dashboard/student.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/student.py) | [`api/routes/dashboard.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/dashboard.py) | `session.report` fallback |
| School dashboard data | [`dashboard/school.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/school.py) | [`api/routes/dashboard.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/dashboard.py) | template hacks |
| Legacy overview page behavior | [`templates/dashboard.html`](/Users/admin_vtion/Desktop/CounselAi/templates/dashboard.html) | `/dashboard` route in [`api/app.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/app.py) | `dashboard.py` |

## If Symptom, Open These Files First

### Live session does not connect
- first: [`static/live/gemini-session.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/gemini-session.js)
- then: [`api/routes/gemini_ws.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/gemini_ws.py)
- then: [`api/gemini_client.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/gemini_client.py)

### Session exists but duration, status, or turn count is wrong
- first: [`api/routes/gemini_ws.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/gemini_ws.py)
- then: [`storage/repositories/live_sessions.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/storage/repositories/live_sessions.py)
- do not start in: [`api/routes/analysis.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/analysis.py)

### Student transcript is missing, late, or duplicated
- first: [`static/live/gemini-session.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/gemini-session.js)
- then: [`api/websocket_handler.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/websocket_handler.py)
- then: [`api/gemini_client.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/gemini_client.py)
- reason: transcript currently has 2 authorities, frontend sidecar text and Gemini input transcription

### Recording is empty, flaky, or camera preview is wrong
- first: [`static/live/media-capture.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/media-capture.js)
- then: [`static/live/analysis.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/analysis.js)
- only change backend if the upload format truly changed

### Live summary renders but counsellor dashboard profile is empty
- first: [`analysis/profile_views.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/profile_views.py)
- then: [`dashboard/counsellor_review.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/counsellor_review.py)
- then: the relevant counsellor template

### Counsellor queue counts or red-flag totals are wrong in both queue and overview page
- first: [`dashboard/counsellor_queue.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/counsellor_queue.py)
- then: [`api/routes/dashboard.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/dashboard.py)
- note: `red_flag` filtering is currently applied after pagination

### Workbench groups the wrong students together
- first: [`templates/dashboard/counsellor.html`](/Users/admin_vtion/Desktop/CounselAi/templates/dashboard/counsellor.html)
- reason: it groups client-side by `student_name`, not `student_id`

### Only the legacy overview page is wrong
- first: [`templates/dashboard.html`](/Users/admin_vtion/Desktop/CounselAi/templates/dashboard.html)
- then: `/dashboard` route in [`api/app.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/app.py)
- do not start in: [`api/routes/dashboard.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/dashboard.py)

### Student or school dashboards are empty even though counsellor review works
- first: confirm real `Profile` rows exist and that the session's `Student.school_id` is set
- then: [`dashboard/student.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/student.py) or [`dashboard/school.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/dashboard/school.py)
- reason: student dashboards do not fall back to legacy `session.report`, and school topic clusters still need either `SignalWindow` rows or `Profile.school_view_json["themes"]`

### `/api/v1/sessions/{id}/report` is empty or weird after `/api/analyze-session`
- first: [`analysis/report_generator.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/report_generator.py)
- then: [`api/routes/sessions.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/routes/sessions.py)
- root cause to check: `SessionRecord.report` may contain the wrong writer shape for the reader

### Cross-modal timing or topic windows are wrong
- first: [`storage/repositories/live_sessions.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/storage/repositories/live_sessions.py)
- then: [`analysis/topic_windows.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/topic_windows.py)
- note: live `Turn` rows currently store zero ms timing, and `topic_windows.py` depends on a missing `counselai.signals` package

## Known Reality Checks

- `lang` is accepted by the live route and stored on the session, but [`api/gemini_client.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/gemini_client.py) does not currently use it when building the Gemini live config.
- `Gemini` config reads raw `GEMINI_API_KEY` directly in [`api/gemini_client.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/api/gemini_client.py), not the typed settings object.
- [`analysis/topic_windows.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/topic_windows.py) is dormant. It imports `counselai.signals.*`, but that package does not exist in this repo.
- [`analysis/session_analyzer.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/session_analyzer.py) is not on the active write path today.
- `/api/analyze-session` backfills `Student.school_id` from `student_school` when the live websocket created a session without a school link.
- school topic clusters can now fall back to `Profile.school_view_json["themes"]`, and construct analysis can fall back to `Profile.counsellor_view_json["constructs"]`, when richer signal tables are empty.
- `face_analyzer` assumes a 2-second frame interval, while `/api/analyze-session` extracts frames every 3 seconds.
- Voice analysis can run without transcript text because the current caller does not pass transcript into `analyze_audio()`.
- [`static/live/live.css`](/Users/admin_vtion/Desktop/CounselAi/static/live/live.css) is already 495 LOC. [`static/live/analysis.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/analysis.js) and [`static/live/gemini-session.js`](/Users/admin_vtion/Desktop/CounselAi/static/live/gemini-session.js) are close to the 400 LOC cap. Split before adding more branching.
- The migration graph currently has 2 heads: `a1b2c3d4e5f6` and `003_add_report`. [`alembic/versions/003_add_session_report_field.py`](/Users/admin_vtion/Desktop/CounselAi/alembic/versions/003_add_session_report_field.py) uses `down_revision = None`.
- The legacy test [`tests/test_counselai.py`](/Users/admin_vtion/Desktop/CounselAi/tests/test_counselai.py) still expects removed routes. Do not use it as the source of truth.

## Verification Rules

Always run the smallest command that proves the contract you changed.

### Start the local app

```bash
PYTHONPATH=src python3 -m uvicorn counselai.api.app:app --host 127.0.0.1 --port 8751
```

What it does: starts the local app on the port used by the stable browser lane.

### Live session and end-session reliability

```bash
PYTHONPATH=src COUNSELAI_TEST_URL=http://127.0.0.1:8751 pytest tests/e2e/test_session_end_reliability.py -q
```

What it proves: early `session_id`, clean end-session teardown, transcript-first fallback when video is empty, and no false connection-lost toast.

### Live stubbed browser flow

```bash
PYTHONPATH=src COUNSELAI_TEST_URL=http://127.0.0.1:8751 pytest tests/e2e/test_live_session_stubbed.py -q
```

What it proves: metadata submission, reconnect UI, and analysis progress flow.

### Websocket upgrade and URL propagation

```bash
PYTHONPATH=src COUNSELAI_TEST_URL=http://127.0.0.1:8751 pytest tests/e2e/test_websocket.py -q
```

What it proves: websocket endpoint behavior and metadata propagation.

### Analyze-session backend contract

```bash
PYTHONPATH=src COUNSELAI_TEST_URL=http://127.0.0.1:8751 pytest tests/test_session_reliability.py -q
```

What it proves: `/api/analyze-session` enriches an existing session without overwriting websocket-owned timing and counsellor review can normalize raw report fallback.

### Counsellor queue / workbench

```bash
pytest tests/test_counsellor_workbench.py -q
```

What it proves: queue filters, pagination, red-flag aggregation, and workbench-facing item shape.

### Schema contract

```bash
pytest tests/contract/test_api_schemas.py -q
```

What it proves: response/request schema defaults and backward-compatible serialization.

### School analytics

```bash
pytest tests/unit/test_school_analytics.py -q
```

What it proves: school aggregate calculations and privacy boundaries.

### Dashboard browser lane

```bash
PYTHONPATH=src COUNSELAI_TEST_URL=http://127.0.0.1:8751 pytest tests/e2e/test_dashboard.py tests/e2e/test_dashboard_overview.py tests/e2e/test_counsellor_workbench.py tests/e2e/test_counsellor_review.py tests/e2e/test_student_dashboard.py tests/e2e/test_school_dashboard.py -q
```

What it proves: seeded dashboard pages render correctly in the browser.

### Stable repo lane

```bash
./scripts/run_e2e.sh
```

What it does: runs the stable browser regression files, optional provider smoke, and optional UAT.

### Migration sanity check

```bash
alembic heads
```

What it proves: whether migration history is still split or unexpectedly changed.

## Testing Discipline

- Do not run `pytest` for the whole repo by default.
- Prefer targeted tests first, then escalate to [`scripts/run_e2e.sh`](/Users/admin_vtion/Desktop/CounselAi/scripts/run_e2e.sh) when the change affects shared live flow or multiple dashboards.
- Browser tests depend on the same DB/env as the running server. [`tests/e2e/seed_data.py`](/Users/admin_vtion/Desktop/CounselAi/tests/e2e/seed_data.py) seeds the actual configured database, not a separate isolated temp DB.
- Follow port `8751` unless a task explicitly requires something else. README and some older tests still mention `8501`.

## Change Rules

1. Trace the whole flow before editing.
2. Fix the owner layer first.
3. If a dashboard bug appears in JSON and HTML, fix the service layer, not the template.
4. If a counsellor profile bug involves old rows, fix the adapter in [`profile_views.py`](/Users/admin_vtion/Desktop/CounselAi/src/counselai/analysis/profile_views.py).
5. If the bug is timing or live session status, stay out of `/api/analyze-session`.
6. If you are about to add more logic into `SessionRecord.report`, stop and justify why a separate table or explicit schema is not better.

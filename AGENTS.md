# AGENTS.md — CounselAI Codebase Guide

> Last verified: 2026-04-05 against branch `codex/dashboard-persistence-fix`.

---

## 1. Read This First

1. **One Gemini call per session** — post-session analysis is a single `unified_analyzer.analyze_session()` call. There is no multi-stage pipeline.
2. **Live model**: configured via `settings.gemini_live_model`. **Analysis model**: configured via `settings.gemini_synthesis_model`.
3. **Transcription comes from Gemini Live** via native `input_audio_transcription` / `output_audio_transcription`. No separate ASR service.
4. **SQLite only** — no Postgres, no Redis, no message broker. DB file is `counselai.db`.
5. **6 ORM models**: School, Student, SessionRecord, Turn, Profile, Hypothesis. Nothing else.
6. **3 dashboard audiences**: counsellor (review + queue), student (strengths-only, no clinical data), school (aggregates only, no individual names).
7. **3 routers only**: `routes/gemini_ws.py`, `routes/analysis.py`, `routes/dashboard.py`.
8. **Frontend JS**: 5 files in `static/live/` — `state.js` (shared state + DOM refs), `app.js` (UI helpers + init), `session.js`, `media.js`, `analysis.js`. ES modules, not bundled.
9. **All settings** come from `counselai.settings.Settings` (pydantic-settings, env prefix `COUNSELAI_`).
10. **No dead code directories** — no `_unused_code/`, no `prompts/`, no `repositories/`.

---

## 2. Product Surfaces

### Live Session
Browser opens `/` (live.html). User fills student info + selects case study. JS opens WebSocket to `/api/gemini-ws`. Server proxies audio bidirectionally with Gemini Live. Transcription events flow back to browser in real time. Session auto-wraps at 5:30 and times out at 7:00.

### Post-Session Analysis
When the session ends, `analysis.js` POSTs to `/api/analyze-session` with transcript + optional video. Server runs `unified_analyzer.analyze_session()` (single Gemini call, structured JSON output) and persists results to SessionRecord.report, Profile, and Hypothesis rows. Response is rendered in the browser as the student profile.

### Dashboards
- **Counsellor**: `/api/v1/dashboard/counsellor` (HTML) + `/api/v1/dashboard/counsellor/queue` (JSON) + `/api/v1/dashboard/counsellor/sessions/{id}/review` (JSON)
- **Student**: `/api/v1/dashboard/students/{id}/insights` (HTML)
- **School**: `/api/v1/dashboard/schools/{id}/dashboard` (HTML)

---

## 3. Route Map

14 active endpoints:

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| GET | `/` | `app.index` | Serve live.html |
| GET | `/dashboard` | `app.dashboard` | Serve dashboard/overview.html |
| GET | `/health` | `app.health` | DB connectivity check |
| WS | `/api/gemini-ws` | `gemini_ws.gemini_ws_proxy` | Live audio proxy to Gemini |
| GET | `/api/case-studies` | `analysis.get_case_studies` | List case study bank |
| POST | `/api/analyze-session` | `analysis.analyze_session` | Run post-session analysis |
| GET | `/api/v1/dashboard/counsellor` | `dashboard.counsellor_workbench` | Counsellor workbench HTML |
| GET | `/api/v1/dashboard/counsellor/queue` | `dashboard.counsellor_queue` | Paginated session queue JSON |
| GET | `/api/v1/dashboard/counsellor/sessions/{id}` | `dashboard.counsellor_session_detail_page` | Session review HTML |
| GET | `/api/v1/dashboard/counsellor/sessions/{id}/review` | `dashboard.counsellor_session_review` | Session review JSON |
| GET | `/api/v1/dashboard/counsellor/sessions/{id}/evidence` | `dashboard.counsellor_session_evidence` | Evidence explorer JSON |
| GET | `/api/v1/dashboard/students/{id}/insights` | `dashboard.student_insights_page` | Student insights HTML |
| GET | `/api/v1/dashboard/schools/{id}/dashboard` | `dashboard.school_dashboard_page` | School analytics HTML |
| GET | `/static/...` | StaticFiles mount | JS, CSS, favicon |

---

## 4. Complete File Inventory by User Flow

### App Bootstrap

| File | Purpose |
|------|---------|
| `src/counselai/api/app.py` | FastAPI app: lifespan (DB init, Gemini client), CORS, mounts 3 routers, template routes, static files |
| `src/counselai/settings.py` | Pydantic-settings singleton — all config from `COUNSELAI_*` env vars |
| `src/counselai/logging.py` | `setup_logging()` — stderr handler for `counselai.*` loggers |
| `src/counselai/api/exceptions.py` | Exception hierarchy: GeminiAPIKeyMissing, TranscriptionError |
| `src/counselai/api/schemas.py` | Pydantic request/response models for all API contracts |
| `run.sh` | Dev launcher: uvicorn with --reload on port 8501 |
| `case_studies.py` | Case study bank — list of scenario dicts for Indian class 9-12 |

### Live Session

| File | Purpose |
|------|---------|
| `src/counselai/api/routes/gemini_ws.py` | WebSocket endpoint: creates session row, proxies to Gemini Live, handles GoAway reconnection (up to 20x), finalizes on disconnect |
| `src/counselai/api/gemini_client.py` | Singleton Gemini client, `build_live_config()` with audio modalities + session resumption. Model names from settings |
| `src/counselai/api/constants.py` | `COUNSELLOR_INSTRUCTIONS` system prompt (persona, crisis protocol) + `POST_SESSION_ANALYSIS_PROMPT` |
| `src/counselai/api/websocket_handler.py` | `browser_to_gemini`, `gemini_to_browser`, `TranscriptCollector` (bounded deques), `session_timer`, `keepalive_ping` |
| `src/counselai/api/validators.py` | `validate_ws_params()` — sanitize name, grade (9-12), age (10-20), section, school, scenario, language |
| `src/counselai/api/audio_utils.py` | PCM validation, energy-based VAD, audio level metering |
| `src/counselai/storage/live_sessions.py` | `create_live_session()` + `finalize_live_session()` — session row lifecycle |

### Post-Session Analysis

| File | Purpose |
|------|---------|
| `src/counselai/api/routes/analysis.py` | `/analyze-session` + `/case-studies`; calls unified_analyzer, persists Profile+Hypothesis+report |
| `src/counselai/analysis/unified_analyzer.py` | Single Gemini call with ANALYSIS_SCHEMA (16 required keys); uses cached client from `gemini_client.py` |
| `src/counselai/analysis/dashboard_persistence.py` | `persist_session_analysis()` — writes Profile, Hypothesis, SessionRecord.report rows |
| `src/counselai/api/media_utils.py` | ffmpeg wrappers: `extract_audio_from_video()`, `save_frames_from_video()` |

### Dashboard Read Models

| File | Purpose |
|------|---------|
| `src/counselai/api/routes/dashboard.py` | All dashboard routes — counsellor, student, school (HTML + JSON) |
| `src/counselai/dashboard/counsellor_service.py` | Merged: `get_counsellor_queue()`, `QueueFilters`, `get_session_review()`, `get_session_evidence()` |
| `src/counselai/dashboard/student.py` | `build_student_dashboard()` — strengths-only view, no clinical data. Profiles eagerly loaded (no N+1) |
| `src/counselai/dashboard/school.py` | `SchoolAnalyticsService` — aggregate queries (grade dist, red flags, constructs, topics, fallbacks inlined) |

### Storage Layer

| File | Purpose |
|------|---------|
| `src/counselai/storage/db.py` | Async + sync engines, session factories, SQLite WAL pragmas, `init_db()`, `create_all_tables()`, `health_check()` |
| `src/counselai/storage/models.py` | 6 ORM models + enums + JSONType/UUIDType custom types for SQLite |
| `src/counselai/storage/live_sessions.py` | Live session create/finalize helpers |

### Frontend

| File | Purpose |
|------|---------|
| `static/live/state.js` | Shared state object + DOM refs + screen transitions (no imports — breaks cycles) |
| `static/live/app.js` | UI helpers (status, toast, logging) + event listeners + session init |
| `static/live/session.js` | WebSocket connection, Gemini message handling, audio playback, transcript |
| `static/live/media.js` | Microphone/camera capture, waveform visualizer, MediaRecorder |
| `static/live/analysis.js` | Post-session: `endSession()`, profile rendering, summary display |
| `static/live/live.css` | Styles for the live session page |
| `static/dashboard.css` | Shared styles for all dashboard pages |
| `templates/live.html` | Live session page template |
| `templates/dashboard/base.html` | Jinja2 base template — sidebar nav, shared CSS |
| `templates/dashboard/overview.html` | Dashboard landing page |
| `templates/dashboard/counsellor.html` | Counsellor workbench with session queue |
| `templates/dashboard/counsellor_session.html` | Single session review page |
| `templates/dashboard/student.html` | Student-facing insights page |
| `templates/dashboard/school.html` | School analytics dashboard |

---

## 5. Actual Runtime Flow

### Live Session (step by step)

1. Browser loads `/` -> live.html + app.js (which imports state.js + session.js + media.js + analysis.js)
2. User fills form (name, grade, section, school, age, case study) and clicks Start
3. `session.js` opens WebSocket to `/api/gemini-ws?name=...&grade=...&scenario=...`
4. `gemini_ws.py` validates params via `validators.py`, creates LiveSessionHandle via `live_sessions.py`
5. Server connects to Gemini Live via `gemini_client.py`
6. Server sends `COUNSELLOR_INSTRUCTIONS` + student context as system prompt
7. Server sends 100ms silent PCM audio to trigger Gemini greeting
8. `browser_to_gemini()` forwards mic audio + camera frames to Gemini
9. `gemini_to_browser()` forwards model audio + transcriptions to browser
10. `TranscriptCollector` (bounded deques) accumulates turns
11. `session_timer` injects wrapup prompt at 5:30, sends timeout at 7:00
12. On GoAway from Gemini, server reconnects with session resumption (up to 20 times)
13. On browser disconnect, `finalize_live_session()` saves Turn rows + updates SessionRecord

### Post-Session Analysis (step by step)

1. `analysis.js` calls `POST /api/analyze-session` with transcript JSON + optional video
2. `routes/analysis.py` parses form data; falls back to DB Turn rows if transcript is empty
3. `unified_analyzer.analyze_session()` uses the cached Gemini client, sends structured JSON schema
4. Gemini returns JSON matching ANALYSIS_SCHEMA (16 required top-level keys)
5. `_persist_analysis_to_session()` maps result to Profile + Hypothesis + report JSON
6. Response returns `{profile: ..., face_data: {}, voice_data: {}, session_id: ...}`
7. `analysis.js` renders the profile in the browser summary screen

### Dashboard Read (step by step)

1. Counsellor opens `/api/v1/dashboard/counsellor` -> queue page with filters
2. Queue fetches from `counsellor_service.get_counsellor_queue()` -> paginated sessions with red flag counts
3. Click a session -> `counsellor_service.get_session_review()` normalizes data (Profile first, falls back to report)
4. Student opens `/api/v1/dashboard/students/{id}/insights` -> `student.build_student_dashboard()` returns strengths-only
5. School opens `/api/v1/dashboard/schools/{id}/dashboard` -> `school.SchoolAnalyticsService.full_analytics()` returns aggregates

---

## 6. Ownership Table

| Area | Primary Files | Key Concern |
|------|--------------|-------------|
| Live WS transport | `gemini_ws.py`, `websocket_handler.py` | GoAway reconnection, transcript fidelity |
| Gemini integration | `gemini_client.py`, `constants.py` | Model names from settings, prompt quality |
| Post-session analysis | `unified_analyzer.py`, `routes/analysis.py` | Schema compliance, fallback on failure |
| Persistence | `dashboard_persistence.py`, `live_sessions.py` | Profile/Hypothesis row creation |
| Counsellor dashboard | `counsellor_service.py` | Queue filters, review data normalization |
| Student dashboard | `student.py` | Privacy: no clinical data exposure |
| School dashboard | `school.py` | Privacy: no student names; aggregate accuracy |
| Storage | `db.py`, `models.py` | SQLite WAL mode, FK enforcement |
| Frontend | `state.js`, `app.js`, `session.js`, `media.js`, `analysis.js` | Audio capture, WS message handling |
| Config | `settings.py` | Env var naming, defaults |

---

## 7. If Symptom, Open These Files First

| Symptom | Files to check |
|---------|---------------|
| WS connection fails | `gemini_ws.py`, `gemini_client.py`, `validators.py` |
| No audio from Gemini | `websocket_handler.py` (gemini_to_browser), `gemini_client.py` (build_live_config) |
| Transcript missing | `websocket_handler.py` (TranscriptCollector), `gemini_client.py` (AudioTranscriptionConfig) |
| Session not saved | `live_sessions.py`, `gemini_ws.py` (finalize_live_session call) |
| Analysis returns empty | `unified_analyzer.py` (_fallback_result), `routes/analysis.py` |
| Dashboard shows no data | `dashboard_persistence.py`, `counsellor_service.py` (fallback logic) |
| Student sees clinical data | `student.py` (build_student_dashboard should filter) |
| School shows student names | `school.py` (privacy queries should never join names) |
| GoAway loop / reconnect storm | `gemini_ws.py` (MAX_RECONNECTS, resumption_state) |
| Session timeout not working | `websocket_handler.py` (session_timer), `settings.py` |
| DB locked errors | `db.py` (WAL mode, check_same_thread) |
| Import errors at startup | `app.py` (router mounts) — check for deleted modules |

---

## 8. Known Reality Checks

- **No face_analyzer, voice_analyzer, profile_generator, report_generator** — deleted. Everything goes through `unified_analyzer.py`.
- **No SignalWindow, SignalObservation, Artifact, StudentProfile, SessionFeedback models** — deleted.
- **No analytics router, no sessions router** — only 3 routers.
- **No Redis, no Celery, no background workers** — analysis runs in a thread executor within the request.
- **No WebRTC** — pure WebSocket audio streaming.
- **No `deps.py`** — routes import `get_sync_db` directly from `counselai.storage.db`.
- **Session resumption is Gemini-native** via `session_resumption_update` handles.
- **Devanagari safety net** in `websocket_handler.py` romanizes any Devanagari that slips through ASR.
- **`face_data: {}` and `voice_data: {}`** in the analysis response are populated from unified analysis.
- **Model names** come from `settings.py` via `gemini_client.py` — never hardcoded in business logic.

---

## 9. Verification Rules

Before merging any change, verify:

```bash
# App imports cleanly
cd /Users/admin_vtion/Desktop/CounselAi && PYTHONPATH=src:. python3 -c "from counselai.api.app import app; print('OK')"

# No stale imports in tests
grep -r "SignalWindow\|SignalObservation\|Artifact\|StudentProfile\|SessionFeedback\|counsellor_queue\|counsellor_review\|from counselai.api.deps\|school_fallbacks" tests/ --include="*.py" -l

# Unit tests pass (no server needed)
PYTHONPATH=src:. python3 -m pytest tests/test_profile.py tests/unit/ tests/contract/ -v

# Reliability regression tests (no server needed)
PYTHONPATH=src:. python3 -m pytest tests/test_session_reliability.py -v
```

---

## 10. Change Rules

1. **Never add a new ORM model** without updating `models.py` and verifying `create_all_tables()` picks it up.
2. **Never add a new router** without mounting it in `app.py` and adding it to the route map above.
3. **Never change ANALYSIS_SCHEMA** without updating `_fallback_result()` to match.
4. **Never expose student names** in school analytics queries. School dashboard is aggregate-only.
5. **Never expose risk scores or red flags** in the student dashboard.
6. **Never delete a route** without grepping all test files for that path.
7. **Monkeypatch target for analysis** in tests is `counselai.analysis.unified_analyzer.analyze_session`.
8. **All settings** go through `settings.py` — never read `os.environ` directly in business logic.
9. **Template paths** are relative to `templates/` — dashboard templates extend `dashboard/base.html`.
10. **JS modules** import state from `./state.js` and UI helpers from `./app.js` — no circular imports.

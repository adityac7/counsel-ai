# CounselAI

Evidence-based student counselling platform for Indian schools (classes 9-12).

Real-time voice counselling powered by Gemini Live, with post-session analysis,
profile generation, and multi-level dashboards for counsellors, students, and schools.

## Quick Start

```bash
# 1. Clone & install
git clone <repo-url> && cd counselai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Set environment variables
export GEMINI_API_KEY="your-key"
# Optional: OPENAI_API_KEY, COUNSELAI_DATABASE_URL

# 3. Run
uvicorn counselai.api.app:app --host 0.0.0.0 --port 8501
```

Open http://localhost:8501 for the live counselling interface.

## Project Structure

```
src/counselai/
├── api/               # FastAPI app, routes, WebSocket handlers
│   ├── app.py         # Entry point
│   ├── routes/        # gemini_ws, legacy, dashboard, sessions, live
│   ├── gemini_client.py
│   ├── audio_utils.py
│   ├── websocket_handler.py
│   └── schemas.py
├── prompts/           # Counsellor persona, crisis detection, session stages
├── storage/           # SQLAlchemy models, async DB, repositories
├── ingest/            # Session canonicalization & artifact storage
├── signals/           # Audio, video, content feature extraction
├── analysis/          # Evidence graph, hypothesis generation
├── profiles/          # Profile synthesis & prompt building
├── dashboard/         # Service layers for counsellor, student, school views
├── live/              # Provider abstractions (Gemini Live, OpenAI Realtime)
├── workers/           # Background processing pipeline
├── settings.py        # Centralized config (env vars)
└── logging.py
templates/             # Jinja2 HTML templates
static/                # Favicon, static assets
```

## Configuration

All settings via environment variables with `COUNSELAI_` prefix:

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | — | Google AI API key (required) |
| `OPENAI_API_KEY` | — | OpenAI key (optional, for legacy routes) |
| `COUNSELAI_DATABASE_URL` | `sqlite+aiosqlite:///counselai.db` | Database URL |
| `COUNSELAI_ARTIFACT_ROOT` | `artifacts` | Artifact storage path |
| `COUNSELAI_LOG_LEVEL` | `INFO` | Logging level |

See `src/counselai/settings.py` for the full list.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# E2E tests (needs playwright browsers)
playwright install chromium
pytest tests/e2e/
```

## Architecture

- **Live sessions**: Browser ↔ WebSocket ↔ Gemini Live API (bidirectional audio)
- **Post-session**: Transcript canonicalization → signal extraction (content/audio/video) → evidence graph → hypothesis generation → profile synthesis
- **Dashboards**: Counsellor workbench, student insights, school analytics — all aggregate-only, privacy-first

## License

Proprietary. All rights reserved.

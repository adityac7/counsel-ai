# CounselAI

Evidence-based student counselling platform for Indian schools (classes 9-12).

Real-time voice counselling powered by Gemini Live, with unified post-session
analysis and multi-level dashboards for counsellors, students, and schools.

## Quick Start

```bash
# 1. Clone & install
git clone <repo-url> && cd counselai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Set environment variables
export GEMINI_API_KEY="your-key"

# 3. Run
uvicorn counselai.api.app:app --host 0.0.0.0 --port 8501
```

Open http://localhost:8501 for the live counselling interface.

## Project Structure

```
src/counselai/
├── api/               # FastAPI app, routes, WebSocket handlers
│   ├── app.py         # Entry point
│   ├── routes/        # gemini_ws, analysis, dashboard
│   ├── gemini_client.py
│   ├── websocket_handler.py
│   └── schemas.py
├── analysis/          # Unified Gemini-based session analysis
├── dashboard/         # Service layers for counsellor, student, school views
├── storage/           # SQLAlchemy models, async DB, repositories
├── settings.py        # Centralized config (env vars)
└── logging.py
templates/             # Jinja2 HTML templates
static/                # CSS, JS, favicon
```

## Configuration

All settings via environment variables with `COUNSELAI_` prefix:

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | — | Google AI API key (required) |
| `COUNSELAI_DATABASE_URL` | `sqlite+aiosqlite:///counselai.db` | Database URL |
| `COUNSELAI_LOG_LEVEL` | `INFO` | Logging level |

See `src/counselai/settings.py` for the full list.

## Architecture

- **Live sessions**: Browser -> WebSocket -> Gemini Live API (bidirectional audio + video, native transcription)
- **Post-session**: Single unified Gemini call (transcript + video -> structured JSON analysis)
- **Dashboards**: Counsellor workbench, student insights, school analytics

## License

Proprietary. All rights reserved.

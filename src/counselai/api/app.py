"""CounselAI FastAPI application entry point.

Start with:
    uvicorn counselai.api.app:app --host 0.0.0.0 --port 8501
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from counselai.logging import setup_logging
from counselai.storage.db import init_db

logger = logging.getLogger(__name__)

# Resolve project root (3 levels up: src/counselai/api/app.py)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
templates = Jinja2Templates(directory=str(_PROJECT_ROOT / "templates"))


# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(application: FastAPI):
    """Pre-init Gemini client and DB on startup."""
    setup_logging()
    init_db()

    from counselai.api.gemini_client import init_gemini_client

    try:
        init_gemini_client()
    except Exception as exc:
        logger.warning("Gemini client pre-init failed (will retry lazily): %s", exc)

    yield

    from counselai.storage.db import close_db

    await close_db()


# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------
app = FastAPI(title="CounselAI", version="0.2.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Mount routers
# ---------------------------------------------------------------------------
from counselai.api.routes.gemini_ws import router as gemini_ws_router  # noqa: E402
from counselai.api.routes.legacy import router as legacy_router  # noqa: E402
from counselai.api.routes.dashboard import router as dashboard_router  # noqa: E402
from counselai.api.routes.sessions import router as sessions_router  # noqa: E402
from counselai.api.routes.live import router as live_router  # noqa: E402

app.include_router(gemini_ws_router, prefix="/api", tags=["gemini"])
app.include_router(legacy_router, prefix="/api", tags=["legacy"])
app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(sessions_router, prefix="/api/v1/sessions", tags=["sessions"])
app.include_router(live_router, prefix="/api/v1/live", tags=["live"])

# Static files (favicon etc.)
_STATIC_DIR = _PROJECT_ROOT / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Template-serving routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main live counselling page."""
    response = templates.TemplateResponse("live.html", {"request": request})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the dashboard overview page."""
    response = templates.TemplateResponse("dashboard.html", {"request": request})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/health")
async def health():
    """Lightweight health check."""
    from counselai.storage.db import health_check

    return await health_check()

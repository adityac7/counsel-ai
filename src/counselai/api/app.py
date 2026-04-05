"""CounselAI FastAPI application entry point.

Start with:
    uvicorn counselai.api.app:app --host 0.0.0.0 --port 8501
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from counselai.logging import setup_logging
from counselai.settings import settings
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

    # Ensure all ORM tables exist (idempotent — won't drop existing data)
    from counselai.storage.db import create_all_tables
    await create_all_tables()

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

# CORS — configurable via COUNSELAI_CORS_ORIGINS env var (comma-separated)
_cors_origins = getattr(settings, "cors_origins", "")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins.split(",") if o.strip()] if _cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Mount routers
# ---------------------------------------------------------------------------
from counselai.api.routes.gemini_ws import router as gemini_ws_router  # noqa: E402
from counselai.api.routes.analysis import router as analysis_router  # noqa: E402
from counselai.api.routes.dashboard import router as dashboard_router  # noqa: E402

app.include_router(gemini_ws_router, prefix="/api", tags=["gemini"])
app.include_router(analysis_router, prefix="/api", tags=["analysis"])
app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["dashboard"])

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
    response = templates.TemplateResponse(
        "dashboard/overview.html", {"request": request}
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/health")
async def health():
    """Lightweight health check."""
    from counselai.storage.db import health_check

    return await health_check()

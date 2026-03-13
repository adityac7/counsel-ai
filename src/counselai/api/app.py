"""CounselAI FastAPI application entry point.

Start with:
    uvicorn counselai.api.app:app --host 0.0.0.0 --port 8501
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# ---------------------------------------------------------------------------
# Resolve project root (3 levels up: src/counselai/api/app.py)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import db as legacy_db  # noqa: E402

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(_PROJECT_ROOT / "templates"))


# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(application: FastAPI):
    """Pre-init Gemini client and legacy DB on startup."""
    from counselai.api.gemini_client import init_gemini_client

    legacy_db.init_db()
    try:
        init_gemini_client()
    except Exception as exc:
        logger.warning("Gemini client pre-init failed (will retry lazily): %s", exc)
    yield


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

app.include_router(gemini_ws_router, prefix="/api", tags=["gemini"])
app.include_router(legacy_router, prefix="/api", tags=["legacy"])
app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["dashboard"])


# ---------------------------------------------------------------------------
# Template-serving routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    response = templates.TemplateResponse("live.html", {"request": request})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    response = templates.TemplateResponse("dashboard.html", {"request": request})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

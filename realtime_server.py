"""Legacy entrypoint — delegates to counselai.api.app.

Use `uvicorn counselai.api.app:app` instead.
"""

import sys
from pathlib import Path

# Ensure src/ is on the path for the new package
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from counselai.api.app import app  # noqa: F401, E402

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8501)

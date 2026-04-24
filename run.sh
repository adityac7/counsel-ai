#!/bin/bash
PYTHONPATH=src uvicorn counselai.api.app:app --host 0.0.0.0 --port 8501 --reload --reload-dir src --reload-dir templates --reload-dir static

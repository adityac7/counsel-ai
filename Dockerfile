FROM python:3.12-slim

# System deps (ffmpeg for audio/video processing)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY pyproject.toml .
COPY src/ src/
COPY static/ static/
COPY templates/ templates/
COPY case_studies.py .
COPY alembic/ alembic/

# Install the package in editable mode
RUN pip install --no-cache-dir -e .

# Create artifact directory
RUN mkdir -p /app/artifacts

EXPOSE 8501

CMD ["uvicorn", "counselai.api.app:app", "--host", "0.0.0.0", "--port", "8501"]

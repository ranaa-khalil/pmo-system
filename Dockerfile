# PMO System — Docker image

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN groupadd --system pmo && useradd --system --gid pmo pmo \
    && mkdir -p /app/data /app/uploads \
    && chown -R pmo:pmo /app/data /app/uploads

# Copy application code
COPY app ./app

USER pmo
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# Application startup currently creates/migrates/seeds the database, so keep a
# single worker to ensure those operations run exactly once per container.
CMD ["gunicorn", "app.main:app", "-w", "1", "-k", "uvicorn.workers.UvicornWorker", \
     "-b", "0.0.0.0:8000", "--access-logfile", "-", "--error-logfile", "-"]

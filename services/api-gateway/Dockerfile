FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

# Python deps
COPY services/api-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared utilities
COPY services/shared/ ./shared/

# Service code
COPY services/api-gateway/ .

# Alembic migrations (api-gateway runs migrations on startup)
COPY alembic/ ./alembic/
COPY alembic.ini .

RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

ENV PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["gunicorn", "main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", "--timeout", "120"]

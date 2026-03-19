FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client curl && rm -rf /var/lib/apt/lists/*

# Python deps (layer-cache friendly — install before copying app code)
COPY services/ssh-vault/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared utilities
COPY services/shared/ ./shared/

# Service code
COPY services/ssh-vault/ .

# Non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

ENV PYTHONPATH=/app

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8100/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"]

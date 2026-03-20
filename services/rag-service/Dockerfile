FROM python:3.12-slim

# System deps for sentence-transformers / torch
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/rag-service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Download cross-encoder model to a fixed path accessible at runtime
ENV HF_HOME=/app/.cache/huggingface
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

COPY services/rag-service/ ./
COPY services/shared/ ./shared/

RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/app/.cache/huggingface

EXPOSE 8005

HEALTHCHECK --interval=60s --timeout=15s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:8005/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005", "--workers", "2"]

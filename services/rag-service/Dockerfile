FROM python:3.12-slim

# System deps for sentence-transformers / torch
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/rag-service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Download cross-encoder model at build time so containers start instantly
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

COPY services/rag-service/ ./
COPY services/shared/ ./shared/

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8005

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005", "--workers", "2"]

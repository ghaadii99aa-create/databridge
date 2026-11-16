# Backend image. Build context is the repository root (see docker-compose.yml) so the
# bundled SAMPLE dataset can be copied in.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ /app/backend/
COPY sample_data/ /app/sample_data/

RUN useradd --create-home --uid 10001 databridge \
    && mkdir -p /app/data && chown -R databridge /app/data
USER databridge

ENV DATA_DIR=/app/data \
    SAMPLE_DIR=/app/sample_data \
    LOG_FORMAT=json \
    ENVIRONMENT=production

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"

# Apply migrations, then serve. WEB_CONCURRENCY sets the number of worker processes.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips='*'"]

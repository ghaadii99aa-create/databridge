# Single-service image: FastAPI serves both the API and the built frontend.
# Useful for hosts that run one always-on web service plus a managed PostgreSQL.
FROM node:22-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/ /app/backend/
COPY sample_data/ /app/sample_data/
COPY --from=frontend /app/dist /app/frontend_dist
RUN useradd --create-home --uid 10001 databridge && mkdir -p /app/data && chown -R databridge /app/data
USER databridge
ENV DATA_DIR=/app/data SAMPLE_DIR=/app/sample_data FRONTEND_DIST=/app/frontend_dist LOG_FORMAT=json ENVIRONMENT=production
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips='*'"]

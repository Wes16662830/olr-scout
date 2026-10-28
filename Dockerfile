# One image: FastAPI backend serving the built PWA.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ARG INSTALL_PLAYWRIGHT=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt backend/requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements.txt pytesseract pillow pypdf \
    && (pip install --no-cache-dir pywebpush || echo "pywebpush unavailable: push alerts off") \
    && if [ "$INSTALL_PLAYWRIGHT" = "1" ]; then pip install --no-cache-dir playwright && playwright install --with-deps chromium; fi
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
RUN mkdir -p /app/backend/data
EXPOSE 8000
CMD ["uvicorn", "olr_scout.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

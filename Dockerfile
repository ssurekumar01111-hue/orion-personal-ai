# =============================================================================
# Stage 1: Build the React / Vite Frontend
# =============================================================================
FROM node:22-alpine AS frontend-builder

WORKDIR /build

# Install dependencies using the package-lock file
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy frontend source and build static bundle
COPY frontend/ ./
RUN npm run build

# =============================================================================
# Stage 2: Production Python Runtime
# =============================================================================
FROM python:3.12-slim AS runner

# Install curl for container health check
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create a non-root application user and group
RUN groupadd -g 1001 oriongroup && \
    useradd -u 1001 -g oriongroup -s /bin/sh -m orionuser

# Install Python backend dependencies
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r ./backend/requirements.txt

# Copy backend application source
COPY backend ./backend

# Copy the built production frontend from Stage 1
COPY --from=frontend-builder /build/dist ./frontend/dist

# Ensure the data and workspace directories exist with proper non-root ownership
RUN mkdir -p /app/data/workspace && \
    chown -R orionuser:oriongroup /app

USER orionuser

# Default production configuration (Render injects PORT at runtime)
ENV PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    PORT=8000 \
    PYTHONPATH=/app

EXPOSE 8000

# Container health check pointing to /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Launch uvicorn listening on 0.0.0.0 and dynamically binding to PORT
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

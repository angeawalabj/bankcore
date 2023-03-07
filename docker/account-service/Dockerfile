# AccountService — Dockerfile
# Multi-stage build: builder installs deps, runtime is minimal
#
# Stage 1: builder — installs Python dependencies
# Stage 2: runtime — copies only what's needed, runs as non-root
#
# Build: docker build -t bankcore/account-service:latest .
# Run:   docker run -p 8001:8001 bankcore/account-service:latest

# ─── Stage 1: builder ──────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install system deps needed for compilation (none for stdlib-only project)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for Docker layer caching
# (dependencies change less often than source code)
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Stage 2: runtime ──────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="BankCore Architecture Challenge"
LABEL service="account-service"
LABEL version="1.0.0"

# Security: run as non-root user
RUN addgroup --system bankcore && \
    adduser --system --ingroup bankcore --no-create-home bankcore

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY src/bankcore/ ./bankcore/
COPY docker/account-service/entrypoint.sh ./entrypoint.sh
COPY docker/account-service/server.py ./server.py

# Create data directory for SQLite persistence
RUN mkdir -p /app/data && chown bankcore:bankcore /app/data

# Switch to non-root
USER bankcore

# Environment configuration (overridable via docker run -e or compose)
ENV BANKCORE_ENVIRONMENT=production
ENV BANKCORE_DATABASE_URL=sqlite:////app/data/accounts.db
ENV SERVICE_PORT=8001
ENV SERVICE_HOST=0.0.0.0

# Health check: lightweight Python HTTP check
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "\
import urllib.request, sys; \
try: \
    urllib.request.urlopen('http://localhost:8001/health', timeout=3); \
    sys.exit(0) \
except: \
    sys.exit(1)"

EXPOSE 8001

ENTRYPOINT ["sh", "./entrypoint.sh"]

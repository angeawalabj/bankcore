# TransactionService — Dockerfile
# Identical structure to AccountService — consistency by design.
#
# Build: docker build -t bankcore/transaction-service:latest .
# Run:   docker run -p 8002:8002 -e ACCOUNT_SERVICE_URL=http://account-service:8001 \
#               bankcore/transaction-service:latest

FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime

LABEL maintainer="BankCore Architecture Challenge"
LABEL service="transaction-service"
LABEL version="1.0.0"

RUN addgroup --system bankcore && \
    adduser --system --ingroup bankcore --no-create-home bankcore

WORKDIR /app

COPY --from=builder /install /usr/local
COPY src/bankcore/ ./bankcore/
COPY docker/transaction-service/entrypoint.sh ./entrypoint.sh
COPY docker/transaction-service/server.py ./server.py

RUN mkdir -p /app/data && chown bankcore:bankcore /app/data

USER bankcore

ENV BANKCORE_ENVIRONMENT=production
ENV SERVICE_PORT=8002
ENV SERVICE_HOST=0.0.0.0
ENV ACCOUNT_SERVICE_URL=http://account-service:8001

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "\
import urllib.request, sys; \
try: \
    urllib.request.urlopen('http://localhost:8002/health', timeout=3); \
    sys.exit(0) \
except: \
    sys.exit(1)"

EXPOSE 8002

ENTRYPOINT ["sh", "./entrypoint.sh"]

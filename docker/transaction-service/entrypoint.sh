#!/bin/sh
# TransactionService — Docker entrypoint

set -e

echo "[entrypoint] Starting TransactionService..."
echo "[entrypoint] Environment: ${BANKCORE_ENVIRONMENT:-development}"
echo "[entrypoint] Port: ${SERVICE_PORT:-8002}"
echo "[entrypoint] AccountService URL: ${ACCOUNT_SERVICE_URL:-http://account-service:8001}"

# Wait for AccountService to be ready (max 30s)
echo "[entrypoint] Waiting for AccountService..."
RETRIES=0
MAX_RETRIES=30
until python -c "
import urllib.request, sys
try:
    urllib.request.urlopen('${ACCOUNT_SERVICE_URL:-http://account-service:8001}/health', timeout=2)
    sys.exit(0)
except:
    sys.exit(1)
" 2>/dev/null; do
    RETRIES=$((RETRIES + 1))
    if [ $RETRIES -ge $MAX_RETRIES ]; then
        echo "[entrypoint] AccountService not ready after ${MAX_RETRIES}s — aborting."
        exit 1
    fi
    echo "[entrypoint] AccountService not ready yet (attempt $RETRIES/$MAX_RETRIES)..."
    sleep 1
done

echo "[entrypoint] AccountService is ready. Starting TransactionService."

trap 'kill -TERM $PID' TERM INT

python server.py &
PID=$!

wait $PID
EXIT_CODE=$?

echo "[entrypoint] TransactionService stopped with exit code $EXIT_CODE"
exit $EXIT_CODE

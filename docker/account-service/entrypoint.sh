#!/bin/sh
# AccountService — Docker entrypoint
# Handles graceful shutdown via SIGTERM forwarding

set -e

echo "[entrypoint] Starting AccountService..."
echo "[entrypoint] Environment: ${BANKCORE_ENVIRONMENT:-development}"
echo "[entrypoint] Port: ${SERVICE_PORT:-8001}"

# Forward SIGTERM to the Python process for graceful shutdown
trap 'kill -TERM $PID' TERM INT

python server.py &
PID=$!

wait $PID
EXIT_CODE=$?

echo "[entrypoint] AccountService stopped with exit code $EXIT_CODE"
exit $EXIT_CODE

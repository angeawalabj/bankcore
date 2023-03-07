"""
BankCore — Day 19: AccountService HTTP Server
===============================================
Minimal HTTP server wrapping AccountService for Docker deployment.

Uses Python's built-in http.server — no external web framework.
In production (Day 20+) this would be replaced by FastAPI + uvicorn,
but for Day 19 the goal is containerisation, not web framework selection.

Routes:
  GET  /health              → liveness probe for Docker HEALTHCHECK
  GET  /ready               → readiness probe (DB connection verified)
  GET  /accounts            → list accounts
  GET  /accounts/{id}       → get account by ID
  POST /accounts            → create account
  PATCH /accounts/{id}/balance → update balance
"""

import json
import os
import sys
import signal
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

# Add project root to path
sys.path.insert(0, "/app")

from bankcore.services.account_service.service import AccountService
from bankcore.services.shared.service_client import ServiceRequest


# Global service instance
_account_service = AccountService()
_server = None


class AccountServiceHandler(BaseHTTPRequestHandler):
    """HTTP request handler that delegates to AccountService."""

    def log_message(self, format, *args):
        """Override to use structured logging."""
        print(f"[AccountService] {self.address_string()} - {format % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")

        if path == "/health":
            self._respond(200, {"status": "ok", "service": "account-service"})
            return

        if path == "/ready":
            # Readiness: verify the repository is accessible
            count = _account_service.repository.count()
            self._respond(200, {"status": "ready", "accounts": count})
            return

        # Delegate to AccountService router
        req  = ServiceRequest("GET", path)
        resp = _account_service.handle(req)
        self._respond(resp.status_code, resp.body)

    def do_POST(self):
        body = self._read_body()
        req  = ServiceRequest("POST", self.path.rstrip("/"), body=body)
        resp = _account_service.handle(req)
        self._respond(resp.status_code, resp.body)

    def do_PATCH(self):
        body = self._read_body()
        req  = ServiceRequest("PATCH", self.path.rstrip("/"), body=body)
        resp = _account_service.handle(req)
        self._respond(resp.status_code, resp.body)

    def do_DELETE(self):
        req  = ServiceRequest("DELETE", self.path.rstrip("/"))
        resp = _account_service.handle(req)
        self._respond(resp.status_code, resp.body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _respond(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.end_headers()
        self.wfile.write(payload)


def handle_sigterm(signum, frame):
    """Graceful shutdown on SIGTERM (Docker stop)."""
    print("[AccountService] SIGTERM received — shutting down gracefully...")
    if _server:
        threading.Thread(target=_server.shutdown).start()


def main():
    global _server
    host = os.environ.get("SERVICE_HOST", "0.0.0.0")
    port = int(os.environ.get("SERVICE_PORT", "8001"))

    signal.signal(signal.SIGTERM, handle_sigterm)

    _server = HTTPServer((host, port), AccountServiceHandler)
    print(f"[AccountService] Listening on {host}:{port}")
    print(f"[AccountService] Environment: {os.environ.get('BANKCORE_ENVIRONMENT', 'unknown')}")

    try:
        _server.serve_forever()
    except KeyboardInterrupt:
        print("[AccountService] Keyboard interrupt — stopping.")
    finally:
        _server.server_close()
        print("[AccountService] Server stopped.")


if __name__ == "__main__":
    main()

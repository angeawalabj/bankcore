"""
BankCore — Day 19: TransactionService HTTP Server
===================================================
HTTP server wrapping TransactionMicroservice for Docker deployment.

Connects to AccountService via HTTP (real ServiceClient, not in-process).
Uses ACCOUNT_SERVICE_URL environment variable for service discovery.

Routes:
  GET  /health                → liveness probe
  GET  /ready                 → readiness (AccountService reachable)
  POST /transfers             → execute transfer
  POST /deposits              → execute deposit
  POST /withdrawals           → execute withdrawal
  GET  /transactions          → list transactions
  GET  /transactions/{id}     → get transaction by ID
"""

import json
import os
import sys
import signal
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

sys.path.insert(0, "/app")

from bankcore.services.shared.service_client import (
    ServiceClient, ServiceRequest, ServiceResponse,
)
from bankcore.services.transaction_service.service import TransactionMicroservice
from bankcore.protocols import FakeConfig


def make_http_handler(base_url: str) -> callable:
    """
    Create a ServiceClient handler that calls a real HTTP endpoint.
    This replaces the in-process handler from Day 16.
    Same interface — TransactionMicroservice doesn't know the difference.
    """
    def handler(req: ServiceRequest) -> ServiceResponse:
        url = f"{base_url}{req.path}"

        if req.method == "GET":
            http_req = urllib.request.Request(url, method="GET")
        else:
            body_bytes = json.dumps(req.body).encode("utf-8")
            http_req   = urllib.request.Request(
                url, data=body_bytes, method=req.method
            )
            http_req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(http_req, timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
                return ServiceResponse(response.status, body)
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode("utf-8"))
            return ServiceResponse(e.code, body)
        except (urllib.error.URLError, Exception) as e:
            return ServiceResponse(503, {"error": str(e), "code": "SERVICE_UNAVAILABLE"})

    return handler


# Global service instance
_account_service_url = os.environ.get("ACCOUNT_SERVICE_URL", "http://account-service:8001")
_account_handler     = make_http_handler(_account_service_url)
_account_client      = ServiceClient("account-service", _account_handler)
_tx_service          = TransactionMicroservice(_account_client, FakeConfig())
_server              = None


class TransactionServiceHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"[TransactionService] {self.address_string()} - {format % args}")

    def do_GET(self):
        path = self.path.rstrip("/")

        if path == "/health":
            self._respond(200, {"status": "ok", "service": "transaction-service"})
            return

        if path == "/ready":
            # Check AccountService reachability
            resp = _account_client.get("/health")
            if resp.ok:
                self._respond(200, {
                    "status": "ready",
                    "dependencies": {"account-service": "up"},
                })
            else:
                self._respond(503, {
                    "status": "not ready",
                    "dependencies": {"account-service": "down"},
                })
            return

        req  = ServiceRequest("GET", path)
        resp = _tx_service.handle(req)
        self._respond(resp.status_code, resp.body)

    def do_POST(self):
        body = self._read_body()
        req  = ServiceRequest("POST", self.path.rstrip("/"), body=body)
        resp = _tx_service.handle(req)
        self._respond(resp.status_code, resp.body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
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
    print("[TransactionService] SIGTERM received — shutting down...")
    if _server:
        threading.Thread(target=_server.shutdown).start()


def main():
    global _server
    host = os.environ.get("SERVICE_HOST", "0.0.0.0")
    port = int(os.environ.get("SERVICE_PORT", "8002"))

    signal.signal(signal.SIGTERM, handle_sigterm)

    _server = HTTPServer((host, port), TransactionServiceHandler)
    print(f"[TransactionService] Listening on {host}:{port}")
    print(f"[TransactionService] AccountService URL: {_account_service_url}")

    try:
        _server.serve_forever()
    except KeyboardInterrupt:
        print("[TransactionService] Stopping.")
    finally:
        _server.server_close()


if __name__ == "__main__":
    main()

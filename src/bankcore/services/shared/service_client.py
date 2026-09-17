"""
BankCore — Day 16: Service Communication Layer
================================================
ServiceClient and ServiceRegistry for inter-service communication.

Design decision: use in-process simulation instead of real HTTP for Day 16.
Real HTTP (via httpx or requests) arrives at Day 19 with Docker.
The interface is identical — swapping to real HTTP = changing one line
in ServiceRegistry.

ServiceClient: typed client for calling another microservice.
ServiceRegistry: maps service names to their clients (service discovery).

Every call is auto-traced (Day 20): each _call() opens a Span on the
client's own Tracer, tagged with method/path/status, so a caller can
inspect client.tracer.recent_traces() to see exactly what happened
without touching business logic.

Clean Architecture rule:
    - AccountService NEVER imports TransactionService
    - TransactionService calls AccountService via ServiceClient
    - Neither service imports the other's domain classes
    - Communication is pure dict (JSON-like) across service boundaries
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from datetime import datetime

from bankcore.infrastructure.monitoring.tracer import Tracer


@dataclass
class ServiceRequest:
    """Simulated HTTP request between services."""
    method:  str        # GET, POST, PATCH, DELETE
    path:    str        # /accounts/{id}
    body:    dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    params:  dict = field(default_factory=dict)


@dataclass
class ServiceResponse:
    """Simulated HTTP response from a service."""
    status_code: int
    body:        dict
    headers:     dict = field(default_factory=dict)
    latency_ms:  float = 0.0

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def __repr__(self) -> str:
        return f"ServiceResponse({self.status_code}, {list(self.body.keys())})"


# Type for a request handler function
RequestHandler = Callable[[ServiceRequest], ServiceResponse]


class ServiceClient:
    """
    Client for calling another microservice.

    In Day 16: backed by an in-process handler (no real HTTP).
    In Day 19: backed by real HTTP (httpx) — same interface.

    Usage:
        client = ServiceClient("account-service", handler=account_service.handle)
        response = client.get("/accounts/ACC-001")
        response = client.post("/accounts", {"owner_name": "Alice", ...})
        response = client.patch("/accounts/ACC-001/balance", {"balance": 900.0})
    """

    def __init__(self, service_name: str, handler: RequestHandler) -> None:
        self._name    = service_name
        self._handler = handler
        self._call_count = 0
        self._call_log: list[dict] = []
        self._tracer  = Tracer(service_name)

    def get(self, path: str, params: dict = None) -> ServiceResponse:
        return self._call("GET", path, params=params or {})

    def post(self, path: str, body: dict = None) -> ServiceResponse:
        return self._call("POST", path, body=body or {})

    def patch(self, path: str, body: dict = None) -> ServiceResponse:
        return self._call("PATCH", path, body=body or {})

    def delete(self, path: str) -> ServiceResponse:
        return self._call("DELETE", path)

    def _call(
        self,
        method: str,
        path: str,
        body: dict = None,
        params: dict = None,
    ) -> ServiceResponse:
        import time
        req   = ServiceRequest(method=method, path=path,
                               body=body or {}, params=params or {})

        with self._tracer.start_span(f"{method} {self._name}{path}") as span:
            span.set_tag("service", self._name)
            span.set_tag("http.method", method)
            span.set_tag("http.path", path)

            start = time.perf_counter()
            resp  = self._handler(req)
            resp.latency_ms = (time.perf_counter() - start) * 1000

            span.set_tag("http.status", resp.status_code)
            if not resp.ok:
                span.set_error(f"HTTP {resp.status_code}")

        self._call_count += 1
        self._call_log.append({
            "method":      method,
            "path":        path,
            "status":      resp.status_code,
            "latency_ms":  resp.latency_ms,
            "timestamp":   datetime.now().isoformat(),
        })
        return resp

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def service_name(self) -> str:
        return self._name

    @property
    def tracer(self) -> Tracer:
        """The Tracer recording every call made through this client."""
        return self._tracer

    def get_call_log(self) -> list[dict]:
        return list(self._call_log)

    def reset_stats(self) -> None:
        self._call_count = 0
        self._call_log.clear()


class ServiceRegistry:
    """
    Service discovery registry.

    Maps service names to ServiceClient instances.
    In production this would be backed by Consul, Kubernetes DNS,
    or AWS Service Discovery.

    For Day 16: in-process registry with direct handler wiring.
    For Day 19: each service runs in a Docker container with a real URL.

    Usage:
        registry = ServiceRegistry()
        registry.register("account-service", account_service.handle)
        client = registry.get("account-service")
        response = client.get("/accounts/ACC-001")
    """

    def __init__(self) -> None:
        self._services: dict[str, ServiceClient] = {}

    def register(
        self,
        name: str,
        handler: RequestHandler,
    ) -> ServiceClient:
        """Register a service and return its client."""
        client = ServiceClient(name, handler)
        self._services[name] = client
        return client

    def get(self, name: str) -> ServiceClient:
        """Return the client for a registered service."""
        client = self._services.get(name)
        if client is None:
            available = list(self._services.keys())
            raise KeyError(
                f"Service '{name}' not registered. Available: {available}"
            )
        return client

    def is_registered(self, name: str) -> bool:
        return name in self._services

    def registered_services(self) -> list[str]:
        return list(self._services.keys())

    def total_calls(self) -> int:
        return sum(c.call_count for c in self._services.values())

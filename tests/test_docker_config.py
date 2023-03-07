"""
Tests — Day 19: Docker Configuration
======================================
Tests that validate Docker configuration files without running Docker.

Strategy: verify the correctness of Dockerfiles, docker-compose.yml,
and server.py files by inspecting their content — no Docker daemon needed.

These tests run in CI alongside all other unit tests.
They catch common Docker config mistakes:
  - Missing HEALTHCHECK
  - Non-root user not set
  - Wrong port exposure
  - Missing environment variable declarations
  - Entrypoint not referencing the right script
"""

import sys
import os
import yaml
import json
import pytest

sys.path.insert(0, "src")

DOCKER_DIR = os.path.join(os.path.dirname(__file__), "..", "docker")
ACCOUNT_DIR = os.path.join(DOCKER_DIR, "account-service")
TX_DIR = os.path.join(DOCKER_DIR, "transaction-service")


def read_file(path: str) -> str:
    with open(path) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Dockerfile — AccountService
# ---------------------------------------------------------------------------

class TestAccountServiceDockerfile:

    @pytest.fixture
    def dockerfile(self):
        return read_file(os.path.join(ACCOUNT_DIR, "Dockerfile"))

    def test_uses_slim_base_image(self, dockerfile):
        assert "python:3.12-slim" in dockerfile

    def test_multi_stage_build(self, dockerfile):
        assert "AS builder" in dockerfile
        assert "AS runtime" in dockerfile

    def test_non_root_user(self, dockerfile):
        assert "adduser" in dockerfile
        assert "USER bankcore" in dockerfile

    def test_healthcheck_defined(self, dockerfile):
        assert "HEALTHCHECK" in dockerfile
        assert "/health" in dockerfile

    def test_correct_port_exposed(self, dockerfile):
        assert "EXPOSE 8001" in dockerfile

    def test_environment_variables_declared(self, dockerfile):
        assert "BANKCORE_ENVIRONMENT" in dockerfile
        assert "SERVICE_PORT" in dockerfile

    def test_entrypoint_defined(self, dockerfile):
        assert "ENTRYPOINT" in dockerfile
        assert "entrypoint.sh" in dockerfile

    def test_data_directory_created(self, dockerfile):
        assert "mkdir -p /app/data" in dockerfile

    def test_no_cache_in_pip_install(self, dockerfile):
        assert "--no-cache-dir" in dockerfile


# ---------------------------------------------------------------------------
# Dockerfile — TransactionService
# ---------------------------------------------------------------------------

class TestTransactionServiceDockerfile:

    @pytest.fixture
    def dockerfile(self):
        return read_file(os.path.join(TX_DIR, "Dockerfile"))

    def test_uses_slim_base_image(self, dockerfile):
        assert "python:3.12-slim" in dockerfile

    def test_multi_stage_build(self, dockerfile):
        assert "AS builder" in dockerfile
        assert "AS runtime" in dockerfile

    def test_non_root_user(self, dockerfile):
        assert "USER bankcore" in dockerfile

    def test_healthcheck_defined(self, dockerfile):
        assert "HEALTHCHECK" in dockerfile

    def test_correct_port_exposed(self, dockerfile):
        assert "EXPOSE 8002" in dockerfile

    def test_account_service_url_env_declared(self, dockerfile):
        assert "ACCOUNT_SERVICE_URL" in dockerfile

    def test_longer_start_period_than_account_service(self, dockerfile):
        """TransactionService needs more start time (waits for AccountService)."""
        assert "start-period=10s" in dockerfile or "start_period=10s" in dockerfile or \
               "start-period=15s" in dockerfile or "start_period=15s" in dockerfile


# ---------------------------------------------------------------------------
# docker-compose.yml
# ---------------------------------------------------------------------------

class TestDockerCompose:

    @pytest.fixture
    def compose(self):
        path = os.path.join(DOCKER_DIR, "docker-compose.yml")
        with open(path) as f:
            return yaml.safe_load(f)

    def test_both_services_defined(self, compose):
        services = compose["services"]
        assert "account-service" in services
        assert "transaction-service" in services

    def test_redis_defined(self, compose):
        assert "redis" in compose["services"]

    def test_rabbitmq_defined(self, compose):
        assert "rabbitmq" in compose["services"]

    def test_account_service_port(self, compose):
        ports = compose["services"]["account-service"]["ports"]
        assert any("8001" in str(p) for p in ports)

    def test_transaction_service_port(self, compose):
        ports = compose["services"]["transaction-service"]["ports"]
        assert any("8002" in str(p) for p in ports)

    def test_transaction_depends_on_account(self, compose):
        tx = compose["services"]["transaction-service"]
        assert "depends_on" in tx
        assert "account-service" in tx["depends_on"]

    def test_depends_on_uses_health_condition(self, compose):
        tx      = compose["services"]["transaction-service"]
        dep     = tx["depends_on"]["account-service"]
        assert dep.get("condition") == "service_healthy"

    def test_account_service_has_healthcheck(self, compose):
        hc = compose["services"]["account-service"].get("healthcheck")
        assert hc is not None
        assert hc.get("interval") is not None

    def test_volumes_defined(self, compose):
        assert "volumes" in compose
        assert "account-data" in compose["volumes"]
        assert "redis-data" in compose["volumes"]

    def test_shared_network_defined(self, compose):
        assert "networks" in compose
        services = compose["services"]
        for svc_name in ["account-service", "transaction-service", "redis"]:
            svc = services[svc_name]
            assert "networks" in svc

    def test_account_service_url_in_tx_env(self, compose):
        tx_env = compose["services"]["transaction-service"].get("environment", {})
        if isinstance(tx_env, list):
            env_str = " ".join(tx_env)
        else:
            env_str = " ".join(f"{k}={v}" for k, v in tx_env.items())
        assert "ACCOUNT_SERVICE_URL" in env_str

    def test_restart_policy(self, compose):
        """Services should restart unless explicitly stopped."""
        for svc_name in ["account-service", "transaction-service"]:
            svc = compose["services"][svc_name]
            assert svc.get("restart") == "unless-stopped"

    def test_logging_configured(self, compose):
        """Log rotation prevents disk fill on long-running containers."""
        for svc_name in ["account-service", "transaction-service"]:
            svc = compose["services"][svc_name]
            assert "logging" in svc


# ---------------------------------------------------------------------------
# Entrypoint scripts
# ---------------------------------------------------------------------------

class TestEntrypointScripts:

    def test_account_entrypoint_starts_server(self):
        content = read_file(os.path.join(ACCOUNT_DIR, "entrypoint.sh"))
        assert "python server.py" in content

    def test_account_entrypoint_handles_sigterm(self):
        content = read_file(os.path.join(ACCOUNT_DIR, "entrypoint.sh"))
        assert "TERM" in content
        assert "trap" in content

    def test_tx_entrypoint_waits_for_account_service(self):
        content = read_file(os.path.join(TX_DIR, "entrypoint.sh"))
        assert "account" in content.lower()
        assert "/health" in content

    def test_tx_entrypoint_has_retry_limit(self):
        content = read_file(os.path.join(TX_DIR, "entrypoint.sh"))
        assert "MAX_RETRIES" in content or "max_retries" in content.lower()

    def test_tx_entrypoint_exits_on_timeout(self):
        content = read_file(os.path.join(TX_DIR, "entrypoint.sh"))
        assert "exit 1" in content


# ---------------------------------------------------------------------------
# Server files — structural validation
# ---------------------------------------------------------------------------

class TestServerFiles:

    def test_account_server_has_health_route(self):
        content = read_file(os.path.join(ACCOUNT_DIR, "server.py"))
        assert "/health" in content

    def test_account_server_has_ready_route(self):
        content = read_file(os.path.join(ACCOUNT_DIR, "server.py"))
        assert "/ready" in content

    def test_account_server_handles_sigterm(self):
        content = read_file(os.path.join(ACCOUNT_DIR, "server.py"))
        assert "SIGTERM" in content

    def test_account_server_reads_port_from_env(self):
        content = read_file(os.path.join(ACCOUNT_DIR, "server.py"))
        assert "SERVICE_PORT" in content

    def test_tx_server_reads_account_service_url_from_env(self):
        content = read_file(os.path.join(TX_DIR, "server.py"))
        assert "ACCOUNT_SERVICE_URL" in content

    def test_tx_server_has_ready_route_checking_account_service(self):
        content = read_file(os.path.join(TX_DIR, "server.py"))
        assert "/ready" in content
        assert "account" in content.lower()

    def test_tx_server_uses_real_http_handler(self):
        """TransactionService server makes real HTTP calls (not in-process)."""
        content = read_file(os.path.join(TX_DIR, "server.py"))
        assert "urllib.request" in content

    def test_account_server_non_root_comment_or_structure(self):
        """Server runs as non-root (enforced by Dockerfile USER directive)."""
        dockerfile = read_file(os.path.join(ACCOUNT_DIR, "Dockerfile"))
        assert "USER bankcore" in dockerfile


# ---------------------------------------------------------------------------
# docker-compose.test.yml
# ---------------------------------------------------------------------------

class TestDockerComposeTest:

    @pytest.fixture
    def compose_test(self):
        path = os.path.join(DOCKER_DIR, "docker-compose.test.yml")
        with open(path) as f:
            return yaml.safe_load(f)

    def test_test_runner_service_defined(self, compose_test):
        assert "test-runner" in compose_test["services"]

    def test_test_runner_depends_on_transaction_service(self, compose_test):
        runner = compose_test["services"]["test-runner"]
        assert "depends_on" in runner
        assert "transaction-service" in runner["depends_on"]

    def test_test_runner_runs_pytest(self, compose_test):
        runner  = compose_test["services"]["test-runner"]
        command = str(runner.get("command", ""))
        assert "pytest" in command

    def test_services_use_test_environment(self, compose_test):
        for svc_name in ["account-service", "transaction-service"]:
            svc = compose_test["services"][svc_name]
            env = svc.get("environment", {})
            if isinstance(env, dict):
                assert env.get("BANKCORE_ENVIRONMENT") == "test"
            else:
                assert any("test" in str(e) for e in env)

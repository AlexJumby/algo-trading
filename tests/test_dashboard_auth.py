"""Tests for dashboard Bearer token auth middleware (Fix #4).

Requires fastapi + httpx (dashboard deps). Skipped if not installed.
"""
import os

import pytest

# Set a known token BEFORE importing the app module
os.environ["DASHBOARD_TOKEN"] = "test-secret-token-42"

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
httpx = pytest.importorskip("httpx", reason="httpx not installed (needed for TestClient)")

from fastapi.testclient import TestClient  # noqa: E402

from src.dashboard.app import app, AUTH_TOKEN  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {AUTH_TOKEN}"}


class TestDashboardAuth:
    def test_health_no_auth_required(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_index_no_auth_required(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_status_rejects_without_token(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 401

    def test_status_rejects_wrong_token(self, client):
        resp = client.get("/api/status", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_status_accepts_correct_token(self, client, auth_headers):
        # May fail on DB access, but auth should pass (not 401)
        resp = client.get("/api/status", headers=auth_headers)
        assert resp.status_code != 401

    def test_equity_requires_auth(self, client):
        resp = client.get("/api/equity")
        assert resp.status_code == 401

    def test_trades_requires_auth(self, client):
        resp = client.get("/api/trades")
        assert resp.status_code == 401

"""Health endpoint tests.

/health is the load balancer's cheap liveness check — must never touch deps.
/health/ready verifies Supabase + Redis reachability. Failure returns 503
so orchestrators pull the pod out of rotation while keeping it alive.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


class TestLiveness:
    def test_returns_200_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestReadiness:
    def test_both_deps_ok(self, client, mocker):
        # Mock Supabase chain: get_supabase().table().select().limit().execute()
        mock_supabase = mocker.MagicMock()
        mock_supabase.table().select().limit().execute.return_value = mocker.MagicMock()
        mocker.patch("app.main.get_supabase", return_value=mock_supabase)

        mock_redis = mocker.MagicMock()
        mock_redis.ping.return_value = True
        mocker.patch("app.main.get_redis", return_value=mock_redis)

        r = client.get("/health/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["checks"]["supabase"] == "ok"
        assert body["checks"]["redis"] == "ok"

    def test_supabase_down_returns_503(self, client, mocker):
        mock_supabase = mocker.MagicMock()
        mock_supabase.table().select().limit().execute.side_effect = ConnectionError("boom")
        mocker.patch("app.main.get_supabase", return_value=mock_supabase)

        mock_redis = mocker.MagicMock()
        mock_redis.ping.return_value = True
        mocker.patch("app.main.get_redis", return_value=mock_redis)

        r = client.get("/health/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "not_ready"
        assert "fail" in body["checks"]["supabase"]
        assert body["checks"]["redis"] == "ok"

    def test_redis_down_returns_503(self, client, mocker):
        mock_supabase = mocker.MagicMock()
        mock_supabase.table().select().limit().execute.return_value = mocker.MagicMock()
        mocker.patch("app.main.get_supabase", return_value=mock_supabase)

        mock_redis = mocker.MagicMock()
        mock_redis.ping.side_effect = ConnectionError("redis down")
        mocker.patch("app.main.get_redis", return_value=mock_redis)

        r = client.get("/health/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["checks"]["supabase"] == "ok"
        assert "fail" in body["checks"]["redis"]

    def test_both_down_returns_503(self, client, mocker):
        mock_supabase = mocker.MagicMock()
        mock_supabase.table().select().limit().execute.side_effect = RuntimeError("db")
        mocker.patch("app.main.get_supabase", return_value=mock_supabase)

        mock_redis = mocker.MagicMock()
        mock_redis.ping.side_effect = RuntimeError("redis")
        mocker.patch("app.main.get_redis", return_value=mock_redis)

        r = client.get("/health/ready")
        assert r.status_code == 503
        body = r.json()
        assert "fail" in body["checks"]["supabase"]
        assert "fail" in body["checks"]["redis"]

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fitmas.legacy.app.api.basic_auth import BasicAuthMiddleware


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/secret")
    def secret():
        return {"data": "private"}

    return TestClient(app)


def test_auth_disabled_when_no_password(monkeypatch):
    monkeypatch.delenv("FITMAS_APP_PASSWORD", raising=False)
    assert _client().get("/secret").status_code == 200


def test_401_without_credentials(monkeypatch):
    monkeypatch.setenv("FITMAS_APP_PASSWORD", "pw")
    resp = _client().get("/secret")
    assert resp.status_code == 401
    assert "Basic" in resp.headers.get("www-authenticate", "")


def test_200_with_correct_credentials(monkeypatch):
    monkeypatch.setenv("FITMAS_APP_PASSWORD", "pw")
    monkeypatch.setenv("FITMAS_APP_USER", "loic")
    token = base64.b64encode(b"loic:pw").decode()
    assert _client().get("/secret", headers={"Authorization": f"Basic {token}"}).status_code == 200


def test_401_with_wrong_password(monkeypatch):
    monkeypatch.setenv("FITMAS_APP_PASSWORD", "pw")
    token = base64.b64encode(b"loic:wrong").decode()
    assert _client().get("/secret", headers={"Authorization": f"Basic {token}"}).status_code == 401


def test_health_always_open(monkeypatch):
    monkeypatch.setenv("FITMAS_APP_PASSWORD", "pw")
    assert _client().get("/health").status_code == 200

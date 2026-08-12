from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


client = TestClient(app)


def test_health_is_public() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_admin_check_requires_header(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "phase-one-secret")
    get_settings.cache_clear()

    assert client.get("/api/admin/check").status_code == 401
    assert client.get("/api/admin/check", headers={"X-Admin-Password": "wrong"}).status_code == 401

    response = client.get(
        "/api/admin/check", headers={"X-Admin-Password": "phase-one-secret"}
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "set-cookie" not in response.headers
    get_settings.cache_clear()

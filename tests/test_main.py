from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-pass")

    from app import main as app_main
    from app.config import ConfigManager
    from app.db import Database
    from app.services import ClientService

    cfg_path = tmp_path / "config.yaml"
    db_path = tmp_path / "telearr.db"

    config_manager = ConfigManager(cfg_path)
    db = Database(db_path)
    client_service = ClientService(db)

    app_main.config_manager = config_manager
    app_main.db = db
    app_main.client_service = client_service
    app_main.CONFIG_PATH = cfg_path
    app_main.DB_PATH = db_path
    app_main.DATA_DIR = tmp_path

    app_main.BOT_RUNTIME["enabled"] = False
    app_main.BOT_RUNTIME["running"] = False
    app_main.BOT_RUNTIME["last_error"] = None

    return TestClient(app_main.app)


class TestHealth:
    def test_health_endpoint(self, test_client):
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "bot" in data


class TestLogin:
    def test_login_page(self, test_client):
        response = test_client.get("/login")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_login_success(self, test_client):
        response = test_client.post(
            "/login", data={"password": "test-pass"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert "telearr_session" in response.cookies

    def test_login_failure(self, test_client):
        response = test_client.post("/login", data={"password": "wrong-pass"})
        assert response.status_code == 401

    def test_logout(self, test_client):
        response = test_client.get("/logout", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


class TestDashboard:
    def test_dashboard_redirects_when_not_authenticated(self, test_client):
        response = test_client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_dashboard_renders_when_authenticated(self, test_client):
        login = test_client.post(
            "/login", data={"password": "test-pass"}, follow_redirects=False
        )
        cookie = login.cookies["telearr_session"]

        response = test_client.get("/", cookies={"telearr_session": cookie})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestClientManagement:
    def _login(self, test_client):
        login = test_client.post(
            "/login", data={"password": "test-pass"}, follow_redirects=False
        )
        return login.cookies["telearr_session"]

    def test_approve_client_requires_auth(self, test_client):
        response = test_client.post(
            "/clients/12345/approve",
            data={"token": "some-token"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_block_client_requires_auth(self, test_client):
        response = test_client.post("/clients/12345/block", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_unblock_client_requires_auth(self, test_client):
        response = test_client.post("/clients/12345/unblock", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_approve_client(self, test_client):
        cookie = self._login(test_client)

        from app.main import client_service
        from app.db import Database
        import secrets

        db: Database = client_service.db

        db.execute(
            "INSERT INTO clients (telegram_user_id, username, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)",
            (999, "approve_me", "2024-01-01T00:00:00", "2024-01-01T00:00:00"),
        )
        token = secrets.token_urlsafe(12)
        db.execute(
            "INSERT INTO pair_tokens (telegram_user_id, token, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (999, token, "2099-01-01T00:00:00+00:00", "2024-01-01T00:00:00"),
        )

        response = test_client.post(
            f"/clients/999/approve",
            data={"token": token},
            cookies={"telearr_session": cookie},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"

        state = client_service.get_client_state(999)
        assert state["approved"] == 1

    def test_block_client(self, test_client):
        cookie = self._login(test_client)
        from app.main import client_service
        from app.db import Database

        db: Database = client_service.db
        db.execute(
            "INSERT INTO clients (telegram_user_id, username, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)",
            (777, "block_me", "2024-01-01T00:00:00", "2024-01-01T00:00:00"),
        )

        response = test_client.post(
            "/clients/777/block",
            cookies={"telearr_session": cookie},
            follow_redirects=False,
        )
        assert response.status_code == 303

        state = client_service.get_client_state(777)
        assert state["blocked"] == 1

    def test_block_and_unblock_client(self, test_client):
        cookie = self._login(test_client)
        from app.main import client_service
        from app.db import Database

        db: Database = client_service.db
        db.execute(
            "INSERT INTO clients (telegram_user_id, username, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)",
            (888, "test_user", "2024-01-01T00:00:00", "2024-01-01T00:00:00"),
        )

        response = test_client.post(
            "/clients/888/block",
            cookies={"telearr_session": cookie},
            follow_redirects=False,
        )
        assert response.status_code == 303

        state = client_service.get_client_state(888)
        assert state["blocked"] == 1

        response = test_client.post(
            "/clients/888/unblock",
            cookies={"telearr_session": cookie},
            follow_redirects=False,
        )
        assert response.status_code == 303

        state = client_service.get_client_state(888)
        assert state["blocked"] == 0


class TestConfigSave:
    def test_save_config_requires_auth(self, test_client):
        response = test_client.post(
            "/config/save", data={"config_yaml": "test"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_save_config(self, test_client):
        login = test_client.post(
            "/login", data={"password": "test-pass"}, follow_redirects=False
        )
        cookie = login.cookies["telearr_session"]

        response = test_client.post(
            "/config/save",
            data={"config_yaml": "telegram:\n  bot_token: 'updated'\n"},
            cookies={"telearr_session": cookie},
        )
        assert response.status_code == 200

        from app.main import config_manager
        cfg = config_manager.config
        assert cfg.telegram.bot_token == "updated"

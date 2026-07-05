from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc

from app.services import ClientService


class TestEnsureClient:
    def test_creates_new_client(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        row = db.fetchone(
            "SELECT * FROM clients WHERE telegram_user_id = ?", (12345,)
        )
        assert row is not None
        assert row["username"] == "testuser"
        assert row["approved"] == 0
        assert row["blocked"] == 0

    def test_updates_existing_client(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        mock_telegram_user.username = "updateduser"
        svc.ensure_client(mock_telegram_user)
        rows = db.fetchall("SELECT * FROM clients WHERE telegram_user_id = ?", (12345,))
        assert len(rows) == 1
        assert rows[0]["username"] == "updateduser"

    def test_handles_none_username(self, db, mock_telegram_user_no_username):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user_no_username)
        row = db.fetchone(
            "SELECT * FROM clients WHERE telegram_user_id = ?", (67890,)
        )
        assert row is not None
        assert row["username"] is None


class TestPairTokens:
    def test_create_pair_token(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        token, expires_at = svc.create_pair_token(12345)
        assert len(token) > 0
        assert expires_at is not None
        row = db.fetchone(
            "SELECT * FROM pair_tokens WHERE telegram_user_id = ?", (12345,)
        )
        assert row is not None
        assert row["token"] == token
        assert row["used"] == 0

    def test_approve_with_valid_token(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        token, _ = svc.create_pair_token(12345)
        result = svc.approve_with_token(12345, token)
        assert result is True
        state = svc.get_client_state(12345)
        assert state["approved"] == 1

    def test_approve_with_wrong_token(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        svc.create_pair_token(12345)
        result = svc.approve_with_token(12345, "wrong-token")
        assert result is False

    def test_approve_with_expired_token(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        token, _ = svc.create_pair_token(12345)
        db.execute(
            "UPDATE pair_tokens SET expires_at = ? WHERE token = ?",
            ((datetime.now(UTC) - timedelta(hours=1)).isoformat(), token),
        )
        result = svc.approve_with_token(12345, token)
        assert result is False

    def test_approve_with_used_token(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        token, _ = svc.create_pair_token(12345)
        svc.approve_with_token(12345, token)
        result = svc.approve_with_token(12345, token)
        assert result is False

    def test_approve_nonexistent_user(self, db):
        svc = ClientService(db)
        result = svc.approve_with_token(99999, "some-token")
        assert result is False


class TestBlockUnblock:
    def test_set_blocked(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        svc.set_blocked(12345, True)
        state = svc.get_client_state(12345)
        assert state["blocked"] == 1

    def test_set_unblocked(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        svc.set_blocked(12345, True)
        svc.set_blocked(12345, False)
        state = svc.get_client_state(12345)
        assert state["blocked"] == 0


class TestGetClientState:
    def test_returns_none_if_not_found(self, db):
        svc = ClientService(db)
        assert svc.get_client_state(99999) is None

    def test_returns_client_dict(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        state = svc.get_client_state(12345)
        assert isinstance(state, dict)
        assert state["telegram_user_id"] == 12345
        assert state["username"] == "testuser"


class TestListClients:
    def test_returns_all_clients(self, db, mock_telegram_user, mock_telegram_user_no_username):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        svc.ensure_client(mock_telegram_user_no_username)
        clients = svc.list_clients()
        assert len(clients) == 2

    def test_returns_empty_when_no_clients(self, db):
        svc = ClientService(db)
        assert svc.list_clients() == []


class TestListPendingTokens:
    def test_returns_pending_tokens(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        svc.create_pair_token(12345)
        pending = svc.list_pending_tokens()
        assert len(pending) == 1
        assert pending[0]["telegram_user_id"] == 12345

    def test_excludes_approved_clients(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        token, _ = svc.create_pair_token(12345)
        svc.approve_with_token(12345, token)
        pending = svc.list_pending_tokens()
        assert pending == []

    def test_excludes_expired_tokens(self, db, mock_telegram_user):
        svc = ClientService(db)
        svc.ensure_client(mock_telegram_user)
        svc.create_pair_token(12345)
        db.execute(
            "UPDATE pair_tokens SET expires_at = ?",
            ((datetime.now(UTC) - timedelta(hours=1)).isoformat(),),
        )
        pending = svc.list_pending_tokens()
        assert pending == []

    def test_returns_empty_when_no_tokens(self, db):
        svc = ClientService(db)
        assert svc.list_pending_tokens() == []


class TestLogging:
    def test_log_search(self, db):
        svc = ClientService(db)
        svc.log_search(12345, "serie", "Breaking Bad")
        rows = db.fetchall("SELECT * FROM search_logs")
        assert len(rows) == 1
        assert rows[0]["media_type"] == "serie"
        assert rows[0]["query"] == "Breaking Bad"

    def test_log_activity(self, db):
        svc = ClientService(db)
        svc.log_activity(12345, "add", "Added series: Test")
        rows = db.fetchall("SELECT * FROM activity_logs")
        assert len(rows) == 1
        assert rows[0]["action"] == "add"
        assert rows[0]["details"] == "Added series: Test"

    def test_last_searches(self, db):
        svc = ClientService(db)
        for i in range(5):
            svc.log_search(i, "serie", f"Query {i}")
        searches = svc.last_searches(3)
        assert len(searches) == 3

    def test_last_activities(self, db):
        svc = ClientService(db)
        for i in range(5):
            svc.log_activity(i, "action", f"Details {i}")
        activities = svc.last_activities(3)
        assert len(activities) == 3

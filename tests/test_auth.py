from __future__ import annotations

from app.auth import SessionAuth, verify_password


class TestVerifyPassword:
    def test_matches(self):
        assert verify_password("admin", "admin") is True

    def test_does_not_match(self):
        assert verify_password("admin", "wrong") is False

    def test_empty(self):
        assert verify_password("", "") is True

    def test_empty_vs_non_empty(self):
        assert verify_password("", "admin") is False

    def test_unicode(self):
        assert verify_password("ñoño", "ñoño") is True
        assert verify_password("ñoño", "nono") is False


class TestSessionAuth:
    def test_create_session_returns_string(self):
        auth = SessionAuth("secret")
        token = auth.create_session()
        assert isinstance(token, str)
        assert len(token) > 0

    def test_is_valid_with_valid_token(self):
        auth = SessionAuth("secret")
        token = auth.create_session()
        assert auth.is_valid(token) is True

    def test_is_valid_with_none(self):
        auth = SessionAuth("secret")
        assert auth.is_valid(None) is False

    def test_is_valid_with_empty(self):
        auth = SessionAuth("secret")
        assert auth.is_valid("") is False

    def test_is_valid_with_tampered_token(self):
        auth = SessionAuth("secret")
        token = auth.create_session()
        tampered = token[:-1] + ("x" if token[-1] != "x" else "y")
        assert auth.is_valid(tampered) is False

    def test_is_valid_with_garbage(self):
        auth = SessionAuth("secret")
        assert auth.is_valid("not-a-valid-token") is False

    def test_different_secret_invalidates(self):
        auth1 = SessionAuth("secret1")
        auth2 = SessionAuth("secret2")
        token = auth1.create_session()
        assert auth2.is_valid(token) is False

    def test_same_secret_validates(self):
        auth1 = SessionAuth("same-secret")
        auth2 = SessionAuth("same-secret")
        token = auth1.create_session()
        assert auth2.is_valid(token) is True

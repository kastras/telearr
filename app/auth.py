from __future__ import annotations

import hmac
import secrets
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


SESSION_MAX_AGE_SECONDS = 8 * 60 * 60


def verify_password(plain_password: str, expected_password: str) -> bool:
    return hmac.compare_digest(
        plain_password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )


class SessionAuth:
    def __init__(self, secret: str):
        self.secret = secret
        self._serializer: URLSafeTimedSerializer | None = None

    @property
    def serializer(self) -> URLSafeTimedSerializer:
        if self._serializer is None:
            self._serializer = URLSafeTimedSerializer(self.secret, salt="telearr-admin")
        return self._serializer

    def create_session(self) -> str:
        return self.serializer.dumps({"role": "admin", "csrf": secrets.token_urlsafe(32)})

    def session_data(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        try:
            data: Any = self.serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
        except (BadSignature, SignatureExpired):
            return None
        return data if isinstance(data, dict) and data.get("role") == "admin" else None

    def is_valid(self, token: str | None) -> bool:
        return self.session_data(token) is not None

    def is_valid_csrf(self, token: str | None, csrf_token: str) -> bool:
        data = self.session_data(token)
        csrf = data.get("csrf") if data else None
        return isinstance(csrf, str) and hmac.compare_digest(csrf, csrf_token)

from __future__ import annotations

import hmac
from typing import Any

from itsdangerous import URLSafeSerializer


def verify_password(plain_password: str, expected_password: str) -> bool:
    return hmac.compare_digest(
        plain_password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )


class SessionAuth:
    def __init__(self, secret: str):
        self.secret = secret
        self._serializer: URLSafeSerializer | None = None

    @property
    def serializer(self) -> URLSafeSerializer:
        if self._serializer is None:
            self._serializer = URLSafeSerializer(self.secret, salt="telearr-admin")
        return self._serializer

    def create_session(self) -> str:
        return self.serializer.dumps({"role": "admin"})

    def is_valid(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            data: Any = self.serializer.loads(token)
        except Exception:
            return False
        return data.get("role") == "admin"

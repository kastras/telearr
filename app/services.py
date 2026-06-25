from __future__ import annotations

from datetime import UTC, datetime, timedelta
import secrets
from typing import Any

from .db import Database


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ClientService:
    def __init__(self, db: Database):
        self.db = db

    def ensure_client(self, user: Any) -> None:
        row = self.db.fetchone(
            "SELECT telegram_user_id FROM clients WHERE telegram_user_id = ?",
            (user.id,),
        )
        if row:
            self.db.execute(
                """
                UPDATE clients
                SET username = ?, first_name = ?, last_name = ?, last_seen_at = ?
                WHERE telegram_user_id = ?
                """,
                (user.username, user.first_name, user.last_name, now_iso(), user.id),
            )
            return

        ts = now_iso()
        self.db.execute(
            """
            INSERT INTO clients (telegram_user_id, username, first_name, last_name, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user.id, user.username, user.first_name, user.last_name, ts, ts),
        )

    def create_pair_token(self, telegram_user_id: int) -> tuple[str, str]:
        token = secrets.token_urlsafe(12)
        expires_at = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
        self.db.execute(
            "INSERT INTO pair_tokens (telegram_user_id, token, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (telegram_user_id, token, expires_at, now_iso()),
        )
        return token, expires_at

    def get_client_state(self, telegram_user_id: int) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "SELECT * FROM clients WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        if not row:
            return None
        return dict(row)

    def approve_with_token(self, telegram_user_id: int, token: str) -> bool:
        row = self.db.fetchone(
            """
            SELECT token, expires_at, used FROM pair_tokens
            WHERE telegram_user_id = ? AND token = ?
            ORDER BY id DESC LIMIT 1
            """,
            (telegram_user_id, token),
        )
        if not row:
            return False

        expires = datetime.fromisoformat(row["expires_at"])
        if row["used"] or expires < datetime.now(UTC):
            return False

        self.db.execute(
            "UPDATE clients SET approved = 1, blocked = 0 WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        self.db.execute(
            "UPDATE pair_tokens SET used = 1 WHERE telegram_user_id = ? AND token = ?",
            (telegram_user_id, token),
        )
        return True

    def set_blocked(self, telegram_user_id: int, blocked: bool) -> None:
        self.db.execute(
            "UPDATE clients SET blocked = ? WHERE telegram_user_id = ?",
            (1 if blocked else 0, telegram_user_id),
        )

    def list_clients(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall("SELECT * FROM clients ORDER BY last_seen_at DESC")
        return [dict(r) for r in rows]

    def list_pending_tokens(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT c.telegram_user_id, c.username, c.first_name, c.last_name, p.token, p.expires_at
            FROM clients c
            JOIN pair_tokens p ON p.telegram_user_id = c.telegram_user_id
            WHERE c.approved = 0 AND c.blocked = 0 AND p.used = 0
            ORDER BY p.id DESC
            """
        )

        now = datetime.now(UTC)
        valid: list[dict[str, Any]] = []
        seen: set[int] = set()
        for r in rows:
            if r["telegram_user_id"] in seen:
                continue
            if datetime.fromisoformat(r["expires_at"]) < now:
                continue
            valid.append(dict(r))
            seen.add(r["telegram_user_id"])

        return valid

    def log_search(self, telegram_user_id: int, media_type: str, query: str) -> None:
        self.db.execute(
            "INSERT INTO search_logs (telegram_user_id, media_type, query, created_at) VALUES (?, ?, ?, ?)",
            (telegram_user_id, media_type, query, now_iso()),
        )

    def log_activity(self, telegram_user_id: int, action: str, details: str) -> None:
        self.db.execute(
            "INSERT INTO activity_logs (telegram_user_id, action, details, created_at) VALUES (?, ?, ?, ?)",
            (telegram_user_id, action, details, now_iso()),
        )

    def last_searches(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT * FROM search_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    def last_activities(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT * FROM activity_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

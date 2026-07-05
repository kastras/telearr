from __future__ import annotations

from pathlib import Path
import sqlite3

from app.db import Database


class TestDatabase:
    def test_init_creates_schema(self, tmp_db_path: Path):
        db = Database(tmp_db_path)
        tables = db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        names = [r["name"] for r in tables]
        assert "clients" in names
        assert "pair_tokens" in names
        assert "search_logs" in names
        assert "activity_logs" in names

    def test_execute_insert_and_fetchone(self, tmp_db_path: Path):
        db = Database(tmp_db_path)
        db.execute(
            "INSERT INTO clients (telegram_user_id, username, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)",
            (1, "user1", "2024-01-01T00:00:00", "2024-01-01T00:00:00"),
        )
        row = db.fetchone("SELECT * FROM clients WHERE telegram_user_id = ?", (1,))
        assert row is not None
        assert row["username"] == "user1"

    def test_fetchone_returns_none_when_not_found(self, tmp_db_path: Path):
        db = Database(tmp_db_path)
        row = db.fetchone("SELECT * FROM clients WHERE telegram_user_id = ?", (999,))
        assert row is None

    def test_fetchall_returns_all_rows(self, tmp_db_path: Path):
        db = Database(tmp_db_path)
        for i in range(3):
            db.execute(
                "INSERT INTO clients (telegram_user_id, username, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)",
                (i, f"user{i}", "2024-01-01T00:00:00", "2024-01-01T00:00:00"),
            )
        rows = db.fetchall("SELECT * FROM clients ORDER BY telegram_user_id")
        assert len(rows) == 3
        assert rows[0]["telegram_user_id"] == 0
        assert rows[2]["telegram_user_id"] == 2

    def test_fetchall_empty(self, tmp_db_path: Path):
        db = Database(tmp_db_path)
        rows = db.fetchall("SELECT * FROM clients")
        assert rows == []

    def test_row_factory_is_sqlite_row(self, tmp_db_path: Path):
        db = Database(tmp_db_path)
        db.execute(
            "INSERT INTO clients (telegram_user_id, username, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)",
            (1, "test", "2024-01-01T00:00:00", "2024-01-01T00:00:00"),
        )
        row = db.fetchone("SELECT * FROM clients WHERE telegram_user_id = ?", (1,))
        assert isinstance(row, sqlite3.Row)

    def test_multiple_operations(self, tmp_db_path: Path):
        db = Database(tmp_db_path)
        db.execute(
            "INSERT INTO clients (telegram_user_id, username, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)",
            (1, "alice", "2024-01-01", "2024-01-01"),
        )
        db.execute(
            "UPDATE clients SET username = ? WHERE telegram_user_id = ?",
            ("alice_updated", 1),
        )
        row = db.fetchone("SELECT username FROM clients WHERE telegram_user_id = ?", (1,))
        assert row["username"] == "alice_updated"

    def test_init_is_idempotent(self, tmp_db_path: Path):
        Database(tmp_db_path)
        Database(tmp_db_path)
        db = Database(tmp_db_path)
        rows = db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        assert len(rows) == 4

from __future__ import annotations

from pathlib import Path
import pytest

from app.db import Database


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def db(tmp_db_path: Path) -> Database:
    return Database(tmp_db_path)


@pytest.fixture
def mock_telegram_user():
    class FakeUser:
        id = 12345
        username = "testuser"
        first_name = "Test"
        last_name = "User"

    return FakeUser()


@pytest.fixture
def mock_telegram_user_no_username():
    class FakeUser:
        id = 67890
        username = None
        first_name = "NoName"
        last_name = None

    return FakeUser()


@pytest.fixture
def sample_config_yaml() -> str:
    return """
telegram:
  bot_token: "123:abc"

sonarr:
  base_url: "http://sonarr:8989"
  api_token: "sonarr-token"

radarr:
  base_url: "http://radarr:7878"
  api_token: "radarr-token"

runtime:
  admin_password: "admin123"
  session_secret: "secret123"

defaults:
  series_root_folder: "/tv"
  movies_root_folder: "/movies"
  series_quality_profile_id: 4
  movies_quality_profile_id: 3
  series_default_resolution: "1080p"
  series_default_audio: "multi"
  movies_default_resolution: "4k"
  movies_default_audio: "multi"
  series_quality_profiles:
    "1080p|multi": 4
    "720p|multi": 3
  movies_quality_profiles:
    "4k|multi": 6
    "1080p|multi": 5
  series_language_profiles:
    "espanol": 1
    "espanol-ingles": 2
  series_add_tags:
    - "tv"
    - "series"
  movies_add_tags:
    - "peliculas"
"""


@pytest.fixture
def sample_config_yaml_with_int_tags() -> str:
    return """
telegram:
  bot_token: "123:abc"

sonarr:
  base_url: "http://sonarr:8989"
  api_token: "sonarr-token"

radarr:
  base_url: "http://radarr:7878"
  api_token: "radarr-token"

runtime:
  admin_password: "admin"
  session_secret: "change-me"

defaults:
  series_root_folder: "/tv"
  movies_root_folder: "/movies"
  series_quality_profile_id: 1
  movies_quality_profile_id: 1
  series_add_tags:
    - 1
    - 2
  movies_add_tags:
    - 3
"""

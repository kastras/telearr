from __future__ import annotations

from pathlib import Path
import pytest

from app.config import (
    AppConfig,
    AppRuntimeConfig,
    ArrServiceConfig,
    ConfigManager,
    DefaultMediaConfig,
    TelegramConfig,
)


class TestParseHelpers:
    def test_parse_int_list(self):
        assert ConfigManager._parse_int_list("1,2,3") == [1, 2, 3]

    def test_parse_int_list_with_spaces(self):
        assert ConfigManager._parse_int_list(" 1 , 2 , 3 ") == [1, 2, 3]

    def test_parse_int_list_empty(self):
        assert ConfigManager._parse_int_list("") == []

    def test_parse_int_list_whitespace(self):
        assert ConfigManager._parse_int_list("   ") == []

    def test_parse_int_list_skips_invalid(self):
        assert ConfigManager._parse_int_list("1,abc,3") == [1, 3]

    def test_parse_int_list_all_invalid(self):
        assert ConfigManager._parse_int_list("abc,def") == []

    def test_parse_str_list(self):
        assert ConfigManager._parse_str_list("a,b,c") == ["a", "b", "c"]

    def test_parse_str_list_with_spaces(self):
        assert ConfigManager._parse_str_list(" a , b , c ") == ["a", "b", "c"]

    def test_parse_str_list_empty(self):
        assert ConfigManager._parse_str_list("") == []

    def test_parse_str_list_skips_empty(self):
        assert ConfigManager._parse_str_list("a,,b") == ["a", "b"]


class TestConfigManagerInitFromEnv:
    def test_creates_yaml_when_not_exists(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
        monkeypatch.setenv("SONARR_URL", "http://env-sonarr:8989")
        monkeypatch.setenv("SONARR_API_TOKEN", "env-sonarr-token")
        monkeypatch.setenv("RADARR_URL", "http://env-radarr:7878")
        monkeypatch.setenv("RADARR_API_TOKEN", "env-radarr-token")
        monkeypatch.setenv("ADMIN_PASSWORD", "env-pass")
        monkeypatch.setenv("SESSION_SECRET", "env-secret")
        monkeypatch.setenv("SERIES_ROOT_FOLDER", "/env-tv")
        monkeypatch.setenv("MOVIES_ROOT_FOLDER", "/env-movies")
        monkeypatch.setenv("SERIES_QUALITY_PROFILE_ID", "4")
        monkeypatch.setenv("SERIES_ADD_TAGS", "tag1,tag2")
        monkeypatch.setenv("MOVIES_ADD_TAGS", "tag3")

        config_path = tmp_path / "config.yaml"
        cm = ConfigManager(config_path)
        cfg = cm.config

        assert cfg.telegram.bot_token == "env-token"
        assert cfg.sonarr.base_url == "http://env-sonarr:8989"
        assert cfg.sonarr.api_token == "env-sonarr-token"
        assert cfg.radarr.base_url == "http://env-radarr:7878"
        assert cfg.radarr.api_token == "env-radarr-token"
        assert cfg.runtime.admin_password == "env-pass"
        assert cfg.runtime.session_secret == "env-secret"
        assert cfg.defaults.series_root_folder == "/env-tv"
        assert cfg.defaults.movies_root_folder == "/env-movies"
        assert cfg.defaults.series_quality_profile_id == 4
        assert cfg.defaults.series_add_tags == ["tag1", "tag2"]
        assert cfg.defaults.movies_add_tags == ["tag3"]
        assert config_path.exists()

    def test_uses_defaults_when_no_env(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SONARR_URL", raising=False)
        config_path = tmp_path / "config.yaml"
        cm = ConfigManager(config_path)
        cfg = cm.config
        assert cfg.telegram.bot_token == ""
        assert cfg.runtime.admin_password == "admin"
        assert cfg.runtime.session_secret == "change-me"
        assert cfg.defaults.series_quality_profile_id == 1


class TestConfigManagerLoadFromYaml:
    def test_loads_valid_yaml(self, tmp_path: Path, sample_config_yaml: str):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(sample_config_yaml)
        cm = ConfigManager(config_path)
        cfg = cm.config

        assert cfg.telegram.bot_token == "123:abc"
        assert cfg.sonarr.base_url == "http://sonarr:8989"
        assert cfg.sonarr.api_token == "sonarr-token"
        assert cfg.radarr.base_url == "http://radarr:7878"
        assert cfg.radarr.api_token == "radarr-token"
        assert cfg.runtime.admin_password == "admin123"
        assert cfg.runtime.session_secret == "secret123"
        assert cfg.defaults.series_root_folder == "/tv"
        assert cfg.defaults.movies_root_folder == "/movies"
        assert cfg.defaults.series_quality_profile_id == 4
        assert cfg.defaults.movies_quality_profile_id == 3
        assert cfg.defaults.series_default_resolution == "1080p"
        assert cfg.defaults.series_default_audio == "multi"
        assert cfg.defaults.movies_default_resolution == "4k"
        assert cfg.defaults.movies_default_audio == "multi"
        assert cfg.defaults.series_quality_profiles == {"1080p|multi": 4, "720p|multi": 3}
        assert cfg.defaults.movies_quality_profiles == {"4k|multi": 6, "1080p|multi": 5}
        assert cfg.defaults.series_language_profiles == {"espanol": 1, "espanol-ingles": 2}
        assert cfg.defaults.series_add_tags == ["tv", "series"]
        assert cfg.defaults.movies_add_tags == ["peliculas"]

    def test_loads_empty_yaml(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("")
        cm = ConfigManager(config_path)
        cfg = cm.config
        assert isinstance(cfg, AppConfig)

    def test_loads_partial_yaml(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("telegram:\n  bot_token: 'partial-token'\n")
        cm = ConfigManager(config_path)
        cfg = cm.config
        assert cfg.telegram.bot_token == "partial-token"
        assert cfg.sonarr.base_url == ""

    def test_converts_int_tags_to_strings(self, tmp_path: Path, sample_config_yaml_with_int_tags: str):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(sample_config_yaml_with_int_tags)
        cm = ConfigManager(config_path)
        cfg = cm.config
        assert cfg.defaults.series_add_tags == ["1", "2"]
        assert cfg.defaults.movies_add_tags == ["3"]

    def test_handlists_non_list_tags(self, tmp_path: Path):
        yaml = """
defaults:
  series_add_tags: "not-a-list"
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml)
        cm = ConfigManager(config_path)
        assert cm.config.defaults.series_add_tags == []


class TestConfigManagerWriteAndUpdate:
    def test_get_yaml_text(self, tmp_path: Path, sample_config_yaml: str):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(sample_config_yaml)
        cm = ConfigManager(config_path)
        text = cm.get_yaml_text()
        assert "123:abc" in text
        assert "sonarr:8989" in text

    def test_update_from_yaml_text(self, tmp_path: Path, sample_config_yaml: str):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(sample_config_yaml)
        cm = ConfigManager(config_path)
        new_yaml = sample_config_yaml.replace("admin123", "newpass")
        new_yaml = new_yaml.replace("secret123", "newsecret")
        cm.update_from_yaml_text(new_yaml)
        cfg = cm.config
        assert cfg.runtime.admin_password == "newpass"
        assert cfg.runtime.session_secret == "newsecret"

    def test_update_from_yaml_text_invalid(self, tmp_path: Path, sample_config_yaml: str):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(sample_config_yaml)
        cm = ConfigManager(config_path)
        with pytest.raises(Exception):
            cm.update_from_yaml_text("not: valid: yaml: [[]]")

    def test_refresh(self, tmp_path: Path, sample_config_yaml: str):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(sample_config_yaml)
        cm = ConfigManager(config_path)
        original = cm.config.runtime.admin_password
        config_path.write_text(sample_config_yaml.replace("admin123", "refreshed"))
        cm.refresh()
        assert cm.config.runtime.admin_password == "refreshed"

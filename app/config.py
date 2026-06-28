from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import threading
from typing import Any

import yaml


@dataclass
class TelegramConfig:
    bot_token: str = ""


@dataclass
class ArrServiceConfig:
    base_url: str = ""
    api_token: str = ""


@dataclass
class AppRuntimeConfig:
    admin_password: str = "admin"
    session_secret: str = "change-me"


@dataclass
class DefaultMediaConfig:
    series_root_folder: str = ""
    movies_root_folder: str = ""
    series_quality_profile_id: int = 1
    movies_quality_profile_id: int = 1
    series_default_resolution: str = "1080p"
    series_default_audio: str = "multi"
    movies_default_resolution: str = "1080p"
    movies_default_audio: str = "multi"
    series_quality_profiles: dict[str, int] = field(default_factory=dict)
    movies_quality_profiles: dict[str, int] = field(default_factory=dict)
    series_language_profiles: dict[str, int] = field(default_factory=dict)
    series_add_tags: list[str] = field(default_factory=list)
    movies_add_tags: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    telegram: TelegramConfig
    sonarr: ArrServiceConfig
    radarr: ArrServiceConfig
    runtime: AppRuntimeConfig
    defaults: DefaultMediaConfig


class ConfigManager:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._lock = threading.Lock()
        self._config = self._load_or_init()

    @property
    def config(self) -> AppConfig:
        with self._lock:
            return self._config

    @staticmethod
    def _parse_int_list(raw: str) -> list[int]:
        if not raw.strip():
            return []
        values: list[int] = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                values.append(int(token))
            except ValueError:
                continue
        return values

    @staticmethod
    def _parse_str_list(raw: str) -> list[str]:
        if not raw.strip():
            return []
        return [s.strip() for s in raw.split(",") if s.strip()]

    def _load_or_init(self) -> AppConfig:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        if self.config_path.exists():
            return self._read_yaml(self.config_path.read_text(encoding="utf-8"))

        env = __import__("os").environ
        cfg = AppConfig(
            telegram=TelegramConfig(bot_token=env.get("TELEGRAM_BOT_TOKEN", "")),
            sonarr=ArrServiceConfig(
                base_url=env.get("SONARR_URL", ""),
                api_token=env.get("SONARR_API_TOKEN", ""),
            ),
            radarr=ArrServiceConfig(
                base_url=env.get("RADARR_URL", ""),
                api_token=env.get("RADARR_API_TOKEN", ""),
            ),
            runtime=AppRuntimeConfig(
                admin_password=env.get("ADMIN_PASSWORD", "admin"),
                session_secret=env.get("SESSION_SECRET", "change-me"),
            ),
            defaults=DefaultMediaConfig(
                series_root_folder=env.get("SERIES_ROOT_FOLDER", ""),
                movies_root_folder=env.get("MOVIES_ROOT_FOLDER", ""),
                series_quality_profile_id=int(env.get("SERIES_QUALITY_PROFILE_ID", "1")),
                movies_quality_profile_id=int(env.get("MOVIES_QUALITY_PROFILE_ID", "1")),
                series_default_resolution=env.get("SERIES_DEFAULT_RESOLUTION", "1080p"),
                series_default_audio=env.get("SERIES_DEFAULT_AUDIO", "multi"),
                movies_default_resolution=env.get("MOVIES_DEFAULT_RESOLUTION", "1080p"),
                movies_default_audio=env.get("MOVIES_DEFAULT_AUDIO", "multi"),
                series_add_tags=self._parse_str_list(env.get("SERIES_ADD_TAGS", "")),
                movies_add_tags=self._parse_str_list(env.get("MOVIES_ADD_TAGS", "")),
            ),
        )
        self._write_yaml(cfg)
        return cfg

    def _read_yaml(self, raw: str) -> AppConfig:
        data = yaml.safe_load(raw) or {}

        # Sanitize defaults to ensure series_add_tags and movies_add_tags contain strings
        defaults_data = data.get("defaults", {})
        for tag_field in ["series_add_tags", "movies_add_tags"]:
            if tag_field in defaults_data:
                raw_tags = defaults_data[tag_field]
                if isinstance(raw_tags, list):
                    # Convert all values to strings (supports both names and numeric IDs)
                    defaults_data[tag_field] = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
                else:
                    defaults_data[tag_field] = []

        return AppConfig(
            telegram=TelegramConfig(**data.get("telegram", {})),
            sonarr=ArrServiceConfig(**data.get("sonarr", {})),
            radarr=ArrServiceConfig(**data.get("radarr", {})),
            runtime=AppRuntimeConfig(**data.get("runtime", {})),
            defaults=DefaultMediaConfig(**defaults_data),
        )

    def _write_yaml(self, cfg: AppConfig) -> None:
        self.config_path.write_text(
            yaml.safe_dump(asdict(cfg), sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )

    def get_yaml_text(self) -> str:
        return self.config_path.read_text(encoding="utf-8")

    def update_from_yaml_text(self, raw: str) -> AppConfig:
        cfg = self._read_yaml(raw)
        with self._lock:
            self._write_yaml(cfg)
            self._config = cfg
            return self._config

    def refresh(self) -> AppConfig:
        with self._lock:
            self._config = self._read_yaml(self.config_path.read_text(encoding="utf-8"))
            return self._config

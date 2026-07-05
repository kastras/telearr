from __future__ import annotations

from typing import Any

from telegram import Update


def safe_reply_target(update: Update):
    return update.effective_message


def parse_value_and_options(tokens: list[str]) -> tuple[str, dict[str, str]]:
    value_parts: list[str] = []
    options: dict[str, str] = {}
    for token in tokens:
        if "=" in token:
            key, raw_value = token.split("=", 1)
            options[key.strip().lower()] = raw_value.strip().lower()
            continue
        value_parts.append(token)
    return " ".join(value_parts).strip(), options


def profile_key(resolution: str, audio: str) -> str:
    return f"{resolution.lower()}|{audio.lower()}"


def resolution_options(profile_map: dict[str, int], default_resolution: str) -> list[str]:
    values = {k.split("|", 1)[0].strip().lower() for k in profile_map if "|" in k}
    if default_resolution:
        values.add(default_resolution.lower())
    if not values:
        values = {"1080p"}

    order = {"4k": 0, "2160p": 0, "1080p": 1, "720p": 2, "480p": 3}
    return sorted(values, key=lambda x: (order.get(x, 99), x))

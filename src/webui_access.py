# -*- coding: utf-8 -*-
"""WebUI access mode helpers."""

from __future__ import annotations

import os

from src.config import parse_env_bool, setup_env


def is_webui_read_only_mode() -> bool:
    """Return whether WebUI management features should be locked."""
    setup_env()
    return parse_env_bool(os.getenv("WEBUI_READ_ONLY_MODE"), default=False)


def webui_read_only_detail(
    message: str = "WebUI read-only mode is enabled; system settings are not available.",
) -> dict[str, str]:
    """Return the standard API error payload for read-only management mode."""
    return {
        "error": "webui_read_only",
        "message": message,
    }

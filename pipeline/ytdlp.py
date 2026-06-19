"""Helpers for invoking yt-dlp consistently across environments."""

from __future__ import annotations

import shutil
import sys


def command() -> list[str]:
    """Return a runnable yt-dlp command prefix."""
    binary = shutil.which("yt-dlp")
    if binary:
        return [binary]
    return [sys.executable, "-m", "yt_dlp"]

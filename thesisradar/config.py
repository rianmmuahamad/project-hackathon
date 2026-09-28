"""Configuration. `.env` first, real environment second, nothing magic.

Kept deliberately free of third-party imports so it loads in a bare interpreter,
in Hermes' managed venv, and in CI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file without clobbering real env vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_base: str
    home: Path
    engine: str
    model: str | None
    check_budget: int

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)


def settings() -> Settings:
    home = Path(os.environ.get("THESISRADAR_HOME") or (REPO_ROOT / ".thesisradar"))
    if not home.is_absolute():
        home = REPO_ROOT / home
    model = (os.environ.get("THESISRADAR_MODEL") or "").strip()
    try:
        budget = int(os.environ.get("THESISRADAR_CHECK_BUDGET") or 25)
    except ValueError:
        budget = 25
    return Settings(
        api_key=(os.environ.get("SECTORS_API_KEY") or "").strip(),
        api_base=(os.environ.get("SECTORS_API_BASE") or "https://api.sectors.app").rstrip("/"),
        home=home,
        engine=(os.environ.get("THESISRADAR_ENGINE") or "auto").strip().lower(),
        model=model or None,
        check_budget=max(4, budget),
    )
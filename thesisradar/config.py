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
    jev_base: str
    jev_key: str
    jev_model: str
    jev_timeout: int
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_to: str
    smtp_tls: bool
    schedule_at: str
    schedule_days: str

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    @property
    def email_configured(self) -> bool:
        """Whether a digest can be sent at all, checked before any connection."""
        return bool(self.smtp_host and self.smtp_to)

    @property
    def jev_configured(self) -> bool:
        """Whether the decision layer can be reached at all.

        Checked before any request so a missing key never becomes a failed call
        that looks like a gateway outage.
        """
        return bool(self.jev_key)


def settings() -> Settings:
    home = Path(os.environ.get("THESISRADAR_HOME") or (REPO_ROOT / ".thesisradar"))
    if not home.is_absolute():
        home = REPO_ROOT / home
    model = (os.environ.get("THESISRADAR_MODEL") or "").strip()
    try:
        budget = int(os.environ.get("THESISRADAR_CHECK_BUDGET") or 25)
    except ValueError:
        budget = 25
    try:
        jev_timeout = int(os.environ.get("THESISRADAR_JEV_TIMEOUT") or 30)
    except ValueError:
        jev_timeout = 30
    try:
        smtp_port = int(os.environ.get("THESISRADAR_SMTP_PORT") or 587)
    except ValueError:
        smtp_port = 587
    return Settings(
        api_key=(os.environ.get("SECTORS_API_KEY") or "").strip(),
        api_base=(os.environ.get("SECTORS_API_BASE") or "https://api.sectors.app").rstrip("/"),
        home=home,
        engine=(os.environ.get("THESISRADAR_ENGINE") or "auto").strip().lower(),
        model=model or None,
        check_budget=max(4, budget),
        jev_base=(os.environ.get("THESISRADAR_JEV_BASE") or "https://mot.coddx.store/v1").rstrip("/"),
        jev_key=(os.environ.get("THESISRADAR_JEV_KEY") or "").strip(),
        jev_model=(os.environ.get("THESISRADAR_JEV_MODEL") or "jev-1.13-free").strip(),
        jev_timeout=max(5, jev_timeout),
        smtp_host=(os.environ.get("THESISRADAR_SMTP_HOST") or "").strip(),
        smtp_port=max(1, min(65535, smtp_port)),
        smtp_user=(os.environ.get("THESISRADAR_SMTP_USER") or "").strip(),
        smtp_password=os.environ.get("THESISRADAR_SMTP_PASSWORD") or "",
        smtp_from=(os.environ.get("THESISRADAR_SMTP_FROM") or "").strip(),
        smtp_to=(os.environ.get("THESISRADAR_SMTP_TO") or "").strip(),
        smtp_tls=(os.environ.get("THESISRADAR_SMTP_TLS") or "1").strip().lower()
        in ("1", "true", "yes", "on"),
        schedule_at=(os.environ.get("THESISRADAR_SCHEDULE_AT") or "08:00").strip(),
        schedule_days=(os.environ.get("THESISRADAR_SCHEDULE_DAYS") or "mon,tue,wed,thu,fri").strip(),
    )
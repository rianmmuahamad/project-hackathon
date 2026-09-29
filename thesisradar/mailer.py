"""Delivery: turn a batch of notifications into one plain-text email.

Standard library only (`smtplib`, `email.message`). The SMTP object is created by
`builtin_smtp` rather than inside `send`, so a test can hand in a fake with the
same four methods and prove the digest without a socket.

Plain text on purpose: the digest has to survive being read in a terminal, in
Gmail, in a phone notification preview, and in a log file. HTML would render in
none of those better and would hide the verdicts inside markup.
"""

from __future__ import annotations

import socket
import smtplib
import time
from email.message import EmailMessage
from typing import Any

from .config import Settings, settings

# Notifications whose severity is "ok" say a thesis became intact again. Emailing
# those would teach the user to ignore the digest; "info" is kept because a
# first-ever check on a watched thesis is the product's first useful message.
QUIET_SEVERITIES = frozenset({"ok"})


class NotConfigured(RuntimeError):
    """No digest can be sent — a decision, not a failure."""


class MailError(RuntimeError):
    """Delivery was attempted and something went wrong.

    Wraps the `smtplib`/`socket` exception so a caller never has to know which
    module raised and never has to catch a bare `OSError`.
    """


def builtin_smtp(tls: bool = True) -> Any:
    """The real SMTP class for a TLS setting: implicit TLS when `tls` is false."""
    return smtplib.SMTP if tls else smtplib.SMTP_SSL


def recipients(cfg: Settings) -> list[str]:
    return [part.strip() for part in (cfg.smtp_to or "").split(",") if part.strip()]


def survivors(notifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows worth emailing, in the order given."""
    return [n for n in notifications if (n.get("severity") or "info") not in QUIET_SEVERITIES]


def digest_subject(changed: int, symbols: list[str]) -> str:
    word = "change" if changed == 1 else "changes"
    subject = f"Thesis Radar: {changed} status {word}"
    # A thesis can change status twice in one sweep; the subject names it once.
    named = list(dict.fromkeys(s for s in symbols if s))
    if named:
        subject += " — " + ", ".join(named[:4])
        if len(named) > 4:
            subject += f" +{len(named) - 4}"
    return subject


def digest_body(notifications: list[dict[str, Any]], *, when: str,
                checked: int | None = None) -> str:
    """One block per notification, newest first as `list_notifications` returns them."""
    lines = ["Thesis Radar — scheduled check", when, ""]
    total = f" out of {checked} theses checked" if checked is not None else ""
    word = "change" if len(notifications) == 1 else "changes"
    lines.append(f"{len(notifications)} status {word}{total}.")
    lines.append("")
    for note in notifications:
        confidence = note.get("confidence")
        tail = f"  (confidence {confidence:.2f})" if isinstance(confidence, (int, float)) else ""
        lines.append(f"{note.get('symbol') or '—'}  {note.get('title') or ''}{tail}".rstrip())
        body = (note.get("body") or "").strip()
        if body:
            lines.append("  " + body.replace("\n", "\n  "))
        lines.append("")
    lines.append(f"Digest of the checks run at {when}.")
    lines.append("Open the dashboard for the evidence trail behind each verdict.")
    return "\n".join(lines)


def send(subject: str, body: str, *, cfg: Settings | None = None,
         smtp: Any = None) -> dict[str, Any]:
    """Send one digest. Raises `NotConfigured` before touching the network.

    `smtp` is the test seam: either a ready client with `starttls`/`login`/
    `send_message`/`quit`, or a factory called as `factory(host, port, timeout=)`.
    """
    cfg = cfg or settings()
    to = recipients(cfg)
    if not cfg.email_configured or not to:
        raise NotConfigured(
            "email is not configured (set THESISRADAR_SMTP_HOST and THESISRADAR_SMTP_TO)")

    sender = cfg.smtp_from or cfg.smtp_user or f"thesisradar@{socket.gethostname()}"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(to)
    message.set_content(body, subtype="plain")

    started = time.monotonic()
    client = None
    try:
        if smtp is not None and hasattr(smtp, "send_message"):
            client = smtp
        else:
            client = (smtp or builtin_smtp(cfg.smtp_tls))(
                cfg.smtp_host, cfg.smtp_port, timeout=30)
        if cfg.smtp_tls:
            client.starttls()
        # An unauthenticated relay is a real deployment; only log in when the
        # operator supplied both halves of a credential.
        if cfg.smtp_user and cfg.smtp_password:
            client.login(cfg.smtp_user, cfg.smtp_password)
        client.send_message(message)
    except Exception as err:  # noqa: BLE001 — every transport failure is the same to a caller
        raise MailError(f"{type(err).__name__}: {err}") from err
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:  # noqa: BLE001 — a failed QUIT does not unsend the message
                pass

    return {"sent": True, "to": to, "subject": subject,
            "seconds": round(time.monotonic() - started, 3)}
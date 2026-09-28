"""Tolerant JSON extraction, shared by the decomposer and the audit loop.

Models wrap JSON in prose and fences. Pulling the outermost object out is the
only thing we guess at — everything inside stays strictly validated, and a
malformed reply becomes an explicit retry or an `unknown`, never a silent pass.
"""

from __future__ import annotations

import json
from typing import Any


def extract_json(text: str) -> dict[str, Any] | None:
    """Return the outermost JSON object in a reply, or None."""
    if not text:
        return None
    body = text.strip()

    if "```" in body:
        for part in body.split("```"):
            candidate = part.strip()
            if candidate[:4].lower() == "json":
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                body = candidate
                break

    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(body[start:end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def loose_objects(text: str) -> list[Any]:
    """Every balanced top-level {...} in free text, best effort."""
    out: list[Any] = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    out.append(json.loads(text[start:i + 1]))
                except ValueError:
                    pass
                start = -1
    return out
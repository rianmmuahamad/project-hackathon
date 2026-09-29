"""Turn a stored transcript into labelled segments.

`audit._write_transcript` writes a markdown file whose structure is real but
invisible on screen: a preamble, then `## ` headings — Thesis brief, Decision
(Jev), Free read, Tool call N, Verdict, Guardrail (Jev). This module decodes that
structure once, on the server, so the dashboard renders typed segments instead of
11,000 characters of pre-wrapped text.

Two rules keep the raw artifact authoritative:

* the splitter never rewrites text — a segment's `body` is the file's own bytes;
* the dashboard keeps a raw view, so what is on screen can still be checked
  against the `.md` on disk.

Standard library only.
"""

from __future__ import annotations

import json
import re
from typing import Any

SEGMENT_KINDS = ("header", "brief", "decision", "ledger", "tool", "verdict", "guardrail",
                 "round", "note", "other")

# Heading as written in the file -> segment kind. Matched by prefix,
# case-insensitive, against the text after "## ".
HEADING_KINDS: tuple[tuple[str, str], ...] = (
    ("thesis brief", "brief"),
    ("decision (jev)", "decision"),
    ("free read:", "ledger"),
    ("tool call", "tool"),
    ("verdict", "verdict"),
    ("guardrail (jev)", "guardrail"),
    ("round", "round"),
)

LABELS: dict[str, str] = {
    "header": "Pemeriksaan",
    "brief": "Briefing tesis",
    "decision": "Keputusan Jev",
    "ledger": "Memori gratis",
    "tool": "Panggilan tool",
    "verdict": "Putusan agen",
    "guardrail": "Penjaga prosa",
    "round": "Giliran agen",
    "note": "Catatan",
    "other": "Lainnya",
}

HEADING = "## "
TOOL_NAME_RE = re.compile(r":\s*`([^`]+)`")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
NOTE_RE = re.compile(r"^_(.+)_$")
SUMMARY_LIMIT = 160


def _kind_of(title: str) -> str:
    lowered = title.strip().lower()
    for prefix, kind in HEADING_KINDS:
        if lowered.startswith(prefix):
            return kind
    return "other"


def _tool_of(title: str) -> str | None:
    match = TOOL_NAME_RE.search(title)
    return match.group(1).strip() if match else None


def _fenced_summary(body: str) -> str | None:
    """Describe the first fenced JSON block structurally.

    Several sections are nothing but a fenced payload, so their first line is
    "```json" and the second is "{". Naming the shape — how many fields, which —
    is more use in a collapsed row than two characters of punctuation.
    """
    match = re.search(r"```[a-zA-Z]*\n(.*?)\n```", body, re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
    except ValueError:
        return None
    if isinstance(parsed, dict):
        keys = list(parsed)[:6]
        more = "" if len(parsed) <= 6 else ", …"
        return f"{len(parsed)} field: {', '.join(keys)}{more}"
    if isinstance(parsed, list):
        return f"{len(parsed)} entri"
    return None


def _summarise(body: str, tool: str | None) -> str:
    """One line for the collapsed row: first real text, links flattened."""
    first = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if first.startswith("```"):
        structural = _fenced_summary(body)
        if structural:
            return f"{tool}  {structural}" if tool else structural

    for raw in body.splitlines():
        stripped = raw.strip()
        # A fenced block's opening line and its info string are not prose, and
        # neither is a bare fence: "json" is not a summary of anything.
        if stripped.startswith("```") or stripped in ("", "---", "…"):
            continue
        line = stripped.lstrip("#*> `")
        line = MARKDOWN_LINK_RE.sub(r"\1", line).strip()
        # Backticks and emphasis are markdown noise in a one-line summary; the
        # verbatim text is still in the body this row expands to.
        line = line.replace("`", "").replace("**", "")
        if not line or line in ("json", "text", "bash"):
            continue
        # A bare `{` or `}` opening a JSON block summarises nothing.
        if not any(ch.isalnum() for ch in line):
            continue
        if len(line) > SUMMARY_LIMIT:
            line = line[: SUMMARY_LIMIT - 1].rstrip() + "…"
        return f"{tool}  {line}" if tool else line
    return ""


def _segment(kind: str, title: str, body: str = "") -> dict[str, Any]:
    tool = _tool_of(title) if kind == "tool" else None
    return {
        "ordinal": 0,  # assigned by segment_transcript
        "kind": kind,
        "label": LABELS.get(kind, LABELS["other"]),
        "title": title,
        "body": body,
        "tool": tool,
        "summary": _summarise(body, tool),
        "evidence_ordinals": [],
    }


def _split_notes(body: str) -> list[tuple[str, str]]:
    """Pull standalone `_italic_` lines out of a body as their own notes.

    `audit.py` writes these for the paths that are not a section: engine
    unavailable, credit budget exhausted, a skipped repeat call. They are
    findings, so they get their own row rather than sitting inside a section.
    """
    parts: list[tuple[str, str]] = []
    pending: list[str] = []
    for raw in body.splitlines():
        match = NOTE_RE.match(raw.strip())
        if match and len(raw.strip()) > 2:
            buffered = "\n".join(pending).strip("\n")
            if buffered.strip():
                parts.append(("body", buffered))
            pending = []
            parts.append(("note", match.group(1).strip()))
            continue
        pending.append(raw)
    buffered = "\n".join(pending).strip("\n")
    if buffered.strip():
        parts.append(("body", buffered))
    return parts


def segment_transcript(markdown: str | None) -> list[dict[str, Any]]:
    """Split a transcript into typed segments, in file order.

    A document with no `## ` heading still yields one segment, so the UI always
    has something to render and never has to special-case an empty list.
    """
    if not markdown or not markdown.strip():
        return []

    segments: list[dict[str, Any]] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).rstrip()
        if heading is None:
            if body.strip():
                segments.append(_segment("header", "Pemeriksaan", body))
            return
        kind = _kind_of(heading)
        parts = _split_notes(body) or [("body", "")]
        for index, (part_kind, text) in enumerate(parts):
            if part_kind == "note":
                segments.append(_segment("note", text, text))
            elif index == 0:
                segments.append(_segment(kind, heading, text))
            else:
                # A note sat in the middle of the section; whatever follows keeps
                # the section's identity. Never rewrite the heading text.
                segments.append(_segment(kind, heading, text))

    for line in markdown.splitlines():
        if line.startswith(HEADING):
            flush()
            heading = line[len(HEADING):].strip()
            buffer = []
            continue
        buffer.append(line)
    flush()

    for index, segment in enumerate(segments):
        segment["ordinal"] = index
    return segments


def link_evidence(segments: list[dict[str, Any]],
                  evidence: list[dict[str, Any]]) -> None:
    """Attach each evidence row to the segment that produced it, in place.

    The writers use a fixed endpoint vocabulary (`/v2/...`, `tool:<name>`,
    `tool:jev`), verified against a real database, so matching is exact rather
    than heuristic. A row that matches nothing lands on the last segment instead
    of being dropped: a link is a navigation aid, and losing one must not lose
    the row itself.
    """
    if not segments:
        return

    def first(kind: str, predicate=None):  # noqa: ANN001
        for segment in segments:
            if segment["kind"] == kind and (predicate is None or predicate(segment)):
                return segment
        return None

    guardrail_seg = first("guardrail")
    decision_seg = first("decision")
    ledger_seg = first("ledger")
    header_seg = first("header")
    brief_seg = first("brief")
    tool_segs = [s for s in segments if s["kind"] == "tool"]
    last = segments[-1]

    for row in evidence:
        endpoint = str(row.get("endpoint") or "")
        metric = str(row.get("metric") or "")
        target = None

        if endpoint == "tool:jev" and metric.startswith("guardrail."):
            target = guardrail_seg
        elif endpoint == "tool:jev":
            target = decision_seg
        elif endpoint.startswith("tool:"):
            name = endpoint[len("tool:"):]
            if name == "evidence_ledger":
                target = ledger_seg
            else:
                target = next((s for s in tool_segs if s["tool"] == name), None)
            target = target or header_seg
        elif endpoint.startswith("/v2/"):
            target = next((s for s in tool_segs if endpoint in (s["body"] or "")), None)
            target = target or brief_seg

        target = target or last
        ordinal = row.get("ordinal")
        if isinstance(ordinal, int) and ordinal not in target["evidence_ordinals"]:
            target["evidence_ordinals"].append(ordinal)

    for segment in segments:
        segment["evidence_ordinals"].sort()


def decorate(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    """Add `transcript_segments` to a stored check, so callers share one shape."""
    if detail is None:
        return None
    segments = segment_transcript(detail.get("transcript"))
    link_evidence(segments, detail.get("evidence") or [])
    out = dict(detail)
    out["transcript_segments"] = segments
    return out
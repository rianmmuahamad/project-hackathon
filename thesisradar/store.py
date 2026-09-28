"""SQLite store — the agent's memory.

The whole product rests on this file. A thesis is not a chat message: it is a
row with claims, a confidence, a watermark and a history of checks. Every number
the agent used is stored beside the endpoint it came from, so any verdict can be
replayed by hand months later.

Standard library only.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .config import settings

# Thesis lifecycle. `unknown` is a first-class answer: the data may simply not
# say, and pretending otherwise is the failure this product exists to prevent.
STATUSES = ("intact", "weakened", "broken", "needs_review", "unknown")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS theses (
    id              TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    company_name    TEXT,
    statement       TEXT NOT NULL,
    translation     TEXT,
    horizon         TEXT,
    sector          TEXT,
    sub_sector      TEXT,
    source          TEXT DEFAULT 'manual',
    watch           INTEGER DEFAULT 1,
    status          TEXT DEFAULT 'unknown',
    confidence      REAL,
    created_at      TEXT NOT NULL,
    last_checked_at TEXT,
    watermark       TEXT,
    run_id          TEXT
);
CREATE INDEX IF NOT EXISTS idx_theses_symbol ON theses(symbol);

CREATE TABLE IF NOT EXISTS claims (
    id              TEXT PRIMARY KEY,
    thesis_id       TEXT NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
    ordinal         INTEGER NOT NULL,
    text            TEXT NOT NULL,
    metric          TEXT,
    direction       TEXT,
    cadence         TEXT DEFAULT 'quarterly',
    threshold       REAL,
    threshold_target TEXT,
    comparator      TEXT,
    note            TEXT,
    baseline_value  REAL,
    baseline_date   TEXT
);
CREATE INDEX IF NOT EXISTS idx_claims_thesis ON claims(thesis_id);

CREATE TABLE IF NOT EXISTS checks (
    id              TEXT PRIMARY KEY,
    thesis_id       TEXT NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
    run_id          TEXT,
    checked_at      TEXT NOT NULL,
    since           TEXT,
    verdict         TEXT,
    confidence      REAL,
    summary         TEXT,
    engine          TEXT,
    model           TEXT,
    credits         INTEGER DEFAULT 0,
    tool_calls      INTEGER DEFAULT 0,
    transcript_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_checks_thesis ON checks(thesis_id);

CREATE TABLE IF NOT EXISTS claim_results (
    id              TEXT PRIMARY KEY,
    check_id        TEXT NOT NULL REFERENCES checks(id) ON DELETE CASCADE,
    claim_id        TEXT,
    ordinal         INTEGER,
    text            TEXT,
    state           TEXT,
    observed_value  REAL,
    observed_date   TEXT,
    delta           TEXT,
    rationale       TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    id              TEXT PRIMARY KEY,
    check_id        TEXT NOT NULL REFERENCES checks(id) ON DELETE CASCADE,
    ordinal         INTEGER NOT NULL,
    symbol          TEXT,
    metric          TEXT,
    value           TEXT,
    as_of           TEXT,
    endpoint        TEXT,
    params          TEXT,
    note            TEXT
);

CREATE TABLE IF NOT EXISTS changes (
    id              TEXT PRIMARY KEY,
    thesis_id       TEXT NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
    check_id        TEXT,
    ordinal         INTEGER NOT NULL,
    kind            TEXT,
    text            TEXT NOT NULL,
    magnitude       TEXT,
    evidence_ord    INTEGER
);

CREATE TABLE IF NOT EXISTS notifications (
    id              TEXT PRIMARY KEY,
    thesis_id       TEXT NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
    check_id        TEXT,
    created_at      TEXT NOT NULL,
    severity        TEXT DEFAULT 'info',
    title           TEXT,
    body            TEXT,
    read            INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    symbol          TEXT,
    thesis_id       TEXT,
    status          TEXT DEFAULT 'running',
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    credits         INTEGER DEFAULT 0,
    engine          TEXT,
    error           TEXT,
    log_path        TEXT,
    payload         TEXT
);
"""


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@dataclass
class Store:
    path: Path | None = None
    _conn: sqlite3.Connection | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.path is None:
            self.path = settings().home / "radar.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # -- low level ---------------------------------------------------------
    def q(self, sql: str, args: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, tuple(args)).fetchall()

    def x(self, sql: str, args: Iterable[Any] = ()) -> sqlite3.Cursor:
        cur = self._conn.execute(sql, tuple(args))
        self._conn.commit()
        return cur

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- theses ------------------------------------------------------------
    def create_thesis(self, payload: dict[str, Any]) -> str:
        tid = payload.get("id") or new_id("th")
        self.x(
            """INSERT INTO theses (id, symbol, company_name, statement, translation, horizon,
                   sector, sub_sector, source, watch, status, confidence, created_at, watermark)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                tid,
                payload["symbol"].upper(),
                payload.get("company_name"),
                payload["statement"],
                payload.get("translation"),
                payload.get("horizon"),
                payload.get("sector"),
                payload.get("sub_sector"),
                payload.get("source") or "manual",
                1 if payload.get("watch", True) else 0,
                payload.get("status") or "unknown",
                payload.get("confidence"),
                now(),
                payload.get("watermark"),
            ),
        )
        for i, claim in enumerate(payload.get("claims") or []):
            self.add_claim(tid, claim, ordinal=i)
        return tid

    def add_claim(self, thesis_id: str, claim: dict[str, Any], ordinal: int | None = None) -> str:
        cid = claim.get("id") or new_id("cl")
        if ordinal is None:
            row = self.q("SELECT COUNT(*) AS n FROM claims WHERE thesis_id=?", (thesis_id,))
            ordinal = int(row[0]["n"]) if row else 0
        self.x(
            """INSERT INTO claims (id, thesis_id, ordinal, text, metric, direction, cadence,
                   threshold, threshold_target, comparator, note, baseline_value, baseline_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cid, thesis_id, ordinal,
                claim.get("text") or claim.get("statement") or "",
                claim.get("metric"),
                claim.get("direction"),
                claim.get("cadence") or "quarterly",
                claim.get("threshold"),
                claim.get("threshold_target") or "level",
                claim.get("comparator"),
                claim.get("note"),
                claim.get("baseline_value"),
                claim.get("baseline_date"),
            ),
        )
        return cid

    def replace_claims(self, thesis_id: str, claims: list[dict[str, Any]]) -> None:
        self.x("DELETE FROM claims WHERE thesis_id=?", (thesis_id,))
        for i, claim in enumerate(claims):
            self.add_claim(thesis_id, claim, ordinal=i)

    def get_thesis(self, thesis_id: str) -> dict[str, Any] | None:
        rows = self.q("SELECT * FROM theses WHERE id=?", (thesis_id,))
        return self._thesis_bundle(rows[0]) if rows else None

    def find_thesis(self, needle: str) -> dict[str, Any] | None:
        """Resolve by id, then by symbol (newest first)."""
        rows = self.q("SELECT * FROM theses WHERE id=?", (needle,))
        if rows:
            return self._thesis_bundle(rows[0])
        rows = self.q(
            "SELECT * FROM theses WHERE symbol=? ORDER BY created_at DESC LIMIT 1",
            (needle.strip().upper().removesuffix(".JK"),),
        )
        return self._thesis_bundle(rows[0]) if rows else None

    def list_theses(self, watch_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM theses"
        if watch_only:
            sql += " WHERE watch=1"
        sql += " ORDER BY CASE status WHEN 'broken' THEN 0 WHEN 'needs_review' THEN 1 " \
               "WHEN 'weakened' THEN 2 WHEN 'intact' THEN 3 ELSE 4 END, symbol"
        return [self._thesis_bundle(r) for r in self.q(sql)]

    def _thesis_bundle(self, row: sqlite3.Row) -> dict[str, Any]:
        thesis = dict(row)
        thesis["claims"] = [dict(c) for c in
                            self.q("SELECT * FROM claims WHERE thesis_id=? ORDER BY ordinal",
                                   (thesis["id"],))]
        checks = self.q(
            "SELECT id, checked_at, verdict, confidence, summary, engine, model, credits, "
            "tool_calls FROM checks WHERE thesis_id=? ORDER BY checked_at DESC LIMIT 1",
            (thesis["id"],),
        )
        thesis["last_check"] = dict(checks[0]) if checks else None
        change_rows = self.q(
            "SELECT * FROM changes WHERE thesis_id=? ORDER BY rowid DESC LIMIT 12",
            (thesis["id"],),
        )
        thesis["recent_changes"] = [dict(c) for c in change_rows]
        return thesis

    def set_watch(self, thesis_id: str, watch: bool) -> None:
        self.x("UPDATE theses SET watch=? WHERE id=?", (1 if watch else 0, thesis_id))

    def set_status(self, thesis_id: str, status: str, confidence: float | None,
                   watermark: str | None, run_id: str | None) -> None:
        self.x(
            "UPDATE theses SET status=?, confidence=?, watermark=COALESCE(?, watermark), "
            "last_checked_at=?, run_id=COALESCE(?, run_id) WHERE id=?",
            (status, confidence, watermark, now(), run_id, thesis_id),
        )

    # -- checks ------------------------------------------------------------
    def create_check(self, thesis_id: str, *, run_id: str | None = None,
                     since: str | None = None, engine: str | None = None,
                     model: str | None = None) -> str:
        cid = new_id("ck")
        self.x(
            """INSERT INTO checks (id, thesis_id, run_id, checked_at, since, engine, model)
               VALUES (?,?,?,?,?,?,?)""",
            (cid, thesis_id, run_id, now(), since, engine, model),
        )
        return cid

    def finish_check(self, check_id: str, *, verdict: str, confidence: float | None,
                     summary: str | None, credits: int, tool_calls: int,
                     transcript_path: str | None = None) -> None:
        self.x(
            "UPDATE checks SET verdict=?, confidence=?, summary=?, credits=?, tool_calls=?, "
            "transcript_path=? WHERE id=?",
            (verdict, confidence, summary, credits, tool_calls, transcript_path, check_id),
        )

    def add_claim_result(self, check_id: str, result: dict[str, Any], ordinal: int) -> str:
        rid = new_id("cr")
        self.x(
            """INSERT INTO claim_results (id, check_id, claim_id, ordinal, text, state,
                   observed_value, observed_date, delta, rationale)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                rid, check_id, result.get("claim_id"), ordinal,
                result.get("text"), result.get("state"),
                result.get("observed_value"), result.get("observed_date"),
                result.get("delta"), result.get("rationale"),
            ),
        )
        return rid

    def add_evidence(self, check_id: str, item: dict[str, Any], ordinal: int) -> str:
        eid = new_id("ev")
        self.x(
            """INSERT INTO evidence (id, check_id, ordinal, symbol, metric, value, as_of,
                   endpoint, params, note)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                eid, check_id, ordinal, item.get("symbol"), item.get("metric"),
                None if item.get("value") is None else str(item.get("value")),
                item.get("as_of"), item.get("endpoint"),
                json.dumps(item.get("params") or {}, ensure_ascii=False, default=str),
                item.get("note"),
            ),
        )
        return eid

    def add_change(self, thesis_id: str, change: dict[str, Any], ordinal: int,
                   check_id: str | None = None) -> str:
        chid = new_id("ch")
        self.x(
            """INSERT INTO changes (id, thesis_id, check_id, ordinal, kind, text, magnitude,
                   evidence_ord)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                chid, thesis_id, check_id, ordinal, change.get("kind"),
                change.get("text") or "", change.get("magnitude"),
                change.get("evidence_ord"),
            ),
        )
        return chid

    def check_detail(self, check_id: str) -> dict[str, Any] | None:
        rows = self.q("SELECT * FROM checks WHERE id=?", (check_id,))
        if not rows:
            return None
        out = dict(rows[0])
        # A check row exists from the moment it starts. `finished` distinguishes
        # "no verdict yet" from "verdict is unknown", which the UI must not blur.
        out["finished"] = out.get("verdict") is not None
        out["claim_results"] = [dict(r) for r in self.q(
            "SELECT * FROM claim_results WHERE check_id=? ORDER BY ordinal", (check_id,))]
        out["evidence"] = [dict(r) for r in self.q(
            "SELECT * FROM evidence WHERE check_id=? ORDER BY ordinal", (check_id,))]
        out["changes"] = [dict(r) for r in self.q(
            "SELECT * FROM changes WHERE check_id=? ORDER BY ordinal", (check_id,))]
        transcript = out.get("transcript_path")
        if transcript and Path(transcript).is_file():
            out["transcript"] = Path(transcript).read_text(encoding="utf-8")
        return out

    def checks_for(self, thesis_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return [dict(r) for r in self.q(
            "SELECT * FROM checks WHERE thesis_id=? ORDER BY checked_at DESC LIMIT ?",
            (thesis_id, limit))]

    # -- notifications -----------------------------------------------------
    def notify(self, thesis_id: str, *, title: str, body: str,
               severity: str = "info", check_id: str | None = None) -> str:
        nid = new_id("nt")
        self.x(
            """INSERT INTO notifications (id, thesis_id, check_id, created_at, severity,
                   title, body) VALUES (?,?,?,?,?,?,?)""",
            (nid, thesis_id, check_id, now(), severity, title, body),
        )
        return nid

    def list_notifications(self, limit: int = 50, unread_only: bool = False) -> list[dict[str, Any]]:
        sql = ("SELECT n.*, t.symbol, t.statement FROM notifications n "
               "JOIN theses t ON t.id = n.thesis_id")
        if unread_only:
            sql += " WHERE n.read=0"
        sql += " ORDER BY n.created_at DESC LIMIT ?"
        return [dict(r) for r in self.q(sql, (limit,))]

    def mark_read(self, notification_id: str | None = None) -> None:
        if notification_id:
            self.x("UPDATE notifications SET read=1 WHERE id=?", (notification_id,))
        else:
            self.x("UPDATE notifications SET read=1")

    # -- runs --------------------------------------------------------------
    def start_run(self, kind: str, *, symbol: str | None = None,
                  thesis_id: str | None = None, engine: str | None = None,
                  payload: dict[str, Any] | None = None,
                  log_path: str | None = None) -> str:
        rid = new_id("run")
        self.x(
            """INSERT INTO runs (id, kind, symbol, thesis_id, status, started_at, engine,
                   log_path, payload) VALUES (?,?,?,?,?,?,?,?,?)""",
            (rid, kind, symbol, thesis_id, "running", now(), engine, log_path,
             json.dumps(payload or {}, default=str)),
        )
        return rid

    def finish_run(self, run_id: str, *, status: str = "ok", credits: int = 0,
                   error: str | None = None) -> None:
        self.x("UPDATE runs SET status=?, finished_at=?, credits=?, error=? WHERE id=?",
               (status, now(), credits, error, run_id))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self.q("SELECT * FROM runs WHERE id=?", (run_id,))
        return dict(rows[0]) if rows else None

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return [dict(r) for r in self.q(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))]

    def active_run(self) -> dict[str, Any] | None:
        rows = self.q("SELECT * FROM runs WHERE status='running' ORDER BY started_at DESC LIMIT 1")
        return dict(rows[0]) if rows else None

    # -- aggregate ---------------------------------------------------------
    def credits(self) -> dict[str, Any]:
        from .sectors import Ledger
        return Ledger().summary()

    def stats(self) -> dict[str, Any]:
        counts = {s: 0 for s in STATUSES}
        for row in self.q("SELECT status, COUNT(*) AS n FROM theses GROUP BY status"):
            counts[row["status"] or "unknown"] = int(row["n"])
        totals = self.q("SELECT COUNT(*) AS checks, COALESCE(SUM(credits),0) AS credits FROM checks")
        return {
            "theses": sum(counts.values()),
            "by_status": counts,
            "checks": int(totals[0]["checks"]) if totals else 0,
            "check_credits": int(totals[0]["credits"]) if totals else 0,
            "watched": int(self.q("SELECT COUNT(*) AS n FROM theses WHERE watch=1")[0]["n"]),
            "unread": int(self.q("SELECT COUNT(*) AS n FROM notifications WHERE read=0")[0]["n"]),
        }
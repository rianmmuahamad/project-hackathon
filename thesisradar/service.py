"""Service layer — the operations the CLI and the HTTP API both call.

Keeping this separate from both front ends means the terminal, the dashboard and
the tests exercise exactly one implementation of "check this thesis", and a
background job behaves the same however it was started.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date, timedelta
from typing import Any

from . import audit, engines, thesis as thesis_mod, tools
from .config import settings
from .engines import EngineUnavailable
from .sectors import Budget, Sectors
from .store import Store


class JobBusy(RuntimeError):
    """A scan or check is already running.

    Only one job runs at a time, on purpose: a check spends API credits and model
    tokens, so two stray dashboard clicks must not race the same budget ceiling.
    """


class Service:
    def __init__(self, store: Store | None = None) -> None:
        self.cfg = settings()
        self.store = store or Store()
        self._lock = threading.Lock()
        self._current: dict[str, Any] | None = None

    # -- jobs --------------------------------------------------------------
    def current_job(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._current) if self._current else None

    def _begin(self, kind: str, **kw) -> dict[str, Any]:
        with self._lock:
            if self._current and self._current.get("state") == "running":
                raise JobBusy(
                    f"a {self._current['kind']} job is already running "
                    f"(since {self._current['started_at']}); wait for it to finish"
                )
            self._current = {"kind": kind, "state": "running",
                             "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                             "events": [], "result": None, "error": None, **kw}
            return self._current

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        with self._lock:
            if self._current is not None:
                self._current["events"].append(
                    {"at": time.strftime("%H:%M:%S"), "kind": kind, **payload})
                self._current["events"] = self._current["events"][-200:]

    def _end(self, *, result: Any = None, error: str | None = None) -> None:
        with self._lock:
            if self._current is not None:
                self._current["state"] = "error" if error else "done"
                self._current["result"] = result
                self._current["error"] = error
                self._current["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    def _sectors(self, budget: int) -> Sectors:
        return Sectors(budget=Budget(limit=budget))

    def _engine(self, override: str | None = None) -> tuple[Any, str]:
        choice = override or self.cfg.engine
        return engines.make(choice, model=self.cfg.model)

    # -- theses ------------------------------------------------------------
    def create_thesis(self, *, text: str, symbol: str | None = None, statement: str | None = None,
                      company_name: str | None = None, horizon: str | None = None,
                      engine_override: str | None = None, capture_baselines: bool = True,
                      symbols_hint: str | None = None) -> dict[str, Any]:
        """Turn a paragraph into a stored, checkable thesis."""
        symbol = (symbol or symbols_hint or "").strip().upper().removesuffix(".JK")
        if not symbol:
            raise ValueError("a stock symbol is required")

        budget = self._sectors(20)
        statement = (statement or text or "").strip()
        if not statement:
            raise ValueError("a thesis statement is required")

        engine = None
        engine_note = None
        try:
            engine, engine_note = self._engine(engine_override)
        except EngineUnavailable as err:
            engine_note = str(err)

        split = thesis_mod.decompose(statement, engine)

        if not company_name:
            try:
                meta = budget.company_meta(symbol)
                company_name = meta.get("company_name")
            except Exception:  # noqa: BLE001 — a missing name must not block creation
                company_name = None

        for claim in split["claims"]:
            claim["symbol"] = symbol
            if capture_baselines and claim.get("cadence") == "quarterly":
                try:
                    thesis_mod.capture_baseline(claim, budget)
                except Exception:  # noqa: BLE001
                    pass

        thesis_id = self.store.create_thesis({
            "symbol": symbol,
            "company_name": company_name,
            "statement": statement,
            "translation": json.dumps(split, ensure_ascii=False),
            "horizon": horizon,
            "claims": split["claims"],
            "source": "agent" if split.get("mode") == "model" else "heuristic",
            "status": "unknown",
        })
        return {
            "thesis": self.store.get_thesis(thesis_id),
            "decomposition": split,
            "engine_note": engine_note,
            "credits": budget.budget.spent,
        }

    def update_claims(self, thesis_id: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
        clean = []
        for claim in claims:
            field = claim.get("metric")
            from . import metrics as metric_mod
            resolved = metric_mod.normalise(field)
            if not resolved:
                continue
            clean.append({
                "text": (claim.get("text") or field or "").strip(),
                "metric": resolved,
                "direction": claim.get("direction") or "up",
                "cadence": claim.get("cadence") or "quarterly",
                "threshold": claim.get("threshold"),
                "threshold_target": claim.get("threshold_target") or "level",
                "comparator": claim.get("comparator"),
                "baseline_value": claim.get("baseline_value"),
                "baseline_date": claim.get("baseline_date"),
            })
        if not clean:
            raise ValueError("no claim had a metric that could be resolved")
        self.store.replace_claims(thesis_id, clean)
        return self.store.get_thesis(thesis_id) or {}

    # -- checking ----------------------------------------------------------
    def _run_check(self, thesis_id: str, engine_override: str | None,
                   budget: int | None) -> dict[str, Any]:
        """The check itself, with no job bookkeeping — callable inside a sweep."""
        thesis = self.store.get_thesis(thesis_id)
        if thesis is None:
            raise ValueError(f"no thesis {thesis_id}")
        engine, note = self._engine(engine_override)
        if note:
            self._emit("engine", {"detail": note})
        limit = budget or self.cfg.check_budget
        return audit.run(thesis_id, engine=engine, store=self.store,
                         sectors=self._sectors(limit), on_event=self._emit)

    def check_thesis(self, thesis_id: str, *, engine_override: str | None = None,
                     budget: int | None = None) -> dict[str, Any]:
        thesis = self.store.get_thesis(thesis_id)
        if thesis is None:
            raise ValueError(f"no thesis {thesis_id}")
        self._begin("check", thesis_id=thesis_id, symbol=thesis["symbol"])
        try:
            result = self._run_check(thesis_id, engine_override, budget)
            self._end(result=result)
            return result
        except Exception as err:  # noqa: BLE001 — surfaced to the UI verbatim
            self._end(error=f"{type(err).__name__}: {err}")
            raise

    def check_all(self, *, watch_only: bool = True, limit: int | None = None,
                  engine_override: str | None = None) -> dict[str, Any]:
        """Check every watched thesis — the routine the product is built around."""
        theses = self.store.list_theses(watch_only=watch_only)
        if limit:
            theses = theses[:limit]
        if not theses:
            return {"checked": 0, "results": [], "note": "no theses to check"}
        self._begin("check_all", count=len(theses), symbol=None)
        results: list[dict[str, Any]] = []
        try:
            changed = 0
            for thesis in theses:
                self._emit("thesis", {"symbol": thesis["symbol"], "id": thesis["id"]})
                try:
                    out = self._run_check(thesis["id"], engine_override, None)
                except Exception as err:  # noqa: BLE001 — one failure must not stop the sweep
                    results.append({"thesis_id": thesis["id"], "symbol": thesis["symbol"],
                                    "error": f"{type(err).__name__}: {err}"})
                    continue
                if out.get("previous_status") != out.get("status"):
                    changed += 1
                results.append({"thesis_id": thesis["id"], "symbol": thesis["symbol"],
                                "status": out["status"],
                                "previous_status": out.get("previous_status"),
                                "confidence": out.get("confidence"),
                                "summary": out.get("summary"),
                                "credits": out.get("credits")})
            summary = {"checked": len(results), "changed": changed, "results": results}
            self._end(result=summary)
            return summary
        except Exception as err:  # noqa: BLE001
            self._end(error=f"{type(err).__name__}: {err}")
            raise

    # -- reads -------------------------------------------------------------
    def queue(self) -> list[dict[str, Any]]:
        """The worklist: worst first, with what changed last time it was checked."""
        out = []
        for thesis in self.store.list_theses():
            out.append({
                "id": thesis["id"],
                "symbol": thesis["symbol"],
                "company_name": thesis.get("company_name"),
                "statement": thesis["statement"],
                "status": thesis["status"],
                "confidence": thesis["confidence"],
                "watch": bool(thesis.get("watch")),
                "claims": len(thesis.get("claims") or []),
                "last_checked_at": thesis.get("last_checked_at"),
                "watermark": thesis.get("watermark"),
                "last_check": thesis.get("last_check"),
                "changes": thesis.get("recent_changes") or [],
            })
        return out

    def thesis_detail(self, thesis_id: str) -> dict[str, Any] | None:
        thesis = self.store.get_thesis(thesis_id)
        if thesis is None:
            needle = self.store.find_thesis(thesis_id)
            thesis = needle
        if thesis is None:
            return None
        checks = self.store.checks_for(thesis["id"], limit=12)
        detail = dict(thesis)
        detail["checks"] = checks
        detail["notifications"] = self.store.list_notifications(limit=20)
        if checks:
            detail["latest"] = self.store.check_detail(checks[0]["id"])
        return detail

    def check_detail(self, check_id: str) -> dict[str, Any] | None:
        return self.store.check_detail(check_id)

    def stats(self) -> dict[str, Any]:
        return {"store": self.store.stats(), "credits": self.store.credits(),
                "engine": engines.describe(), "job": self.current_job()}

    # -- thesis drafts -----------------------------------------------------
    def suggest_theses(self, *, sub_sector: str = "banks", count: int = 3,
                       horizon: str = "2 kuartal") -> dict[str, Any]:
        """Draft theses from what the numbers actually say.

        This is the widest-scope convenience the product offers: read the
        subsector, find names whose reported metrics make a specific claim true,
        and write the thesis down. It is clearly marked as generated, because a
        drafted thesis is a starting point a human confirms, not advice.
        """
        budget = self._sectors(30)
        rows = budget.screener(where=f"sub_sector = '{sub_sector}'",
                               order_by="-market_cap", limit=12)
        drafts: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for row in rows:
            symbol = (row.get("symbol") or "").removesuffix(".JK")
            if not symbol:
                continue
            try:
                quarterly = budget.quarterly(symbol, n_quarters=6)
            except Exception:  # noqa: BLE001
                continue
            from . import metrics as metric_mod
            loan = metric_mod.series_of(quarterly, "gross_loan")
            nii = metric_mod.series_of(quarterly, "net_interest_income")
            if len(loan) < 5:
                continue

            # A draft must obey the same guard the measurement obeys. Writing
            # "kredit menyusut 1.5% YoY" from a series that breaks is exactly the
            # error this product exists to prevent — and a drafter that skipped
            # the guard would launder it into the user's own words.
            for series, name in ((loan, "gross_loan"), (nii, "net_interest_income")):
                found = metric_mod.break_index(series, name)
                if found:
                    index, jump = found
                    skipped.append({
                        "symbol": symbol,
                        "reason": (f"{name} moves {jump * 100:+.1f}% in one quarter "
                                   f"({series[index - 1]['date']} → {series[index]['date']}), so the "
                                   f"reported series is inconsistent and no thesis is drafted from it"),
                    })
                    break
            else:
                loan_delta = metric_mod.pct_change(loan[-1]["value"], loan[-5]["value"])
                nii_delta = (metric_mod.pct_change(nii[-1]["value"], nii[-5]["value"])
                             if len(nii) >= 5 else None)
                if loan_delta is None:
                    continue
                direction = "tumbuh" if loan_delta > 0 else "menyusut"
                statement = (
                    f"Kredit {symbol} {direction} {abs(loan_delta) * 100:.1f}% YoY "
                    f"(kuartal {loan[-1]['date']})"
                )
                if nii_delta is not None:
                    statement += (f", pendapatan bunga bersih "
                                  f"{'naik' if nii_delta > 0 else 'turun'} "
                                  f"{abs(nii_delta) * 100:.1f}% YoY")
                drafts.append({
                    "symbol": symbol,
                    "company_name": row.get("company_name"),
                    "statement": statement,
                    "horizon": horizon,
                    "evidence": {
                        "gross_loan_delta_pct": round(loan_delta * 100, 2),
                        "nii_delta_pct": None if nii_delta is None else round(nii_delta * 100, 2),
                        "as_of": loan[-1]["date"],
                    },
                    "generated": True,
                })
            if len(drafts) >= count:
                break
        return {"sub_sector": sub_sector, "drafts": drafts, "skipped": skipped,
                "credits": budget.budget.spent,
                "note": "Generated from reported metrics — confirm or edit before trusting it."}

    def watchlist(self, *, symbol: str | None = None, action: str = "list") -> dict[str, Any]:
        if action == "add" and symbol:
            thesis = self.store.find_thesis(symbol)
            if thesis:
                self.store.set_watch(thesis["id"], True)
                return {"action": "add", "thesis": thesis["symbol"]}
            return {"action": "add", "error": f"no thesis for {symbol}"}
        if action == "remove" and symbol:
            thesis = self.store.find_thesis(symbol)
            if thesis:
                self.store.set_watch(thesis["id"], False)
                return {"action": "remove", "thesis": thesis["symbol"]}
            return {"action": "remove", "error": f"no thesis for {symbol}"}
        if action == "read":
            self.store.mark_read()
            return {"action": "read"}
        return {"watchlist": [t["symbol"] for t in self.store.list_theses(watch_only=True)]}

    def notifications(self, *, unread_only: bool = False) -> list[dict[str, Any]]:
        return self.store.list_notifications(unread_only=unread_only)
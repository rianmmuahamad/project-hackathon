"""Sectors Financial API client.

Three jobs, and nothing else:

1. one place that knows the endpoint shapes (verified against the published
   OpenAPI document at https://docs.sectors.app/schema.json),
2. an on-disk response cache so re-checking a thesis costs nothing,
3. a credit ledger — every call is priced at 1 credit and every ledger row says
   whether it went to the network or was served from cache.

Standard library only (`urllib`), so the core runs in any interpreter.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
from urllib.parse import quote
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .config import REPO_ROOT, settings

# The API sits behind Cloudflare, which rejects the stock `Python-urllib/x.y`
# signature with a 1010. An honest identifying UA is required, not a spoofed one.
USER_AGENT = "thesisradar/0.1 (+https://github.com/rianmmuahamad/project-hackathon)"


class SectorsError(RuntimeError):
    pass


class BudgetExceeded(SectorsError):
    """Raised before a call that would spend credits past the hard ceiling."""


@dataclass
class Budget:
    """A hard credit ceiling for one job. 0 means unlimited."""

    limit: int = 0
    spent: int = 0

    def charge(self, n: int = 1) -> None:
        if self.limit and self.spent + n > self.limit:
            raise BudgetExceeded(
                f"credit budget exhausted: {self.spent} spent of {self.limit}, "
                f"this call needs {n}"
            )
        self.spent += n

    @property
    def remaining(self) -> int | None:
        return None if not self.limit else max(0, self.limit - self.spent)


def bare(symbol: str) -> str:
    """`BBCA.JK` / `bbca` -> `BBCA`. Every endpoint wants the bare ticker."""
    return (symbol or "").strip().upper().removesuffix(".JK")


def _clean_commodity(name: str) -> str:
    """Trim a commodity name. The API is case-insensitive ('gold' works) but a
    trailing space is a URL error, so trimming is the fix and case is left alone
    to keep the stored name identical to the API's own spelling."""
    return (name or "").strip()

def last_available_day() -> str:
    """The newest date the API will accept as an `end` bound.

    Daily and index data are end-of-day, and the API rejects any `end` it
    considers to be in the future — it compares against its own date, which can
    lag the workstation's clock by a day. Clamping to yesterday is correct for
    EOD data in every timezone and removes an entire class of 400s.
    """
    return (date.today() - timedelta(days=1)).isoformat()


class Ledger:
    """Append-only credit audit trail. One JSON line per call."""

    def __init__(self, path=None) -> None:
        self.path = path or (settings().home / "credits.jsonl")

    def record(self, *, path: str, params: dict[str, Any], credits: int,
               cached: bool, status: int, ms: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "path": path,
            "params": params,
            "credits": credits,
            "cached": cached,
            "status": status,
            "ms": ms,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def summary(self) -> dict[str, Any]:
        spent = cached = calls = 0
        per_path: dict[str, int] = {}
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                calls += 1
                if row.get("cached"):
                    cached += 1
                else:
                    spent += int(row.get("credits") or 0)
                    per_path[row["path"]] = per_path.get(row["path"], 0) + 1
        return {
            "calls": calls,
            "network_calls": calls - cached,
            "cached_calls": cached,
            "credits_spent": spent,
            "by_endpoint": dict(sorted(per_path.items(), key=lambda kv: -kv[1])),
        }


class Cache:
    """Content-addressed on-disk cache. Keyed on path + params, never on the key."""

    def __init__(self, root=None, ttl_seconds: int = 6 * 3600) -> None:
        self.root = root or (settings().home / "cache")
        self.ttl = ttl_seconds

    def _file(self, key: str):
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> Any | None:
        path = self._file(key)
        if not path.is_file():
            return None
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        if time.time() - float(row.get("ts") or 0) > self.ttl:
            return None
        return row.get("payload")

    def put(self, key: str, payload: Any) -> None:
        path = self._file(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"ts": time.time(), "payload": payload}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )


class Sectors:
    """Thin, cached, budget-aware wrapper over the v2 REST API."""

    def __init__(self, api_key: str | None = None, api_base: str | None = None,
                 budget: Budget | None = None, cache: Cache | None = None,
                 ledger: Ledger | None = None) -> None:
        cfg = settings()
        self.api_key = api_key if api_key is not None else cfg.api_key
        self.api_base = (api_base or cfg.api_base).rstrip("/")
        self.budget = budget or Budget()
        self.cache = cache if cache is not None else Cache()
        self.ledger = ledger or Ledger()
        self.calls: list[dict[str, Any]] = []

    # -- transport ---------------------------------------------------------
    def _request(self, path: str, params: dict[str, Any]) -> Any:
        if not self.api_key:
            raise SectorsError("SECTORS_API_KEY is not set (copy .env.example to .env)")

        clean = {k: v for k, v in params.items() if v not in (None, "")}
        query = urllib.parse.urlencode(clean, doseq=True)
        url = f"{self.api_base}{path}" + (f"?{query}" if query else "")

        key = hashlib.sha256(f"{path}?{query}".encode()).hexdigest()
        hit = self.cache.get(key)
        if hit is not None:
            self.ledger.record(path=path, params=clean, credits=0, cached=True, status=200, ms=0)
            self.calls.append({"path": path, "params": clean, "credits": 0, "cached": True})
            return hit

        self.budget.charge(1)
        started = time.time()
        req = urllib.request.Request(url, headers={
            "Authorization": self.api_key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        })
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = resp.read().decode("utf-8")
                status = resp.status
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:300]
            self.ledger.record(path=path, params=clean, credits=1, cached=False,
                               status=err.code, ms=int((time.time() - started) * 1000))
            raise SectorsError(f"{err.code} on {path}: {detail}") from err
        except urllib.error.URLError as err:
            raise SectorsError(f"network error on {path}: {err.reason}") from err

        ms = int((time.time() - started) * 1000)
        self.ledger.record(path=path, params=clean, credits=1, cached=False, status=status, ms=ms)
        self.calls.append({"path": path, "params": clean, "credits": 1, "cached": False, "ms": ms})

        try:
            payload = json.loads(body)
        except ValueError as err:
            raise SectorsError(f"non-JSON response from {path}") from err
        self.cache.put(key, payload)
        return payload

    # -- endpoints ---------------------------------------------------------
    def screener(self, *, where: str | None = None, q: str | None = None,
                 order_by: str | None = None, limit: int | None = None,
                 include_query_values: bool = True) -> list[dict[str, Any]]:
        payload = self._request("/v2/companies/", {
            "where": where, "q": q, "order_by": order_by, "limit": limit,
            "include_query_values": "true" if include_query_values else None,
        })
        rows = payload.get("results") or []
        return [flatten_screener_row(r) for r in rows]

    def daily(self, symbol: str, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        return self._request(f"/v2/daily/{bare(symbol)}/", {"start": start, "end": end}) or []

    def foreign_flow(self, symbol: str, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        payload = self._request(f"/v2/foreign-flow/{bare(symbol)}/", {"start": start, "end": end}) or {}
        return payload.get("data") or []

    def foreign_flow_universe(self, date: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        payload = self._request("/v2/foreign-flow/", {"date": date, "limit": limit})
        if isinstance(payload, dict):
            return payload.get("data") or payload.get("results") or []
        return payload or []

    def broker_top(self, symbol: str, start: str | None = None, end: str | None = None,
                   n_brokers: int = 10) -> dict[str, Any]:
        return self._request(f"/v2/broker-summary/{bare(symbol)}/top/", {
            "start": start, "end": end, "n_brokers": n_brokers,
        }) or {}

    def filings(self, *, symbol: str | None = None, sector: str | None = None,
                start: str | None = None, end: str | None = None, limit: int = 30,
                transaction_type: str | None = None) -> list[dict[str, Any]]:
        payload = self._request("/v2/filings/", {
            "symbol": bare(symbol) if symbol else None, "sector": sector,
            "start": start, "end": end, "limit": limit,
            "transaction_type": transaction_type,
        }) or {}
        return payload.get("results") or []

    def news(self, *, symbols: str | None = None, sector: str | None = None,
             keyword: str | None = None, start: str | None = None, end: str | None = None,
             limit: int = 30) -> list[dict[str, Any]]:
        payload = self._request("/v2/news/", {
            "symbols": symbols, "sector": sector, "keyword": keyword,
            "start": start, "end": end, "limit": limit,
        }) or {}
        return payload.get("results") or payload.get("data") or []

    def company_report(self, symbol: str, sections: str = "overview") -> dict[str, Any]:
        payload = self._request(f"/v2/company/report/{bare(symbol)}/", {"sections": sections})
        return payload or {}

    def segments(self, symbol: str, year: int | None = None) -> dict[str, Any]:
        return self._request(f"/v2/company/get-segments/{bare(symbol)}/",
                             {"financial_year": year}) or {}

    def shareholders(self, symbol: str, year: int | None = None) -> dict[str, Any]:
        return self._request(f"/v2/company/shareholders-composition/{bare(symbol)}/",
                             {"year": year}) or {}

    def quarterly(self, symbol: str, n_quarters: int = 8) -> list[dict[str, Any]]:
        rows = self._request(f"/v2/financials/quarterly/{bare(symbol)}/",
                             {"n_quarters": n_quarters}) or []
        return [flatten_financial_row(r) for r in rows]

    def commodities(self) -> list[dict[str, Any]]:
        """Every commodity the API prices, with its coverage window.

        The window matters: 17 of the 18 stop at 2026-02-15 while Gold and Silver
        run to 2026-09-01, so a "current" claim about most commodities is stale by
        more than half a year. The caller must be able to see that.
        """
        return self._request("/v2/mining/commodities/", {}) or []

    def commodity_prices(self, name: str, *, start_year: int, end_year: int) -> list[dict[str, Any]]:
        """Monthly price history. The API rejects a range wider than 3 years."""
        quoted = quote(_clean_commodity(name), safe="")
        return self._request(f"/v2/mining/commodities/{quoted}/price/",
                             {"start_year": start_year, "end_year": end_year}) or []

    def commodity_production(self, name: str) -> list[dict[str, Any]]:
        """Annual production for one commodity, newest year first as the API returns it."""
        return self._request("/v2/mining/total-production/",
                             {"commodity_type": _clean_commodity(name)}) or []

    def quarterly_dates(self, symbol: str) -> dict[str, Any]:
        return self._request(f"/v2/company/get_quarterly_financial_dates/{bare(symbol)}/", {}) or {}

    def corporate_actions(self, symbol: str) -> dict[str, Any]:
        return self._request(f"/v2/company/corporate-actions/{bare(symbol)}/", {}) or {}

    def suspensions(self, *, symbol: str | None = None, start: str | None = None,
                    end: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        payload = self._request("/v2/suspensions/", {
            "symbol": bare(symbol) if symbol else None,
            "start": start, "end": end, "limit": limit,
        }) or {}
        return payload.get("results") or payload.get("data") or []

    def subsector_report(self, sub_sector: str, sections: str = "statistics,valuation") -> dict[str, Any]:
        return self._request(f"/v2/subsector/report/{sub_sector}/", {"sections": sections}) or {}

    def company_meta(self, symbol: str) -> dict[str, Any]:
        """Name and classification for one ticker.

        The screener's `where` clauses are matched against the exchange's own
        symbols, which carry the `.JK` suffix — the per-symbol endpoints do not.
        Getting this wrong returns an empty list rather than an error, so it is
        handled in one place.
        """
        symbol = bare(symbol)
        try:
            rows = self.screener(where=f"symbol = '{symbol}.JK'", limit=1)
        except SectorsError:
            rows = []
        if rows:
            return {"symbol": symbol, "company_name": rows[0].get("company_name"),
                    "source": "screener"}
        try:
            overview = (self.company_report(symbol, sections="overview").get("overview") or {})
        except SectorsError:
            return {"symbol": symbol, "company_name": None, "source": None}
        return {"symbol": symbol,
                "company_name": overview.get("company_name"),
                "sector": overview.get("sector"),
                "sub_sector": overview.get("sub_sector"),
                "market_cap": overview.get("market_cap"),
                "source": "report"}

    def index_daily(self, index_code: str, start: str | None = None,
                    end: str | None = None) -> list[dict[str, Any]]:
        return self._request(f"/v2/index-daily/{index_code.lower()}/",
                             {"start": start, "end": end}) or []

    def top_changes(self, *, sub_sector: str | None = None, periods: str = "7d,30d",
                    classifications: str = "top_gainers,top_losers",
                    n_stock: int = 5) -> dict[str, Any]:
        return self._request("/v2/companies/top-changes/", {
            "sub_sector": sub_sector, "periods": periods,
            "classifications": classifications, "n_stock": n_stock,
        }) or {}

    def index_universe(self, date: str | None = None) -> list[dict[str, Any]]:
        return self._request("/v2/index-daily/", {"date": date}) or []

    def subscriptions_ok(self) -> bool:
        try:
            self._request("/v2/tags/", {})
            return True
        except SectorsError:
            return False


# --------------------------------------------------------------------------
# normalisers — one flat shape per row, so metrics are addressable by name
# --------------------------------------------------------------------------
def flatten_screener_row(row: dict[str, Any]) -> dict[str, Any]:
    """Lift the screener's `query_values` up beside symbol/company_name."""
    out = dict(row)
    out.update(row.get("query_values") or {})
    out.pop("query_values", None)
    return out


def flatten_financial_row(row: dict[str, Any]) -> dict[str, Any]:
    """Merge `financials_sector_metrics` (bank/insurance metrics) into the row.

    The API nests `net_interest_income`, `gross_loan`, `total_deposit` and
    friends there; flattening means a claim can name any metric without the
    caller knowing which shelf it sits on.
    """
    out = dict(row)
    out.update(row.get("financials_sector_metrics") or {})
    out.pop("financials_sector_metrics", None)
    return out


def metric_series(rows: list[dict[str, Any]], metric: str) -> list[dict[str, Any]]:
    """Extract one metric across a quarterly series, oldest first, gaps dropped."""
    out = []
    for row in rows:
        value = row.get(metric)
        if isinstance(value, (int, float)):
            out.append({"date": row.get("date"), "value": float(value)})
    out.sort(key=lambda r: str(r.get("date") or ""))
    return out


def static_asset_hint() -> str:
    return str(REPO_ROOT / "web")
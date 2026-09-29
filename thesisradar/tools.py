"""The agent's hands.

Every tool here answers a *question an analyst would actually ask* ("is this
move the company's, or the market's?"), not "call this endpoint". That is the
difference between a product and an MCP wrapper, and it is also what makes the
transcript worth reading: the tool name alone tells you what the agent was
trying to find out.

Tools return plain dicts; `execute()` serialises them. Each result carries the
endpoint and params it came from so any number can be traced back by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable
from urllib.parse import quote

from . import metrics
from .sectors import Sectors, SectorsError, bare, last_available_day


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        out = default
    return max(low, min(high, out))


def _as_date(value: Any, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return default


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., dict[str, Any]]
    provenance: list[dict[str, Any]] = field(default_factory=list)

    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------
def what_changed(s: Sectors, symbol: str, since: str = "") -> dict[str, Any]:
    """Everything genuinely new for one name since a date, in one call.

    The point of the watermark: the agent should never re-read a name it already
    examined, and should always see exactly what appeared since it last looked.
    """
    symbol = bare(symbol)
    since = _as_date(since, _days_ago(30))
    today = last_available_day()

    price = s.daily(symbol, start=since, end=today)
    flow = s.foreign_flow(symbol, start=since, end=today)
    filings = s.filings(symbol=symbol, start=since, end=today, limit=30)
    news = s.news(symbols=symbol, start=since, end=today, limit=20)
    actions = s.corporate_actions(symbol)
    suspensions = s.suspensions(symbol=symbol, start=since, end=today, limit=20)

    closes = [r for r in price if isinstance(r.get("close"), (int, float))]
    traded = [r for r in closes if (r.get("volume") or 0) > 0]
    no_trade = len(closes) - len(traded)
    first = traded[0] if traded else (closes[0] if closes else None)
    last = closes[-1] if closes else None
    raw_move = None
    traded_move = None
    if first and last and first.get("close"):
        raw_move = (last["close"] - first["close"]) / first["close"]
    if len(traded) >= 2 and traded[0].get("close"):
        traded_move = (traded[-1]["close"] - traded[0]["close"]) / traded[0]["close"]

    net_foreign = sum(float(r.get("net_foreign_inflow") or 0) for r in flow)
    buy_days = sum(1 for r in flow if float(r.get("net_foreign_inflow") or 0) > 0)
    sell_days = sum(1 for r in flow if float(r.get("net_foreign_inflow") or 0) < 0)

    buys = [f for f in filings if (f.get("transaction_type") or "").lower() == "buy"]
    sells = [f for f in filings if (f.get("transaction_type") or "").lower() == "sell"]

    recent_actions = _recent_corporate_actions(actions, since)

    return {
        "symbol": symbol,
        "since": since,
        "price": {
            "sessions": len(closes),
            "sessions_with_no_trade": no_trade,
            "first_close": first.get("close") if first else None,
            "last_close": last.get("close") if last else None,
            "change_pct": None if raw_move is None else round(raw_move * 100, 2),
            "change_pct_traded_only": None if traded_move is None else round(traded_move * 100, 2),
        },
        "foreign": {
            "days": len(flow),
            "net_inflow_idr": round(net_foreign),
            "net_inflow_display": metrics.describe(net_foreign),
            "buy_days": buy_days,
            "sell_days": sell_days,
            "_note": ("A large move with sessions_with_no_trade > 0 or a corporate action in the "
                      "window is an artefact, not a signal."),
        },
        "insiders": {
            "filings": len(filings),
            "buy": len(buys),
            "sell": len(sells),
            "recent": [{
                "date": (f.get("timestamp") or "")[:10],
                "type": f.get("transaction_type"),
                "title": (f.get("title") or "")[:160],
                "holder_type": f.get("holder_type"),
            } for f in filings[:8]],
        },
        "news": [{
            "date": (n.get("published_at") or n.get("date") or n.get("timestamp") or "")[:10],
            "title": (n.get("title") or "")[:180],
            "tags": n.get("tags"),
        } for n in news[:10]],
        "corporate_actions": recent_actions,
        "suspensions": [{
            "date": (r.get("date") or r.get("suspension_date") or "")[:10],
            "reason": (r.get("reason") or "")[:200],
        } for r in suspensions[:5]],
    }


def _recent_corporate_actions(payload: dict[str, Any], since: str) -> list[dict[str, Any]]:
    """Flatten whatever action buckets the API returned into dated rows."""
    out: list[dict[str, Any]] = []
    buckets = payload.get("actions") if isinstance(payload.get("actions"), dict) else payload
    if not isinstance(buckets, dict):
        return out
    for kind, rows in buckets.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            when = str(row.get("date") or row.get("ex_date") or row.get("payment_date") or "")
            if when and when[:10] >= since:
                out.append({
                    "kind": kind,
                    "date": when[:10],
                    "detail": {k: v for k, v in row.items() if k not in ("date",)},
                })
    out.sort(key=lambda r: r["date"], reverse=True)
    return out[:10]


def fundamentals_delta(s: Sectors, symbol: str, metric: str = "", quarters: int = 8) -> dict[str, Any]:
    """The direction of one named metric over recent quarters.

    Returns the whole series, not just a number: the agent must be able to see a
    one-quarter dip inside a two-year uptrend, and say so.
    """
    symbol = bare(symbol)
    quarters = _clamp_int(quarters, 8, 2, 16)
    field = metrics.normalise(metric) or metrics.detect_metric(metric or "")
    rows = s.quarterly(symbol, n_quarters=quarters)

    if not field:
        available = sorted({
            k for row in rows for k, v in row.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        })
        return {
            "symbol": symbol, "metric": metric, "resolved": None, "series": [],
            "error": f"unknown metric '{metric}'",
            "known_metrics": available,
            "_note": "Pick a metric from known_metrics.",
        }

    series = metrics.series_of(rows, field)

    if not series:
        resolved, fallback_note = metrics.with_fallback(
            field, lambda name: bool(metrics.series_of(rows, name)))
        if resolved != field:
            series = metrics.series_of(rows, resolved)
            field = resolved
        else:
            fallback_note = None
    else:
        fallback_note = None

    if not series:
        available = sorted({
            k for row in rows for k, v in row.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        })
        return {"symbol": symbol, "metric": field, "resolved": None, "series": [],
                "requested": metric,
                "error": f"no {field} reported for {symbol}",
                "known_metrics": available,
                "_note": "Pick a metric from known_metrics."}

    latest = series[-1]
    prior = series[-5] if len(series) >= 5 else (series[0] if series else None)
    delta = None
    if prior and prior.get("value"):
        delta = metrics.pct_change(latest["value"], prior["value"])

    values = [p["value"] for p in series]
    steps = [round((b - a) / abs(a) * 100, 2) for a, b in zip(values, values[1:]) if a]

    caution = metrics.caution_for(metric or "", field) or fallback_note

    return {
        "symbol": symbol,
        "metric": field,
        "resolved": field,
        "requested": metric,
        "caution": caution,
        "series": [{"date": p["date"], "value": p["value"],
                    "display": metrics.describe(p["value"])} for p in series],
        "latest": {"date": latest["date"], "value": latest["value"],
                   "display": metrics.describe(latest["value"])},
        "delta_yoy_pct": None if delta is None else round(delta * 100, 2),
        "delta_yoy_display": "n/a" if delta is None else f"{delta * 100:+.1f}%",
        "quarterly_change_pct": steps,
        "direction_last3": metrics.direction_from_delta(
            None if len(values) < 2 or not values[-2] else (values[-1] - values[-2]) / abs(values[-2])
        ),
        "endpoint": f"/v2/financials/quarterly/{symbol}/",
        "params": {"n_quarters": quarters},
    }

def commodity_price(s: Sectors, commodity: str, years: int = 3) -> dict[str, Any]:
    """The monthly price series for ONE commodity in USD/ton.

    Returns the series and recent year-on-year changes so the agent can see the trend.
    """
    commodity = (commodity or "").strip()
    years = _clamp_int(years, 3, 1, 3)
    this_year = date.today().year
    rows = s.commodity_prices(commodity, start_year=this_year - years + 1, end_year=this_year)
    clean = []
    for r in rows:
        if r.get("date") and r.get("price_usd_per_ton") is not None:
            clean.append({"date": str(r["date"]), "value": float(r["price_usd_per_ton"])})
    clean.sort(key=lambda r: r["date"])

    if not clean:
        return {
            "symbol": commodity, "metric": "commodity_price", "series": [],
            "error": f"no price data reported for commodity '{commodity}'",
            "endpoint": f"/v2/mining/commodities/{quote(commodity, safe='')}/price/",
        }

    latest = clean[-1]
    yoy_idx = len(clean) - 13 if len(clean) > 12 else 0
    prior = clean[yoy_idx] if len(clean) > 1 else None
    delta = metrics.pct_change(latest["value"], prior["value"]) if prior and prior.get("value") else None

    staleness_days = 0
    try:
        staleness_days = (date.today() - date.fromisoformat(latest["date"])).days
    except ValueError:
        pass

    return {
        "symbol": commodity,
        "metric": "commodity_price",
        "series": [{"date": p["date"], "value": p["value"], "display": f"{p['value']:,.2f} USD/ton"} for p in clean],
        "latest": {"date": latest["date"], "value": latest["value"], "display": f"{latest['value']:,.2f} USD/ton"},
        "delta_yoy_pct": None if delta is None else round(delta * 100, 2),
        "delta_yoy_display": "n/a" if delta is None else f"{delta * 100:+.1f}%",
        "staleness_days": staleness_days,
        "endpoint": f"/v2/mining/commodities/{quote(commodity, safe='')}/price/",
        "params": {"start_year": this_year - years + 1, "end_year": this_year},
    }


def commodity_production(s: Sectors, commodity: str) -> dict[str, Any]:
    """Annual production for ONE commodity in Indonesia, with volume and YoY changes."""
    commodity = (commodity or "").strip()
    rows = s.commodity_production(commodity)
    clean = []
    for r in rows:
        year = r.get("year")
        if year is not None and r.get("production_volume") is not None:
            clean.append({
                "year": int(year),
                "date": str(year),
                "value": float(r["production_volume"]),
                "prev_value": r.get("prev_year_volume"),
                "unit": r.get("unit", "Mt"),
                "yoy_change_percent": r.get("yoy_change_percent"),
            })
    clean.sort(key=lambda r: r["year"])

    if not clean:
        return {
            "symbol": commodity, "metric": "production_volume", "series": [],
            "error": f"no production data reported for commodity '{commodity}'",
            "endpoint": "/v2/mining/total-production/",
        }

    latest = clean[-1]
    return {
        "symbol": commodity,
        "metric": "production_volume",
        "series": [{"date": str(p["year"]), "value": p["value"], "display": f"{p['value']:,.2f} {p['unit']}",
                    "yoy_change_percent": p["yoy_change_percent"]} for p in clean],
        "latest": {"date": str(latest["year"]), "value": latest["value"], "display": f"{latest['value']:,.2f} {latest['unit']}"},
        "delta_yoy_pct": latest.get("yoy_change_percent"),
        "delta_yoy_display": "n/a" if latest.get("yoy_change_percent") is None else f"{latest['yoy_change_percent']:+.1f}%",
        "unit": latest["unit"],
        "endpoint": "/v2/mining/total-production/",
        "params": {"commodity_type": commodity},
    }


def flow_delta(s: Sectors, symbol: str, days: int = 21) -> dict[str, Any]:
    """Is the money still coming in, or has it turned?

    Compares the recent stretch against the one before it, so "the accumulation
    stalled two weeks ago" is visible rather than averaged away.
    """
    symbol = bare(symbol)
    days = _clamp_int(days, 21, 5, 90)
    start = _days_ago(days)
    end = last_available_day()

    flow = s.foreign_flow(symbol, start=start, end=end)
    top = s.broker_top(symbol, start=start, end=end, n_brokers=8)

    half = len(flow) // 2
    recent, earlier = flow[half:], flow[:half]
    net = lambda rows: sum(float(r.get("net_foreign_inflow") or 0) for r in rows)

    return {
        "symbol": symbol,
        "window_days": days,
        "days_reported": len(flow),
        "net_inflow_idr": round(net(flow)),
        "net_inflow_display": metrics.describe(net(flow)),
        "first_half_display": metrics.describe(net(earlier)),
        "second_half_display": metrics.describe(net(recent)),
        "turned": (net(earlier) > 0) != (net(recent) > 0) if flow else None,
        "daily": [{
            "date": r.get("date"),
            "net_inflow_display": metrics.describe(float(r.get("net_foreign_inflow") or 0)),
            "foreign_share": r.get("foreign_share"),
        } for r in flow[-10:]],
        "brokers_accumulating": [{
            "code": b.get("broker_code") or b.get("code"),
            "name": b.get("broker_name") or b.get("name"),
            "net_idr_display": metrics.describe(float(b.get("net_value") or b.get("net_idr") or 0)),
        } for b in (top.get("top_buyers") or top.get("top_accumulations") or [])[:5]],
        "brokers_distributing": [{
            "code": b.get("broker_code") or b.get("code"),
            "name": b.get("broker_name") or b.get("name"),
            "net_idr_display": metrics.describe(float(b.get("net_value") or b.get("net_idr") or 0)),
        } for b in (top.get("top_sellers") or top.get("top_distributions") or [])[:5]],
        "endpoints": [f"/v2/foreign-flow/{symbol}/", f"/v2/broker-summary/{symbol}/top/"],
    }


def insider_activity(s: Sectors, symbol: str, since: str = "") -> dict[str, Any]:
    """Who inside the company has been buying or selling, and how much."""
    symbol = bare(symbol)
    since = _as_date(since, _days_ago(90))
    end = last_available_day()
    rows = s.filings(symbol=symbol, start=since, end=end, limit=30)
    buys = [r for r in rows if (r.get("transaction_type") or "").lower() == "buy"]
    sells = [r for r in rows if (r.get("transaction_type") or "").lower() == "sell"]
    return {
        "symbol": symbol,
        "since": since,
        "count": len(rows),
        "buys": len(buys),
        "sells": len(sells),
        "net_direction": "buy" if len(buys) > len(sells) else ("sell" if len(sells) > len(buys) else "mixed"),
        "filings": [{
            "date": (r.get("timestamp") or "")[:10],
            "type": r.get("transaction_type"),
            "holder_type": r.get("holder_type"),
            "title": (r.get("title") or "")[:200],
            "source": r.get("source"),
        } for r in rows[:12]],
        "endpoint": "/v2/filings/",
        "params": {"symbol": symbol, "start": since},
    }


def corporate_action_check(s: Sectors, symbol: str, since: str = "") -> dict[str, Any]:
    """Is this price move real, or the mechanical effect of a corporate action?

    Splits, rights issues and dividends move prices without anyone changing their
    mind about the company. Also reports trading halts, because a suspension pins
    the last close and manufactures a fake trend.
    """
    symbol = bare(symbol)
    since = _as_date(since, _days_ago(90))
    end = last_available_day()
    actions = s.corporate_actions(symbol)
    suspensions = s.suspensions(symbol=symbol, start=since, end=end, limit=20)
    return {
        "symbol": symbol,
        "since": since,
        "actions": _recent_corporate_actions(actions, since),
        "raw_action_keys": sorted(k for k, v in (actions or {}).items() if isinstance(v, list) and v),
        "suspensions": [{
            "date": (r.get("date") or r.get("suspension_date") or "")[:10],
            "reason": (r.get("reason") or "")[:200],
            "notice": r.get("link") or r.get("url"),
        } for r in suspensions],
        "sessions_at_risk": len(suspensions),
        "endpoints": [f"/v2/company/corporate-actions/{symbol}/", "/v2/suspensions/"],
    }


def sector_context(s: Sectors, symbol: str, metric: str = "") -> dict[str, Any]:
    """Is this the company, or the whole sector?

    A bank whose loans grew 4% while the sector grew 6% is losing share: the same
    number is good news in one context and bad in the other, and only this
    comparison can tell the two apart.
    """
    symbol = bare(symbol)
    profile = s.company_report(symbol, sections="overview")
    overview = profile.get("overview") or {}
    sub_sector = (overview.get("sub_sector") or "").lower().replace(" ", "-")
    snapshot = {}
    peers: list[dict[str, Any]] = []
    if sub_sector:
        snapshot = s.subsector_report(sub_sector, sections="statistics,valuation,market_cap")
        peers = s.screener(where=f"sub_sector = '{sub_sector}'", order_by="-market_cap", limit=10)

    field = metrics.normalise(metric) if metric else None
    peer_series: list[dict[str, Any]] = []
    if field and peers:
        for peer in peers[:6]:
            # Comparing a company against itself is meaningless, and it would
            # re-fetch the subject's financials under a different window — a
            # second charge for data this check already paid for.
            peer_symbol = bare(peer["symbol"])
            if peer_symbol == symbol:
                continue
            rows = s.quarterly(peer_symbol, n_quarters=5)
            series = metrics.series_of(rows, field)
            if len(series) >= 2:
                change = metrics.pct_change(series[-1]["value"], series[0]["value"])
                peer_series.append({
                    "symbol": peer_symbol,
                    "delta_pct": None if change is None else round(change * 100, 2),
                })

    return {
        "symbol": symbol,
        "company_name": overview.get("company_name"),
        "sector": overview.get("sector"),
        "sub_sector": overview.get("sub_sector"),
        "subsector_statistics": snapshot.get("statistics"),
        "subsector_valuation": snapshot.get("valuation"),
        "peer_count": len(peers),
        "peers": [{"symbol": bare(p["symbol"]), "company_name": p.get("company_name"),
                   "market_cap": p.get("market_cap")} for p in peers[:6]],
        "peer_metric_moves": peer_series,
        "endpoints": ["/v2/company/report/{symbol}/", f"/v2/subsector/report/{sub_sector}/", "/v2/companies/"],
    }


def market_context(s: Sectors, since: str = "") -> dict[str, Any]:
    """What the whole market did, so a company move can be discounted against it."""
    since = _as_date(since, _days_ago(30))
    end = last_available_day()
    series = s.index_daily("ihsg", start=since, end=end)
    clean = [r for r in series if isinstance(r.get("price"), (int, float))]
    change = None
    if len(clean) >= 2 and clean[0]["price"]:
        change = (clean[-1]["price"] - clean[0]["price"]) / clean[0]["price"]
    return {
        "index": "IHSG",
        "since": since,
        "sessions": len(clean),
        "first": clean[0]["price"] if clean else None,
        "last": clean[-1]["price"] if clean else None,
        "change_pct": None if change is None else round(change * 100, 2),
        "endpoint": "/v2/index-daily/{index_code}/",
        "_note": "Subtract this from a stock's move before calling the move unusual.",
    }


def news_search(s: Sectors, symbol: str = "", keyword: str = "", since: str = "",
                limit: int = 20) -> dict[str, Any]:
    """What has actually been written, with dates — for testing a causal story."""
    since = _as_date(since, _days_ago(30))
    end = last_available_day()
    rows = s.news(symbols=bare(symbol) if symbol else None, keyword=keyword or None,
                  start=since, end=end,
                  limit=_clamp_int(limit, 20, 1, 30))
    return {
        "symbol": bare(symbol) if symbol else None,
        "keyword": keyword or None,
        "since": since,
        "count": len(rows),
        "articles": [{
            "date": (r.get("published_at") or r.get("date") or r.get("timestamp") or "")[:10],
            "title": (r.get("title") or "")[:200],
            "tags": r.get("tags"),
            "url": r.get("url") or r.get("link"),
        } for r in rows],
        "endpoint": "/v2/news/",
    }


def screen_companies(s: Sectors, query: str = "", where: str = "", order_by: str = "",
                     limit: int = 10) -> dict[str, Any]:
    """Find names by plain-language or SQL-like criteria — the widest single door.

    Useful when a thesis is about a theme ("banks with the fastest loan growth")
    rather than one ticker that is already known.
    """
    rows = s.screener(q=query or None, where=where or None, order_by=order_by or None,
                      limit=_clamp_int(limit, 10, 1, 50))
    return {
        "query": query or where or None,
        "count": len(rows),
        "companies": [{
            "symbol": bare(r.get("symbol")),
            "company_name": r.get("company_name"),
            "values": {k: v for k, v in r.items()
                       if k not in ("symbol", "company_name") and v is not None},
        } for r in rows],
        "endpoint": "/v2/companies/",
    }


def evidence_ledger(store, symbol: str) -> dict[str, Any]:
    """What this product has already gathered about a name.

    Read this before spending credits: the answer may already be on disk, and
    repeating a call the constraint system has already paid for is waste.
    """
    symbol = bare(symbol)
    thesis = None
    rows = store.q("SELECT id, statement, status, confidence, last_checked_at FROM theses "
                   "WHERE symbol=? ORDER BY created_at DESC", (symbol,))
    if rows:
        thesis = dict(rows[0])
    evidence = store.q(
        "SELECT e.metric, e.value, e.as_of, e.endpoint FROM evidence e "
        "JOIN checks c ON c.id = e.check_id JOIN theses t ON t.id = c.thesis_id "
        "WHERE t.symbol=? ORDER BY e.ordinal DESC LIMIT 40", (symbol,))
    return {
        "symbol": symbol,
        "prior_thesis": thesis,
        "prior_evidence": [dict(e) for e in evidence],
        "note": "Empty means this is the first time the product has looked at this name.",
    }


TOOLS: tuple[Tool, ...] = (
    Tool(
        "what_changed",
        "Everything genuinely new for one stock since a date: price (and whether any "
        "sessions had no trading at all), foreign flow, insider filings, news, corporate "
        "actions and trading halts. Start here — it is the cheapest way to see whether "
        "there is anything to investigate.",
        {"type": "object", "properties": {
            "symbol": {"type": "string", "description": "IDX ticker, e.g. BBRI"},
            "since": {"type": "string", "description": "YYYY-MM-DD. Default: 30 days ago."},
        }, "required": ["symbol"]},
        what_changed,
    ),
    Tool(
        "fundamentals_delta",
        "The quarterly series for ONE named metric, with its year-on-year and "
        "quarter-on-quarter change. Use it to test a claim like 'loans growing double "
        "digits' or 'NIM rising'. Returns the whole series so a one-quarter dip inside a "
        "two-year trend is visible rather than averaged away.",
        {"type": "object", "properties": {
            "symbol": {"type": "string"},
            "metric": {"type": "string", "description":
                       "Analyst name: revenue, earnings, net interest income, gross loan, "
                       "total deposit, provision, total_assets, total_equity, free_cash_flow…"},
            "quarters": {"type": "integer", "description": "How many quarters (default 8, max 16)."},
        }, "required": ["symbol", "metric"]},
        fundamentals_delta,
    ),
    Tool(
        "commodity_price",
        "The monthly price series for ONE commodity in USD/ton, with its year-on-year and "
        "quarter-on-year moves. Use it for a claim about what a commodity price did.",
        {"type": "object", "properties": {
            "commodity": {"type": "string", "description": "e.g. Nickel, Gold, Coal"},
            "years": {"type": "integer", "description": "how many years back (max 3)"},
        }, "required": ["commodity"]},
        commodity_price,
    ),
    Tool(
        "commodity_production",
        "Annual production for ONE commodity in Indonesia, with volume and year-on-year change. "
        "Use it for a claim about output or supply.",
        {"type": "object", "properties": {
            "commodity": {"type": "string", "description": "e.g. Nickel, Coal"},
        }, "required": ["commodity"]},
        commodity_production,
    ),
    Tool(
        "flow_delta",
        "Whether the money is still arriving or has turned: net foreign flow split into "
        "first half vs second half of the window, plus the broker desks accumulating and "
        "distributing. Use it when a claim depends on accumulation continuing.",
        {"type": "object", "properties": {
            "symbol": {"type": "string"},
            "days": {"type": "integer", "description": "Window in days (default 21, max 90)."},
        }, "required": ["symbol"]},
        flow_delta,
    ),
    Tool(
        "insider_activity",
        "Insider and major-shareholder buy/sell filings with dates and holder types. Use "
        "it to check whether the people with the most information are acting the way the "
        "thesis assumes.",
        {"type": "object", "properties": {
            "symbol": {"type": "string"},
            "since": {"type": "string", "description": "YYYY-MM-DD. Default: 90 days ago."},
        }, "required": ["symbol"]},
        insider_activity,
    ),
    Tool(
        "corporate_action_check",
        "Whether a price move is real or the mechanical result of a split, rights issue or "
        "dividend, and whether the stock was suspended. A halt pins the last close and "
        "manufactures a fake trend — this tool is how that gets caught.",
        {"type": "object", "properties": {
            "symbol": {"type": "string"},
            "since": {"type": "string", "description": "YYYY-MM-DD. Default: 90 days ago."},
        }, "required": ["symbol"]},
        corporate_action_check,
    ),
    Tool(
        "sector_context",
        "Whether a move belongs to the company or to the whole sector: subsector "
        "aggregates, the largest peers, and the same metric measured across those peers. "
        "A bank growing loans 4% while its sector grew 6% is losing share.",
        {"type": "object", "properties": {
            "symbol": {"type": "string"},
            "metric": {"type": "string", "description": "Optional metric to compare with peers."},
        }, "required": ["symbol"]},
        sector_context,
    ),
    Tool(
        "market_context",
        "What the IHSG did over the same window. Discount a stock's move against this "
        "before calling it unusual — in a market that fell 3%, a stock that fell 3% is not "
        "telling you anything about that company.",
        {"type": "object", "properties": {
            "since": {"type": "string", "description": "YYYY-MM-DD. Default: 30 days ago."},
        }},
        market_context,
    ),
    Tool(
        "news_search",
        "Dated articles, filtered by stock or keyword. Use it to test a causal story: if "
        "the move happened on a date with no news, the story is probably wrong.",
        {"type": "object", "properties": {
            "symbol": {"type": "string"},
            "keyword": {"type": "string"},
            "since": {"type": "string"},
            "limit": {"type": "integer"},
        }},
        news_search,
    ),
    Tool(
        "screen_companies",
        "Find stocks by plain language or SQL-like criteria, e.g. 'banks with the highest "
        "loan growth'. Use it when a thesis is about a theme rather than one known ticker.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "Natural language, e.g. 'top 5 banks by loan growth'"},
            "where": {"type": "string", "description": "SQL-like alternative, e.g. \"sub_sector = 'banks'\""},
            "order_by": {"type": "string"},
            "limit": {"type": "integer"},
        }},
        screen_companies,
    ),
)

BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}

# `evidence_ledger` reads local state, so it takes the store instead of the API;
# it is registered separately to keep the remote tools' signature uniform.
LOCAL_TOOLS = {"evidence_ledger": evidence_ledger}


def schemas() -> list[dict[str, Any]]:
    """Tool definitions for the function-calling engine."""
    out = [t.schema() for t in TOOLS]
    out.append({
        "name": "evidence_ledger",
        "description": "What this product has already gathered about a stock. Read it "
                       "before spending credits — the answer may already be on disk.",
        "parameters": {"type": "object",
                       "properties": {"symbol": {"type": "string"}},
                       "required": ["symbol"]},
    })
    return out


def execute(name: str, args: dict[str, Any], sectors: Sectors, store, *,
            thesis: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one tool call and report how many credits it cost."""
    args = args or {}
    if thesis and thesis.get("subject_type") == "commodity":
        if name in ("what_changed", "fundamentals_delta", "flow_delta", "insider_activity",
                    "corporate_action_check", "sector_context"):
            return {
                "error": "this tool is for equities; use commodity_price or commodity_production",
                "credits": 0,
            }
    if name in LOCAL_TOOLS:
        return {"result": LOCAL_TOOLS[name](store, **args), "credits": 0}

    tool = BY_NAME.get(name)
    if tool is None:
        return {"error": f"unknown tool '{name}'", "credits": 0,
                "known_tools": sorted(BY_NAME) + sorted(LOCAL_TOOLS)}

    before = sectors.budget.spent
    try:
        result = tool.run(sectors, **args)
    except SectorsError as err:
        return {"error": str(err), "credits": sectors.budget.spent - before}
    except TypeError as err:
        return {"error": f"bad arguments for {name}: {err}", "credits": sectors.budget.spent - before}
    return {"result": result, "credits": sectors.budget.spent - before}
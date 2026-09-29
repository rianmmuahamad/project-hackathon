"""Metric vocabulary — the bridge between a sentence and a number.

A thesis says "NIM naik". The API says `net_interest_income`. This module is the
only place that knows the mapping, so a claim can be written in analyst language
and still resolve to a field that exists.

Everything here is deliberately strict: if a metric cannot be resolved, the
caller is told so. A silently-skipped claim would be an invisible lie.
"""

from __future__ import annotations

import re
from typing import Any

# Analyst phrasing -> API field. Indonesian and English, because the theses are
# written in both. Order matters only for readability; lookup is exact.
METRIC_ALIASES: dict[str, str] = {
    # headline P&L
    "revenue": "revenue",
    "pendapatan": "revenue",
    "top line": "revenue",
    "earnings": "earnings",
    "net income": "earnings",
    "net profit": "earnings",
    "laba": "earnings",
    "laba bersih": "earnings",
    "profit": "earnings",
    "ebitda": "ebitda",
    "ebit": "ebit",
    # bank-specific (delivered inside `financials_sector_metrics`)
    "nii": "net_interest_income",
    "net interest income": "net_interest_income",
    "pendapatan bunga bersih": "net_interest_income",
    "interest income": "interest_income",
    "pendapatan bunga": "interest_income",
    "interest expense": "interest_expense",
    "beban bunga": "interest_expense",
    "gross loan": "gross_loan",
    "gross loans": "gross_loan",
    "loans": "gross_loan",
    "kredit": "gross_loan",
    "loan book": "gross_loan",
    "net loan": "net_loan",
    "total deposit": "total_deposit",
    "deposits": "total_deposit",
    "dana pihak ketiga": "total_deposit",
    "dpk": "total_deposit",
    "allowance for loans": "allowance_for_loans",
    "ckpn": "allowance_for_loans",
    "loan loss allowance": "allowance_for_loans",
    "provision": "provision",
    "provisions": "provision",
    "provisioning": "provision",
    "non interest income": "non_interest_income",
    "fee income": "non_interest_income",
    "operating expense": "operating_expense",
    "beban operasional": "operating_expense",
    "cost": "operating_expense",
    # Ratios the API does not compute. They are mapped to the closest reported
    # field, and `caution_for` says out loud that the proxy can diverge — a
    # margin can fall while the underlying income rises, and silently treating
    # them as the same number would be exactly the kind of quiet error this
    # product exists to prevent.
    "nim": "net_interest_income",
    "net interest margin": "net_interest_income",
    "npl": "provision",
    "npf": "provision",
    "non performing loan": "provision",
    "kredit bermasalah": "provision",
    "car": "total_equity",
    "capital adequacy": "total_equity",
    # balance sheet / cash
    "total assets": "total_assets",
    "assets": "total_assets",
    "aset": "total_assets",
    "total equity": "total_equity",
    "equity": "total_equity",
    "ekuitas": "total_equity",
    "stockholders equity": "stockholders_equity",
    "total liabilities": "total_liabilities",
    "total debt": "total_debt",
    "operating cash flow": "operating_cash_flow",
    "arus kas operasi": "operating_cash_flow",
    "free cash flow": "free_cash_flow",
    "arus kas bebas": "free_cash_flow",
    "net cash flow": "net_cash_flow",
    "investing cash flow": "investing_cash_flow",
    "financing cash flow": "financing_cash_flow",
    # commodity subjects
    "harga": "commodity_price", "harga komoditas": "commodity_price",
    "price": "commodity_price", "commodity price": "commodity_price",
    "harga nikel": "commodity_price", "harga emas": "commodity_price",
    "harga batu bara": "commodity_price", "harga tembaga": "commodity_price",
    "produksi": "production_volume", "production": "production_volume",
    "volume produksi": "production_volume", "produksi nikel": "production_volume",
    "produksi batu bara": "production_volume", "output": "production_volume",
}

# Metrics the API computes per-year rather than per-quarter. Baseline capture
# must use a different endpoint for these, so they are flagged rather than
# silently producing an empty series.
PRICE_METRICS = ("close", "price", "harga", "market_cap", "kapitalisasi")

# How many observations make a year, per claim cadence. The year-on-year offset
# is derived from this instead of being hardcoded to quarters.
PERIODS_PER_YEAR: dict[str, int] = {
    "quarterly": 4,
    "commodity_price": 12,   # the price endpoint returns monthly rows
    "production": 1,         # the production endpoint returns annual rows
}

_ALLOWED = set(METRIC_ALIASES.values())

# Some canonical fields come back empty for whole sectors — the API reports banks'
# equity under `stockholders_equity` and leaves `total_equity` null. Rather than
# pick one and hope, a requested metric may declare documented fallbacks, and the
# tool says in its result when one was used.
FALLBACKS: dict[str, list[str]] = {
    "total_equity": ["stockholders_equity"],
    "total_assets": [],
    "earnings": [],
}


def with_fallback(field: str, has_value) -> tuple[str, str | None]:
    """Resolve `field` to itself or a documented fallback that actually has data.

    Returns (resolved_field, note). The note is surfaced to the agent, because
    silently reading a different field than the one asked for would be exactly
    the kind of quiet substitution this product exists to prevent.
    """
    if has_value(field):
        return field, None
    for alternative in FALLBACKS.get(field, []):
        if has_value(alternative):
            return alternative, (
                f"The API reports no `{field}` for this company; `{alternative}` is the "
                f"comparable field it does report."
            )
    return field, None


def normalise(name: str | None) -> str | None:
    """Resolve a metric name to an API field, or None if it is not one."""
    if not name:
        return None
    key = re.sub(r"[^a-z0-9 ]", " ", str(name).strip().lower())
    key = re.sub(r"\s+", " ", key).strip()
    if key in _ALLOWED:
        return key
    if key in METRIC_ALIASES:
        return METRIC_ALIASES[key]
    # "nii growth" -> "nii" -> net_interest_income
    for alias in sorted(METRIC_ALIASES, key=len, reverse=True):
        if key.startswith(alias + " ") or key.endswith(" " + alias):
            return METRIC_ALIASES[alias]
    return None


def caution_for(requested: str, field: str) -> str | None:
    """Warn when a ratio was resolved to a proxy field.

    Returns None when the requested name and the resolved field mean the same
    thing. The warning is part of the tool result, not a log line, so it reaches
    the agent and the reader.
    """
    text = (requested or "").lower()
    if field == "net_interest_income" and re.search(r"\b(nim|net interest margin|margin)\b", text):
        return ("NIM is a margin ratio; the API reports net interest income. The two can move "
                "in opposite directions when the balance sheet grows, so treat this as a proxy.")
    if field == "provision" and re.search(r"\b(npl|npf|non performing)\b", text):
        return ("The API does not expose NPL/NPF levels. Provision and allowance_for_loans are "
                "the closest reported figures; the ratio itself cannot be verified from here.")
    if field == "total_equity" and re.search(r"\b(car|capital adequacy)\b", text):
        return ("The API does not expose CAR. Equity is reported, but CAR is equity against "
                "risk-weighted assets, which is not available — treat this as a proxy.")
    return None


def detect_metric(text: str) -> str | None:
    """Find the first known metric mentioned in a free-text claim."""
    low = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())
    low = re.sub(r"\s+", " ", low)
    best: tuple[int, str] | None = None
    for alias, field in METRIC_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", low):
            if best is None or len(alias) > best[0]:
                best = (len(alias), field)
    return best[1] if best else None


def pct_change(new: float, old: float) -> float | None:
    if not old:
        return None
    return (new - old) / abs(old)


def compare(value: float | None, comparator: str | None, threshold: float | None) -> bool | None:
    """Evaluate a claim's arithmetic. None means "the data cannot say"."""
    if value is None or threshold is None:
        return None
    op = (comparator or ">=").strip()
    if op in (">", "gt", "above", "lebih dari"):
        return value > threshold
    if op in (">=", "gte", "at least", "minimal", "sekurangnya"):
        return value >= threshold
    if op in ("<", "lt", "below", "kurang dari"):
        return value < threshold
    if op in ("<=", "lte", "at most", "maksimal"):
        return value <= threshold
    return None


def trend(series: list[float], direction: str) -> bool | None:
    """Does a series move in the claimed direction over its most recent steps?

    Tested on the last three observations so a single noisy quarter cannot
    decide a thesis on its own.
    """
    clean = [v for v in series if isinstance(v, (int, float))]
    if len(clean) < 2:
        return None
    window = clean[-3:] if len(clean) >= 3 else clean
    steps = [b - a for a, b in zip(window, window[1:])]
    if not steps:
        return None
    if direction in ("up", "naik", "increase", "grow", "growth", "meningkat"):
        return all(s > 0 for s in steps)
    if direction in ("down", "turun", "decrease", "fall", "decline", "menurun"):
        return all(s < 0 for s in steps)
    if direction in ("flat", "stable", "datar", "stabil"):
        base = window[0]
        if not base:
            return None
        return all(abs((v - base) / base) < 0.02 for v in window)
    return None


def describe(value: float | None, currency: bool = True) -> str:
    """Human-scale formatting for evidence rows (IDR trillions / percentages)."""
    if value is None:
        return "n/a"
    if not currency:
        return f"{value:,.2f}"
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if magnitude >= 1e12:
        return f"{sign}Rp{magnitude / 1e12:,.2f}T"
    if magnitude >= 1e9:
        return f"{sign}Rp{magnitude / 1e9:,.1f}M"
    if magnitude >= 1e6:
        return f"{sign}Rp{magnitude / 1e6:,.0f}jt"
    return f"{sign}Rp{magnitude:,.0f}"


def direction_from_delta(delta: float | None) -> str:
    if delta is None:
        return "unknown"
    if delta > 0.005:
        return "up"
    if delta < -0.005:
        return "down"
    return "flat"


# How far a metric may move in one quarter before the series is treated as
# inconsistent rather than as news. Real restatements look like this: BMRI's
# reported gross loans went from Rp1,850T to Rp1,568T in a single quarter, which
# is a definitional break, not a bank shrinking 15% in three months. A year-on-year
# comparison that spans such a break is meaningless, and reporting it as "loans
# fell 1.5%" would be exactly the quiet error this product exists to prevent.
#
# The bands are asymmetric on purpose. A loan book can genuinely grow quickly; it
# cannot genuinely shrink quickly. A 15% quarterly *drop* in gross loans is a
# red flag under any reading, while 15% growth is merely brisk.
#
#   (max quarterly growth, max quarterly drop)
DISCONTINUITY_BANDS: dict[str, tuple[float, float]] = {
    # stocks — balance-sheet lines: fast growth is possible, fast shrinkage is not
    "gross_loan": (0.20, 0.08), "net_loan": (0.20, 0.08),
    "total_deposit": (0.20, 0.08), "total_assets": (0.18, 0.08),
    "total_equity": (0.25, 0.12), "stockholders_equity": (0.25, 0.12),
    "allowance_for_loans": (0.35, 0.20), "total_liabilities": (0.25, 0.10),
    "total_debt": (0.35, 0.25), "non_loan_assets": (0.30, 0.15),
    # flows — genuinely volatile, but still bounded
    "revenue": (0.60, 0.45), "earnings": (0.70, 0.60),
    "net_interest_income": (0.35, 0.20), "interest_income": (0.40, 0.25),
    "interest_expense": (0.60, 0.50), "non_interest_income": (0.70, 0.60),
    "operating_expense": (0.45, 0.35), "provision": (1.20, 0.90),
    "ebit": (0.70, 0.60), "ebitda": (0.70, 0.60),
    "operating_cash_flow": (1.50, 1.50), "free_cash_flow": (1.50, 1.50),
    "net_cash_flow": (1.50, 1.50), "investing_cash_flow": (1.50, 1.50),
    "financing_cash_flow": (1.50, 1.50),
    # commodities
    "production_volume": (3.00, 1.00),
}
DEFAULT_BAND: tuple[float, float] = (1.00, 0.60)


def band_for(metric: str) -> tuple[float, float]:
    return DISCONTINUITY_BANDS.get(metric, DEFAULT_BAND)


def break_index(series: list[dict[str, Any]], metric: str) -> tuple[int, float] | None:
    """First quarter-on-quarter move beyond the metric's band, and how big it was.

    `series` is oldest-first. The returned index is the *later* observation, so a
    break at index 6 means the value at 6 and everything after it may be measured
    on a different basis from what came before.
    """
    growth_band, drop_band = band_for(metric)
    for i in range(1, len(series)):
        earlier = series[i - 1]["value"]
        later = series[i]["value"]
        if not earlier:
            continue
        change = (later - earlier) / abs(earlier)
        if change > growth_band or change < -drop_band:
            return i, change
    return None


def series_of(rows: list[dict[str, Any]], metric: str) -> list[dict[str, Any]]:
    """One metric across rows, oldest first, non-numeric gaps dropped."""
    out: list[dict[str, Any]] = []
    for row in rows or []:
        value = row.get(metric)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append({"date": row.get("date"), "value": float(value)})
    out.sort(key=lambda r: str(r.get("date") or ""))
    return out
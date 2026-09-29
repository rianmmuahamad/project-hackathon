"""Turning a sentence into claims a machine can check.

A thesis is written the way people actually talk — *"beli BBRI karena NIM naik
dan kredit tumbuh dua digit"* — and that sentence is useless to a program until
it becomes claims with a metric, a direction and a cadence.

Two paths, same output shape:

* **model-assisted** (`decompose`) — the engine proposes the split;
* **heuristic** (`decompose_offline`) — sentence and conjunction boundaries plus
  the metric vocabulary, used when no engine is available.

Both are allowed to fail, and the failures are surfaced: a fragment with no
resolvable metric lands in `unresolved`, which the product displays as "cannot
be verified" instead of quietly dropping it. A thesis that is half-unverifiable
is a finding, not a bug.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import metrics
from .engines import Engine, EngineUnavailable
from .jsonx import extract_json as _extract_json

CADENCES = ("quarterly", "price", "flow", "insider", "news", "corporate_action", "valuation",
            "commodity_price", "production")
DIRECTIONS = ("up", "down", "flat", "none")

KNOWN_METRICS = sorted(set(metrics.METRIC_ALIASES.values()))
EQUITY_METRICS = KNOWN_METRICS
COMMODITY_METRICS = ["commodity_price", "production_volume"]


def known_metrics_for(subject_type: str) -> list[str]:
    return COMMODITY_METRICS if subject_type == "commodity" else EQUITY_METRICS

# A claim can be checkable without being a single API field. Valuation is the
# case that matters: "still cheap against the big banks" needs a peer comparison,
# not one metric. Such claims are kept and routed to the agent with
# `metric: null` and the `valuation` cadence — dropping them as "unresolved"
# would delete a legitimate analytical question from the product.
VALUATION_RE = re.compile(
    r"\b(valuasi|valuation|murah|mahal|cheap|expensive|undervalued|overvalued|"
    r"pe\b|pb\b|p/e|p/b|price[- ]to[- ](?:book|earnings)|diskon|discount)\b",
    re.IGNORECASE,
)

SPLIT_RE = re.compile(
    r"\s*(?:\bdan\b|\bserta\b|\bjuga\b|\band\b|\bplus\b|;|•|\n|,(?![^()]*\)))\s*",
    re.IGNORECASE,
)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

# Words that carry a thesis' intent but no metric: keeping them out of the claim
# list is correct, and they are reported rather than silently dropped.
PREAMBLE_RE = re.compile(
    r"^\s*(beli|jual|buy|sell|hold|tahan|watch|pantau|saya|aku|i|the thesis is|"
    r"tesis(nya)?|reason|karena|because|supaya|so that)\b[\s:,-]*",
    re.IGNORECASE,
)


def decompose_offline(text: str, *, subject_type: str = "equity") -> dict[str, Any]:
    """Split on sentence and conjunction boundaries, keep what has a metric."""
    claims: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for sentence in SENTENCE_RE.split(text or ""):
        for fragment in SPLIT_RE.split(sentence):
            fragment = (fragment or "").strip(" -–—.:;")
            if len(fragment) < 3:
                continue
            core = PREAMBLE_RE.sub("", fragment).strip()
            field = metrics.detect_metric(core)
            if field is None:
                if VALUATION_RE.search(core):
                    claims.append(_shape(core, None, cadence="valuation"))
                    continue
                unresolved.append({"text": fragment,
                                   "reason": "no metric in this fragment can be resolved"})
                continue
            claims.append(_shape(core, field))

    return {
        "mode": "offline",
        "claims": claims,
        "unresolved": unresolved,
    }


GROWTH_RE = re.compile(
    r"\b(naik|tumbuh|meningkat|bertumbuh|up|rise|rising|grow|growth|higher|expand|"
    r"turun|menurun|decline|lower|shrink|drop|fall)\b",
    re.IGNORECASE,
)


def _shape(text: str, field: str | None, direction: str | None = None,
           cadence: str | None = None) -> dict[str, Any]:
    """Fill in direction/threshold/cadence from the wording, without inventing."""
    low = text.lower()
    if direction is None:
        if re.search(r"\b(naik|tumbuh|meningkat|up|rise|rising|grow|growth|higher|expand)\b", low):
            direction = "up"
        elif re.search(r"\b(turun|menurun|melemah|down|fall|decline|lower|shrink|drop)\b", low):
            direction = "down"
        elif re.search(r"\b(stabil|datar|flat|stable|unchanged)\b", low):
            direction = "flat"
        else:
            direction = "none"

    number = None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(%|persen|percent|x\b)?", low)
    if match:
        try:
            number = float(match.group(1).replace(",", "."))
        except ValueError:
            number = None
        if number is not None and match.group(2) in ("%", "persen", "percent"):
            number = number / 100

    # "kredit tumbuh minimal 10%" is a statement about the *growth rate*, not
    # about the loan book's size. Testing 1.58e12 >= 0.1 would pass for any
    # company ever, so the target is recorded and the comparison respects it.
    threshold_target = "growth" if (number is not None and GROWTH_RE.search(low)) else "level"

    if cadence is None:
        if field == "commodity_price":
            cadence = "commodity_price"
        elif field == "production_volume":
            cadence = "production"
        elif VALUATION_RE.search(low):
            cadence = "valuation"
        elif re.search(r"\b(asing|foreign flow|broker|akumulasi|accumulat|net buy)\b", low):
            cadence = "flow"
        elif re.search(r"\b(insider|orang dalam|filing|direksi|komisaris)\b", low):
            cadence = "insider"
        elif re.search(r"\b(harga|price|saham|stock|naik dari|turun ke)\b", low):
            cadence = "price"
        elif re.search(r"\b(dividen|dividend|rights|stock split|aksi korporasi)\b", low):
            cadence = "corporate_action"
        else:
            cadence = "quarterly"

    return {
        "text": text.strip(),
        "metric": field,
        "direction": direction,
        "cadence": cadence,
        "threshold": number,
        "threshold_target": threshold_target,
        "comparator": ">=" if direction == "up" and number is not None else None,
        "note": ("Settled by a peer comparison rather than one reported field — see sector_context."
                 if cadence == "valuation" else None),
    }


DECOMPOSE_SYSTEM = """You turn an investment thesis written in plain language into claims that a program can check.

Rules:
- Return 1 to 6 claims. Split compound sentences: one claim per independently checkable idea.
- Every claim MUST have a `metric` from the allowed list, EXCEPT a relative judgement such as valuation ("murah dibanding bank lain", "cheap versus peers"): for those set `metric` to null and `cadence` to "valuation". Anything else you cannot express with an allowed metric goes in `unresolved` — never invent a metric.
- `direction` is what the thesis asserts about the metric: up, down, flat, or none (when the thesis only mentions it).
- If the thesis states a number ("tumbuh dua digit" = 10%, "di atas 5%"), put it in `threshold`. "dua digit" means 0.10. Set `threshold_target` to "growth" when the number describes a growth rate ("kredit tumbuh 10%") and "level" when it describes the value itself ("CAR di atas 20"). Getting this wrong makes the claim untestable.
- `cadence` is the data family that would settle it: quarterly, price, flow, insider, news, corporate_action, valuation.
- For a commodity subject the only allowed metrics are commodity_price (the monthly
  price series) and production_volume (the annual production series). Map "harga naik
  terus" to commodity_price with cadence "commodity_price", and "produksi naik" to
  production_volume with cadence "production".
- Ignore intent words (beli/jual/hold) — they are not claims. Record them in `unresolved` with the reason.
- Reply with ONLY a JSON object, no prose, no code fence:
  {"claims": [{"text": "...", "metric": "...", "direction": "up", "cadence": "quarterly", "threshold": null, "comparator": null}],
   "unresolved": [{"text": "...", "reason": "..."}]}"""


def decompose(text: str, engine: Engine | None = None, *,
              subject_type: str = "equity") -> dict[str, Any]:
    """Model-assisted decomposition, falling back to the heuristic on any failure."""
    if engine is None:
        return decompose_offline(text, subject_type=subject_type)

    allowed = known_metrics_for(subject_type)
    system = DECOMPOSE_SYSTEM + "\n\nAllowed metrics: " + ", ".join(allowed)
    messages = [{"role": "user", "content": f"Thesis:\n{text}"}]
    try:
        turn = engine.reply(system, messages, tools=[])
    except EngineUnavailable as err:
        out = decompose_offline(text, subject_type=subject_type)
        out["engine_error"] = str(err)
        return out

    parsed = _extract_json(turn.text)
    if not parsed or not isinstance(parsed.get("claims"), list):
        out = decompose_offline(text, subject_type=subject_type)
        out["engine_error"] = "engine did not return usable JSON; used the offline splitter"
        out["raw_reply"] = turn.text[:800]
        return out

    claims: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for raw in parsed["claims"]:
        if not isinstance(raw, dict):
            continue
        field = metrics.normalise(raw.get("metric"))
        body = str(raw.get("text") or "").strip()
        direction = str(raw.get("direction") or "").lower()
        cadence = str(raw.get("cadence") or "").lower()

        if not field:
            # A model that names no metric is usually describing a relative
            # judgement (valuation, share) rather than a number. Keep it, routed
            # to the agent, instead of discarding the user's own reasoning.
            if cadence == "valuation" or VALUATION_RE.search(body):
                claim = _shape(body or str(raw), None, cadence="valuation")
                claims.append(claim)
                continue
            unresolved.append({"text": body or str(raw), "reason": "metric could not be resolved"})
            continue

        claim = _shape(body or str(raw.get("metric")), field,
                       direction if direction in DIRECTIONS else None,
                       cadence if cadence in CADENCES else None)
        threshold = raw.get("threshold")
        if isinstance(threshold, (int, float)):
            claim["threshold"] = float(threshold)
            claim["comparator"] = raw.get("comparator") or (">=" if claim["direction"] == "up" else None)
            target = str(raw.get("threshold_target") or "").lower()
            if target in ("growth", "level"):
                claim["threshold_target"] = target
        claims.append(claim)

    for raw in parsed.get("unresolved") or []:
        if isinstance(raw, dict) and raw.get("text"):
            unresolved.append({"text": str(raw["text"])[:300],
                               "reason": str(raw.get("reason") or "not checkable with available data")})
        elif isinstance(raw, str) and raw.strip():
            unresolved.append({"text": raw.strip()[:300],
                               "reason": "not checkable with available data"})

    if not claims:
        fallback = decompose_offline(text, subject_type=subject_type)
        fallback["engine_error"] = "engine returned no usable claims; used the offline splitter"
        return fallback

    return {"mode": "model", "claims": claims, "unresolved": unresolved,
            "raw_reply": None}


def capture_baseline(claim: dict[str, Any], sectors, quarters: int = 6) -> dict[str, Any]:
    """Record where the metric stood when the thesis was written.

    Without this, "kredit tumbuh dua digit" has no anchor and the first check
    cannot say whether anything changed.
    """
    field = metrics.normalise(claim.get("metric"))
    if not field or claim.get("cadence") != "quarterly":
        return claim
    try:
        rows = sectors.quarterly(claim.get("symbol") or "", n_quarters=quarters) \
            if claim.get("symbol") else []
    except Exception:  # noqa: BLE001 — a missing baseline must not abort the thesis
        rows = []
    series = metrics.series_of(rows, field)
    if series:
        claim["baseline_value"] = series[-1]["value"]
        claim["baseline_date"] = series[-1]["date"]
    return claim
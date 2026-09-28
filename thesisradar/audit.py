"""The audit loop — where a thesis is measured, then argued.

The split of responsibility is the whole design:

* **Code measures.** Latest value, year-on-year change, baseline drift and the
  threshold test are computed here, from cached API rows. A number in a verdict
  is therefore never something a model typed.
* **The agent interprets.** Context (sector, market, corporate actions, insider
  behaviour), the reason a claim weakened, what changed since the last check and
  how confident the conclusion deserves to be — that is the model's job, and the
  tools it chooses are recorded.

When no engine is available the measurements and the evidence trail are still
produced, the verdict degrades to `needs_review`, and the reason says so. The
product must not invent an opinion it cannot justify.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import metrics, tools
from .config import settings
from .engines import Engine, EngineUnavailable
from .jsonx import extract_json
from .jev import JevUnavailable, jev_from_settings
from .sectors import Sectors, SectorsError, bare, last_available_day
from .store import Store

MAX_TOOL_ROUNDS = 3

# How many quarters are pulled per symbol. Twelve covers a year-on-year
# comparison, the quarterly shape around it, and enough history to notice that a
# reported series has been restated rather than having moved.
QUARTER_WINDOW = 12

# Cadences code cannot settle from a single reported field. Valuation claims are
# the case that matters: "cheap versus peers" needs the agent plus guardrails,
# while a claim measured from a quarterly series does not.
_SETTLEABLE_CADENCES = {"quarterly"}

MAX_JEV_CLAIMS = 12           # one question per claim, all in a single call
TOOL_CALLS_WHEN_ASSISTED = 2  # budget for the agent when Jev already decided
CONFIDENCE_CEILING_WHEN_UNGUARDED = 0.6
GUARDRAIL_THRESHOLD = 0.5

# Number-shaped tokens an agent might cite: percentages, basis points, multiples,
# IDR magnitudes, and bare figures. Used to build the guardrail's candidate list.
CITED_NUMBER_RE = re.compile(
    r"(?<![\d.,])"
    r"[+-]?\d+(?:[.,]\d+)?"
    r"(?:\s*(?:%|bps|persen|percent|x|kali|triliun|miliar|juta|ribu|T\b|M\b|B\b))?",
    re.IGNORECASE,
)

# "Rp2,4 triliun" is how Indonesian writes currency with no space after the
# prefix, and the lookbehind above correctly refuses a digit glued to a word —
# so the prefix is removed first rather than special-cased inside the pattern.
CURRENCY_PREFIX_RE = re.compile(r"\bRp\.?\s?", re.IGNORECASE)

# One claim's state, in the product's vocabulary.
SUPPORTED = "supported"
WEAKENING = "weakening"
BROKEN = "broken"
UNKNOWN = "unknown"

STATE_TO_STATUS = {
    SUPPORTED: "intact",
    WEAKENING: "weakened",
    BROKEN: "broken",
    UNKNOWN: "needs_review",
}


@dataclass
class Measurement:
    claim_id: str
    ordinal: int
    text: str
    metric: str | None
    state: str
    observed_value: float | None = None
    observed_date: str | None = None
    delta: float | None = None
    baseline_delta: float | None = None
    rationale: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_row(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "ordinal": self.ordinal,
            "text": self.text,
            "state": self.state,
            "observed_value": self.observed_value,
            "observed_date": self.observed_date,
            "delta": None if self.delta is None else f"{self.delta * 100:+.1f}% YoY",
            "rationale": self.rationale,
        }


# --------------------------------------------------------------------------
# watermark
# --------------------------------------------------------------------------
def compute_watermark(thesis: dict[str, Any], sectors: Sectors, days: int = 45,
                     quarterly_rows: list[dict[str, Any]] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """The date the agent should look forward from, and the evidence for it.

    A thesis is only interesting *since the last time it was checked*. Using the
    previous check's date means a re-check costs nothing and reads nothing twice.
    """
    symbol = thesis["symbol"]
    previous = (thesis.get("watermark") or "").strip()
    since = previous or (date.today() - timedelta(days=days)).isoformat()
    evidence: list[dict[str, Any]] = []

    rows = quarterly_rows
    if rows is None:
        try:
            rows = sectors.quarterly(symbol, n_quarters=QUARTER_WINDOW)
        except SectorsError:
            rows = []
    if rows:
        latest = max((r.get("date") or "") for r in rows)
        evidence.append({
            "symbol": symbol, "metric": "latest_quarterly_report", "value": latest,
            "as_of": latest, "endpoint": f"/v2/financials/quarterly/{symbol}/",
            "params": {"n_quarters": QUARTER_WINDOW}, "note": "newest quarter on file",
        })

    try:
        prices = sectors.daily(symbol, start=since, end=last_available_day())
    except SectorsError:
        prices = []
    traded = [r for r in prices if (r.get("volume") or 0) > 0]
    if traded:
        evidence.append({
            "symbol": symbol, "metric": "last_traded_session",
            "value": traded[-1].get("date"), "as_of": traded[-1].get("date"),
            "endpoint": f"/v2/daily/{symbol}/", "params": {"start": since},
            "note": f"{len(prices) - len(traded)} session(s) in the window had no trading",
        })

    watermark = last_available_day()
    return watermark, evidence


# --------------------------------------------------------------------------
# deterministic measurement
# --------------------------------------------------------------------------
def measure(thesis: dict[str, Any], sectors: Sectors,
            quarterly_rows: list[dict[str, Any]] | None = None) -> tuple[list[Measurement], list[dict[str, Any]]]:
    """Compute each claim's state from reported numbers. No model involved."""
    symbol = thesis["symbol"]
    measurements: list[Measurement] = []
    evidence: list[dict[str, Any]] = []

    rows = quarterly_rows
    quarterly_error: str | None = None
    if rows is None:
        try:
            rows = sectors.quarterly(symbol, n_quarters=QUARTER_WINDOW)
        except SectorsError as err:
            rows = []
            quarterly_error = str(err)

    for claim in thesis.get("claims") or []:
        field_name = metrics.normalise(claim.get("metric"))
        ordinal = int(claim.get("ordinal") or 0)
        base = Measurement(claim_id=claim["id"], ordinal=ordinal, text=claim.get("text") or "",
                           metric=field_name, state=UNKNOWN)

        if not field_name or claim.get("cadence") not in ("quarterly", "valuation"):
            base.rationale = ("Not measured here: this claim is not a quarterly report metric, "
                              "so it has to be settled with tools and judgement.")
            measurements.append(base)
            continue

        if claim.get("cadence") == "valuation":
            base.rationale = ("Relative valuation cannot be read from one field; the agent must "
                              "compare this company against its peers with sector_context.")
            measurements.append(base)
            continue

        if rows is None:
            base.rationale = "Quarterly financials could not be fetched for this check."
            measurements.append(base)
            continue

        series = metrics.series_of(rows, field_name)
        if not series:
            resolved, _note = metrics.with_fallback(
                field_name, lambda name: bool(metrics.series_of(rows, name)))
            if resolved != field_name:
                field_name = resolved
                series = metrics.series_of(rows, field_name)

        if not series:
            base.rationale = f"The API reports no {field_name} for {symbol}."
            measurements.append(base)
            continue

        latest = series[-1]
        base.observed_value = latest["value"]
        base.observed_date = latest["date"]

        yoy_index = len(series) - 5 if len(series) >= 5 else 0
        yoy_point = series[yoy_index] if len(series) > 1 else None
        if yoy_point and yoy_point.get("value"):
            base.delta = metrics.pct_change(latest["value"], yoy_point["value"])

        # A year-on-year figure that spans a restatement is not a trend, it is a
        # comparison of two different definitions. Refuse it out loud.
        found = metrics.break_index(series, field_name)
        broken_at, jump = found if found else (None, 0.0)
        spans_break = broken_at is not None and broken_at > yoy_index

        if spans_break and broken_at is not None:
            earlier = series[broken_at - 1]
            growth_band, drop_band = metrics.band_for(field_name)
            base.delta = None
            base.state = UNKNOWN
            base.rationale = (
                f"The reported {field_name} series is inconsistent: it moves "
                f"{jump * 100:+.1f}% between {earlier['date']} and "
                f"{series[broken_at]['date']}, which is a restatement or a change of definition "
                f"rather than trading. A year-on-year comparison would span that break, so this "
                f"claim cannot be measured from the series as published."
            )
            base.evidence.append({
                "symbol": symbol, "metric": f"{field_name} discontinuity",
                "value": (f"{metrics.describe(series[broken_at]['value'])} from "
                          f"{metrics.describe(earlier['value'])}"),
                "as_of": series[broken_at]["date"],
                "endpoint": f"/v2/financials/quarterly/{symbol}/",
                "params": {"n_quarters": QUARTER_WINDOW},
                "note": (f"{jump * 100:+.1f}% in one quarter, outside the "
                         f"+{growth_band:.0%}/-{drop_band:.0%} band for this metric — treated as "
                         f"a definitional break"),
            })
            measurements.append(base)
            evidence.extend(base.evidence)
            continue
        baseline = claim.get("baseline_value")
        if isinstance(baseline, (int, float)) and baseline:
            base.baseline_delta = metrics.pct_change(latest["value"], float(baseline))
        else:
            base.baseline_delta = None

        values = [p["value"] for p in series]
        trending = metrics.trend(values, claim.get("direction") or "none")

        # The comparator means different things depending on what the threshold
        # is about. "Kredit tumbuh minimal 10%" is about the growth rate; a claim
        # phrased as a level is about the value. Comparing a Rp1.5 quadrillion
        # balance against 0.1 would pass for any company on earth.
        if claim.get("threshold") is None:
            threshold_ok = None
        elif (claim.get("threshold_target") or "level") == "growth":
            threshold_ok = metrics.compare(base.delta, claim.get("comparator"),
                                           claim.get("threshold"))
        else:
            threshold_ok = metrics.compare(latest["value"], claim.get("comparator"),
                                           claim.get("threshold"))

        base.state, base.rationale = _judge_claim(claim, base, trending, threshold_ok, series)
        base.evidence.append({
            "symbol": symbol, "metric": field_name,
            "value": metrics.describe(latest["value"]), "as_of": latest["date"],
            "endpoint": f"/v2/financials/quarterly/{symbol}/",
            "params": {"n_quarters": 12},
            "note": f"latest reported; {_delta_text(base.delta)} YoY",
        })
        if claim.get("baseline_value") is not None:
            base.evidence.append({
                "symbol": symbol, "metric": f"{field_name} at thesis time",
                "value": metrics.describe(claim.get("baseline_value")),
                "as_of": claim.get("baseline_date"),
                "endpoint": f"/v2/financials/quarterly/{symbol}/",
                "params": {"n_quarters": 12},
                "note": "recorded when the thesis was written",
            })
        evidence.extend(base.evidence)
        measurements.append(base)

    return measurements, evidence


def _delta_text(delta: float | None) -> str:
    if delta is None:
        return "no comparable prior figure"
    return f"{delta * 100:+.1f}%"


def _judge_claim(claim: dict[str, Any], base: Measurement, trending: bool | None,
                 threshold_ok: bool | None, series: list[dict[str, Any]]) -> tuple[str, str]:
    """Turn arithmetic into a state, and say exactly which arithmetic decided it."""
    direction = (claim.get("direction") or "none").lower()
    parts: list[str] = []

    if base.delta is not None:
        parts.append(f"{claim.get('metric') or base.metric} is {_delta_text(base.delta)} year-on-year")

    if threshold_ok is False:
        target = "growth" if (claim.get("threshold_target") or "level") == "growth" else "level"
        return BROKEN, "; ".join(parts + [
            f"the thesis set a {claim.get('comparator') or '>='} threshold of "
            f"{claim.get('threshold')} on {target} and the reported figures do not clear it"])

    if direction in ("none", ""):
        return UNKNOWN, "; ".join(parts + ["the thesis asserts no direction, so nothing is "
                                           "falsifiable from this metric alone"])

    if trending is True:
        return SUPPORTED, "; ".join(parts + [
            f"and the last movements are all {direction}, so the claim holds"])

    if trending is False:
        steps = [round((b - a) / abs(a) * 100, 2)
                 for a, b in zip([p["value"] for p in series], [p["value"] for p in series][1:]) if a]
        recent = steps[-3:] if steps else []
        return WEAKENING, "; ".join(parts + [
            f"but the recent movements ({', '.join(f'{s:+.1f}%' for s in recent) or 'n/a'}) "
            f"are not consistently {direction}, so the claim no longer holds cleanly"])

    return UNKNOWN, "; ".join(parts + ["not enough history to test the direction"])


def _measurement_shortfall(m: Measurement) -> str | None:
    """Why a three-state measurement cannot support a decision, or None.

    `None` means the arithmetic already decided this claim, so nobody — not the
    agent, and not Jev — needs to be asked about it.
    """
    if m.state in (SUPPORTED, WEAKENING, BROKEN):
        return None
    if m.metric is None:
        return "no single reported metric represents what the thesis claims"
    if m.observed_date is None:
        return f"the API reports no {m.metric} for this company"
    return None


def _cadence_of(measurement: Measurement, thesis: dict[str, Any]) -> str | None:
    for claim in thesis.get("claims") or []:
        if claim.get("id") == measurement.claim_id:
            return claim.get("cadence")
    return None


def _represented_fields(measurements: list[Measurement],
                        evidence: list[dict[str, Any]]) -> list[str]:
    """The literal metric names and observed values an agent may cite.

    The guardrail is only as good as this list: anything missing here is a false
    positive waiting for an honest sentence. So it deliberately over-includes —
    the field name, every analyst alias for that field, and the formatted value.
    """
    fields: set[str] = set()
    for measurement in measurements:
        if measurement.metric:
            fields.add(measurement.metric)
            for alias, target in metrics.METRIC_ALIASES.items():
                if target == measurement.metric:
                    fields.add(alias)
                    fields.add(target)
        if measurement.observed_value is not None:
            fields.add(metrics.describe(measurement.observed_value))
    for row in evidence:
        if row.get("metric"):
            fields.add(str(row["metric"]))
        if row.get("value") is not None:
            fields.add(str(row["value"]))
    return sorted(fields)


# --------------------------------------------------------------------------
# Jev — the decision layer
# --------------------------------------------------------------------------
def _claim_evidence(measurement: Measurement) -> str:
    """One claim's own numbers, as a sentence for that claim's question only.

    Kept explicit and short: the metric, its value, the change, the arithmetic's
    own verdict and the reason for it. Nothing from the other claims.
    """
    bits: list[str] = []
    if measurement.metric:
        bits.append(f"{measurement.metric}")
    if measurement.observed_value is not None:
        bits.append(f"= {metrics.describe(measurement.observed_value)}")
    if measurement.observed_date:
        bits.append(f"on {measurement.observed_date}")
    if measurement.delta is not None:
        bits.append(f"({measurement.delta * 100:+.1f}% YoY)")
    arithmetic = measurement.state
    if measurement.rationale:
        bits.append(f". {measurement.rationale}. Arithmetic verdict: {arithmetic}.")
    else:
        bits.append(f". Arithmetic verdict: {arithmetic}.")
    return " ".join(bits)


def _jev_state(thesis: dict[str, Any]) -> str:
    """The shared, non-per-claim state Jev is asked against.

    Deliberately excludes the per-claim numbers: those belong to each claim's own
    question. Handing Jev one state containing every claim is what produced the
    generalisation this replaced.
    """
    lines = [
        f"STOCK: {thesis['symbol']}"
        + (f" ({thesis['company_name']})" if thesis.get("company_name") else ""),
        f"THESIS AS WRITTEN: {thesis['statement']}",
        f"HORIZON: {thesis.get('horizon') or 'unspecified'}",
        f"STATUS BEFORE THIS CHECK: {thesis.get('status') or 'unknown'}",
    ]
    return "\n".join(lines)


def _decide_with_jev(thesis: dict[str, Any], measurements: list[Measurement],
                     brief: str, jev: Any, emit=None,
                     transcript: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Ask Jev for a state on every claim the arithmetic could not settle.

    Returns {claim_id: {"state": ..., "rationale": ..., "confidence": ...,
    "probabilities": ...}}, plus "__decidable__" naming the one extra fact that
    would change the answer. An empty dict means nothing was sent or the gateway
    failed, and the caller keeps the agent as decider.
    """
    if jev is None:
        return {}

    settleable = [m for m in measurements
                  if _measurement_shortfall(m) is None
                  and _cadence_of(m, thesis) in _SETTLEABLE_CADENCES][:MAX_JEV_CLAIMS]
    if not settleable:
        return {}

    questions: dict[str, dict[str, Any]] = {}
    for index, measurement in enumerate(settleable):
        # Each question carries its own claim's numbers and says so, because a
        # single shared state made Jev generalise: with three claims presented
        # together, one claim's negative context dragged the other two down, and
        # a claim whose loans grew 16.4% with every quarter rising came back
        # "weakening" at 0.95. TypeSafe's own guidance is that each question
        # should be narrow and self-contained; a shared state is exactly what
        # they warn against.
        evidence = _claim_evidence(measurement)
        questions[f"claim_{index}"] = {
            "type": "choice",
            "instructions": (f"Judge ONLY this claim, on only the evidence stated for it: "
                             f"\"{measurement.text}\". Its evidence: {evidence}"),
            "criteria": {
                "supported": "the claim clearly holds on its own evidence",
                "weakening": ("the claim is not contradicted, but its trend or the shared "
                              "context no longer supports it cleanly"),
                "broken": "the claim's own evidence contradicts it",
                "unknown": "the evidence cannot settle this claim either way",
            },
        }
    # An extra call here is not free: it decides whether the agent loop runs at
    # all, and therefore whether a check takes one second or three minutes.
    questions["decidable"] = {
        "type": "choice",
        "instructions": ("Which single additional fact would most change these judgements, and can "
                         "it be obtained from a market-data API at all?"),
        "criteria": {
            "none": "no further data would change the judgements",
            "context:market": "what the whole market did over the same window",
            "context:sector": "what this company's sector and peers did",
            "insider": "whether company insiders have been buying or selling",
            "news": "whether there is dated news that explains the move",
            "corporate_action": ("whether the price move is a split, rights issue or dividend, or "
                                 "the stock was suspended"),
            "external": "the deciding fact is outside market data and no API call can settle it",
        },
    }

    state = _jev_state(thesis) + "\n\nDecide each claim from its own evidence. Answer only from what is given."
    try:
        decision = jev.ask(state, questions)
    except Exception as err:  # noqa: BLE001 — the decision layer is never fatal
        if emit:
            emit("jev_error", {"detail": str(err)[:200]})
        if transcript is not None:
            transcript.append(f"\n_Jev unavailable: {err}_")
        return {}

    out: dict[str, dict[str, Any]] = {}
    for index, measurement in enumerate(settleable):
        answer = decision.answers.get(f"claim_{index}")
        if answer is None:
            continue
        out[measurement.claim_id] = {
            "state": str(answer.value),
            "rationale": (f"Jev decided {answer.value} over this claim's measured evidence "
                          f"(confidence {answer.confidence:.2f})"
                          if answer.confidence is not None
                          else f"Jev decided {answer.value} over this claim's measured evidence"),
            "confidence": answer.confidence,
            "probabilities": dict(answer.probabilities),
        }

    decidable = decision.answers.get("decidable")
    out["__decidable__"] = str(decidable.value) if decidable else None

    if transcript is not None:
        rows = [row for row in decision.rows()]
        transcript.append(
            "\n## Decision (Jev)\n\n"
            f"{len(settleable)} claim question(s) and 1 routing question, answered in "
            f"{decision.seconds:.2f}s by `{decision.model}` "
            f"(input {decision.usage.get('input_tokens', '?')} tokens). "
            "Typed answers, not parsed prose.\n\n```json\n"
            + json.dumps(rows, ensure_ascii=False, indent=2) + "\n```"
        )
    if emit:
        emit("jev", {"claims": len(settleable), "seconds": round(decision.seconds, 2),
                     "model": decision.model, "decidable": out.get("__decidable__")})
    return out


def _cited_numbers(text: str, limit: int = 40) -> list[str]:
    """Every number-looking token in a report, deduped, in order.

    Extracting candidates in code rather than asking the model to notice them is
    what makes the guardrail reliable: the model's remaining job is the easy,
    positively-framed one — pick the number that no evidence supports — instead
    of the unreliable one — search a paragraph for something that is absent.
    Measured: a negated Nul question scored an honest sentence with no numbers at
    all at 0.76 and one citing only evidence at 0.89, so nothing separated.
    """
    out: list[str] = []
    seen: set[str] = set()
    for match in CITED_NUMBER_RE.finditer(CURRENCY_PREFIX_RE.sub("", text or "")):
        token = match.group(0).strip()
        if not any(ch.isdigit() for ch in token) or token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= limit:
            break
    return out


def _check_report(report: str, represented: list[str], sentences: list[str],
                  jev: Any) -> dict[str, Any]:
    """Ask Jev whether the agent's prose cites numbers the evidence does not contain.

    This is the enforcement of a prompt rule that was previously only a wish:
    `SYSTEM` says not to invent figures, and a run still produced "NIM <6%".
    """
    blank: dict[str, Any] = {"flagged": False, "score": None, "unrepresented": [],
                             "checked": []}
    if not report or jev is None or not represented:
        # A guardrail with no anchors cannot tell a fabrication from a legitimate
        # sentence, and a false accusation is worse than no accusation.
        return blank

    candidates = _cited_numbers(report)
    if not candidates:
        # Nothing to check, so nothing to pay for.
        return blank

    questions = {
        "unsupported": {
            "type": "choice",
            "instructions": ("Which one of these numbers taken from the report is not stated "
                             "anywhere in the evidence sentences?"),
            "criteria": dict(
                [("none", "every number in the report is stated in the evidence")]
                + [(candidate, f"the report says {candidate}, which is absent from the evidence")
                   for candidate in candidates]
            ),
        },
    }
    state = ("REPORT TO CHECK:\n" + report[:6000]
             + "\n\nREPRESENTED FIELDS (the only fields the evidence covers):\n"
             + ", ".join(represented[:120])
             + "\n\nEVIDENCE SENTENCES:\n"
             + ("\n".join(sentences[:40])[:4000] or "(none)"))
    try:
        decision = jev.ask(state, questions)
    except Exception as err:  # noqa: BLE001 — a broken guardrail must not block a check
        return {**blank, "candidates": candidates, "error": str(err)[:200]}

    answer = decision.answers.get("unsupported")
    if answer is None or str(answer.value) == "none":
        return {**blank, "checked": candidates}

    confidence = float(answer.confidence) if answer.confidence is not None else None
    flagged = confidence is None or confidence >= GUARDRAIL_THRESHOLD
    return {
        "flagged": flagged,
        "score": confidence,
        "unrepresented": [str(answer.value)] if flagged else [],
        "checked": candidates,
    }


def rollup(measurements: list[Measurement]) -> tuple[str, str]:
    """One status from many claim states, with the reason spelled out."""
    states = [m.state for m in measurements] or [UNKNOWN]
    if BROKEN in states:
        broken = sum(1 for s in states if s == BROKEN)
        return "broken", f"{broken} of {len(states)} claim(s) are broken"
    if WEAKENING in states:
        weak = sum(1 for s in states if s == WEAKENING)
        return "weakened", f"{weak} of {len(states)} claim(s) no longer hold cleanly"
    if all(s == SUPPORTED for s in states):
        return "intact", f"all {len(states)} measured claim(s) hold"
    return "needs_review", "not enough of the thesis could be measured to reach a conclusion"


# --------------------------------------------------------------------------
# the agent
# --------------------------------------------------------------------------
SYSTEM = """You are the analyst behind Thesis Radar. A user has written down why they own a stock, and you are checking whether that reasoning still survives contact with the data.

The claims that are already decided have been decided from measured numbers, and that decision is not yours to revisit. Your one job is context: find out whether the surrounding facts change how those decisions should be read.

- Is the move in the company, or in the whole sector or market? A stock that fell 3% on a day the index fell 3% has told you nothing about that company.
- Is the price action real, or the mechanical effect of a split, rights issue or dividend? Is the stock suspended? A halt pins the last close and manufactures a fake trend.
- Is the money still moving the way the position assumes?
- Does the written story have a dated cause? If the move happened on a day with no news, the story is probably wrong.
- Is a missing number actually missing? If the API does not report what the thesis leans on, say so rather than reasoning around it.

Rules:
- Do NOT restate the decided claims and do NOT dispute them.
- Call `what_changed` first; it is ONE call returning price, foreign flow, insider filings, news and corporate actions.
- Then conclude. You may make one more call only if `what_changed` left the question the routing step named genuinely unanswered.
- `market_context` and `news_search` take NO symbol argument — they are market-wide. Passing one will fail.
- Never introduce a number, ratio or metric that no tool returned. "NIM below 6%" is not allowed.
- If the data cannot settle something, say so. An honest "cannot tell from here" beats a confident guess.

You have two turns. Use the first to call a tool, the second to reply with only the JSON block.

When you have enough — or when you have spent your budget — end your reply with exactly one JSON block and no other text after it. `claim_states` is optional: include it ONLY for a claim you were told could not be measured, and never to overrule a decided one.

{"claim_states": [{"claim_id": "...", "state": "supported|weakening|broken|unknown", "rationale": "..."}],
 "changes": [{"kind": "data|context|risk", "text": "what is different since the last check", "magnitude": "e.g. -8% YoY"}],
 "context": {"sector": "what the sector did", "market": "what the index did", "idiosyncratic": true},
 "confidence": 0.0,
 "summary": "two sentences a human can act on",
 "falsifiers": ["the specific data that would change your mind"],
 "notification": "one line, only if the status changed in a way that matters"}

To call a tool, put this at the very end of your reply instead:

TOOL CALLS:
{"tool": "tool_name", "args": {"symbol": "BBRI"}}

One tool call per reply. After the tool result you will be asked to continue."""


def _thesis_brief(thesis: dict[str, Any], measurements: list[Measurement],
                  watermark: str) -> str:
    lines = [
        f"STOCK: {thesis['symbol']}"
        + (f" ({thesis['company_name']})" if thesis.get("company_name") else ""),
        f"THESIS AS WRITTEN: {thesis['statement']}",
        f"HORIZON: {thesis.get('horizon') or 'unspecified'}",
        f"STATUS BEFORE THIS CHECK: {thesis.get('status') or 'unknown'}"
        + (f" (confidence {thesis['confidence']:.2f})" if thesis.get("confidence") is not None else ""),
        f"WATERMARK: look for what is new since {thesis.get('watermark') or watermark}",
        "",
        "CLAIMS AND THEIR MEASUREMENT (computed from reported data, not by you):",
    ]
    for m in measurements:
        obs = metrics.describe(m.observed_value) if m.observed_value is not None else "n/a"
        delta = "" if m.delta is None else f", {m.delta * 100:+.1f}% YoY"
        lines.append(
            f"  [{m.ordinal}] {m.claim_id} — {m.text}\n"
            f"      metric={m.metric or 'unresolved'} observed={obs}{delta} "
            f"as_of={m.observed_date or 'n/a'} measured_state={m.state}\n"
            f"      why: {m.rationale}"
        )
    unresolved = thesis.get("translation") and json.loads(thesis["translation"] or "{}")
    if isinstance(unresolved, dict):
        for item in unresolved.get("unresolved") or []:
            lines.append(f"  [unresolved] {item.get('text')} — {item.get('reason')}")
    return "\n".join(lines)


def _results_message(step: tools.Tool | None, name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, default=str)
    if len(body) > 12000:
        body = body[:12000] + "… (truncated)"
    return f"TOOL RESULT for {name}:\n{body}\n\nContinue your investigation, or emit the final JSON block."


def run(thesis_id: str, *, engine: Engine, store: Store, sectors: Sectors,
        symbol_override: str | None = None, max_rounds: int = MAX_TOOL_ROUNDS,
        on_event=None, jev: Any = None) -> dict[str, Any]:
    """Measure one thesis, decide it, argue about the context, persist everything.

    Three layers, in order of authority:

    1. **code** measures the reported numbers;
    2. **Jev** decides what those numbers mean for each claim, and guards the
       prose that follows;
    3. **the engine** supplies context prose, and decides only what neither of
       the first two could.

    Passing `jev` injects the decision client (tests use a stub); omitting it
    resolves the configured one, or none when the decision layer is unavailable.
    """
    thesis = store.get_thesis(thesis_id)
    if thesis is None:
        raise ValueError(f"no thesis {thesis_id}")
    if symbol_override:
        thesis["symbol"] = bare(symbol_override)

    emit = on_event or (lambda *a, **k: None)
    engine_meta = engine.identify()
    decider = jev if jev is not None else jev_from_settings()

    # Resolve the watermark before the check row exists, so the row records the
    # date the agent actually looked forward from. Without it the change strip
    # cannot be independently verified from the database.
    try:
        quarterly_rows = sectors.quarterly(thesis["symbol"], n_quarters=QUARTER_WINDOW)
    except SectorsError:
        quarterly_rows = []

    watermark, watermark_evidence = compute_watermark(thesis, sectors,
                                                     quarterly_rows=quarterly_rows)
    run_id = store.start_run("check", symbol=thesis["symbol"], thesis_id=thesis_id,
                            engine=engine_meta.get("engine"))
    check_id = store.create_check(thesis_id, run_id=run_id, since=thesis.get("watermark"),
                                 engine=engine_meta.get("engine"),
                                 model=engine_meta.get("model"))

    transcript: list[str] = []
    steps: list[dict[str, Any]] = []

    try:
        measurements, measurement_evidence = measure(thesis, sectors,
                                                     quarterly_rows=quarterly_rows)
        status, rollup_reason = rollup(measurements)

        emit("measured", {"status": status, "reason": rollup_reason,
                          "claims": [m.to_row() for m in measurements]})

        brief = _thesis_brief(thesis, measurements, watermark)
        transcript.append("## Thesis brief\n\n```\n" + brief + "\n```")

        # The decision comes before the agent runs, and it is what decides
        # whether the agent runs at all. Asking Jev costs about a second; asking
        # the engine costs about a minute per turn.
        jev_states = _decide_with_jev(thesis, measurements, brief, decider,
                                      emit=emit, transcript=transcript)
        decidable = jev_states.pop("__decidable__", None)
        shortfall_ids = {m.claim_id for m in measurements
                         if _measurement_shortfall(m) is not None}
        fully_decided = len(jev_states) == len(measurements)
        needs_agent = (not fully_decided) or (decidable not in (None, "none"))
        loop_rounds = 0 if not needs_agent else min(max_rounds, TOOL_CALLS_WHEN_ASSISTED)
        if not needs_agent:
            transcript.append(
                "\n_The agent loop was skipped: every claim was decided from measured data, and "
                "Jev reports no further available fact that would change those decisions._\n")
            emit("skipped", {"reason": "every claim decided; no further data would change it"})

        # The free read is done for the agent rather than trusted to it: it costs
        # no credits, it is always relevant, and making it conditional would let a
        # paid call happen before the product's own memory was consulted.
        try:
            prior = tools.execute("evidence_ledger", {"symbol": thesis["symbol"]}, sectors, store)
            ledger_row = {"name": "evidence_ledger", "args": {"symbol": thesis["symbol"]},
                          "credits": prior.get("credits", 0), "result": prior.get("result")}
            steps.append(ledger_row)
            transcript.append("\n## Free read: `evidence_ledger`\n\n```json\n"
                              + json.dumps(prior.get("result"), ensure_ascii=False,
                                           default=str)[:4000] + "\n```")
        except Exception as err:  # noqa: BLE001 — memory is helpful, never required
            transcript.append(f"\n_evidence_ledger unavailable: {err}_")

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": brief + "\n\nStart investigating."},
        ]
        if needs_agent and shortfall_ids:
            messages[0]["content"] += (
                "\n\nThe following claim(s) could NOT be measured and are yours to settle with "
                "tools and judgement: "
                + ", ".join(shortfall_ids)
                + ". Every other claim is already decided — do not restate or dispute it."
            )

        # A repeated identical call is pure waste: the answer is already in the
        # transcript. The loop recognises it, refuses to spend the credit, and
        # tells the model to move on instead of silently rerunning it.
        seen_calls: set[tuple[str, str]] = {("evidence_ledger", json.dumps({"symbol": thesis["symbol"]}, sort_keys=True))}

        verdict: dict[str, Any] | None = None
        engine_error: str | None = None
        last_text = ""
        native = getattr(engine, "protocol", "prompt") == "native"

        for round_no in range(loop_rounds):
            remaining = sectors.budget.remaining
            if remaining is not None and remaining <= 0:
                transcript.append(f"\n_Credit budget exhausted after {round_no} round(s)._")
                break
            emit("thinking", {"round": round_no + 1})
            try:
                turn = engine.reply(SYSTEM, messages, tools.schemas())
            except EngineUnavailable as err:
                engine_error = str(err)
                transcript.append(f"\n_Engine unavailable: {err}_")
                break

            parsed = extract_json(turn.text)
            if parsed and ("claim_states" in parsed or "summary" in parsed):
                verdict = parsed
                last_text = turn.text
                transcript.append(f"\n## Verdict\n\n```json\n"
                                  f"{json.dumps(parsed, ensure_ascii=False, indent=2)}\n```")
                break

            if not turn.calls:
                last_text = turn.text
                transcript.append(f"\n## Round {round_no + 1}\n\n{turn.text}\n")
                messages.append({"role": "assistant", "content": turn.text or "(no output)"})
                messages.append({"role": "user", "content":
                                 "You did not emit the final JSON block and did not request a tool. "
                                 "Either call a tool or emit the JSON verdict now."})
                continue

            call = turn.calls[0]
            name = str(call.get("name"))
            args = call.get("arguments") or {}
            fingerprint = (name, json.dumps(args, sort_keys=True, default=str))

            if fingerprint in seen_calls:
                transcript.append(f"\n## Round {round_no + 1}\n\n"
                                  f"_Skipped a repeat of `{name}`; the earlier result stands._\n")
                messages.append({"role": "assistant", "content": turn.text or f"(calling {name})"})
                messages.append({"role": "user", "content":
                                 f"You already called {name} with those exact arguments; the result is "
                                 f"above and unchanged. Choose a different tool or conclude with the "
                                 f"final JSON block."})
                continue
            seen_calls.add(fingerprint)

            emit("tool", {"tool": name, "args": args, "round": round_no + 1})
            outcome = tools.execute(name, args, sectors, store)
            step_record = {"name": name, "args": args,
                           "credits": outcome.get("credits", 0),
                           "result": outcome.get("result", outcome.get("error"))}
            steps.append(step_record)
            transcript.append(
                f"\n## Tool call {len(steps)}: `{name}`\n\n"
                f"```json\n{json.dumps(args, ensure_ascii=False)[:1500]}\n```\n\n"
                f"```json\n{json.dumps(step_record['result'], ensure_ascii=False, default=str)[:4000]}\n```"
            )
            emit("tool_result", {"tool": name, "credits": outcome.get("credits", 0)})

            if native:
                messages.append({"role": "assistant", "content": turn.text or None,
                                 "tool_calls": [{"id": call.get("id") or f"call_{round_no}",
                                                 "type": "function",
                                                 "function": {"name": name,
                                                              "arguments": json.dumps(args)}}]})
                messages.append({"role": "tool", "tool_call_id": call.get("id") or f"call_{round_no}",
                                 "content": json.dumps(outcome, default=str)[:12000]})
            else:
                messages.append({"role": "assistant", "content": turn.text or f"(calling {name})"})
                messages.append({"role": "user", "content": _results_message(None, name, outcome)})

        # -- decide ----------------------------------------------------------
        # Jev's answer stands for every claim it decided; a measurement that code
        # settled stands; the engine may only touch a claim neither of them could.
        final_states: dict[str, dict[str, Any]] = dict(jev_states)
        agent_states = _merge_states(measurements, verdict)
        overrule_notes: list[str] = []
        for claim_id, override in agent_states.items():
            measurement = next((m for m in measurements if m.claim_id == claim_id), None)
            if measurement is None:
                continue
            measured_state = final_states.get(claim_id, {}).get("state", measurement.state)
            if override.get("state") == measured_state:
                continue
            if _measurement_shortfall(measurement) is None and claim_id in jev_states:
                # Refused: the claim was decided from measured data, and prose
                # does not get to overrule arithmetic.
                overrule_notes.append(
                    f"{measurement.text}: engine proposed {override['state']}, "
                    f"refused in favour of the measured/decided {measured_state}"
                )
                continue
            final_states[claim_id] = override

        # -- guard the prose the engine wrote --------------------------------
        represented = _represented_fields(measurements, measurement_evidence)
        guardrail = {"flagged": False, "score": None, "unrepresented": [], "checked": []}
        if needs_agent and verdict is not None:
            # Only the prose is checked. The verdict JSON carries internal
            # numbers — probabilities, confidence — that are outputs of the
            # system, not claims about the company; feeding them in produced a
            # false positive on a real run ("cites 0.2", which was a probability).
            report = (last_text or "").strip()
            if not report:
                report = json.dumps(verdict.get("summary") or "", ensure_ascii=False)
            guardrail = _check_report(
                report, represented,
                [e["note"] for e in measurement_evidence if e.get("note")] + [brief],
                decider,
            )
            emit("guardrail", {"flagged": guardrail["flagged"], "score": guardrail["score"],
                               "unrepresented": guardrail["unrepresented"],
                               "checked": len(guardrail.get("checked") or [])})
            transcript.append(
                "\n## Guardrail (Jev)\n\n"
                f"Checked {len(guardrail.get('checked') or [])} cited number(s) against the "
                f"evidence. "
                + (f"**Flagged**: cites `{guardrail['unrepresented']}` "
                   f"(confidence {guardrail['score']}) — not present in the evidence."
                   if guardrail["flagged"] else "No unsupported figure found.")
            )

        # Did the agent actually add anything? A context finding, a settled claim
        # it was asked to settle, or a falsifier we did not already have.
        agent_contributed = bool(
            (verdict or {}).get("context") or (verdict or {}).get("falsifiers")
            or [s for s in steps if s.get("name") not in ("evidence_ledger",)]
        )

        if engine_error:
            decision_path = "measurement"
        elif not needs_agent and jev_states:
            decision_path = "jev"
        elif guardrail.get("flagged"):
            decision_path = "agent_unverified"
        elif agent_contributed and jev_states:
            # "jev+agent" should mean the agent actually added something, not
            # merely that it had the opportunity to — and never when there is no
            # decision layer behind the verdict at all.
            decision_path = "jev+agent"
        elif jev_states:
            decision_path = "jev"
        else:
            decision_path = "agent"

        final_status, final_reason = _status_from_states(final_states, status)
        if overrule_notes:
            final_reason += "; " + "; ".join(overrule_notes)

        if guardrail.get("flagged"):
            if final_status == "intact":
                final_status = "weakened"
                final_reason += ("; status capped at weakened: the prose cites a figure the "
                                 "evidence does not contain")
            store.add_evidence(check_id, {
                "symbol": thesis["symbol"],
                "metric": "guardrail.unrepresented_numbers",
                "value": f"{guardrail['score']:.2f}" if guardrail.get("score") is not None else "flag",
                "as_of": last_available_day(), "endpoint": "tool:jev",
                "params": {"flagged": guardrail["unrepresented"]},
                "note": "Jev Choice: the report cites numbers absent from the evidence",
            }, -1)

        confidence = _confidence(verdict, final_states, engine_error is not None,
                                 jev_states=jev_states, decision_path=decision_path)

        for m in measurements:
            row = m.to_row()
            override = final_states.get(m.claim_id)
            if override and override.get("state") and override["state"] != m.state:
                source = "Jev" if m.claim_id in jev_states else "Agent"
                row["rationale"] = (
                    f"{source} overruled the measurement ({m.state} → {override['state']}): "
                    f"{override.get('rationale') or 'no reason given'}"
                )
                row["state"] = override["state"]
            store.add_claim_result(check_id, row, m.ordinal)

        ordinal = 0
        for item in watermark_evidence + measurement_evidence:
            store.add_evidence(check_id, item, ordinal)
            ordinal += 1
        for claim_id, state in jev_states.items():
            store.add_evidence(check_id, {
                "symbol": thesis["symbol"], "metric": f"jev.claim_state",
                "value": state.get("state"),
                "as_of": last_available_day(), "endpoint": "tool:jev",
                "params": {"claim_id": claim_id,
                           "confidence": state.get("confidence"),
                           "probabilities": state.get("probabilities")},
                "note": "Jev decided this claim from the measured evidence",
            }, ordinal)
            ordinal += 1
        for step in steps:
            if isinstance(step.get("result"), dict):
                for metric_name, value in list(step["result"].items())[:20]:
                    if isinstance(value, (int, float, str)) and metric_name not in ("note", "_note"):
                        store.add_evidence(check_id, {
                            "symbol": thesis["symbol"], "metric": f"{step['name']}.{metric_name}",
                            "value": value, "as_of": last_available_day(),
                            "endpoint": f"tool:{step['name']}",
                            "params": step.get("args"), "note": None,
                        }, ordinal)
                        ordinal += 1

        changes = list(verdict.get("changes") or []) if verdict else []
        if not verdict:
            for m in measurements:
                if m.state in (BROKEN, WEAKENING):
                    changes.insert(0, {"kind": "data", "magnitude":
                                       None if m.delta is None else f"{m.delta * 100:+.1f}% YoY",
                                       "text": f"{m.text} — {m.rationale}"})
        for i, change in enumerate(changes):
            if isinstance(change, dict) and change.get("text"):
                store.add_change(thesis_id, change, i, check_id=check_id)

        summary = _summary(verdict, rollup_reason, final_reason, engine_error,
                           decision_path=decision_path, jev_states=jev_states,
                           guardrail=guardrail)
        transcript_path = _write_transcript(check_id, thesis, transcript, steps, engine_meta)

        store.finish_check(check_id, verdict=final_status, confidence=confidence,
                           summary=summary, credits=sectors.budget.spent,
                           tool_calls=len(steps), transcript_path=str(transcript_path),
                           decision_path=decision_path,
                           confidence_source=_confidence_source(jev_states, decision_path))

        previous_status = thesis.get("status")
        store.set_status(thesis_id, final_status, confidence, watermark, run_id)

        if previous_status != final_status:
            severity = {"broken": "alert", "weakened": "warning",
                        "needs_review": "info", "intact": "ok"}.get(final_status, "info")
            note = (verdict or {}).get("notification") if verdict else None
            store.notify(
                thesis_id,
                title=f"{thesis['symbol']}: {previous_status or 'unknown'} → {final_status}",
                body=note or summary,
                severity=severity,
                check_id=check_id,
            )

        store.finish_run(run_id, status="ok", credits=sectors.budget.spent)
        emit("done", {"check_id": check_id, "status": final_status,
                      "confidence": confidence, "summary": summary})

        return {
            "check_id": check_id,
            "run_id": run_id,
            "thesis_id": thesis_id,
            "symbol": thesis["symbol"],
            "status": final_status,
            "previous_status": previous_status,
            "confidence": confidence,
            "summary": summary,
            "engine": engine_meta,
            "engine_error": engine_error,
            "decision_path": decision_path,
            "guardrail": guardrail,
            "jev_claims": len(jev_states),
            "decidable": decidable,
            "measurements": [m.to_row() for m in measurements],
            "claims_final": [_final_row(m, final_states, jev_states) for m in measurements],
            "agent_states": final_states,
            "steps": steps,
            "credits": sectors.budget.spent,
            "transcript_path": str(transcript_path),
            "context": (verdict or {}).get("context"),
            "falsifiers": (verdict or {}).get("falsifiers") or [],
        }
    except (SectorsError, ValueError) as err:
        store.finish_check(check_id, verdict="unknown", confidence=None,
                           summary=f"check failed: {err}", credits=sectors.budget.spent,
                           tool_calls=len(steps))
        store.finish_run(run_id, status="error", credits=sectors.budget.spent, error=str(err))
        raise


def _merge_states(measurements: list[Measurement],
                  verdict: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The agent may overrule a measurement, but only by name and with a reason."""
    out: dict[str, dict[str, Any]] = {}
    if not verdict:
        return out
    known = {m.claim_id for m in measurements}
    for item in verdict.get("claim_states") or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("claim_id") or "")
        state = str(item.get("state") or "").lower()
        if cid in known and state in (SUPPORTED, WEAKENING, BROKEN, UNKNOWN):
            out[cid] = {"state": state, "rationale": item.get("rationale")}
    return out


def _final_row(measurement: Measurement, final_states: dict[str, dict[str, Any]],
               jev_states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A claim as it was finally decided, with the layer that decided it.

    The measurement's own state is not the answer once a decision layer has
    spoken, so reporting `to_row()` here would show a verdict the product did not
    actually reach.
    """
    row = measurement.to_row()
    decided = final_states.get(measurement.claim_id) or {}
    if decided.get("state"):
        row["measured_state"] = measurement.state
        row["state"] = decided["state"]
    row["decided_by"] = ("jev" if measurement.claim_id in jev_states
                         else ("agent" if decided.get("state")
                               and decided["state"] != measurement.state else "measurement"))
    return row


def _status_from_states(states: dict[str, dict[str, Any]], measured_status: str) -> tuple[str, str]:
    if not states:
        return measured_status, "status came from measurement only"
    values = [s["state"] for s in states.values()]
    if BROKEN in values:
        return "broken", f"{values.count(BROKEN)} claim(s) broken after the agent's review"
    if WEAKENING in values:
        return "weakened", f"{values.count(WEAKENING)} claim(s) weakened after the agent's review"
    if all(v == SUPPORTED for v in values):
        return "intact", "every claim held after the agent's review"
    return "needs_review", "the agent could not settle every claim"


def _confidence(verdict: dict[str, Any] | None, states: dict[str, dict[str, Any]],
                errored: bool, *, jev_states: dict[str, dict[str, Any]] | None = None,
                decision_path: str | None = None) -> float:
    """How much the verdict deserves to be trusted, and where that came from.

    A decided claim's confidence is Jev's, averaged. A rule-derived fallback is
    capped when the only thing behind the verdict is unguarded prose, because
    "the model said so" is not a measurement.
    """
    if errored:
        return 0.0
    if jev_states and decision_path in ("jev", "jev+agent"):
        values = [float(s["confidence"]) for s in jev_states.values()
                  if isinstance(s.get("confidence"), (int, float))]
        if values:
            return round(sum(values) / len(values), 2)

    value = (verdict or {}).get("confidence")
    try:
        out = float(value)
    except (TypeError, ValueError):
        if not states:
            return 0.35
        settled = sum(1 for s in states.values() if s["state"] != UNKNOWN)
        out = round(0.4 + 0.5 * settled / len(states), 2)
    if decision_path in ("agent", "agent_unverified"):
        # Unguarded or demonstrably unverifiable prose is not a measurement, so it
        # cannot carry the confidence a measurement would. `agent_unverified` was
        # the hole here: the guardrail had already caught a fabricated figure, and
        # the run still carried the model's own 0.95 into the stored check.
        out = min(out, CONFIDENCE_CEILING_WHEN_UNGUARDED)
    return max(0.0, min(1.0, out))


def _confidence_source(jev_states: dict[str, dict[str, Any]] | None,
                       decision_path: str | None) -> str:
    """A one-word label for where the number above came from."""
    if decision_path in ("jev", "jev+agent") and jev_states:
        return "jev"
    if decision_path in ("agent", "agent_unverified"):
        return "prose"
    return "rule"


def _summary(verdict: dict[str, Any] | None, rollup_reason: str,
             final_reason: str, engine_error: str | None,
             *, decision_path: str | None = None,
             jev_states: dict[str, dict[str, Any]] | None = None,
             guardrail: dict[str, Any] | None = None) -> str:
    prefix = ""
    if guardrail and guardrail.get("flagged"):
        score = guardrail.get("score")
        prefix = (f"⚠︎ cites a figure the evidence does not contain"
                  f"{f' ({score:.2f})' if isinstance(score, (int, float)) else ''} "
                  f"[{', '.join(guardrail.get('unrepresented') or [])}]. ")
    if engine_error:
        return (f"Measured without an agent: {rollup_reason}. The agent was unavailable "
                f"({engine_error}), so the interpretation is not attempted.")
    if verdict and verdict.get("summary"):
        return prefix + str(verdict["summary"])[:2000]
    if decision_path == "jev" and jev_states:
        held = sum(1 for s in jev_states.values() if s.get("state") == SUPPORTED)
        return prefix + (f"{final_reason}. {held} of {len(jev_states)} claim(s) still hold; "
                         f"decided from measured data with no agent turn needed.")
    return prefix + f"{final_reason}. Measurements: {rollup_reason}."


def _write_transcript(check_id: str, thesis: dict[str, Any], transcript: list[str],
                      steps: list[dict[str, Any]], engine_meta: dict[str, Any]) -> Path:
    root = settings().home / "transcripts"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{check_id}.md"
    header = [
        f"# Check {check_id} — {thesis['symbol']}",
        "",
        f"- engine: `{engine_meta.get('engine')}`"
        + (f" model `{engine_meta.get('model')}`" if engine_meta.get("model") else ""),
        f"- thesis: {thesis['statement']}",
        f"- tool calls: {len(steps)}",
        "",
        "Every number the verdict rests on is in this file with the endpoint it came from.",
        "",
    ]
    path.write_text("\n".join(header) + "\n".join(transcript), encoding="utf-8")
    return path
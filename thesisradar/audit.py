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
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import metrics, tools
from .config import settings
from .engines import Engine, EngineUnavailable
from .jsonx import extract_json
from .sectors import Budget, Sectors, SectorsError, bare, last_available_day
from .store import Store

MAX_TOOL_ROUNDS = 6

# How many quarters are pulled per symbol. Twelve covers a year-on-year
# comparison, the quarterly shape around it, and enough history to notice that a
# reported series has been restated rather than having moved.
QUARTER_WINDOW = 12

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
        broken_at = metrics.break_index(series, field_name)
        spans_break = broken_at is not None and broken_at > yoy_index

        if spans_break:
            earlier = series[broken_at - 1]
            later = series[broken_at]
            jump = metrics.pct_change(later["value"], earlier["value"])
            base.delta = None
            base.state = UNKNOWN
            base.rationale = (
                f"The reported {field_name} series is inconsistent: it moves "
                f"{jump * 100:+.1f}% between {earlier['date']} and {later['date']}, which is a "
                f"restatement or a change of definition rather than trading. A year-on-year "
                f"comparison would span that break, so this claim cannot be measured from the "
                f"series as published."
            )
            base.evidence.append({
                "symbol": symbol, "metric": f"{field_name} discontinuity",
                "value": f"{metrics.describe(later['value'])} from {metrics.describe(earlier['value'])}",
                "as_of": later["date"],
                "endpoint": f"/v2/financials/quarterly/{symbol}/",
                "params": {"n_quarters": 12},
                "note": (f"{jump * 100:+.1f}% in one quarter, beyond the "
                         f"{metrics.DISCONTINUITY_BANDS.get(field_name, metrics.DEFAULT_BAND):.0%} "
                         f"band for this metric — treated as a definitional break"),
            })
            measurements.append(base)
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

Your job is NOT to agree with the thesis. It is to find out whether it is still true, and to say plainly when it is not. "This claim no longer holds, because X" is the most valuable thing you can produce. Do not restate the numbers you were given; they are already measured. Your value is context:

- Is the move in the company, or in the whole sector or market? Use market_context and sector_context. A stock that fell 3% on a day the index fell 3% has told you nothing about that company.
- Is the price action real, or the mechanical effect of a split, rights issue or dividend? Is the stock suspended? A halt pins the last close and manufactures a fake trend. Use corporate_action_check and what_changed.
- Is the money still moving the way the position assumes? Use flow_delta and insider_activity.
- Does the written story have a dated cause? Use news_search. If the move happened on a day with no news, the story is probably wrong.
- Is a missing number actually missing? If the API does not report what the thesis leans on, say so rather than reasoning around it.

Rules:
- ALWAYS call `evidence_ledger` first. It costs 0 credits and tells you whether this name has been examined before.
- ALWAYS call `what_changed` before anything else paid: it is one call that returns price, foreign flow, insider filings, news and corporate actions together.
- Prefer cheap evidence first, and do not call the same tool twice with the same arguments.
- `market_context` and `news_search` take NO symbol argument — they are market-wide. Passing one will fail.
- Every conclusion must name the evidence it rests on.
- Never introduce a number, ratio or metric that no tool returned. If a figure (a NIM percentage, an NPL ratio) was not in a tool result, you cannot cite it — say the data does not settle that point instead.
- If the data cannot settle something, say so. An honest "cannot tell from here" beats a confident guess, and is a valid verdict.

You have at most 4 tool calls. Spend them on the two or three that would actually change your mind, then conclude. Keep each reply short — one or two sentences of reasoning, then either the tool block or the verdict block, never both.

When you have enough — or when you have spent your budget — end your reply with exactly one JSON block and no other text after it:

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
        on_event=None) -> dict[str, Any]:
    """Measure one thesis, let the agent argue about it, persist everything."""
    thesis = store.get_thesis(thesis_id)
    if thesis is None:
        raise ValueError(f"no thesis {thesis_id}")
    if symbol_override:
        thesis["symbol"] = bare(symbol_override)

    emit = on_event or (lambda *a, **k: None)
    engine_meta = engine.identify()

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

        # A repeated identical call is pure waste: the answer is already in the
        # transcript. The loop recognises it, refuses to spend the credit, and
        # tells the model to move on instead of silently rerunning it.
        seen_calls: set[tuple[str, str]] = {("evidence_ledger", json.dumps({"symbol": thesis["symbol"]}, sort_keys=True))}

        verdict: dict[str, Any] | None = None
        engine_error: str | None = None
        native = getattr(engine, "protocol", "prompt") == "native"

        for round_no in range(max_rounds):
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
                transcript.append(f"\n## Verdict\n\n```json\n"
                                  f"{json.dumps(parsed, ensure_ascii=False, indent=2)}\n```")
                break

            if not turn.calls:
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

        # -- persist ---------------------------------------------------------
        final_states = _merge_states(measurements, verdict)
        final_status, final_reason = _status_from_states(final_states, status)
        confidence = _confidence(verdict, final_states, engine_error is not None)

        for m in measurements:
            row = m.to_row()
            override = final_states.get(m.claim_id)
            if override and override.get("state") and override["state"] != m.state:
                row["rationale"] = (
                    f"Agent overruled the measurement ({m.state} → {override['state']}): "
                    f"{override.get('rationale') or 'no reason given'}"
                )
                row["state"] = override["state"]
            store.add_claim_result(check_id, row, m.ordinal)

        ordinal = 0
        for item in watermark_evidence + measurement_evidence:
            store.add_evidence(check_id, item, ordinal)
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

        summary = _summary(verdict, rollup_reason, final_reason, engine_error)
        transcript_path = _write_transcript(check_id, thesis, transcript, steps, engine_meta)

        store.finish_check(check_id, verdict=final_status, confidence=confidence,
                           summary=summary, credits=sectors.budget.spent,
                           tool_calls=len(steps), transcript_path=str(transcript_path))

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
            "measurements": [m.to_row() for m in measurements],
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
                errored: bool) -> float:
    if errored:
        return 0.0
    value = (verdict or {}).get("confidence")
    try:
        out = float(value)
    except (TypeError, ValueError):
        # No stated confidence: derive a conservative one from how much was settled.
        if not states:
            return 0.35
        settled = sum(1 for s in states.values() if s["state"] != UNKNOWN)
        return round(0.4 + 0.5 * settled / len(states), 2)
    return max(0.0, min(1.0, out))


def _summary(verdict: dict[str, Any] | None, rollup_reason: str,
             final_reason: str, engine_error: str | None) -> str:
    if engine_error:
        return (f"Measured without an agent: {rollup_reason}. The agent was unavailable "
                f"({engine_error}), so the interpretation is not attempted.")
    if verdict and verdict.get("summary"):
        return str(verdict["summary"])[:2000]
    return f"{final_reason}. Measurements: {rollup_reason}."


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
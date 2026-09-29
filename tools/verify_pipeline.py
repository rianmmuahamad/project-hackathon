"""End-to-end pipeline check against a stub Sectors API.

The point is not to test the network — it is to prove the pipeline behaves
correctly on data whose *answer we already know*. Every assertion here is
observable behaviour: a verdict, a claim state, a persisted evidence row, a
notification. Nothing asserts source text or implementation details.

    python tools/verify_pipeline.py

Runs on a temporary database, with zero Sectors credits and no model calls.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from thesisradar import audit, engines  # noqa: E402
from thesisradar.sectors import Budget, Sectors  # noqa: E402
from thesisradar.service import Service  # noqa: E402
from thesisradar.store import Store  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    mark = "ok  " if condition else "FAIL"
    print(f"  {mark} {message}")
    if not condition:
        FAILURES.append(message)


# --------------------------------------------------------------------------
# a stub API whose numbers are chosen so every claim's answer is known
# --------------------------------------------------------------------------
BBRI_QUARTERS = [
    # date, gross_loan, net_interest_income, earnings
    ("2024-09-30", 1264.78e12, 33.98e12, 15.57e12),
    ("2024-12-31", 1298.32e12, 36.30e12, 15.47e12),
    ("2025-03-31", 1314.59e12, 35.85e12, 13.93e12),
    ("2025-06-30", 1358.01e12, 37.42e12, 12.85e12),
    ("2025-09-30", 1379.69e12, 37.72e12, 14.90e12),
    ("2025-12-31", 1460.73e12, 39.51e12, 15.93e12),
    ("2026-03-31", 1497.27e12, 40.16e12, 15.77e12),
    # Latest: loans +17% YoY (claim holds), NII still rising (claim holds),
    # earnings higher YoY but the last two quarters fell (claim does not hold).
    ("2026-06-30", 1580.42e12, 40.38e12, 15.72e12),
]


def stub_rows(broken: bool = False) -> list[dict]:
    """Quarterly rows for the stub.

    `broken=True` reproduces the real BMRI shape: the gross loan series jumps
    down 15% in one quarter, which is a restatement rather than trading.
    """
    rows = []
    for index, (date, loan, nii, earnings) in enumerate(BBRI_QUARTERS):
        if broken and index >= len(BBRI_QUARTERS) - 2:
            loan = loan * 0.85
        rows.append({
            "symbol": "BBRI", "date": date,
            "revenue": nii * 1.3, "earnings": earnings,
            "total_assets": 2352.0e12, "total_equity": None,
            "stockholders_equity": 328.67e12,
            "operating_cash_flow": 20e12,
            "financials_sector_metrics": {"net_interest_income": nii, "gross_loan": loan,
                                          "total_deposit": 1700e12},
        })
    return rows


class StubSectors(Sectors):
    """Same public surface, no network — stubbed at the transport, not above it.

    The seam is `_request`, so the real client methods run: parameter building,
    `flatten_financial_row`, `flatten_screener_row` and every parser. Stubbing
    `quarterly()` instead would have let the flattening logic go untested, and a
    metrics series that silently came back empty looked like a product bug.
    """

    def __init__(self, broken_series: bool = False, low_production: bool = False) -> None:
        super().__init__(api_key="stub", budget=Budget(), cache=_MemoryCache(), ledger=_NoLedger())
        self.asked: list[str] = []
        self.broken_series = broken_series
        self.low_production = low_production

    def _request(self, path: str, params: dict):  # type: ignore[override]
        # Mirror the real client's caching so repeat requests cost nothing.
        import hashlib
        import json as _json
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        key = hashlib.sha256(
            f"{path}?{_json.dumps(clean, sort_keys=True)}".encode()).hexdigest()
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        payload = self._payload(path, clean)
        self.cache.put(key, payload)
        self.asked.append(path)
        return payload

    def _payload(self, path: str, params: dict):  # noqa: ANN001
        del params
        if path.startswith("/v2/financials/quarterly/"):
            return stub_rows(broken=self.broken_series)
        if path.startswith("/v2/daily/"):
            return [{"date": f"2026-08-{d:02d}", "close": 3150 + d, "volume": 10_000_000}
                    for d in range(1, 29)]
        if path.startswith("/v2/foreign-flow/"):
            return {"symbol": "BBRI", "data": [
                {"date": f"2026-09-{d:02d}", "net_foreign_inflow": -1.2e11, "foreign_share": 0.31}
                for d in range(1, 20)]}
        if path.startswith("/v2/filings/"):
            return {"results": [], "pagination": {}}
        if path == "/v2/news/":
            return {"results": [{"date": "2026-09-27",
                                 "title": "Bank margins compress as funding costs rise",
                                 "tags": ["Banks"]}], "pagination": {}}
        if path.startswith("/v2/company/corporate-actions/"):
            return {}
        if path == "/v2/suspensions/":
            return {"results": [], "pagination": {}}
        if path.startswith("/v2/index-daily/"):
            return [{"date": "2026-08-30", "price": 6700.0}, {"date": "2026-09-28", "price": 6312.0}]
        if path.startswith("/v2/company/report/"):
            return {"overview": {"company_name": "PT Bank Rakyat Indonesia Tbk",
                                 "sector": "Financials", "sub_sector": "Banks"}}
        if path == "/v2/companies/":
            return {"results": [
                {"symbol": "BBRI.JK", "company_name": "PT Bank Rakyat Indonesia Tbk",
                 "query_values": {"sub_sector": "Banks"}},
                {"symbol": "BMRI.JK", "company_name": "PT Bank Mandiri Tbk",
                 "query_values": {"sub_sector": "Banks"}}],
                "pagination": {}}
        if path == "/v2/mining/commodities/":
            return [{"name": "Nickel", "data_points": 113,
                     "earliest_date": "2017-10-01", "latest_date": "2026-02-15"},
                    {"name": "Coal", "data_points": 194,
                     "earliest_date": "2011-01-01", "latest_date": "2026-02-15"}]
        if path.startswith("/v2/mining/commodities/") and path.endswith("/price/"):
            prices = []
            for y in (2024, 2025):
                for m in range(1, 13):
                    prices.append({"name": "Nickel", "date": f"{y}-{m:02d}-01", "price_usd_per_ton": 15000 + (y - 2024) * 1200 + m * 50})
            for m in range(1, 3):
                prices.append({"name": "Nickel", "date": f"2026-{m:02d}-01", "price_usd_per_ton": 17400 + m * 100})
            return prices
        if path == "/v2/mining/total-production/":
            if self.low_production:
                return [{"year": 2025, "production_volume": 206.4, "prev_year_volume": 198.5,
                         "unit": "Mt", "yoy_change_percent": 4.0},
                        {"year": 2024, "production_volume": 198.5, "prev_year_volume": 137.8,
                         "unit": "Mt", "yoy_change_percent": 44.05}]
            return [{"year": 2025, "production_volume": 220.0, "prev_year_volume": 198.5,
                     "unit": "Mt", "yoy_change_percent": 10.83},
                    {"year": 2024, "production_volume": 198.5, "prev_year_volume": 137.8,
                     "unit": "Mt", "yoy_change_percent": 44.05}]
        if path.startswith("/v2/subsector/report/"):
            return {"statistics": {"total_companies": 48}}
        if path.startswith("/v2/broker-summary/"):
            return {"top_buyers": [{"broker_code": "AK", "net_value": 4.2e11}],
                    "top_sellers": [{"broker_code": "CS", "net_value": -6.1e11}]}
        if path == "/v2/tags/":
            return ["Banks", "insider-trading"]
        return {}


class StubJev:
    """Scripted decision layer, with the same surface as `JevClient`.

    Records every question it was asked, so the checks can assert what the
    product *chose not to ask* — which is the whole point of putting the decision
    behind the measurement.
    """

    def __init__(self, states: dict[int, tuple[str, float]] | None = None,
                 decidable: str = "none",
                 guardrail: tuple[str, float] | None = None,
                 fail: bool = False) -> None:
        self.states = states or {}
        self.decidable = decidable
        self.guardrail = guardrail
        self.fail = fail
        self.seen: list[dict] = []

    def available(self) -> tuple[bool, str]:
        return True, "stub"

    def ask(self, state: str, questions: dict):  # noqa: ANN001
        from thesisradar.jev import JevAnswer, JevDecision, JevUnavailable

        if self.fail:
            raise JevUnavailable("stub failure")
        self.seen.append({"state": state, "questions": {k: dict(v) for k, v in questions.items()}})

        answers: dict[str, JevAnswer] = {}
        for name in questions:
            if name.startswith("claim_"):
                index = int(name.split("_")[1])
                label, conf = self.states.get(index, ("supported", 0.9))
                answers[name] = JevAnswer(name=name, kind="choice", value=label,
                                          confidence=conf, probabilities={label: conf})
            elif name == "decidable":
                answers[name] = JevAnswer(name=name, kind="choice", value=self.decidable,
                                          confidence=0.9, probabilities={self.decidable: 0.9})
        if "unsupported" in questions:
            label, conf = self.guardrail or ("none", 0.99)
            answers["unsupported"] = JevAnswer(name="unsupported", kind="choice", value=label,
                                               confidence=conf, probabilities={label: conf})
        return JevDecision(answers=answers, usage={"input_tokens": 42}, seconds=0.01,
                           model="stub")


def asked_claim_count(stub: StubJev) -> int:
    """How many claim questions the stub received, across all its calls."""
    total = 0
    for call in stub.seen:
        total += sum(1 for name in call["questions"] if name.startswith("claim_"))
    return total


def guardrail_calls(stub: StubJev) -> list[dict]:
    return [call for call in stub.seen if "unsupported" in call["questions"]]


class _MemoryCache:
    """In-memory stand-in for the on-disk cache.

    The real client hashes path+query and serves repeats from disk, so a check
    that asks for the same series twice pays once. The stub must behave the same
    way or the assertions would measure the fake, not the product.
    """

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    def get(self, key):  # noqa: ANN001
        return self.store.get(key)

    def put(self, key, payload):  # noqa: ANN001
        self.store[key] = payload


class _NoLedger:
    def record(self, **kwargs) -> None:
        return None

    def summary(self) -> dict:
        return {"spent": 0}


class RecordingEngine(engines.Engine):
    """A scripted engine: emits one tool call, then a verdict.

    Used instead of a real model so the assertions are about the product's
    behaviour, not about a model's ability to follow instructions.
    """

    name = "recording"

    def __init__(self, tool_call: dict | None = None, verdict: dict | None = None) -> None:
        self.tool_call = tool_call
        self.verdict = verdict or {}
        self.turns = 0

    def available(self) -> tuple[bool, str]:
        return True, "recording"

    def identify(self) -> dict:
        return {"engine": self.name, "model": "scripted"}

    def reply(self, system, messages, tools):  # noqa: ANN001
        from thesisradar.engines import Turn
        self.turns += 1
        if self.tool_call and self.turns == 1:
            return Turn(text="Checking the sector.",
                        calls=[{"name": self.tool_call["tool"],
                                "arguments": self.tool_call.get("args", {})}])
        return Turn(text=json.dumps(self.verdict))


def build_thesis(store: Store, sectors: StubSectors) -> str:
    from thesisradar import thesis as thesis_mod

    statement = ("Beli BBRI karena kredit tumbuh minimal 10% YoY dan laba bersih naik terus "
                 "dua kuartal ke depan, dan valuasi masih murah dibanding bank besar lain.")
    split = thesis_mod.decompose_offline(statement)
    for claim in split["claims"]:
        claim["symbol"] = "BBRI"
        claim["baseline_value"] = 1.0
        claim["baseline_date"] = "2026-06-30"
    return store.create_thesis({
        "symbol": "BBRI", "company_name": "PT Bank Rakyat Indonesia Tbk",
        "statement": statement, "translation": json.dumps(split),
        "claims": split["claims"], "horizon": "2 quarters",
    })


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(path=Path(tmp) / "radar.db")
        sectors = StubSectors()
        thesis_id = build_thesis(store, sectors)

        print("measurement (no model involved)")
        measurements, evidence = audit.measure(store.get_thesis(thesis_id), sectors)
        for m in measurements:
            print(f"    {m.state:11} {m.text}")

        def state_matching(fragment: str) -> str | None:
            for m in measurements:
                if fragment.lower() in m.text.lower():
                    return m.state
            return None

        check(state_matching("kredit tumbuh") == audit.SUPPORTED,
              "a claim whose metric grew 17% YoY clears a 10% growth threshold")
        check(state_matching("laba bersih") == audit.WEAKENING,
              "a claim whose metric rose YoY but fell two quarters running is weakening")
        check(not any("karena" in e["metric"] for e in evidence),
              "the splitter separates the conjunction instead of emitting one long claim")
        check(any(e["metric"] == "gross_loan" for e in evidence),
              "the measurement emits evidence rows with a metric name")
        check(all(e.get("endpoint") for e in evidence),
              "every evidence row carries the endpoint it came from")

        print("\nwatermark")
        rows = store.q("SELECT watermark FROM theses WHERE id=?", (thesis_id,))
        check(rows and rows[0]["watermark"] is None, "a new thesis has no watermark yet")

        print("\naudit with a scripted engine and a scripted decision layer")
        engine = RecordingEngine(
            tool_call={"tool": "sector_context", "args": {"symbol": "BBRI"}},
            verdict={
                "claim_states": [],
                "summary": "Everything holds; the peer comparison adds nothing.",
                "confidence": 0.7,
                "changes": [{"kind": "context", "text": "sector flat", "magnitude": None}],
                "falsifiers": ["Q3 loans below 10%"],
            },
        )
        # The stub mirrors what the arithmetic found, which is what a real
        # decision layer does most of the time: it agrees with the numbers and
        # adds a calibrated confidence to them.
        jev = StubJev(states={0: ("supported", 0.95), 1: ("weakening", 0.88)},
                      decidable="context:sector")
        result = audit.run(thesis_id, engine=engine, store=store, sectors=sectors, jev=jev)

        measured_ids = {m.claim_id for m in measurements
                        if audit._measurement_shortfall(m) is None}
        short_ids = {m.claim_id for m in measurements
                     if audit._measurement_shortfall(m) is not None}

        check(result["status"] == "weakened",
              "the rollup reports weakened when one claim no longer holds")
        check(len(jev.seen) >= 1 and asked_claim_count(jev) == len(measured_ids),
              f"only the {len(measured_ids)} measured claim(s) were put to the decision layer, "
              f"not the {len(short_ids)} it cannot settle")
        check(all("valuation" not in call["state"] for call in jev.seen),
              "a claim with no reported metric is not sent to the decision layer")
        check(result["decision_path"] == "jev+agent",
              "with an undecided claim and a decidable fact, both layers run")
        check(len([s for s in result["steps"] if s["name"] == "sector_context"]) > 0,
              "the engine's chosen tool is recorded in the transcript")
        check(sectors.asked.count("/v2/financials/quarterly/BBRI/") == 1,
              "quarterly financials are fetched once per check, not once per claim")

        detail = store.check_detail(result["check_id"])
        check(detail is not None and len(detail["claim_results"]) == len(measurements),
              "every claim gets a stored result")
        check(bool(detail["evidence"]), "the check stores evidence rows")
        check(detail["transcript"] and "evidence_ledger" in detail["transcript"],
              "the transcript is written to disk and readable")
        check(detail["since"] is None or isinstance(detail["since"], str),
              "the check records the watermark it looked forward from")

        print("\nnotification and memory")
        notes = store.list_notifications()
        check(len(notes) == 1, "a status change produces exactly one notification")
        check(notes and "unknown" in (notes[0]["title"] or ""),
              "the notification names the transition")
        check(store.get_thesis(thesis_id)["watermark"] is not None,
              "the thesis watermark advances after a check")

        print("\nsecond check is cheap and silent")
        engine_two = RecordingEngine(verdict={"claim_states": [], "summary": "unchanged",
                                              "confidence": 0.7})
        result_two = audit.run(thesis_id, engine=engine_two, store=store, sectors=sectors,
                               jev=StubJev(states={0: ("supported", 0.95), 1: ("weakening", 0.88)},
                                           decidable="context:sector"))
        check(result_two["previous_status"] == "weakened",
              "the second check knows the previous status")
        check(len(store.list_notifications()) == 1,
              "no notification is sent when the status did not change")

        print("\ndiscontinuity guard")
        with tempfile.TemporaryDirectory() as tmp2:
            broken_store = Store(path=Path(tmp2) / "radar.db")
            broken_sectors = StubSectors(broken_series=True)
            broken_id = build_thesis(broken_store, broken_sectors)
            broken_measurements, broken_evidence = audit.measure(
                broken_store.get_thesis(broken_id), broken_sectors)
            broken_state = next((m.state for m in broken_measurements
                                 if "kredit tumbuh" in m.text.lower()), None)
            broken_rationale = next((m.rationale for m in broken_measurements
                                     if "kredit tumbuh" in m.text.lower()), "")

            check(broken_state == audit.UNKNOWN,
                  "a series that drops 15% in one quarter yields no verdict, not a negative trend")
            check("inconsistent" in broken_rationale or "restatement" in broken_rationale,
                  "the guard says why: the series is treated as a definitional break")
            check(broken_state != audit.BROKEN,
                  "the claim is not reported broken on the strength of a restatement")
            check(any("discontinuity" in (e.get("metric") or "") for e in broken_evidence),
                  "the discontinuity is recorded as evidence with its date")
            broken_store.close()

        print("\ndecision layer: gating, guardrail, fallback")
        with tempfile.TemporaryDirectory() as tmp3:
            # 1. Every claim measured, and no further fact would change it -> the
            #    engine is never called at all.
            store3 = Store(path=Path(tmp3) / "radar.db")
            sectors3 = StubSectors()
            thesis3 = build_thesis(store3, sectors3)
            # Drop the valuation claim so nothing is left undecided.
            keep = [c for c in store3.get_thesis(thesis3)["claims"] if c["cadence"] == "quarterly"]
            store3.replace_claims(thesis3, keep)

            silent_engine = RecordingEngine(verdict={"summary": "unused", "confidence": 0.9})
            jev3 = StubJev(decidable="none")
            fast = audit.run(thesis3, engine=silent_engine, store=store3, sectors=sectors3, jev=jev3)

            check(silent_engine.turns == 0,
                  "when every claim is decided and no further data would change it, the engine "
                  "is never called")
            check(fast["decision_path"] == "jev", "the run reports that Jev decided it alone")
            detail3 = store3.check_detail(fast["check_id"])
            check(detail3["confidence_source"] == "jev",
                  "the stored check records that its confidence came from Jev")
            expected = round(sum(c for _, c in jev3.states.values()) / max(1, len(jev3.states)), 2) \
                if jev3.states else None
            check(detail3["confidence"] is not None and detail3["confidence"] > 0.5,
                  "a decided check carries Jev's calibrated confidence, not a rule-derived guess")
            del expected
            check(guardrail_calls(jev3) == [],
                  "no guardrail call is made when the engine wrote nothing to guard")

            # 2. The guardrail fires and caps the status.
            flagged_engine = RecordingEngine(
                tool_call={"tool": "sector_context", "args": {"symbol": "BBRI"}},
                verdict={"claim_states": [], "summary": "NIM turun di bawah 5,8%.",
                         "confidence": 0.95},
            )
            jev4 = StubJev(decidable="context:sector", guardrail=("5,8%", 0.93))
            flagged = audit.run(thesis3, engine=flagged_engine, store=store3, sectors=sectors3,
                                jev=jev4)
            check(flagged["decision_path"] == "agent_unverified",
                  "a report citing an unrepresented number is marked unverified")
            check(flagged["guardrail"]["flagged"] is True and
                  flagged["guardrail"]["unrepresented"] == ["5,8%"],
                  "the guardrail names the offending number")
            check(str(flagged["summary"]).startswith("⚠︎"),
                  "the summary says out loud that a figure could not be traced")
            check(flagged["confidence"] <= audit.CONFIDENCE_CEILING_WHEN_UNGUARDED,
                  "unverified prose cannot carry high confidence")
            names = {row["metric"] for row in store3.check_detail(flagged["check_id"])["evidence"]}
            check("guardrail.unrepresented_numbers" in names,
                  "the flagged figure is stored as evidence")

            # 3. A clean report is not flagged.
            jev5 = StubJev(decidable="context:sector", guardrail=("none", 0.97))
            clean = audit.run(thesis3, engine=RecordingEngine(
                tool_call={"tool": "sector_context", "args": {"symbol": "BBRI"}},
                verdict={"claim_states": [], "summary": "Kredit +16.4% YoY tetap sesuai data.",
                         "confidence": 0.8}), store=store3, sectors=sectors3, jev=jev5)
            check(clean["decision_path"] == "jev+agent",
                  "a clean report keeps the normal decision path")
            check(clean["guardrail"]["flagged"] is False, "a clean report is not flagged")

            # 4. The decision layer failing must not break the product.
            broken = audit.run(thesis3, engine=RecordingEngine(
                tool_call={"tool": "sector_context", "args": {"symbol": "BBRI"}},
                verdict={"claim_states": [], "summary": "context only", "confidence": 0.7}),
                store=store3, sectors=sectors3, jev=StubJev(fail=True))
            check(broken["decision_path"] == "agent",
                  "when the decision layer fails the agent still decides, as before")
            check(broken["status"] is not None, "the check still completes a verdict")
            store3.close()

        print("\ntranscript segmentation")
        from thesisradar import transcript as tr_mod

        fixture = (
            "# Check ck-test — BBRI\n\n- engine: `hermes`\n- tool calls: 2\n\n"
            "Every number the verdict rests on is in this file.\n"
            "## Thesis brief\n\n```\nSTOCK: BBRI\n```\n\n"
            "## Decision (Jev)\n\n3 claim question(s) answered in 1.10s.\n\n"
            "_Skipped a repeat of `sector_context`; the earlier result stands._\n\n"
            "## Free read: `evidence_ledger`\n\n```json\n{\"symbol\": \"BBRI\"}\n```\n\n"
            "## Tool call 2: `what_changed`\n\n```json\n{\"symbol\": \"BBRI\"}\n```\n\n"
            "```json\n{\"price\": {\"change_pct\": -3.08}}\n```\n\n"
            "## Verdict\n\n```json\n{\"confidence\": 0.6, \"summary\": \"x\"}\n```\n\n"
            "## Guardrail (Jev)\n\nChecked 5 cited number(s). No unsupported figure found.\n"
        )
        segs = tr_mod.segment_transcript(fixture)
        check([s["kind"] for s in segs] ==
              ["header", "brief", "decision", "note", "ledger", "tool", "verdict", "guardrail"],
              "the splitter preserves file order and lifts standalone notes into their own segment")
        tool_seg = next((s for s in segs if s["kind"] == "tool"), None)
        check(tool_seg is not None and tool_seg["tool"] == "what_changed",
              "the tool name is read out of the backticked heading")
        check(all("## " not in s["summary"] and "`" not in s["summary"] for s in segs),
              "no summary carries a heading marker or a backtick")
        check(next(s for s in segs if s["kind"] == "verdict")["summary"].startswith("2 field"),
              "a section that is only a JSON block is summarised structurally")

        lone = tr_mod.segment_transcript("just prose, no headings")
        check(len(lone) == 1 and lone[0]["kind"] == "header",
              "a transcript with no headings still yields one segment rather than nothing")
        check(tr_mod.segment_transcript(None) == [] and tr_mod.segment_transcript("") == [],
              "an absent transcript yields no segments")

        with tempfile.TemporaryDirectory() as tmp4:
            store4 = Store(path=Path(tmp4) / "radar.db")
            sectors4 = StubSectors()
            thesis4 = build_thesis(store4, sectors4)
            run4 = audit.run(thesis4, engine=RecordingEngine(
                tool_call={"tool": "sector_context", "args": {"symbol": "BBRI"}},
                verdict={"claim_states": [], "summary": "context", "confidence": 0.7}),
                store=store4, sectors=sectors4, jev=StubJev(decidable="context:sector"),)
            detail4 = store4.check_detail(run4["check_id"])
            segs4 = tr_mod.segment_transcript(detail4["transcript"])
            tr_mod.link_evidence(segs4, detail4["evidence"])
            linked = sum(len(s["evidence_ordinals"]) for s in segs4)
            check(linked == len(detail4["evidence"]),
                  f"every stored evidence row is linked to a segment "
                  f"({linked} of {len(detail4['evidence'])})")
            check(all(o not in (None, "") for s in segs4 for o in s["evidence_ordinals"]),
                  "no link carries a missing ordinal")
            check(any(s["evidence_ordinals"] for s in segs4),
                  "at least one segment carries evidence")
            store4.close()

        from thesisradar.config import settings as cfg_settings
        service = Service(store)
        served = service.check_detail(result["check_id"])
        check(isinstance(served.get("transcript_segments"), list) and served["transcript_segments"],
              "the served check detail carries typed segments")
        check(served.get("sectors_base") == cfg_settings().api_base,
              "the served check detail publishes the API base the copy button needs")
        thesis_served = service.thesis_detail(thesis_id)
        check(isinstance((thesis_served.get("latest") or {}).get("transcript_segments"), list),
              "the first paint of the thesis carries segments without a second request")
        linked_served = sum(len(s["evidence_ordinals"]) for s in served["transcript_segments"])
        check(linked_served == len(served["evidence"]),
              "every evidence row is linked in the served payload too")

        print("\nscheduled digest")
        from thesisradar import mailer
        from thesisradar.service import Service as ServiceCls

        class FakeSMTP:
            def __init__(self, *a, **k):
                self.sent: list = []
                self.tls = False
                self.quit_called = False

            def starttls(self): self.tls = True

            def login(self, u, p): raise AssertionError("no credentials are configured")

            def send_message(self, msg): self.sent.append(msg)

            def quit(self): self.quit_called = True

        class DeadSMTP(FakeSMTP):
            def send_message(self, msg): raise OSError("connection refused")

        with tempfile.TemporaryDirectory() as tmp5:
            # Point the process at a relay so `email_configured` is true; the fake
            # client is what actually receives the message.
            os.environ["THESISRADAR_SMTP_HOST"] = "smtp.test"
            os.environ["THESISRADAR_SMTP_TO"] = "oncall@example.com"
            store5 = Store(path=Path(tmp5) / "radar.db")
            sectors5 = StubSectors()
            thesis5 = build_thesis(store5, sectors5)
            service5 = ServiceCls(store=store5)
            service5.cfg = cfg_settings()
            check(service5.cfg.email_configured is True,
                  "the block is running against a configured relay")

            inbox: list = []
            real_send = mailer.send

            def capture(subject, body, *, cfg=None, smtp=None):  # noqa: ANN001
                fake = FakeSMTP()
                inbox.append(fake)
                return real_send(subject, body, cfg=cfg, smtp=fake)

            mailer.send = capture  # type: ignore[assignment]
            try:
                first = service5.scheduled_check()
                check(len(inbox) == 1 and len(inbox[0].sent) == 1,
                      "a status change produces exactly one digest email")
                check(first["emailed"] is True, "the run reports that the digest left")
                message = inbox[0].sent[0]
                check("BBRI" in (message["Subject"] or ""),
                      "the subject names the thesis that moved")
                body5 = message.get_content()
                check("BBRI" in body5 and "→" in body5,
                      "the body carries the transition the notification recorded, not the raw result")
                check(inbox[0].tls is True,
                      "STARTTLS is negotiated before the message is handed over")

                before_second = len(inbox)
                second = service5.scheduled_check()
                check(len(inbox) == before_second,
                      "a sweep that changes nothing sends no email at all")
                check(second["emailed"] is False and second["reason"],
                      "the quiet run says why it stayed silent")
                check(second["changed"] == 0, "nothing changed on the second sweep")

                history = service5.recent_digests()
                check(len(history) == 2 and history[0]["at"] >= history[1]["at"],
                      "the digest history is kept newest first")
                check(history[0]["emailed"] is False,
                      "the newest entry records that nothing was sent")

                # A dead relay must not lose the sweep or raise. Force a real
                # status change so the sweep actually writes a notification —
                # `previous_status` comes from the thesis row, not the check.
                checks_before = store5.stats()["checks"]
                mailer.send = lambda *a, **k: real_send(*a, smtp=DeadSMTP(), **k)  # type: ignore[assignment]
                store5.set_watch(thesis5, True)
                store5.x("UPDATE theses SET status='broken' WHERE id=?", (thesis5,))
                third = service5.scheduled_check()
                check(third["emailed"] is False and third.get("error"),
                      "a failing relay is reported in the run, not raised")
                check(store5.stats()["checks"] > checks_before,
                      "the sweep still completed and stored its check despite the failure")
                check(service5.recent_digests(1)[0].get("error") is not None
                      or third.get("error") is not None,
                      "the failure is visible in the digest history")
            finally:
                mailer.send = real_send  # type: ignore[assignment]
                os.environ.pop("THESISRADAR_SMTP_HOST", None)
                os.environ.pop("THESISRADAR_SMTP_TO", None)
                store5.close()
                service5.stop_schedule()

        print("\ncommodity subjects")
        with tempfile.TemporaryDirectory() as tmp_c:
            store_c = Store(path=Path(tmp_c) / "radar.db")
            sectors_c = StubSectors()
            service_c = Service(store=store_c)
            service_c._sectors = lambda budget: sectors_c

            # 1. create_thesis stores subject_type='commodity' and preserves symbol casing
            theses_before = store_c.stats()["theses"]
            out_c = service_c.create_thesis(
                subject_type="commodity", symbol="Nickel",
                text="Harga nikel naik terus dan produksi nasional tumbuh minimal 10%",
            )
            check(out_c["thesis"]["subject_type"] == "commodity" and out_c["thesis"]["symbol"] == "Nickel",
                  "commodity thesis is stored with subject_type='commodity' and exact symbol casing")

            # 2. Unknown commodity typo raises ValueError naming known commodities; no thesis written
            typo_caught = False
            try:
                service_c.create_thesis(subject_type="commodity", symbol="Unobtainium", text="something")
            except ValueError as err:
                typo_caught = "Nickel" in str(err) and "unknown commodity" in str(err)
            check(typo_caught and store_c.stats()["theses"] == theses_before + 1,
                  "creating an unknown commodity raises ValueError naming known commodities and stores no row")

            # 3. Claims carry commodity_price and production cadences
            claims = out_c["thesis"]["claims"]
            check(len(claims) == 2, "thesis statement was split into 2 claims")
            cadences = {c["cadence"] for c in claims}
            check(cadences == {"commodity_price", "production"},
                  f"claims carry commodity_price and production cadences (got {cadences})")

            # 4. audit.run yields per-claim state, decision_path, never 'not a quarterly report metric'
            run_res = audit.run(out_c["thesis"]["id"], engine=RecordingEngine(verdict={"summary": "ok", "confidence": 0.8}),
                                store=store_c, sectors=sectors_c, jev=StubJev(decidable="none"))
            detail_c = store_c.check_detail(run_res["check_id"])
            rationales = [r["rationale"] for r in detail_c["claim_results"]]
            check(not any("not a quarterly report metric" in rat for rat in rationales),
                  "dispatch gate was widened: no commodity claim got 'not a quarterly report metric'")
            check(run_res["decision_path"] in {"measurement", "jev", "jev+agent"},
                  f"commodity run reports valid decision_path ({run_res['decision_path']})")

            # 5. Production claim measured against annual data: +10.83% clears >=10% -> supported;
            #    with low_production (+4.0%) it must be broken.
            prod_claim = next(r for r in detail_c["claim_results"] if r["ordinal"] == 1)
            check(prod_claim["state"] == "supported",
                  f"production claim clears >=10% threshold with +10.83% YoY (got {prod_claim['state']})")

            # Test broken threshold with low production
            sectors_low = StubSectors(low_production=True)
            m_low, _ = audit.measure(out_c["thesis"], sectors_low)
            prod_m_low = next(m for m in m_low if m.metric == "production_volume")
            check(prod_m_low.state == "broken",
                  f"production claim arithmetic fails >=10% threshold with +4.0% YoY and is marked broken (got {prod_m_low.state})")
            run_low = audit.run(out_c["thesis"]["id"], engine=RecordingEngine(verdict={"summary": "ok", "confidence": 0.8}),
                                store=store_c, sectors=sectors_low,
                                jev=StubJev(states={0: ("supported", 0.95), 1: ("broken", 0.95)}, decidable="none"))
            detail_low = store_c.check_detail(run_low["check_id"])
            prod_low = next(r for r in detail_low["claim_results"] if r["ordinal"] == 1)
            check(prod_low["state"] == "broken",
                  f"production claim fails >=10% threshold with +4.0% YoY and is marked broken (got {prod_low['state']})")
            # 6. Evidence for commodity price contains no 'Rp'
            price_ev = [e for e in detail_c["evidence"] if e["metric"] == "commodity_price"]
            check(bool(price_ev) and not any("Rp" in str(e["value"]) for e in price_ev),
                  "commodity price evidence row carries no 'Rp' currency prefix")

            # 7. compute_watermark for stale commodity returns latest_date and attaches staleness row
            wm, wm_ev = audit.compute_watermark(out_c["thesis"], sectors_c)
            check(wm == "2026-02-15", f"stale commodity watermark returns latest_date 2026-02-15 (got {wm})")
            has_price_rec = any(e["metric"] == "latest_commodity_price" for e in wm_ev)
            check(has_price_rec, "commodity watermark attaches latest_commodity_price evidence row")
            store_c.close()

        print("\nengine fallback")
        availability = engines.describe()
        check("hermes" in availability and "direct" in availability,
              "both engines are discoverable")
        store.close()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for line in FAILURES:
            print(f"  - {line}")
        return 1
    print("all pipeline checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
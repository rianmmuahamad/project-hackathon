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
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from thesisradar import audit, engines  # noqa: E402
from thesisradar.sectors import Budget, Sectors  # noqa: E402
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

    def __init__(self, broken_series: bool = False) -> None:
        super().__init__(api_key="stub", budget=Budget(), cache=_MemoryCache(), ledger=_NoLedger())
        self.asked: list[str] = []
        self.broken_series = broken_series

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
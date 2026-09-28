"""`python -m thesisradar <command>` — the terminal front end.

Same service calls the dashboard makes, so the demo and the UI cannot drift.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import engines
from .config import settings
from .sectors import Budget, Sectors
from .service import JobBusy, Service
from .store import Store

STATUS_MARK = {"broken": "BROKEN", "weakened": "WEAK", "needs_review": "REVIEW",
               "intact": "INTACT", "unknown": "UNKNOWN"}


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _progress(kind: str, payload: dict) -> None:
    if kind == "tool":
        print(f"    → {payload['tool']}({json.dumps(payload.get('args') or {})[:90]})")
    elif kind == "tool_result":
        print(f"      {payload['credits']} credit(s)")
    elif kind == "thesis":
        print(f"  {payload['symbol']}", flush=True)
    elif kind == "engine":
        print(f"  engine: {payload['detail']}")


# --------------------------------------------------------------------------
def cmd_doctor(args) -> int:
    cfg = settings()
    store = Store()
    print("Thesis Radar — environment")
    print(f"  {'ok  ' if cfg.has_key else 'FAIL'} Sectors API key"
          f"{'' if cfg.has_key else '  (copy .env.example to .env and add your key)'}")
    print(f"  ok   data directory          {cfg.home}")

    ok = False
    if cfg.has_key:
        try:
            probe = Sectors(budget=Budget(limit=2))
            probe._request("/v2/tags/", {})
            ok = True
        except Exception as err:  # noqa: BLE001
            print(f"  FAIL Sectors API            {err}")
    print(f"  {'ok  ' if ok else 'FAIL'} Sectors API reachable")
    print(f"  ok   theses stored           {store.stats()['theses']} "
          f"({store.stats()['checks']} checks)")

    eng = engines.describe()
    for name, info in eng.items():
        mark = "ok  " if info["available"] else "warn"
        print(f"  {mark} {name:22} {info['detail']}")

    ledger = store.credits()
    print(f"  ok   credits                 {ledger['credits_spent']} spent across "
          f"{ledger['calls']} call(s), {ledger['cached_calls']} served from cache")
    print()
    print("  ready" if (cfg.has_key and ok) else "  not ready")
    return 0 if (cfg.has_key and ok) else 1


def cmd_new(args) -> int:
    service = Service()
    text = args.text or (Path(args.file).read_text(encoding="utf-8") if args.file else "")
    if not text.strip():
        print("nothing to work with: pass the thesis as an argument or via --file", file=sys.stderr)
        return 2
    try:
        out = service.create_thesis(text=text, symbol=args.symbol, horizon=args.horizon,
                                    engine_override=args.engine,
                                    capture_baselines=not args.no_baseline)
    except (ValueError, JobBusy) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    thesis = out["thesis"]
    print(f"{thesis['symbol']} — {thesis.get('company_name') or ''}")
    print(f"thesis: {thesis['statement']}")
    print(f"split by: {out['decomposition']['mode']}"
          + (f" ({out.get('engine_note')})" if out.get("engine_note") else ""))
    print(f"claims ({len(thesis['claims'])}):")
    for claim in thesis["claims"]:
        base = ""
        if claim.get("baseline_value") is not None:
            base = f"  [baseline {claim['baseline_date']}]"
        print(f"  {claim['ordinal'] + 1}. {claim['text']}")
        print(f"     metric={claim['metric']} direction={claim['direction']} "
              f"cadence={claim['cadence']} threshold={claim['threshold']}{base}")
    unresolved = out["decomposition"].get("unresolved") or []
    if unresolved:
        print(f"cannot be checked with this data ({len(unresolved)}):")
        for item in unresolved:
            print(f"  - {item['text']}  ({item['reason']})")
    print(f"\nid: {thesis['id']}   credits: {out['credits']}")
    return 0


def cmd_check(args) -> int:
    service = Service()
    target = service.store.find_thesis(args.thesis)
    if target is None:
        print(f"no thesis matching {args.thesis}", file=sys.stderr)
        return 2
    print(f"checking {target['symbol']} …", flush=True)
    try:
        out = service.check_thesis(target["id"], engine_override=args.engine, budget=args.budget)
    except Exception as err:  # noqa: BLE001
        print(f"check failed: {err}", file=sys.stderr)
        return 1

    prev = out.get("previous_status") or "unknown"
    print(f"\n{STATUS_MARK.get(out['status'], out['status'])}   {prev} → {out['status']}"
          f"   confidence {out['confidence']}")
    print(f"{out['summary']}\n")
    for row in out["measurements"]:
        print(f"  [{row['state']:11}] {row['text']}")
        print(f"                {row['delta'] or 'n/a'}  {row['rationale']}")
    if out.get("context"):
        print(f"\n  context: {json.dumps(out['context'], ensure_ascii=False)}")
    if out.get("falsifiers"):
        print("\n  what would change this verdict:")
        for item in out["falsifiers"]:
            print(f"    - {item}")
    print(f"\n  tools used ({len(out['steps'])}): "
          + ", ".join(s["name"] for s in out["steps"]))
    print(f"  credits: {out['credits']}   transcript: {out['transcript_path']}")
    if out.get("engine_error"):
        print(f"  engine problem: {out['engine_error']}")
    return 0


def cmd_credits(args) -> int:
    """The credit ledger: what was spent, where, and what the cache saved."""
    store = Store()
    ledger = store.credits()
    stats = store.stats()
    print("Sectors API credits — this project")
    print(f"  spent            {ledger['credits_spent']}")
    print(f"  calls            {ledger['calls']} ({ledger['network_calls']} network, "
          f"{ledger['cached_calls']} served from cache)")
    print(f"  checks run       {stats['checks']} ({stats['check_credits']} credits)")
    print(f"  theses           {stats['theses']} ({stats['watched']} watched)")
    if ledger["by_endpoint"]:
        print("\n  by endpoint:")
        for endpoint, count in ledger["by_endpoint"].items():
            print(f"    {count:>5}  {endpoint}")
    if not args.json:
        print(f"\n  ledger file      {settings().home / 'credits.jsonl'}")
    if args.json:
        _print(ledger)
    return 0


def cmd_queue(args) -> int:
    service = Service()
    rows = service.queue()
    if not rows:
        print("no theses yet — `python -m thesisradar new --symbol BBRI \"...\"`")
        return 0
    print(f"{'':6} {'STATUS':9} {'CONF':>5}  {'SYMBOL':7} {'CLAIMS':>6}  LAST CHECKED")
    for row in rows:
        mark = {"broken": "!!!", "weakened": " ! ", "needs_review": " ? ",
                "intact": "   "}.get(row["status"], "   ")
        conf = "" if row["confidence"] is None else f"{row['confidence']:.2f}"
        print(f"{mark:6} {STATUS_MARK.get(row['status'], row['status']):9} {conf:>5}  "
              f"{row['symbol']:7} {row['claims']:>6}  {row['last_checked_at'] or 'never'}")
        if row["changes"]:
            recent = row["changes"][0]
            print(f"       └ {recent['text'][:110]}")
    return 0


def cmd_show(args) -> int:
    service = Service()
    target = service.store.find_thesis(args.thesis)
    if target is None:
        print(f"no thesis matching {args.thesis}", file=sys.stderr)
        return 2
    detail = service.thesis_detail(target["id"])
    print(f"{detail['symbol']} — {detail.get('company_name') or ''}")
    print(f"thesis: {detail['statement']}")
    print(f"status: {detail['status']}  confidence: {detail['confidence']}  "
          f"watermark: {detail.get('watermark')}")
    print(f"\nclaims ({len(detail['claims'])}):")
    for claim in detail["claims"]:
        print(f"  {claim['ordinal'] + 1}. {claim['text']}  [{claim['metric']}/{claim['direction']}]")

    latest = detail.get("latest")
    if latest:
        print(f"\nlatest check {latest['checked_at']} — {latest['verdict']} "
              f"({latest['confidence']})")
        print(f"  {latest['summary']}")
        print("\n  claim results:")
        for row in latest["claim_results"]:
            print(f"    [{row['state']:11}] {row['text']}")
            print(f"                  {row['rationale']}")
        print("\n  changes since the previous check:")
        for row in latest["changes"] or []:
            mag = f" ({row['magnitude']})" if row.get("magnitude") else ""
            print(f"    - [{row.get('kind') or 'data'}] {row['text']}{mag}")
        print("\n  evidence:")
        for row in latest["evidence"]:
            print(f"    {row['ordinal']:>2}. {row['metric']} = {row['value']} "
                  f"as of {row['as_of']}  ← {row['endpoint']}")
    if detail.get("checks"):
        print("\n  history:")
        for row in detail["checks"]:
            conf = "" if row["confidence"] is None else f"{row['confidence']:.2f}"
            print(f"    {row['checked_at']}  {row['verdict']:13} {conf}")
    return 0


def cmd_check_all(args) -> int:
    service = Service()
    try:
        out = service.check_all(watch_only=not args.all, limit=args.limit,
                                engine_override=args.engine)
    except JobBusy as err:
        print(f"busy: {err}", file=sys.stderr)
        return 1
    print(f"checked {out['checked']}, changed {out.get('changed', 0)}")
    for row in out["results"]:
        if row.get("error"):
            print(f"  {row['symbol']:7} ERROR {row['error']}")
        else:
            arrow = f"{row.get('previous_status')} → {row['status']}"
            print(f"  {row['symbol']:7} {arrow:26} {row.get('credits', 0)} credits")
    return 0


def cmd_draft(args) -> int:
    service = Service()
    out = service.suggest_theses(sub_sector=args.subsector, count=args.count)
    print(f"{out['note']}  ({out['credits']} credits)")
    for draft in out["drafts"]:
        print(f"\n{draft['symbol']} — {draft.get('company_name') or ''}")
        print(f"  {draft['statement']}")
        print(f"  {json.dumps(draft['evidence'], ensure_ascii=False)}")
    for item in out.get("skipped") or []:
        print(f"\n{item['symbol']} — tidak dibuatkan tesis")
        print(f"  {item['reason']}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn
    host = args.host
    port = args.port
    print(f"dashboard: http://{host}:{port}")
    uvicorn.run("thesisradar.server:app", host=host, port=port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="thesisradar", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="environment, engine and credit check")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("new", help="write down a thesis and split it into checkable claims")
    p.add_argument("text", nargs="?", help="the thesis in plain language")
    p.add_argument("--symbol", "-s", required=False, help="IDX ticker, e.g. BBRI")
    p.add_argument("--file", help="read the thesis from a file instead")
    p.add_argument("--horizon", default="2 quarters")
    p.add_argument("--engine", choices=["auto", "hermes", "direct"])
    p.add_argument("--no-baseline", action="store_true",
                   help="skip recording the metric's value at thesis time")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("check", help="audit one thesis")
    p.add_argument("thesis", help="thesis id or ticker")
    p.add_argument("--engine", choices=["auto", "hermes", "direct"])
    p.add_argument("--budget", type=int, help="Sectors credit ceiling for this check")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("check-all", help="audit every watched thesis")
    p.add_argument("--all", action="store_true", help="include theses that are not watched")
    p.add_argument("--limit", type=int)
    p.add_argument("--engine", choices=["auto", "hermes", "direct"])
    p.set_defaults(func=cmd_check_all)

    p = sub.add_parser("queue", help="the worklist, worst first")
    p.set_defaults(func=cmd_queue)

    p = sub.add_parser("credits", help="the credit ledger: spend by endpoint, and cache savings")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_credits)

    p = sub.add_parser("show", help="one thesis with its evidence and history")
    p.add_argument("thesis", help="thesis id or ticker")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("draft", help="propose theses from what the numbers say")
    p.add_argument("--subsector", default="banks")
    p.add_argument("--count", type=int, default=3)
    p.set_defaults(func=cmd_draft)

    p = sub.add_parser("serve", help="run the dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8788)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
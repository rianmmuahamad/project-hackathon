"""Exercise every HTTP endpoint the dashboard uses, against a running server.

The dashboard talks to a JSON API, and nothing in the Python test suite proves
those routes exist, accept their bodies, or return the shape the TypeScript
expects. This does, in a few seconds, against a real server.

    python -m thesisradar serve &        # in another shell
    python tools/api_smoke.py [--base http://127.0.0.1:8788]

Costs Sectors credits only for the endpoints it knowingly triggers (the draft
proposal, and any check it starts), so it stays inside a couple of credits.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

FAILURES: list[str] = []
UA = "thesisradar-smoke/0.1"


def call(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={"Accept": "application/json", "User-Agent": UA,
                 **({"Content-Type": "application/json"} if data else {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode()
            status = response.status
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")[:300]
    except urllib.error.URLError as err:
        return 0, f"connection failed: {err.reason}"
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, raw[:300]


def expect(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{'' if ok else '  — ' + detail}")
    if not ok:
        FAILURES.append(f"{label} ({detail})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8788")
    parser.add_argument("--write", action="store_true",
                        help="also exercise POST routes (creates a thesis and runs a check)")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    print(f"server: {base}")

    status, health = call(base, "GET", "/api/health")
    expect("GET /api/health", status == 200 and isinstance(health, dict) and health.get("ok") is True,
           str(health))
    if status != 200:
        print("\nthe server is not answering; start it with `python -m thesisradar serve`")
        return 1
    engines = (health or {}).get("engine") or {}
    expect("health reports both engines", "hermes" in engines and "direct" in engines, str(engines))

    status, stats = call(base, "GET", "/api/stats")
    expect("GET /api/stats", status == 200 and "store" in (stats or {}) and "credits" in (stats or {}),
           str(stats)[:200])

    status, queue = call(base, "GET", "/api/queue")
    expect("GET /api/queue returns a list", status == 200 and isinstance(queue.get("theses"), list),
           str(queue)[:200])
    rows = (queue or {}).get("theses") or []
    expect("queue rows carry the fields the UI reads",
           all({"id", "symbol", "status", "claims", "changes"} <= set(row) for row in rows),
           "missing keys in a row")

    status, credits = call(base, "GET", "/api/credits")
    expect("GET /api/credits", status == 200 and "credits_spent" in (credits or {}), str(credits)[:200])

    status, notes = call(base, "GET", "/api/notifications")
    expect("GET /api/notifications", status == 200 and isinstance(notes.get("notifications"), list),
           str(notes)[:200])

    status, job = call(base, "GET", "/api/job")
    expect("GET /api/job", status == 200 and "job" in (job or {}), str(job)[:200])

    status, draft = call(base, "GET", "/api/draft?subsector=banks&count=2")
    expect("GET /api/draft proposes theses with evidence",
           status == 200 and isinstance(draft.get("drafts"), list)
           and (not draft["drafts"] or "evidence" in draft["drafts"][0]),
           str(draft)[:300])

    status, missing = call(base, "GET", "/api/thesis/th-does-not-exist")
    expect("unknown thesis is a 404, not a stack trace", status == 404, f"got {status}: {missing}")

    if rows:
        thesis_id = rows[0]["id"]
        status, detail = call(base, "GET", f"/api/thesis/{thesis_id}")
        expect("GET /api/thesis/<id> returns claims and checks",
               status == 200 and isinstance(detail.get("claims"), list)
               and isinstance(detail.get("checks"), list),
               str(detail)[:200])

        status, events = call(base, "GET", "/api/events")
        expect("GET /api/events is an SSE stream", status == 200, f"got {status}")

        latest = (detail.get("checks") or [None])[0]
        if latest:
            status, check = call(base, "GET", f"/api/check/{latest['id']}")
            expect("GET /api/check/<id> returns results, evidence and changes",
                   status == 200
                   and isinstance(check.get("claim_results"), list)
                   and isinstance(check.get("evidence"), list)
                   and isinstance(check.get("changes"), list),
                   str(check)[:200])
            expect("stored evidence carries its endpoint",
                   all(row.get("endpoint") for row in (check.get("evidence") or [])),
                   "an evidence row has no endpoint")

        if args.write:
            status, watched = call(base, "POST", "/api/watch",
                                   {"symbol": rows[0]["symbol"], "action": "add"})
            expect("POST /api/watch", status == 200, str(watched)[:200])

            status, created = call(base, "POST", "/api/thesis",
                                   {"symbol": "TLKM",
                                    "statement": "TLKM laba bersih naik dan pendapatan tumbuh.",
                                    "horizon": "2 kuartal"})
            expect("POST /api/thesis returns a decomposition",
                   status == 200 and isinstance((created or {}).get("decomposition"), dict),
                   str(created)[:300])

            status, read = call(base, "POST", "/api/notifications/read", {})
            expect("POST /api/notifications/read", status == 200, str(read)[:200])

            if (created or {}).get("thesis"):
                new_id = created["thesis"]["id"]
                status, started = call(base, "POST", f"/api/thesis/{new_id}/check", {})
                expect("POST /api/thesis/<id>/check starts a background job",
                       status in (200, 409), f"got {status}: {started}")
                if status == 409:
                    print("       (a job was already running — refusal is the designed behaviour)")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} endpoint check(s) failed:")
        for line in FAILURES:
            print(f"  - {line}")
        return 1
    print("all endpoint checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
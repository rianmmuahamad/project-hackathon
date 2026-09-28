"""Check every endpoint this project calls against the published OpenAPI document.

A wrong path does not raise at import time — it returns a 404 at runtime, which in
a demo is indistinguishable from "the data is missing". This script makes the
mismatch a build-time error instead.

    python tools/verify_endpoints.py [--schema PATH|URL] [--live]

`--live` additionally calls each endpoint once and reports the HTTP status.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SPEC_URL = "https://docs.sectors.app/schema.json"
CACHE = ROOT / ".thesisradar" / "schema.json"

# Endpoints worth a live probe, with arguments that should exist on any recent
# dataset. Deliberately small: this is a shape check, not a crawl.
LIVE_PROBES: list[tuple[str, dict[str, str]]] = [
    ("/v2/companies/", {"where": "sub_sector = 'banks'", "limit": "1"}),
    ("/v2/daily/{symbol}/", {"symbol": "BBRI"}),
    ("/v2/foreign-flow/{symbol}/", {"symbol": "BBRI"}),
    ("/v2/broker-summary/{symbol}/top/", {"symbol": "BBRI"}),
    ("/v2/filings/", {"symbol": "BBRI", "limit": "1"}),
    ("/v2/news/", {"symbols": "BBRI", "limit": "1"}),
    ("/v2/company/report/{symbol}/", {"symbol": "BBRI", "sections": "overview"}),
    ("/v2/financials/quarterly/{symbol}/", {"symbol": "BBRI", "n_quarters": "2"}),
    ("/v2/company/corporate-actions/{symbol}/", {"symbol": "BBRI"}),
    ("/v2/company/get-segments/{symbol}/", {"symbol": "BBRI"}),
    ("/v2/company/shareholders-composition/{symbol}/", {"symbol": "BBRI"}),
    ("/v2/suspensions/", {"symbol": "BBRI", "limit": "1"}),
    ("/v2/subsector/report/{sub_sector}/", {"sub_sector": "banks"}),
    ("/v2/index-daily/{index_code}/", {"index_code": "ihsg"}),
    ("/v2/index-daily/", {}),
    ("/v2/companies/top-changes/", {}),
    ("/v2/tags/", {}),
    ("/v2/companies/quarterly-financial-dates/", {}),
]


def load_spec(source: str) -> dict:
    if source.startswith("http"):
        if CACHE.is_file():
            try:
                return json.loads(CACHE.read_text(encoding="utf-8"))
            except ValueError:
                pass
        # `Python-urllib` is rejected by the CDN in front of the docs with a 1010,
        # same as the API. Identify honestly.
        request = urllib.request.Request(source, headers={
            "Accept": "application/json",
            "User-Agent": "thesisradar/0.1 (+https://github.com/rianmmuahamad/project-hackathon)",
        })
        with urllib.request.urlopen(request, timeout=60) as resp:
            spec = json.loads(resp.read().decode())
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(spec), encoding="utf-8")
        return spec
    return json.loads(Path(source).read_text(encoding="utf-8"))


def paths_used_in_client() -> set[str]:
    """Every literal path string the packaged client sends, normalised.

    f-string arguments appear verbatim in the source (`{bare(symbol)}`), so
    placeholders are collapsed to the OpenAPI spelling (`{symbol}`) before
    comparison — otherwise every parameterised endpoint looks like a mismatch.
    """
    text = (ROOT / "thesisradar" / "sectors.py").read_text(encoding="utf-8")
    found = set(re.findall(r'f?"(/v2/[^"]*?)"', text))
    return {re.sub(r"\{[^}]*\}", "{p}", p) for p in found if p.startswith("/v2/")}


def normalise(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{p}", path)


# Every public client method with arguments that should exist on any dataset.
# These run against a stubbed transport, so they cost nothing and still exercise
# the real request-building code.
CLIENT_PROBES: list[tuple[str, dict]] = [
    ("screener", {"where": "sub_sector = 'banks'", "limit": 1}),
    ("screener", {"q": "top banks", "limit": 1}),
    ("daily", {"symbol": "BBRI", "start": "2026-01-01", "end": "2026-02-01"}),
    ("foreign_flow", {"symbol": "BBRI"}),
    ("foreign_flow_universe", {"limit": 5}),
    ("broker_top", {"symbol": "BBRI", "n_brokers": 3}),
    ("filings", {"symbol": "BBRI", "limit": 2}),
    ("news", {"symbols": "BBRI", "limit": 2}),
    ("company_report", {"symbol": "BBRI", "sections": "overview"}),
    ("segments", {"symbol": "BBRI"}),
    ("shareholders", {"symbol": "BBRI"}),
    ("quarterly", {"symbol": "BBRI", "n_quarters": 2}),
    ("quarterly_dates", {"symbol": "BBRI"}),
    ("corporate_actions", {"symbol": "BBRI"}),
    ("suspensions", {"symbol": "BBRI", "limit": 2}),
    ("subsector_report", {"sub_sector": "banks"}),
    ("index_daily", {"index_code": "ihsg"}),
    ("top_changes", {}),
    ("index_universe", {}),
    ("company_meta", {"symbol": "BBRI"}),
]


def match_template(concrete: str, templates: dict[str, set[str]]) -> set[str] | None:
    """Find the documented template a concrete call path belongs to.

    The stub transport sees `/v2/daily/BBRI/`, the spec documents
    `/v2/daily/{symbol}/`. Each template becomes a one-segment wildcard regex.
    """
    if concrete in templates:
        return templates[concrete]
    for template, declared in templates.items():
        pattern = "^" + re.sub(r"\\\{[^}]*\\\}", "[^/]+", re.escape(template)) + "$"
        if re.match(pattern, concrete):
            return declared
    return None


def probe_client(spec: dict) -> tuple[list[str], int]:
    """Run every client method with a stub transport; report undeclared params."""
    import types

    from thesisradar.sectors import Budget, Sectors

    documented: dict[str, set[str]] = {}
    for raw_path, entry in spec.get("paths", {}).items():
        documented[normalise(raw_path)] = {
            p.get("name") for p in entry.get("get", {}).get("parameters", [])
        }

    captured: list[tuple[str, set[str]]] = []

    def fake_request(self, path: str, params: dict) -> dict:  # noqa: ANN001
        clean = {k for k, v in params.items() if v not in (None, "")}
        captured.append((path, clean))
        return {}

    client = Sectors(api_key="stub", budget=Budget())
    client._request = types.MethodType(fake_request, client)  # type: ignore[method-assign]

    for method, kwargs in CLIENT_PROBES:
        fn = getattr(client, method, None)
        if fn is None:
            captured.append((f"missing method {method}", set()))
            continue
        try:
            fn(**kwargs)
        except Exception as err:  # noqa: BLE001 — bad args are also a finding
            captured.append((f"{method} raised {type(err).__name__}: {err}", set()))

    # Parameters the nested response objects echo back are not request parameters.
    response_keys = {"include_query_values"}
    complaints: list[str] = []
    for path, names in captured:
        declared = match_template(normalise(path), documented)
        if declared is None:
            complaints.append(f"{path} is not in the spec")
            continue
        for name in sorted(names):
            if name not in declared and name not in response_keys:
                complaints.append(f"{path} sends `{name}`, spec declares {sorted(declared)}")
    return complaints, len(captured)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default=SPEC_URL)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    spec = load_spec(args.schema)
    documented = {normalise(p) for p in spec.get("paths", {})}
    used = paths_used_in_client()

    print(f"spec: {args.schema}")
    print(f"documented paths: {len(documented)}")
    print(f"paths the client calls: {len(used)}\n")

    missing = sorted(p for p in used if p not in documented)
    for path in sorted(used):
        mark = "ok  " if path in documented else "MISS"
        entry = spec.get("paths", {}).get(path, {})
        methods = ",".join(m.upper() for m in entry if m in ("get", "post")) if path in documented else ""
        print(f"  {mark} {path:52} {methods}")

    if missing:
        print(f"\n{len(missing)} path(s) are not in the published spec:")
        for path in missing:
            print(f"  - {path}")
        print("\nEither the path changed or it was never right. Fix before shipping.")
        return 1

    # Parameters the client sends must be declared by the spec: an undeclared
    # parameter is typically ignored, which looks like a working call that
    # quietly returned the wrong slice of data. Verified by running the real
    # client methods against a stubbed transport — no network, no credits.
    undeclared, probed = probe_client(spec)
    for line in undeclared:
        print(f"  - {line}")
    if undeclared:
        print(f"\n{len(undeclared)} parameter mismatch(es) across {probed} probe(s)")
        return 1
    print(f"\nparameter check: {probed} client call(s) send only declared parameters")

    if args.live:
        from thesisradar.config import settings
        from thesisradar.sectors import Budget, Sectors, SectorsError

        if not settings().has_key:
            print("\n--live skipped: SECTORS_API_KEY is not set")
            return 0
        client = Sectors(budget=Budget(limit=len(LIVE_PROBES) + 4))
        print(f"\nlive probes ({len(LIVE_PROBES)}):")
        failures = 0
        for raw_path, params in LIVE_PROBES:
            # Path parameters belong in the path. This API rejects unknown query
            # parameters outright, so sending `symbol` twice is a 400 — a harness
            # bug that would otherwise look like a client bug.
            remaining = dict(params)
            path = raw_path
            for placeholder in re.findall(r"\{(\w+)\}", raw_path):
                value = remaining.pop(placeholder, None)
                if value is None:
                    continue
                # The client's own spellings: lowercase index codes, bare tickers.
                if placeholder == "index_code":
                    value = value.lower()
                path = path.replace(f"{{{placeholder}}}", value)
            if "{" in path:
                failures += 1
                print(f"  SKIP {raw_path} (no probe value)")
                continue
            try:
                client._request(path, remaining)
                print(f"  200 {path}")
            except SectorsError as err:
                failures += 1
                print(f"  ERR {path}\n      {err}")
        print(f"\n{len(LIVE_PROBES) - failures}/{len(LIVE_PROBES)} endpoints answered")
        return 1 if failures else 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
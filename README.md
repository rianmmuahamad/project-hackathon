# Thesis Radar

**Problem statement (1 sentence):** People who own Indonesian stocks write down a reason for
holding them and then never re-test it, so a thesis that has quietly stopped being true keeps
driving decisions — and nothing in the market tells them which part broke.

Thesis Radar turns "why I own this" into claims a program can check, measures them against
Sectors data on every run, and puts an agent on the questions arithmetic cannot settle — is this
move the company's or the whole market's, is it the mechanical result of a corporate action, is
the money still moving the way the position assumes. The verdict is allowed to be *the thesis no
longer holds*, and two of the first real runs came back that way.

> **Ringkas (ID):** Orang menulis alasan membeli sebuah saham lalu tidak pernah mengujinya lagi.
> Thesis Radar memecah alasan itu jadi klaim yang bisa diperiksa, mengukurnya terhadap data
> Sectors, dan menugaskan agen pada pertanyaan yang tidak bisa dijawab aritmetika: apakah
> pergerakan ini milik perusahaan atau pasar, apakah cuma efek aksi korporasi, apakah uangnya
> masih bergerak sesuai posisi. Jawabannya boleh "tesis ini sudah tidak berlaku" — dan itu
> memang keluar dari run nyata pertama.

---

## The failure this exists to prevent

A metric can move for a reason that has nothing to do with the business, and the naive reading
is not just late — it is wrong. Two examples from live runs:

| | What a screener sees | What the check showed | Verdict |
| --- | --- | --- | --- |
| **BBRI** | "NII +7.9% YoY, loans +16.4% YoY" | The two arithmetic claims held. The written claim — *"laba masih akan naik dua kuartal ke depan"* — did not: the last three quarters moved **+6.9%, −0.9%, −0.3%**. The price fall was entirely IHSG beta (−5.79% index vs −3.08% stock), so it said nothing about the company | `weakened` |
| **BMRI** | "gross loans −1.5% YoY" | The reported loan series **breaks**: Rp1,850T → Rp1,568T in one quarter. That is a restatement or a change of definition, not a bank shrinking 15% in three months — so the year-on-year figure spans two different definitions and cannot be quoted at all | `needs_review`, with the discontinuity named |

The second one is the product working on itself: the first version of the measurement code
happily reported "loans fell 1.5%" across that break. It now refuses.

---

## How it works

```
                        ┌──────────────────────────────────────────────┐
  Sectors Financial API │  decompose (0-1 credit)                      │
  ─────────────────────►│  "kredit tumbuh 10% & laba naik terus"       │
                        │   → claim[gross_loan, up, ≥10%, growth]      │
                        │   → claim[earnings, up]                      │
                        │   → unresolved: "beli BBRI" (intent word)    │
                        └───────────────────┬──────────────────────────┘
                                            │ baseline recorded now
                                            ▼
                        ┌──────────────────────────────────────────────┐
                        │  MEASURE — code, not a model (1 credit)      │
                        │  · latest value, YoY, quarterly shape        │
                        │  · threshold test (level vs growth)          │
                        │  · discontinuity guard on the series         │
                        └───────────────────┬──────────────────────────┘
                                            ▼
                        ┌──────────────────────────────────────────────┐
                        │  INTERPRET — the agent (0-8 credits)         │
                        │  chooses from 10 tools:                      │
                        │   what_changed · fundamentals_delta ·        │
                        │   flow_delta · insider_activity ·            │
                        │   corporate_action_check · sector_context ·  │
                        │   market_context · news_search ·             │
                        │   screen_companies · evidence_ledger         │
                        └───────────────────┬──────────────────────────┘
                                            ▼
                    verdict + per-claim states + what changed
                          + evidence with endpoints + transcript
```

### The split that makes a verdict trustworthy

**Code measures.** Latest value, year-on-year change, the quarterly shape, and the threshold
test are computed in Python from stored rows. No number in a verdict is typed by a model.

**The agent interprets.** Sector and market context, corporate actions, insider behaviour, why a
claim weakened, what changed since the last check, and how confident the conclusion deserves to
be. Every tool it chooses is recorded.

When no engine is available the measurements and the evidence trail are still produced and the
verdict degrades to `needs_review`, saying so. The product never invents an opinion it cannot
justify.

### Memory is the product

Each check stores a **watermark** — the date it looked forward from. The next check reads only
what is newer than it, which is why re-checking is nearly free and why the change strip
("since 22 Sep: …") is evidence rather than a summary.

---

## What makes this an agent product, not an MCP client

The track disqualifies wiring an off-the-shelf client to the Sectors MCP with a clever prompt:
*"If the product would disappear when the team's prompt is removed from someone else's client, it
does not meet this track's bar."*

The test this repo has to pass:

```bash
rm -rf prompts/                 # there is no such directory
python -m thesisradar check BBRI   # still measures, still scores, still persists
```

| Track requirement | Where it lives |
| --- | --- |
| Multi-step reasoning flows | `thesisradar/audit.py` — decompose → measure → hypothesise → choose tools → revise → verdict |
| Custom tool-use pipelines | `thesisradar/tools.py` — ten tools that answer *questions* ("is this move the company's or the market's?"), not endpoint wrappers |
| Routing between data sources | the agent chooses across price, foreign flow, broker desks, filings, news, corporate actions, suspensions, subsector peers and the index |
| Memory or state management | `thesisradar/store.py` — theses, claims, checks, evidence, changes, watermarks, notifications, credit ledger |
| Autonomous task execution | budget-bounded checks that run to a verdict unattended; `check-all` sweeps every watched thesis; duplicates are refused rather than re-paid |
| Purpose-built interface | `web/` — a thesis workspace built for exactly one task, served by `thesisradar serve` |

Hermes is used as an **engine, not as the product**, and that is enforced in code: one `Engine`
interface, two implementations (`hermes` — the local agent driven headless with its own toolsets
disabled; `direct` — any OpenAI-compatible endpoint). Deleting Hermes leaves the same loop, the
same tools, the same state, the same interface.

---

## Quickstart

```bash
git clone https://github.com/rianmmuahamad/project-hackathon.git
cd project-hackathon
cp .env.example .env            # add your Sectors API key
python -m thesisradar doctor    # environment, engines, credits

python -m thesisradar new --symbol BBRI \
  "Beli BBRI karena kredit tumbuh minimal 10% YoY dan pendapatan bunga bersih naik terus."
python -m thesisradar check BBRI
python -m thesisradar serve     # dashboard on http://127.0.0.1:8788
```

Python 3.11+ and the standard library for the core; `fastapi` + `uvicorn` for the server;
Node 20+ only to rebuild the dashboard (the build output is committed).

| Command | Cost | What it does |
| --- | --- | --- |
| `new --symbol X "<thesis>"` | 1–2 | split into checkable claims and record each metric's baseline |
| `check X [--budget N]` | ~2–10 | measure, let the agent interpret, persist a verdict |
| `check-all [--all]` | per thesis | sweep every watched thesis, notify only on change |
| `queue` | 0 | the worklist, worst first |
| `show X` | 0 | one thesis with its evidence, history and transcript |
| `draft` | ~6 | propose theses that the reported numbers already support |
| `doctor` | ≤1 | environment, engine availability, credit ledger |
| `serve` | 0 | the dashboard |

### Credit discipline

1,000 credits is a hackathon budget, so the product treats them as a constraint rather than a
footnote:

- every response is cached on disk, keyed by path + query — a re-check reads local files;
- the free `evidence_ledger` read and the quarterly fetch happen once and are shared;
- an identical repeat tool call is **refused**, not re-paid;
- every check runs under a hard credit ceiling and stops when it is reached;
- `radar credits` / `GET /api/credits` report spend per endpoint, including what the cache saved.

---

## Verification

```bash
python tools/verify_endpoints.py          # every client path + parameter against the live OpenAPI doc
python tools/verify_endpoints.py --live   # + one real call per endpoint
python tools/verify_pipeline.py           # end-to-end behaviour, no network, no credits
cd web && npm run build                   # typecheck + bundle
```

`verify_pipeline.py` is the one that matters: it runs the whole pipeline against a stub API whose
numbers are chosen so every answer is known — a claim whose metric grew 17% must clear a 10%
growth threshold, a claim whose metric fell two quarters running must come back `weakening`, a
status change must produce exactly one notification and a no-op must produce none.

## Layout

```
thesisradar/
  config.py     environment, paths
  sectors.py    Sectors API client: cache, credit ledger, end-date clamping
  metrics.py    analyst language → API field; trend, threshold, discontinuity
  thesis.py     decompose a thesis into claims (model-assisted + offline fallback)
  tools.py      the agent's ten tools
  engines.py    Engine interface: hermes | direct
  audit.py      the loop: measure → interpret → persist
  store.py      SQLite: theses, claims, checks, evidence, changes, notifications
  service.py    operations shared by CLI and server
  server.py     JSON API + SSE live transcript
  cli.py        the terminal front end
web/            React 19 + TypeScript + Vite dashboard (built output committed)
tools/          verification scripts
```

## Limits, stated plainly

- Quarterly figures come from the API as reported per quarter (verified against BBRI and BMRI
  series); the product does not restate them, and refuses a comparison it can detect as spanning
  a restatement.
- The API exposes no NIM, NPL or CAR ratios. A thesis phrased with those is mapped to the closest
  reported field **and the tool result says so** rather than silently substituting.
- There is no automated trading, and no investment advice: the product reports what changed and
  how confident it is. Every screen carries that framing.
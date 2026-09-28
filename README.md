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
                        │  DECIDE — Jev, one call, ~1 s (no credits)   │
                        │  per claim: typed state + confidence +       │
                        │  probabilities (not parsed prose)            │
                        │  routing: which further fact would change it │
                        └───────────────────┬──────────────────────────┘
                            ┌───────────────┴────────────────┐
                    decidable == none                otherwise
                            ▼                                ▼
              ┌──────────────────────┐      ┌────────────────────────────────┐
              │  no agent turn       │      │  INTERPRET — the engine         │
              │  verdict from measured│     │  context only, 2-tool budget    │
              │  data alone (≈1 s)    │     │  then Jev guards its prose      │
              └───────────┬──────────┘      └───────────────┬────────────────┘
                          └───────────────┬─────────────────┘
                                          ▼
                    verdict + per-claim states + what changed
                          + evidence with endpoints + transcript
```

The **routing question** is what makes the cheap path possible. Asking the agent to look at market
context when the market did nothing is pure cost; asking Jev whether any available fact would
change the judgement, in the same call that decided the claims, costs nothing and answers it.

### The split that makes a verdict trustworthy

**Code measures.** Latest value, year-on-year change, the quarterly shape, and the threshold
test are computed in Python from stored rows. No number in a verdict is typed by a model.

**Jev decides.** TypeSafe's System One model — not an LLM — takes the measured evidence and
returns a *typed* state for each claim with a calibrated `confidence` and the full probability
distribution, plus one routing question: which single further fact, if any, would change those
judgements. One call, about a second, and nothing parsed out of prose. When no further fact would
change the answer, the agent loop is **skipped entirely**.

**Jev also guards the prose.** The prompt rule "never introduce a number that no tool returned"
used to be a wish, and a live run still produced *"NIM <6%"*. Now every number-shaped token the
agent writes is extracted, and Jev is asked which one, if any, the evidence does not contain. A
flagged report caps the status and is stored as evidence.

**The engine supplies context.** A stock that fell 3% on a day the index fell 3% has told you
nothing about that company; whether a move is a split or a suspension is not in the numbers. That
is the agent's whole job now — prose about context, with a two-tool budget.

Each check stores which path decided it (`decision_path`) and where its confidence came from
(`confidence_source`), so the product's central claim is inspectable rather than asserted.

Measured on real runs, before and after the decision layer:

| | before | after |
| --- | --- | --- |
| a check | 157–187 s | **81 s** |
| per-claim verdict | free-form JSON, sometimes `[]` | typed, with probabilities |
| confidence | the model's own number (`0.35`, `0.4`, `0.6`) | Jev's calibrated value (`0.67`, `0.95`) |
| invented figures | unenforced prompt rule | flagged, capped, stored |

When no engine is available the measurements and the evidence trail are still produced and the
verdict degrades to `needs_review`, saying so; when the decision layer is unreachable the agent
decides alone, exactly as before. The product never invents an opinion it cannot justify.

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
| Multi-step reasoning flows | `thesisradar/audit.py` — decompose → measure → decide (Jev) → interpret → guard → verdict |
| Custom tool-use pipelines | `thesisradar/tools.py` — ten tools that answer *questions* ("is this move the company's or the market's?"), not endpoint wrappers |
| Routing between data sources | Jev decides *whether* the agent needs to run and what it should look for; the agent then chooses across price, foreign flow, broker desks, filings, news, corporate actions, suspensions, subsector peers and the index |
| Memory or state management | `thesisradar/store.py` — theses, claims, checks, evidence, changes, watermarks, notifications, credit ledger |
| Autonomous task execution | budget-bounded checks that run to a verdict unattended; `check-all` sweeps every watched thesis; duplicates are refused rather than re-paid |
| Purpose-built interface | `web/` — a thesis workspace built for exactly one task, served by `thesisradar serve` |

Hermes is used as an **engine, not as the product**, and that is enforced in code: one `Engine`
interface, two implementations (`hermes` — the local agent driven headless with its own toolsets
disabled; `direct` — any OpenAI-compatible endpoint). Deleting Hermes leaves the same loop, the
same tools, the same state, the same interface. The same holds for Jev: the decision layer sits
behind one client with a documented fallback, and `python tools/verify_pipeline.py` proves the
whole pipeline still works when it raises.

### Why a System One model, and not a bigger prompt

Three jobs, three tools, each doing what it is actually good at:

| job | who | why not the others |
| --- | --- | --- |
| measure reported numbers | Python | a language model cannot be trusted with arithmetic |
| decide a claim's state, and guard prose | Jev (`Choice`, `Nul`) | answers arrive as typed values with calibrated probabilities; no tokens to parse, no prose to trust |
| write context prose | an LLM | Jev generates no text at all — this is the one thing it cannot do |

The guardrail is the clearest illustration. Asking an LLM "did you make that number up?" gets an
opinion. Extracting the numbers in code and asking Jev *which one is absent from the evidence*
gets a probability, and it separates cleanly: five honest sentences measured 0.07–0.09, four
invented figures 0.64–1.00, and a sentence with no numbers at all skips the model entirely.

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
- `thesisradar credits` / `GET /api/credits` report spend per endpoint, including what the cache
  saved — the ledger file is `.thesisradar/credits.jsonl`, one line per call.

---

## Verification

```bash
python tools/verify_endpoints.py          # every client path + parameter against the live OpenAPI doc
python tools/verify_endpoints.py --live   # + one real call per endpoint
python tools/verify_pipeline.py           # end-to-end behaviour, no network, no credits
python -m thesisradar serve &             # then, against a running server:
python tools/api_smoke.py [--write]       # every HTTP route the dashboard uses
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
  jev.py        Jev (TypeSafe System One) — decision layer and prose guardrail
  audit.py      the loop: measure → decide → interpret → guard → persist
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
- The prose guardrail checks *numbers*, not claims: it catches "NIM below 5,8%" because no tool
  returned that figure, but a sentence with no figures in it is only as good as the evidence
  underneath it. A sentence that cites nothing skips the model call entirely.
- There is no automated trading, and no investment advice: the product reports what changed and
  how confident it is. Every screen carries that framing.
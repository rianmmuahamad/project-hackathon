# Thesis Radar — Project Reference

The complete technical map of the project: what it is, how every part works, and where each
behaviour lives in the code. For the *investing* concept behind it (what a thesis is, why it goes
stale, how a claim becomes checkable), read [`THESIS-PRIMER.md`](THESIS-PRIMER.md) first.

---

## 1. The problem

An investor writes down why they own a stock:

> "Buy BBRI because loans grow at least 10% YoY and net interest income keeps rising."

That sentence is a **thesis** — a reason, not a price target. It is written once, and then the world
moves. Loan growth decelerates. Net interest income flattens. The price falls for reasons that have
nothing to do with the company.

Nothing tells the owner. The position is still held, but the *reason* for holding it stopped being
true — and the only way to find out was to open the annual report, pull the quarterly figures, and
remember what the original numbers were.

**Thesis Radar closes that gap.** It turns the written reason into machine-checkable claims,
measures them against reported data, and answers one question on a schedule: *does this reasoning
still hold?*

### What it is not

- **Not investment advice.** It reports what changed and how confident it is. It never says buy or
  sell. Every screen carries that framing.
- **Not automated trading.** There is no order path anywhere in the codebase (verified: no
  `order`/`execute`/`broker_order` call exists).
- **Not a chatbot.** There is no free-form chat box. The interface is a research workspace built
  for exactly one workflow.

---

## 2. Three layers of authority

The central design decision: **three different tools do three different jobs, and each one is
better at its job than the others would be.**

| Job | Who does it | Why not the others |
| --- | --- | --- |
| Measure reported numbers | **Python** | A language model cannot be trusted with arithmetic. 16.4% must be 16.4%. |
| Decide a claim's state, guard prose | **Jev** (TypeSafe System One) | Answers arrive as typed values with calibrated probabilities — no prose to parse, no text to trust. |
| Write context prose | **an LLM** (Hermes or any OpenAI-compatible model) | Jev generates no text at all. This is the one job it cannot do. |

Authority is ordered, and the order is enforced in code:

1. **A measurement that already decided a claim wins.** The engine may not overrule arithmetic.
2. **Jev's typed decision beats prose.** It is made from the evidence, with a probability attached.
3. **The engine fills the gap** — the claims nobody else could settle, and the context around them.

The consequence is deliberate: the product is **useful when the model is unavailable**. It degrades
to measurement-only, says so out loud, and caps its own confidence at `0.0`.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  INPUT                                                              │
│  "Beli BBRI karena kredit tumbuh minimal 10% YoY ..."               │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  thesis.decompose()  ← LLM, with an
                               ▼                        offline fallback
┌─────────────────────────────────────────────────────────────────────┐
│  CLAIMS (stored in SQLite)                                          │
│  { metric: gross_loan,           direction: up, threshold: 0.10 }   │
│  { metric: net_interest_income,  direction: up, threshold: null }   │
│  { metric: earnings,             direction: up, threshold: null }   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  THE CHECK  — audit.run()                                           │
│                                                                     │
│  1. watermark      what is new since the last check?   [code]       │
│  2. measure        fetch series, compute YoY, trend,   [code]       │
│                    test thresholds, detect discontinuities          │
│  3. roll up        worst claim decides the status      [code]       │
│  4. brief          assemble the evidence into text     [code]       │
│  5. decide         typed Choice over each unsettled    [Jev]        │
│                    claim, per-claim scoped evidence                 │
│  6. gate           is an agent turn needed at all?     [code]       │
│  7. investigate    loop: model calls tools, or emits   [LLM]        │
│                    the verdict JSON                                 │
│  8. merge          Jev's states stand; the engine may  [code]       │
│                    only touch claims neither settled                │
│  9. guard          does the prose cite a number no     [Jev]        │
│                    tool returned?                                   │
│ 10. finalise       status, confidence, summary         [code]       │
│ 11. persist        claims, evidence, changes, notify   [code]       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  OUTPUT                                                             │
│  verdict · per-claim states · evidence table · change strip ·       │
│  transcript · notification · email digest                           │
└─────────────────────────────────────────────────────────────────────┘
```

Every stage records **who decided it**: `decision_path` is one of
`measurement` · `jev` · `jev+agent` · `agent` · `agent_unverified`.

---

## 4. The pipeline, stage by stage

### Stage 1 — Decompose (`thesis.py`)

A paragraph becomes 1–6 claims that a program can check.

`decompose()` asks the model, with an instruction that is strict about the shape of a claim:

> Every claim MUST have a `metric` from the allowed list, EXCEPT a relative judgement such as
> valuation … for those set `metric` to null and `cadence` to "valuation". Anything else you cannot
> express with an allowed metric goes in `unresolved` — **never invent a metric**.

Two fallbacks exist, and both matter:

- **No engine** → `decompose_offline()`, a heuristic over sentence and conjunction boundaries.
- **Bad reply** → the same heuristic, with `engine_error` recorded so the user can see why.

A claim carries: `text`, `metric`, `direction` (up/down/flat/none), `threshold` and `threshold_target`
(`growth` vs `level`), `cadence` (quarterly/price/flow/insider/news/corporate_action/valuation), and
a baseline value + date captured at thesis time.

Typical output:

```json
{"claims": [
  {"text": "kredit tumbuh minimal 10% YoY", "metric": "gross_loan",
   "direction": "up", "threshold": 0.1, "threshold_target": "growth", "cadence": "quarterly"},
  {"text": "pendapatan bunga bersih naik terus", "metric": "net_interest_income",
   "direction": "up", "threshold": null, "cadence": "quarterly"},
  {"text": "valuasi masih murah dibanding bank besar lain", "metric": null,
   "direction": "none", "cadence": "valuation"}
]}
```

### Stage 2 — Watermark (`audit.compute_watermark`)

Each thesis stores the date the check last looked *forward from*. On a re-check, the client only
asks for data newer than that. This is what makes re-checking nearly free, and why the change strip
("since 22 Sep: …") is evidence rather than a summary.

### Stage 3 — Measure (`audit.measure`)

Pure arithmetic, no model. For each claim:

- convert requested language to an API field — `kredit` → `gross_loan`, `laba bersih` → `earnings`,
  `NII` → `net_interest_income` (a large Indonesian/English alias table, `metrics.METRIC_ALIASES`);
- pull the quarterly series, compute **YoY** and the **quarter-on-quarter steps**;
- test the thesis's own threshold, if it set one;
- apply the **discontinuity guard** (below);
- emit `supported` / `weakening` / `broken` / `unknown`, **with the arithmetic written out** as the
  rationale.

The threshold test is checked *first*, because a number is not an opinion:

```python
if threshold_ok is False:
    return BROKEN, "...the thesis set a >= threshold of 0.1 on growth and the
                     reported figures do not clear it"
```

Then the direction, with the trend rule:

```python
if trending is True:   return SUPPORTED, "...and the last movements are all up, so the claim holds"
if trending is False:  return WEAKENING, "...but the recent movements (+6.9%, -0.9%, -0.3%)
                                          are not consistently up, so the claim no longer holds"
```

### The discontinuity guard (`metrics.break_index`)

The most important correctness decision in the codebase.

A real case: BMRI's reported `gross_loan` moved **Rp1,850T → Rp1,568T in one quarter (−15.2%)**. The
naive code read this as a true decline, reported "−1.5% YoY", and marked the thesis `broken`.

It was a **restatement** — the reported series changed basis, not the business. So each metric now
carries an asymmetric band, and a quarter-on-quarter move outside it is treated as a **data
integrity signal, not a trend**:

```python
DISCONTINUITY_BANDS = {
    "gross_loan": (0.20, 0.08),      # growth up to +20% plausible; shrinkage beyond -8% is not
    "revenue":    (0.60, 0.45),
    "provision":  (1.20, 0.90),
    ...
}
DEFAULT_BAND = (1.00, 0.60)
```

Bands are **asymmetric on purpose**: a bank's loan book can grow 20% in a quarter, but it cannot
shrink 20% without something extraordinary having happened. When a break is detected the product
**refuses the comparison**, sets the claim to `unknown`, and stores the break as evidence with its
date and the band used — an honest "I cannot compare across this line" instead of a confident wrong
answer.

### Stage 4 — Roll up (`audit._status_from_states`)

The worst claim decides the thesis:

```
any claim broken      → broken
any claim weakening   → weakened
all supported         → intact
otherwise             → needs_review
```

### Stage 5 — Decide (Jev)

`audit._decide_with_jev()` asks Jev a **typed `Choice` question per unsettled claim**, carrying only
that claim's own evidence. It returns a state plus a calibrated probability, and the code records
whether it overruled the arithmetic. A stored example, verbatim:

```
"Jev overruled the measurement (supported → weakening): Jev decided weakening
 over this claim's measured evidence (confidence 0.95)"
```

Read that literally: **the arithmetic said this claim was supported, and the decision layer
disagreed with a 0.95 probability.** It is exactly the case where the numbers alone were not enough.

This stage also does **routing**: its answer determines whether the agent runs at all (`needs_agent`).

### Stage 6 — Gate (`audit.py:762`)

```python
needs_agent   = (not fully_decided) or (decidable not in (None, "none"))
loop_rounds   = 0 if not needs_agent else min(max_rounds, TOOL_CALLS_WHEN_ASSISTED)
```

If every claim was already decided from measured data, **the model is never called**. This is why a
fully-decided check is near-instant and costs almost nothing.

### Stage 7 — Investigate (the agent loop)

A real loop, written in this repo — not a single prompt:

```python
for round_no in range(loop_rounds):          # MAX_TOOL_ROUNDS = 3
    if sectors.budget.remaining <= 0: break  # hard credit ceiling
    turn = engine.reply(SYSTEM, messages, tools.schemas())
    ...
    if fingerprint in seen_calls:            # an identical repeat is REFUSED, not re-paid
        messages.append({"role": "user", "content":
            "You already called {name} with those exact arguments; the result is above
             and unchanged. Choose a different tool or conclude."})
        continue
    outcome = tools.execute(name, args, sectors, store)
    messages.append({"role": "user", "content": _results_message(None, name, outcome)})
```

Behaviours encoded in the loop:

- **Budget ceiling** stops the loop mid-investigation, and the transcript says so.
- **Duplicate-call refusal** — the same tool with the same arguments is answered from the
  transcript instead of spending another credit.
- **Nudge on a stall** — a reply with neither a tool call nor a verdict JSON gets told to produce one.
- **Early exit** — a usable verdict JSON breaks the loop immediately.

The model's one job, from `SYSTEM`: *the decided claims are not yours to revisit; your job is
context* — is the move in the company or the sector, is the price action real or a split/halt
artefact, is the money still flowing the way the thesis assumes, does the story have a dated cause.

### Stage 8 — Merge (with a veto)

```python
if _measurement_shortfall(measurement) is None and claim_id in jev_states:
    # Refused: the claim was decided from measured data, and prose
    # does not get to overrule arithmetic.
    overrule_notes.append(f"...engine proposed {state}, refused in favour of {measured_state}")
    continue
```

The engine can only touch a claim that **neither** arithmetic **nor** Jev could settle. Everything
else is refused and recorded in the notes.

### Stage 9 — Guard (Jev)

A prose guardrail, and the design that replaced a broken one.

An LLM answer to "did you make that number up?" is an opinion. So the code extracts every
number-shaped token from the prose and asks Jev a **positively-framed `Choice`**: *which of these
candidates is absent from the evidence?*

Measured behaviour: five honest sentences scored 0.07–0.09; four fabricated figures scored
0.64–1.00; a sentence with no numbers skips the model entirely. Threshold `0.5`.

A flag caps the status (`intact` → `weakened`), prefixes the summary with `⚠︎`, stores the offending
number as evidence, and caps confidence. Rejected alternative, for the record: a *negated* question
("does the report cite any number not present…") scored honest sentences at 0.65–0.89 — including one
with no numbers at all at 0.76. Positively-framed Choice over code-extracted candidates is what
works.

### Stage 10–11 — Finalise and persist

Status, confidence (Jev's calibrated probability when Jev decided; capped when unguarded), a summary
a human can act on, then one transaction writing claims, evidence, changes, and — only when the
status actually moved — a notification.

---

## 5. Data layer (`sectors.py`)

- **REST, not MCP.** `https://api.sectors.app`, **17 distinct query paths** under `/v2/...`, plain
  `urllib` — no third-party HTTP client, so the client runs in a bare interpreter.
- **Disk cache** keyed by `sha256(path + "?" + urlencoded params)`. A re-check reads local files, and
  a cache hit is recorded in the ledger with `credits: 0` so the saving is visible.
- **Credit ledger** — append-only `.thesisradar/credits.jsonl`, one line per call, reported per
  endpoint including what the cache saved.
- **Hard budget ceiling** per check (`THESISRADAR_CHECK_BUDGET`, default 25).

Endpoint paths used (17):

```
financials/quarterly/{sym}        daily/{sym}                foreign-flow/{sym}
foreign-flow/                     broker-summary/{sym}/top/  filings/
news/                             company/report/{sym}       company/get-segments/{sym}
company/shareholders-composition/{sym}
company/corporate-actions/{sym}   company/get_quarterly_financial_dates/{sym}
subsector/report/{sector}         suspensions/               companies/
companies/top-changes/            index-daily/{index}        index-daily/
tags/
```

---

## 6. Memory (`store.py`)

Eight SQLite tables (WAL mode). This is what makes the product a *system* rather than a function
call:

| Table | Holds |
| --- | --- |
| `theses` | symbol, statement, status, confidence, **watermark**, watch flag, baseline |
| `claims` | decomposed claims: metric, direction, cadence, threshold, baseline value + date |
| `checks` | one row per run: verdict, confidence, credits, tool_calls, `decision_path`, `confidence_source`, `since` |
| `claim_results` | per-claim state + observed value + date + delta + **the rationale** |
| `evidence` | every number with its source: metric, value, as_of, **endpoint**, params, note |
| `changes` | what moved since the last check, with magnitude and the evidence ordinal |
| `notifications` | status transitions, with severity `alert`/`warning`/`info`/`ok` |
| `runs` | job lifecycle and log paths |

The evidence table is the audit artifact: **every number in a verdict traces to an endpoint and a
parameter set**. The dashboard exposes it with a copyable `curl` per row.

---

## 7. The agent (`tools.py`, `engines.py`)

**Ten tools**, defined as JSON Schema, each answering a *question* rather than wrapping an endpoint:

| Tool | Question it answers |
| --- | --- |
| `what_changed` | Everything new since a date — price, flow, filings, news, actions. The cheapest first call. |
| `fundamentals_delta` | The quarterly series for one metric, with YoY and QoQ. |
| `flow_delta` | Is the money still arriving, or has it turned? |
| `insider_activity` | Insider and major-shareholder buy/sell filings, dated. |
| `corporate_action_check` | Is this price move real, or a split/rights/dividend artefact? Is it suspended? |
| `sector_context` | Is the move the company's, or the whole sector's? |
| `market_context` | What did the IHSG do over the same window? |
| `news_search` | Dated articles, to test a causal story. |
| `screen_companies` | Find stocks by plain language or SQL-like criteria. |
| `evidence_ledger` | What this product already knows. Zero credits — read it first. |

**Two engines behind one interface** (`engines.Engine`), so Hermes is removable:

- `hermes` — drives the locally installed Hermes agent headless with **its own toolsets disabled**
  (`-t '' --ignore-rules --max-turns 8`). Hermes is used as a *model endpoint*, not as the product:
  the loop, the tools, the toolsets, the state and the UI are all this repo's.
- `direct` — any OpenAI-compatible endpoint with native function calling.

`engines.make()` picks the best available and reports which.

---

## 8. Autonomy

A product that only reports a change to someone already staring at the dashboard has not solved the
problem. So the sweep runs itself:

- **The server owns the clock.** `serve` starts the schedule in the FastAPI lifespan and stops it on
  shutdown — `THESISRADAR_SCHEDULE_AT` (default `08:00`), `THESISRADAR_SCHEDULE_DAYS`
  (default `mon,tue,wed,thu,fri`), `Asia/Jakarta`.
- **The clock takes "now" as an argument** (`schedule.due_at(now, when, days)`), so it is verified by
  arithmetic instead of by sleeping until morning.
- **The timer waits on a `threading.Event`, never `time.sleep`** — `stop()` returns in ~0 ms, and
  `start()` twice is a no-op.
- **One daemon thread**, and a sweep that raises is reported to `on_error` rather than killing the
  thread. A scheduler that dies silently is worse than no scheduler.
- **The digest is built from stored notifications**, not from the sweep's return value — so a manual
  button press and a scheduled run produce the same email. `ok` transitions are silenced (a return
  to `intact` is not news); `info` is kept, because a first-ever check is the product's first useful
  message.
- **Delivery is best-effort.** An unreachable relay is recorded as `emailed: false` with the error
  and never raises — the checks ran, the evidence is stored, and the run degrades to what the product
  was before email existed instead of losing a sweep.

`python -m thesisradar scheduler --now` is the demo path: one sweep, then wait. `Scheduler.run_once()`
is the documented entry point for an external driver (systemd timer, `hermes cron`) if a deployment
wants the timer outside the process.

---

## 9. Interfaces

**CLI** — the same service calls the dashboard makes:

| Command | Cost | What it does |
| --- | --- | --- |
| `new --symbol X "<thesis>"` | 1–2 | split into claims, record baselines |
| `check X [--budget N]` | ~2–10 | measure, interpret, persist a verdict |
| `check-all [--all]` | per thesis | sweep every watched thesis |
| `queue` | 0 | the worklist, worst first |
| `show X` | 0 | one thesis with evidence, history, transcript |
| `draft` | ~6 | propose theses the reported numbers already support |
| `credits` | 0 | spend per endpoint, including cache savings |
| `digest [--send]` | 0 | build the pending digest; email it |
| `scheduler` | per thesis | run the sweep unattended, on a wall clock |
| `doctor` | ≤1 | environment, engines, email, credit ledger |
| `serve` | 0 | the dashboard, which also runs the schedule |

**HTTP API** — 15 JSON/SSE routes, plus two static-file routes serving the built dashboard.

*Reads* (`GET`): `health`, `stats`, `queue`, `thesis/{id}`, `check/{id}`, `notifications`, `credits`,
`job`, `draft`, and `events` — the last being an SSE stream carrying the live transcript of the
running job, which is what the dashboard's live panel renders.

*Writes* (`POST`): `thesis` (create), `thesis/{id}/check`, `check-all`, `watch`,
`notifications/read`.

**Dashboard** — React 19 + TypeScript + Vite, four domain pages and **no chat box**:

1. **Queue** — the worklist, worst first, with watermark, stats, and the scheduled-digest table.
2. **Compose** — a thesis *statement* textarea (natural language in, claims out), plus model-drafted
   suggestions the user must confirm or edit.
3. **Thesis workspace** — the file: change strip, claims table, evidence table (search, expandable
   rows, copyable `curl`), typed transcript with a raw toggle.
4. **Notifications** — status transitions only.

The `DecisionBadge` shows which layer decided — *"decided by Jev from measured data; no agent turn
needed"*, *"decided by the model alone; confidence is capped"*, *"no interpretation layer was
available"*.

---

## 10. Configuration

`.env` (mode 600, git-ignored; never committed):

```
SECTORS_API_KEY=                  # required
SECTORS_API_BASE=https://api.sectors.app
THESISRADAR_HOME=.thesisradar
THESISRADAR_ENGINE=auto           # auto | hermes | direct
THESISRADAR_MODEL=
THESISRADAR_CHECK_BUDGET=25

# Decision layer
THESISRADAR_JEV_BASE=https://mot.coddx.store/v1
THESISRADAR_JEV_KEY=
THESISRADAR_JEV_MODEL=jev-1.13-free
THESISRADAR_JEV_TIMEOUT=30

# Schedule
THESISRADAR_SCHEDULE_AT=08:00
THESISRADAR_SCHEDULE_DAYS=mon,tue,wed,thu,fri

# Email
THESISRADAR_SMTP_HOST=
THESISRADAR_SMTP_PORT=587         # 587 STARTTLS, 465 implicit TLS
THESISRADAR_SMTP_USER=
THESISRADAR_SMTP_PASSWORD=
THESISRADAR_SMTP_FROM=            # defaults to SMTP_USER
THESISRADAR_SMTP_TO=              # comma-separated
THESISRADAR_SMTP_TLS=1            # 0 = implicit TLS on connect
```

Every layer has a documented fallback, so the product runs with only `SECTORS_API_KEY`.

---

## 11. Verification

```bash
python tools/verify_pipeline.py     # end-to-end behaviour, no network, NO credits, no model
python tools/verify_endpoints.py    # every client path + parameter against the live OpenAPI doc
python tools/verify_endpoints.py --live
python tools/api_smoke.py [--write] # every HTTP route the dashboard uses
cd web && npm run build             # tsc --noEmit && vite build
```

`verify_pipeline.py` is the one that matters. It stubs the Sectors transport (so the real parsers
still run) and the decision layer, and asserts **observable behaviour** against numbers whose answer
is known in advance:

- a claim whose metric grew 17% must clear a 10% threshold;
- a metric that fell two quarters running must come back `weakening`;
- a restatement-shaped jump must be refused, not reported;
- a status change produces exactly one notification, and a no-op produces none;
- a scheduled sweep sends exactly one email for a real change, none when nothing moved, and survives
  a relay that refuses the connection;
- when every claim is decided, **the engine is never called**;
- when the decision layer raises, the agent still decides, exactly as before.

The suite is deliberately hard to fool: stubbing `quarterly()` instead of the transport would have
hidden the flattening logic, and a series that silently came back empty would have looked like a
product bug.

---

## 12. Limits, stated plainly

- Quarterly figures come from the API as reported per quarter; the product does not restate them,
  and refuses a comparison it can detect as spanning a restatement.
- The API exposes no NIM, NPL or CAR ratios. A thesis phrased with those is mapped to the closest
  reported field **and the tool result says so**, rather than silently substituting.
- The prose guardrail checks *numbers*, not claims. A sentence with no figures in it is only as good
  as the evidence underneath it — and a sentence that cites nothing skips the model call entirely.
- The schedule is in-process and in-memory: it runs while `serve` (or `scheduler`) is running, and
  knows nothing about a run that happened on another machine. The durable record is the
  `notifications` table, not the digest history.
- Email is one-way and best-effort. No retry queue, no read receipt.
- **With no engine and no decision layer the product still emits a verdict** from measurement alone
  (`decision_path: measurement`, `confidence: 0.0`, summary prefixed *"Measured without an agent"*).
  For a claim that only the model can settle — valuation, for instance — it returns `needs_review`.
  The honest statement of the split: **the AI decides the qualitative claims and the context; the
  arithmetic decides the quantitative ones.**

---

## 13. File map

```
thesisradar/
  config.py     environment, paths, feature detection (has_key, jev_configured, email_configured)
  sectors.py    Sectors REST client: disk cache, credit ledger, budget ceiling, end-date clamping
  metrics.py    analyst language → API field; YoY, trend, threshold, discontinuity bands
  thesis.py     decompose a thesis into claims (model-assisted + offline fallback)
  tools.py      the agent's ten tools (JSON Schema) + execute()
  engines.py    Engine interface: hermes | direct
  jev.py        Jev (TypeSafe System One) client — decision layer and prose guardrail
  audit.py      the loop: measure → decide → interpret → guard → persist
  store.py      SQLite: theses, claims, checks, claim_results, evidence, changes, notifications, runs
  transcript.py decode the raw transcript into typed segments; link evidence to segments
  service.py    operations shared by CLI and server; jobs, scheduled sweep, digest history
  schedule.py   the clock: parse_when, parse_days, due_at, one daemon thread
  mailer.py     the digest: notification rows → one plain-text email
  server.py     JSON API + SSE live transcript + the schedule lifespan
  cli.py        the terminal front end
web/            React 19 + TypeScript + Vite dashboard (built output committed)
tools/          verification scripts
```

**Core rule:** the agent core, the Sectors client and the store are **standard-library Python** on
purpose. They run in a bare interpreter, inside Hermes' managed venv, and in CI with no drift.
`requirements.txt` holds only `fastapi` + `uvicorn` for the server layer.

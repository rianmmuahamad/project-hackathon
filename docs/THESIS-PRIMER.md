# The Thesis Primer

If the idea behind this project has never been explained to you, start here. Nothing in this
document is about code. It is about the concept the code serves.

---

## Part 1 — What a "thesis" is

An **investment thesis** is the written reason you own something.

Not the price. Not the chart. The *reason*:

> "I own BBRI because loans grow at least 10% YoY and net interest income keeps rising."

That sentence has three properties that matter:

1. **It is written down**, once, in ordinary language.
2. **It contains checkable facts.** "Loans grow at least 10% YoY" is a number that a report either
   shows or does not. It is not "IT'S GOING TO THE MOON".
3. **It can stop being true while the price is still fine.**

That third property is the entire problem.

### Why a thesis goes stale

Consider a real sequence. You buy a bank because loans are growing double digits and margins are
expanding. Six months later:

- loan growth has slowed to 4%;
- margin expansion has flattened;
- the share price is *up*, because the whole sector is up.

Most people would look at that position and feel fine — the price is green. But the *reason* is gone.
You are now holding a stock for a reason you no longer believe, and you would not buy it again today.
Nobody told you. That is the failure this product exists to prevent.

### The difference between a thesis and a prediction

A thesis is **not** "the price will go up". Price is an output of thousands of things, most of them
outside the company. A thesis is a statement about the **business facts** the position rests on.

That distinction is what makes the problem tractable. Nobody can check a price prediction. Everyone
can check whether loans are still growing at 10%.

---

## Part 2 — What a "claim" is

To check a written reason, you split it into **claims**.

Take:

> "Beli BBRI karena kredit tumbuh minimal 10% YoY dan pendapatan bunga bersih naik terus, jadi laba
> masih akan naik dua kuartal ke depan."

This is **three separate claims**, not one:

| # | Claim (verbatim from the thesis) | The fact it asserts | Checkable? |
| --- | --- | --- | --- |
| 1 | *kredit tumbuh minimal 10% YoY* | gross loans grew ≥10% year-on-year | Yes — a number and a threshold |
| 2 | *pendapatan bunga bersih naik terus* | net interest income is rising | Yes — a direction over time |
| 3 | *laba masih akan naik dua kuartal ke depan* | earnings keep rising | Yes — a direction, outcome known later |

And this sentence:

> "BMRI kredit tumbuh dua digit dan laba bersih naik, dan valuasi masih murah dibanding bank besar lain."

is **also** three claims — but the last one is a *different kind* of animal:

| # | Claim | The fact it asserts | Checkable? |
| --- | --- | --- | --- |
| 1 | *BMRI kredit tumbuh dua digit* | gross loans grew ≥10% | Yes |
| 2 | *BMRI laba bersih naik* | earnings are rising | Yes |
| 3 | *valuasi masih murah dibanding bank besar lain* | it is cheap **relative to its peers** | **Not by one number** |

Claim 3 is not a metric. It is a **relative judgement**. It needs a comparison against other banks,
not a single figure from a report. This distinction drives a lot of the design: the first two can be
settled by arithmetic, and the third has to be settled by judgement over evidence.

Every claim therefore carries a small set of attributes:

| Attribute | Meaning | Example |
| --- | --- | --- |
| `metric` | which reported number settles it | `gross_loan` |
| `direction` | what the thesis asserts about it | `up` |
| `threshold` | the bar the thesis set, if any | `0.10` = 10% |
| `threshold_target` | is that bar a **growth rate** or a **level**? | `growth` |
| `cadence` | which data family would settle it | `quarterly` |
| `baseline_value` / `baseline_date` | the number at the moment the thesis was written | Rp1,580.42T @ 2026-06-30 |

That last pair is what makes the comparison honest: you always measure against **what was true when
you wrote the sentence**, not against some arbitrary start date.

### Why the threshold distinction matters

"NIM above 5.8%" sets a **level**. "Kredit tumbuh 10%" sets a **growth rate**. Same-looking
sentence shape, completely different test. If you test a level as though it were a growth rate, the
claim becomes permanently untestable. The code carries this distinction explicitly as
`threshold_target`.

---

## Part 3 — What "measuring" a claim means

Now the concrete part. This is the real, stored result for BBRI:

```
kredit tumbuh minimal 10% YoY
  gross_loan is +16.4% year-on-year
  and the last movements are all up, so the claim holds          → supported

pendapatan bunga bersih naik terus
  net_interest_income is +7.9% year-on-year
  and the last movements are all up, so the claim holds          → supported

laba masih akan naik dua kuartal ke depan
  earnings is +22.3% year-on-year
  but the recent movements (+6.9%, -0.9%, -0.3%)
  are not consistently up, so the claim no longer holds cleanly  → weakening
```

Read claim 3 carefully, because it is the whole idea in one line.

Earnings are **up 22.3% year-on-year** — a headline that sounds bullish. But the last three quarters
went **+6.9%, then −0.9%, then −0.3%**. The yearly number is still positive because of what happened
twelve months ago; the thing the thesis actually claims — earnings *keep rising* — has stopped
happening.

**That is the difference between a number and a thesis.** A screener would show you +22.3% and you
would feel good. The thesis test shows you the trend, and the trend says the reason is gone.

### The four states

| State | Meaning |
| --- | --- |
| `supported` | the arithmetic and the thesis agree |
| `weakening` | the metric is still fine, but the movement the thesis asserts has stopped |
| `broken` | the thesis's own threshold is not met — no judgement needed |
| `unknown` | it cannot be settled from this metric, and must be judged |

Then the states roll up into one verdict for the whole thesis — **the worst claim decides**:

```
any claim broken     → broken
any claim weakening  → weakened
all supported        → intact
otherwise            → needs_review
```

---

## Part 4 — Why a number can lie: the discontinuity problem

This is the single most important story in the project, and it is a *real* case, not a hypothetical.

BMRI's reported `gross_loan` went:

```
Rp1,850T  →  Rp1,568T     (−15.2% in ONE quarter)
```

The naive reading: loans collapsed. Mark the thesis broken.

The correct reading: **the reported series changed basis.** A restatement. The bank did not lose 15%
of its loan book in three months — the figure was re-presented on a different definition.

The first version of this code got it wrong. It reported "−1.5% YoY" and marked the thesis `broken`.
That is a *confidently wrong answer* — the worst possible output, because it looks authoritative.

The fix: every metric carries an **asymmetric band** of plausible quarter-to-quarter movement.

```python
"gross_loan": (0.20, 0.08)   # +20% growth is plausible; −8% shrinkage is not
"revenue":    (0.60, 0.45)
"provision":  (1.20, 0.90)   # loan-loss provisions swing hard in both directions
```

**Asymmetric on purpose.** A bank's loan book can grow 20% in a quarter. It cannot *shrink* 20%
without something extraordinary having happened. When a move falls outside the band, the product
**refuses the comparison**, sets the claim to `unknown`, and stores the break as evidence — with the
date and the band it used.

The output becomes: *"The reported gross_loan series is inconsistent: it moves −15.2% between
2025-12-31 and 2026-03-31, which is a restatement, not trading."*

An honest "I cannot compare across this line" beats a confident wrong number. That principle runs
through the whole product.

---

## Part 5 — The three questions, and who answers them

A check answers three questions. Each has a different best tool.

**Q1. What do the numbers say?**
→ **Arithmetic.** Did loans grow 10%? Did earnings rise three quarters running? No model touches
this. A language model cannot be trusted with a percentage.

**Q2. What do the numbers *mean* here?**
→ **Judgement.** Is a −3% move about the company, or did the whole index fall 3% that day? Is the
price drop real, or the mechanical result of a stock split? Does the story have a dated cause — did
this happen on a day with actual news, or is the explanation invented after the fact?
→ This is where a model earns its place, because it is not a lookup.

**Q3. Is the reasoning still sound?**
→ **The verdict**, rolled up from the claims.

### A worked example of Q2

```
BBNI fell from 3860 to 3460 over 21 traded sessions, with 0 no-trade sessions,
no corporate actions and no suspensions — the price move is real, not a split,
dividend or halt artefact.                                    [−10.36%]

Foreign flow net selling across the window, with sell pressure dominating
buy days.                                  [−Rp178.4B net, 5 buy vs 15 sell days]

New since the watermark: a 2026-09-28 note on liquidity tightening (faster
credit growth than deposit growth), plus 2026-09-27 news naming BBNI among
top foreign net-sell stocks amid broad bank selling.
```

None of those three paragraphs is arithmetic. All three change how you read the numbers. The first
rules out a *fake* price move. The second shows the money is leaving. The third gives the move a
dated cause.

And crucially: the last one also *settled a claim arithmetic could not*. For BMRI, the valuation
claim came back:

```
unknown → supported
"what_changed news on 2026-09-27 reports BMRI and BBNI flagged as cheap stocks"
```

That is the LLM doing the job only it can do: taking a relative judgement with no single metric and
finding evidence for it.

---

## Part 6 — Why the model is not allowed to make things up

If a model writes prose about your money, it can invent a number. It does this fluently, and it
sounds more confident when it does.

So the product runs a **guardrail on the prose**: the code extracts every number-shaped token the
model wrote, and asks a purpose-built decision model *which of these did no tool actually return?*

This is not a prompt asking "are you sure?". It is a typed question with code-extracted candidates.

Measured result: five honest sentences scored **0.07–0.09**; four invented figures scored
**0.64–1.00**. A sentence with no numbers skips the question entirely.

When it fires, the product does four things at once:

1. caps the status (`intact` → `weakened`),
2. prefixes the summary with a visible warning marker,
3. stores the offending figure as evidence, so the audit trail shows what was caught,
4. caps confidence — an unverified claim cannot carry high confidence.

The rejected alternative is worth knowing, because it shows why "just ask the model" fails: a
*negated* question ("does the report cite any number not present…") scored honest sentences at
**0.65–0.89** — including one with no numbers in it at all, at 0.76. Asking positively, over
candidates the code extracted, is what works.

---

## Part 7 — Why the product only speaks when something changed

A daily message that always says "all fine" is a message nobody reads. By the time it matters, it has
been filtered out of your attention.

So the product is built to be **silent**:

- A check stores a **watermark** — the date it is allowed to read forward from. On a re-check it only
  asks the API for what is *newer than that*. Which is why the change strip ("since 22 Sep: …") is
  real evidence rather than a summary, and why re-checking costs almost nothing.
- A notification fires **only on a status transition** — `weakened → broken`, not "checked, still
  fine".
- The email digest silences a return to `intact`. That is not news.
- A check whose claims were all decided from measured data **never calls the model at all**. Measured
  on the stub pipeline: **74.7 ms, zero model turns**, `decision_path: jev`. That is the whole reason
  the product can afford to run on a schedule.

And the schedule is the point: the sweep runs on a wall clock (`08:00`, weekdays, Jakarta time) with
nobody watching. You find out by email, not by remembering to log in.

---

## Part 8 — Reading a verdict

A real stored result, copied out of the database unchanged:

```
BMRI · weakened · confidence 0.84 · decided by Jev and the agent
watermark 2026-09-28

claims
  unknown     BMRI kredit tumbuh dua digit
  weakening   BMRI laba bersih naik
  supported   valuasi masih murah dibanding bank besar lain

changes since 2026-09-28
  data     BMRI fell from 4230 to 4020 over 21 sessions, 0 no-trade sessions
                                                          −4.96%
  data     Foreign flow net outflow over 21 days, sell days dominating
                                                          −Rp1.45T, 6 buy vs 14 sell days
  context  2026-09-28 headline: Foreign Net Sell Widens, dragging BMRI and TL…
           IHSG −1.5% on 2026-09-28, weekly net sell Rp4.39T

evidence
  latest_quarterly_report = 2026-06-30        /v2/financials/quarterly/BMRI/
  last_traded_session = 2026-09-28            /v2/daily/BMRI/
  gross_loan discontinuity = Rp1,568.08T from Rp1,849.9…   as_of 2026-03-31
                                              /v2/financials/quarterly/BMRI/
```

This one example shows nearly the whole product. Read it in four passes:

**1. The `unknown` claim is the discontinuity guard working.** *"kredit tumbuh dua digit"* came back
`unknown`, not `broken` — because the evidence table shows a row named
`gross_loan discontinuity`, recording the jump from Rp1,849.9T to Rp1,568.08T on 2026-03-31. The
product refused to compare across a restatement instead of reporting a fake collapse. Part 4 above is
this exact row.

**2. The `supported` valuation claim is the model earning its place.** This is the claim with no
single metric — the relative judgement. Arithmetic could not settle it. The agent settled it from
dated news, and the rationale says so: *"what_changed news on 2026-09-27 reports BMRI and BBNI
flagged as cheap stocks."* Part 2's third claim type, resolved.

**3. The change strip has dated causes and measured magnitudes.** Not "sentiment weakened" — a
headline with a date, an index move of −1.5%, and a weekly net sell of Rp4.39T. Part 7 in practice.

**4. Every number has an endpoint.** Nothing in that verdict is unattributable. You can re-run each
call yourself, which is the point of the evidence table.

---

## Part 9 — What this product deliberately does not do

- **It does not tell you to buy or sell.** It reports what changed and how confident it is.
- **It does not place trades.** There is no order path in the codebase, at all.
- **It does not predict prices.** A thesis is about business facts, and those are the only things it
  measures.
- **It does not hide a bad number.** When the data is inconsistent, or the metric is missing, or the
  model's prose cites something imaginary, it says so — in the summary, on screen, and in the stored
  evidence.

The one-sentence version of the whole product:

> **You wrote down why you own it. This tells you the moment that stops being true.**

---

## Glossary

| Term | Meaning |
| --- | --- |
| **Thesis** | The written reason for owning a stock. |
| **Claim** | One independently checkable fact inside a thesis. A thesis of 3 claims is 3 checks. |
| **Metric** | The reported number that settles a claim — `gross_loan`, `earnings`, `net_interest_income`. |
| **Threshold** | The bar the thesis itself set ("at least 10%"). Missing it means `broken`, with no judgement involved. |
| **Cadence** | The data family that would settle a claim: quarterly, price, flow, insider, news, corporate action, valuation. |
| **Baseline** | The metric's value on the day the thesis was written — the honest comparison point. |
| **Watermark** | The date a check may read forward from. Makes re-checks cheap and the change strip real. |
| **Verdict** | The rolled-up state of the whole thesis: `intact` / `weakened` / `broken` / `needs_review`. |
| **Restatement** | A reported series re-presented on a different basis. Detected and refused, never traded through. |
| **Discontinuity band** | The plausible range of quarter-to-quarter movement for a metric, asymmetric by design. |
| **Evidence** | Every number behind a verdict, with its endpoint and parameters. |
| **Decision path** | Which layer decided: `measurement`, `jev`, `jev+agent`, `agent`, `agent_unverified`. |
| **Guardrail** | The check that no number in the model's prose is absent from the evidence. |
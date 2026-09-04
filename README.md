# Recoup — AI Revenue Recovery Agent

**Live demo:** `<PASTE YOUR *.onrender.com URL HERE AFTER DEPLOYING>`

An agentic AI system that triages failed subscription payments — diagnosing
why each one failed, prioritizing accounts by an explainable recovery-value
formula, drafting personalized outreach, and grading its own drafts before
they'd ever ship — instead of contacting every failed account equally.

---

## The problem

Every subscription business loses revenue to failed payments: expired
cards, insufficient funds, gateway errors. Most teams contact every failed
account the same way, spending equal effort on low-value, low-likelihood
cases while high-value, easily-recoverable accounts sit untouched.

**If a business recovers even a modest share of the accounts in this
demo's 30-account sample queue, that's real revenue that would otherwise
have silently churned out** — and the point of this project is that
*which* accounts you prioritize, and *how* you approach each one, changes
that number substantially. The dashboard's headline stat quantifies
exactly how much.

## What it does

1. **Diagnoses** why each payment likely failed — technical issue vs.
   churn signal — with a confidence score and a churn-risk label.
2. **Prioritizes** accounts with an explainable formula, not a black box:
   ```
   recovery_score = amount_owed × pay_likelihood × urgency
   ```
3. **Compares itself to a naive baseline** (contact everyone equally, no
   prioritization) on the *same* batch: accounts contacted, revenue
   targeted, expected recovery, simulated revenue recovered, and recovery
   rate — reporting both an expected-value efficiency gain and a
   simulated-outcome efficiency gain.
4. **Checks a deterministic stopping rule** before acting — an account
   with too many prior failed attempts is routed straight to manual
   review and never reaches the automated outreach step at all.
5. **Decides a recovery action from a fixed, bounded set** — `reminder`,
   `payment_link_retry`, `empathetic_outreach`, or `escalate` — and drafts
   a personalized message per top-priority account. No discount offered
   for easy technical failures; more empathetic handling for at-risk
   accounts. The agent cannot invent a fifth action.
6. **Self-critiques its own draft** against a rubric (tone, clarity, no
   over-promising) and **revises once if needed** — a visible agentic QA
   loop, not one-shot generation.
7. **Simulates a recovery outcome** per contacted account (a seeded,
   reproducible draw against the diagnosis's `pay_likelihood`) so the
   dashboard can report a concrete number — "7 of 10 accounts recovered,
   $412 recovered" — alongside the probability-weighted estimate.
8. **Logs a full execution trace and audit log** for every run — a
   `run_id`, timestamps, and a per-account record of every decision, LLM
   call, and outcome, exportable as JSON from the dashboard.

## Why this is agentic, not just generative

A single LLM call wrapped in a UI would take account data in and return a
message out. This system doesn't do that. It chains multiple **autonomous
decisions**, each of which changes what happens next:

- *What to prioritize* — the scoring step decides account order, and that
  order changes which accounts even get a drafted message (only the
  top-N do).
- *Whether the agent is even allowed to act* — the stopping-rule check
  runs before any drafting LLM call. An account that trips it is routed
  to `escalate` deterministically, in code, and never reaches the model.
  This bounds the agent's authority instead of leaving it unrestricted.
- *Whether/how to act* — the action-decision step reads the diagnosis and
  picks one of exactly four allowed actions, differently for a technical
  failure (frictionless payment-method update, no discount) versus a
  churn signal (empathetic, retention-minded outreach). Anything the
  model returns outside that set is coerced back to a safe default in
  code — the model proposes, deterministic validation disposes.
- *Whether its own output is good enough* — the self-critique step is a
  second, independent LLM call that grades the first call's output against
  a fixed rubric and can override it with a revised message. This is the
  part that makes it agentic rather than generative: the system checks and
  corrects its own work as part of the pipeline, before a human ever sees
  the draft.

Generative AI (the Claude API) is used as a *component* inside this loop —
for diagnosis reasoning, message drafting, and critique — but the
structure, ordering, and decision logic around it (the scoring formula,
the stopping rule, the naive-baseline comparison, the bounded action set,
the pass/fail/revise branch, the outcome simulation) is deterministic code
that orchestrates those calls, not another LLM call. `src/agent.py`
reports which stage is which (`"type": "llm"` vs. `"deterministic"` vs.
`"mixed"`) in the `pipeline_trace` it returns, and the dashboard renders
that distinction directly instead of hiding it.

## Architecture

```
payments.csv
     │
     ▼
data_loader.py ──► diagnose.py ──► prioritize.py ──► baseline.py
 (load/clean)      [LLM] reason     (explainable      (naive vs. agent
                     for failure     scoring/rank,      comparison +
                     + confidence +  no LLM)            simulate_outcomes.py
                     pay_likelihood)                    [deterministic,
                                                          seeded])
                         │
                         ▼
                 recommend_action.py
                 ├─ stopping_rules.py           [deterministic — checked FIRST]
                 ├─ [LLM] decide bounded action + draft message
                 └─ [LLM] second call: self-critique + revise once
                         │
                         ▼
                    agent.py (orchestrator)
                    — assigns run_id, builds pipeline_trace + audit_log
                         │
                         ▼
                    server.py (Flask)
                    ├─ serves static/index.html (frontend)
                    └─ POST /api/run (runs the pipeline, returns JSON)
```

Single service, one repo, one host (Render). The same Flask app serves the
HTML/CSS/JS frontend as a static file *and* exposes the `/api/run`
endpoint the frontend calls via `fetch()`. This avoids CORS entirely and
keeps deployment to one step.

## Project structure

```
.
├── data/
│   ├── payments.csv              # mapped, demo-ready dataset (committed)
│   └── raw/                      # put the real Kaggle CSV here (gitignored)
├── src/
│   ├── map_telco_dataset.py      # one-time Kaggle → payments.csv mapper
│   ├── data_loader.py            # load/validate payments.csv
│   ├── prompts.py                # all LLM prompt templates + the bounded action set
│   ├── llm_client.py             # single choke point for Anthropic API calls, incl. 1 bounded retry
│   ├── diagnose.py               # LLM: failure reason, confidence, pay_likelihood, churn risk
│   ├── prioritize.py             # explainable scoring formula (no LLM)
│   ├── stopping_rules.py         # deterministic policy that bounds automated outreach
│   ├── simulate_outcomes.py      # seeded, reproducible simulated recovery outcomes
│   ├── baseline.py               # naive-vs-agent comparison, efficiency gain (expected + simulated)
│   ├── recommend_action.py       # LLM: bounded action + draft, self-critique, per-account trace
│   └── agent.py                  # orchestrates the pipeline; builds run_id, pipeline_trace, audit_log
├── static/
│   └── index.html                # single-page fintech dashboard frontend
├── server.py                     # Flask app — the deployable entry point
├── requirements.txt
├── Procfile
├── render.yaml
├── .env.example
└── .gitignore
```

## Dataset

Source: Kaggle **[Telco Customer Churn](https://www.kaggle.com/datasets/blastchar/telco-customer-churn)**
(`blastchar/telco-customer-churn`), mapped into this schema:

| Source column   | Maps to                | Notes |
|---|---|---|
| `customerID`     | `customer_id`          | |
| `MonthlyCharges`  | `plan_amount`           | |
| `tenure`          | `months_paid_on_time`   | |
| `Churn == "Yes"`  | *(filter)*              | stand-in for "failed payment" queue |
| `PaymentMethod`   | `payment_method`        | diagnosis signal — Electronic check has a historically higher churn correlation in this dataset |
| `Contract`        | `contract_type`         | churn-risk signal |
| `TotalCharges`     | `total_lifetime_value`  | |

**Simulated fields** — the Kaggle dataset has no billing-system data, so
these three are generated with a documented, deterministic rule tied to
real columns (see the docstring in `src/map_telco_dataset.py` for the
exact logic). They are clearly labeled as simulated in the code and are
**not** real payment-gateway data:

- `card_expiry_days` — shorter window for month-to-month contracts
- `last_login_days_ago` — inversely related to tenure
- `failed_attempts` — higher for Electronic check payment method

**Currency:** the source dataset never labels a currency. All amounts are
treated and displayed as USD ($) by standard convention for this dataset;
the source data does not specify a currency.

**This is a payment-recovery prototype adapted from a churn dataset, not a
system trained on real failed-payment records.** The Telco Customer Churn
dataset never contained payment-gateway events — `Churn == "Yes"` is used
here as a stand-in for "this account needs recovery outreach," and the
three simulated fields above are a documented, deterministic proxy for
billing-system signals the source data doesn't have. No part of this
project claims the underlying dataset is real payment data.

**`pay_likelihood` is an LLM estimate, not a trained probability model.**
`diagnose.py` asks Claude to reason about how likely an account is to pay
if contacted, given the available signals (payment method, contract type,
engagement, prior attempts). That's a language-model judgment call, not
output from a model trained and validated on historical payment outcomes.
The UI labels it as an estimate everywhere it's shown, and the simulated
recovery outcomes below are built directly from it — so the same caveat
applies one level further down the pipeline.

## Stopping rule and bounded action set

The agent's authority to act automatically is intentionally limited:

- **Bounded action set** — the drafting step can only choose from four
  actions: `reminder`, `payment_link_retry`, `empathetic_outreach`,
  `escalate` (see `prompts.py`). Anything else the model returns is
  coerced back to `reminder` in code (`recommend_action.py`), and flagged
  as invalid in that account's trace — the model never gets unchecked
  discretion over what it's "allowed" to do.
- **Stopping rule** — before any drafting call happens, `stopping_rules.py`
  checks `failed_attempts` against a configurable ceiling
  (`MAX_AUTOMATED_ATTEMPTS`, default 3). An account over that ceiling is
  routed straight to `escalate` deterministically and never reaches the
  LLM at all. This is the one stopping rule implemented, by design: it
  only needs data already present per account, unlike a rule such as
  "stop after N automated contacts across runs," which would require
  persisting customer state between runs — infrastructure this
  single-pass demo intentionally doesn't add. That's documented here
  rather than silently left out.

## Execution trace and audit log

Every run gets a `run_id` and start/finish timestamps. The API response
includes:

- `pipeline_trace` — the ordered list of pipeline stages, each tagged
  `llm`, `deterministic`, or `mixed`. The dashboard's "Run Agent" loading
  view renders this list directly from the backend response rather than a
  canned animation.
- a per-account `trace` on every top-priority account — the stopping-rule
  check, the action decision, and the critique outcome, each with a short
  reason string.
- `audit_log` — one row per account in the *entire* queue (not just the
  top N): diagnosis, score breakdown, whether it was contacted, the
  decided action, critique result, and simulated outcome. Downloadable as
  JSON from the "Download audit trail" button on the dashboard.

## Simulated recovery outcomes

Alongside the probability-weighted `expected_recovery` figure, the agent
turns each contacted account's `pay_likelihood` into one concrete,
seeded simulated outcome — recovered or not, with a dollar amount — so
the dashboard can show a real-looking result ("7 of 10 recovered, $412")
next to the expected-value estimate. The simulation is seeded per
`customer_id` (see `simulate_outcomes.py`) so the same account with the
same `pay_likelihood` always simulates the same way across runs.

**This is explicitly a simulation, not a real payment result**, and with
a small batch (10 contacted accounts by default) a single simulated run
is one random draw and can vary noticeably run to run — it's meant to
make the demo's impact concrete, not to be read as a statistically robust
outcome. `expected_recovery` is the more stable number for comparing
strategies; the simulated figures are a complementary, more tangible one.

### ⚠️ Data provenance — please read before you submit

This project was built in a sandboxed environment **with no internet
access**, so the real Kaggle CSV could not be downloaded here. To keep
`src/map_telco_dataset.py` fully testable, a synthetic *test* raw file was
generated locally with the real dataset's known column schema and
statistical shape (7,043-row Telco dataset, ~26.6% overall churn rate,
tenure 0–72 months, `MonthlyCharges` roughly $18–$118, the well-documented
correlations between churn and month-to-month contracts / Electronic
check / low tenure, etc.) — but that test file's row-level values are
**fabricated, not scraped or copied from the real dataset**, and it was
deleted after testing. It never shipped.

**The `data/payments.csv` committed in this repo was produced by running
the real mapping script against that synthetic test file** — meaning the
mapping logic, schema, and pipeline are fully real and tested, but the 30
specific rows in the shipped demo data are not literal real Kaggle rows.

**Before you submit this project, regenerate the real thing** (takes under
five minutes):

1. Download `WA_Fn-UseC_-Telco-Customer-Churn.csv` from
   [the Kaggle page](https://www.kaggle.com/datasets/blastchar/telco-customer-churn).
2. Place it at `data/raw/WA_Fn-UseC_-Telco-Customer-Churn.csv`.
3. Run `python src/map_telco_dataset.py` — this overwrites `data/payments.csv`
   with a real 30-row sample drawn from actual Kaggle data.
4. Commit the regenerated `data/payments.csv` before you deploy.

The app runs end-to-end either way (the shipped file works out of the box
for local testing), but real Kaggle-derived data is what you want in the
version you actually submit.

## Example customer journey

One account from a real run, end to end (values illustrative):

1. **Load** — account `9821-QRXTM`, $79.87/month, month-to-month contract,
   Electronic check, 2 prior failed attempts.
2. **Diagnose** *(LLM)* — "Payment method has a history of processing
   issues and the account shows declining engagement" → `failure_type:
   churn_signal`, `confidence: 0.78`, `pay_likelihood: 0.52`,
   `churn_risk: medium`.
3. **Prioritize** *(deterministic)* — `recovery_score = 79.87 × 0.52 ×
   0.83 (urgency) = 34.45` → ranked #2 of 30.
4. **Stopping rule check** *(deterministic)* — 2 failed attempts is under
   the limit of 3 → clear to proceed.
5. **Decide + draft** *(LLM)* — action `empathetic_outreach` (churn risk
   is medium, so no bare technical reminder); drafts a short, warm message
   acknowledging the account and prompting a payment-method update, with
   no invented discount.
6. **Self-critique** *(LLM)* — flags the first draft as slightly vague
   about next steps → revises once → final message ships.
7. **Simulate outcome** *(deterministic, seeded)* — draw against
   `pay_likelihood 0.52` → recovered, $79.87.

All seven steps, plus their full inputs/outputs, are in that account's
entry in `audit_log` for the run.

## Evaluation — AI agent vs. naive baseline

Both strategies run over the **same fixed batch** (`OUTREACH_BUDGET`
accounts, default 10) so the comparison isolates ordering as the only
variable:

| Metric | Naive baseline | AI agent |
|---|---|---|
| Accounts contacted | `outreach_budget`, taken in load order | Same `outreach_budget`, taken by `recovery_score` rank |
| Revenue targeted | Sum of `plan_amount` for those accounts | Sum of `plan_amount` for its (different) accounts |
| Expected recovery | `Σ plan_amount × pay_likelihood` | `Σ plan_amount × pay_likelihood` |
| Revenue recovered (simulated) | From the seeded simulation | From the seeded simulation |
| Recovery rate (simulated) | recovered / contacted | recovered / contacted |
| Efficiency gain | — | % change vs. naive, both on expected value and on the simulated outcome |

Both the expected-value gain and the simulated-outcome gain are reported
side by side on the dashboard (`GET` this via `/api/run` → `summary` and
`baseline_comparison`) rather than collapsing them into one number, since
they answer slightly different questions (statistical expectation vs. one
concrete illustrative run).

## Local run instructions

```bash
git clone <your-repo-url>
cd recoup
pip install -r requirements.txt

# (recommended) regenerate real data first — see "Data provenance" above
python src/map_telco_dataset.py

cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...

export $(cat .env | xargs)   # or use python-dotenv / your shell's preferred method
python server.py
# visit http://localhost:5000 and click "Run Agent"
```

Optional tuning (all have sane defaults, see `.env.example`):

- `TOP_N_FOR_ACTION` — how many top-ranked accounts get a drafted message (default 5)
- `OUTREACH_BUDGET` — how many accounts count as "contacted" in the naive-vs-agent comparison (default 10)
- `MAX_AUTOMATED_ATTEMPTS` — `failed_attempts` ceiling before the stopping rule escalates an account instead of drafting (default 3)

## Deployment (Render, free tier)

1. Push this repo to GitHub.
2. Create a new **Web Service** on [Render](https://render.com), connect
   the repo.
3. Set the `ANTHROPIC_API_KEY` environment variable in Render's dashboard
   (Environment tab) — it's marked `sync: false` in `render.yaml` so it's
   never committed to the repo.
4. Deploy — Render auto-detects `render.yaml`, or use the manual settings:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn server:app`
5. Visit the generated `*.onrender.com` URL — this is the live, public
   link. Paste it at the top of this README before submitting.

No code changes are needed between local run and deployment — `server.py`
already reads the port from the `PORT` environment variable and binds to
`0.0.0.0`, and the API key is read from the environment only (never
hardcoded, never sent to the frontend).

## Notes on robustness

Every LLM call in this pipeline goes through `src/llm_client.py`, which
makes one bounded retry on a transient API error or an unparseable
response before giving up, and parses the response defensively (handles
markdown-fenced JSON, stray prose, etc.) — raising a typed `LLMError` only
after both attempts fail. Each pipeline stage that calls the LLM
(`diagnose.py`, `recommend_action.py`) catches that error per-account and
falls back to a conservative default rather than crashing the batch — so
one malformed response degrades one row of the dashboard instead of
taking down the whole run. The action-decision step additionally validates
every response against the fixed action set (`prompts.ALLOWED_ACTIONS`)
and coerces anything else to a safe default. `server.py`'s `/api/run`
endpoint wraps the whole pipeline in a try/except and always returns clean
JSON, never a bare 500 with a stack trace; the frontend applies its own
45-second request timeout and shows a clear error/empty state rather than
hanging indefinitely.

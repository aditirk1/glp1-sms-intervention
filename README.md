# GoalPost¹

GoalPost¹ is an autonomous check-in engine for obesity and type 2 diabetes patients on GLP-1 therapy. It decides on its own who to contact, when, and what to say. A risk-stratified scheduler contacts patients every 3, 7, or 14 days depending on their dropout risk; replies are scored by an XGBoost model whose SHAP attribution identifies *which* barrier is driving the risk — a weight plateau, side effects, or cost; and a declarative rules engine picks the intervention or escalates to a human. Patients who say nothing at all are treated as the highest-signal case, not as missing data.

Nobody presses a button. One function decides everything:

```
run_due_checkins(now, db)
```

A real clock calls it hourly. The simulator calls it with a fake clock advancing one day at a time across months of virtual time. Same code path, so the demo exercises the production logic rather than a parallel copy of it.

The demo runs end to end with no paid services: no Twilio, no paid LLM API, and no cloud account requiring a credit card.

## What the engine does on each tick

```
run_due_checkins(now)
   |
   v
Refresh weeks_on_therapy from the calendar      <- silent patients age too
   |
   v
Select patients where next_checkin_due <= now
   |
   v
Re-score risk, including the silence features
   |
   v
Evaluate the rule list in priority order
   |
   +--> Send SMS, subject to caps, cooldowns and the send window
   |
   +--> Create a care team task
   |
   v
Set last_contacted_at, then next_checkin_due by tier
```

### Cadence

| Risk tier | Days between check-ins |
| --- | --- |
| red | 3 |
| amber | 7 |
| green | 14 |

Capped at 7 days for anyone in their first 4 weeks regardless of tier, because early titration is when GI dropout clusters.

### The policy

Every decision about what to send and when to involve a human lives in one list in `services/rules.py`, so a clinician can read the whole policy without tracing control flow.

| Rule | Fires when | Action |
| --- | --- | --- |
| `red_sustained` | red on two consecutive scorings | nurse call task |
| `silence_escalate` | two missed check-ins | outreach call task |
| `cost_barrier` | barrier is cost and tier is amber or red | cost-navigation SMS + benefits check task |
| `side_effect` | reply 2 | guidance SMS; two within 4 weeks also raises a GI escalation task |
| `plateau_streak` | reply 3 and risk >= 0.45 | retrieval-grounded plateau message |
| `silence_nudge` | one missed check-in | resend the prompt |
| `doing_well` | reply 1 | acknowledge, let cadence extend |
| `scheduled_checkin` | nothing else applies | the routine 1/2/3 prompt |

Guardrails are enforced centrally in `apply_actions()` rather than by each rule: at most 2 outbound messages per patient per rolling 7 days, a per-rule cooldown, no duplicate message body within 14 days, one SMS per evaluation, and a 9am-8pm send window so the simulator never emits 3am texts. Tasks are deduplicated against anything already open *and* against anything raised recently, because a standing condition like "still red" otherwise regenerates the same task on every tick.

### Silence is a first-class signal

Non-response is the strongest real-world dropout signal, and the original build could not see it at all. Two things were broken: `weeks_on_therapy` only incremented inside the webhook, so a patient who never replied was frozen at week 0 forever, and the model had no feature for non-response.

Now tenure is derived from `therapy_start_date` and refreshed every tick, and `consecutive_no_reply` is a real model feature. It ranks third by mean absolute SHAP value, behind only indication and the plateau streak. Sustained silence — 42 days without a reply, measured from the last reply rather than from a count of missed prompts so that tier cadence does not bias it — marks a patient lost to follow-up.

## Setup

Run these in order from the project root.

**a. Install dependencies**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**b. Configure environment**

```bash
cp .env.example .env
```

Add your `GROQ_API_KEY` to `.env`. Get one free at [console.groq.com](https://console.groq.com) — no credit card required. If you leave it blank everything still runs; the plateau branch falls back to a safe static message instead of a generated one.

**c. Generate the synthetic cohort**

```bash
python data/generate_synthetic.py
```

**d. Train the risk model**

```bash
python model/train_model.py
```

**e. Build the trial-evidence vectorstore**

```bash
python knowledge_base/build_vectorstore.py
```

This downloads the `all-MiniLM-L6-v2` embedding model (~90 MB) on first run and then works offline.

**f. Seed a cohort**

```bash
python -m simulation.seed_cohort --patients 1000 --reset
```

`--reset` drops and recreates every table. There is no Alembic here on purpose: the data is synthetic, so the schema is rebuilt rather than migrated. If you are upgrading an older checkout and see `no such column`, delete the database and reseed:

```bash
rm "GoalPost¹.db" && python -m simulation.seed_cohort --patients 1000 --reset
```

**g. Start the API**

```bash
uvicorn api.main:app --reload --port 8000
```

**h. Start the dashboard** (in a second terminal)

```bash
streamlit run dashboard/app.py --server.port 8501
```

### macOS note: OpenMP

XGBoost needs the OpenMP runtime, which macOS does not ship. If `import xgboost` fails with `Library not loaded: @rpath/libomp.dylib`, install it:

```bash
brew install libomp
```

If you then hit `OMP: Error #179` or a segfault when the API loads both XGBoost and `sentence-transformers`, two copies of OpenMP are being loaded into one process. Point XGBoost at the copy PyTorch already ships so both share one runtime:

```bash
SP=$(python -c "import site; print(site.getsitepackages()[0])")
install_name_tool -add_rpath "$SP/torch/lib" "$SP/xgboost/lib/libxgboost.dylib"
codesign -f -s - "$SP/xgboost/lib/libxgboost.dylib"
```

## Running the demo

1. Open the dashboard at http://localhost:8501. It leads with **Needs a human today** — the work queue the rules engine produced.
2. Press **Run scheduler tick** under Controls. It contacts only the patients whose cadence has come due, so pressing it twice does nothing the second time. That is the point.
3. Open **Simulate an inbound reply**, pick a patient, and answer **3 — Not seeing results**. Watch the risk score, the SHAP-attributed barrier, which rule fired, and any task it raised.
4. Acknowledge or resolve a task in the queue.
5. Filter the roster by **Silent only** to see patients who are accruing risk without ever replying.

Every outbound message is printed to the API console with a `[GoalPost¹ SMS]` prefix rather than sent, so you can watch the whole conversation without a carrier.

## The simulation harness

The point of the harness is that it drives the real scheduler. `run_simulation.py` advances `now` one day at a time and calls the same `run_due_checkins()` the API calls hourly; nothing in `simulation/` reimplements a scheduling decision.

```bash
python -m simulation.run_simulation --arm control      --patients 1000 --weeks 26
python -m simulation.run_simulation --arm intervention --patients 1000 --weeks 26
```

Each arm writes its own SQLite file and a JSON summary under `simulation/results/`, which the dashboard reads through `GET /simulation/results`. A 1000-patient, 26-week run takes about a minute.

- `seed_cohort.py` staggers `therapy_start_date` so the cohort spans weeks 1-52 rather than everyone starting today.
- `patient_behavior.py` gives each patient a latent state the system cannot observe (well, plateau, GI, cost), a reply probability that decays with tenure and risk, a weekly quit hazard, and a 6% slice who go permanently silent. Replies are sampled, not scripted.
- The **control arm still receives cadence prompts and is still scored**. Only the interventions are suppressed, so the comparison isolates acting on the risk signal from merely being contacted.

### Results from the 26-week, 1000-patient run

| | Control | Intervention |
| --- | --- | --- |
| Retention (observed) | 40.2% | **61.7%** |
| Still on therapy (ground truth) | 52.7% | **71.5%** |
| Messages per patient | 16.2 | 24.7 |
| Response rate | 43.4% | 51.3% |
| Tasks raised | 0 | 3,990 (4.0 per patient) |
| Max messages in any 7 days | 2 | 2 |
| Cap violations | 0 | 0 |
| Messages outside the send window | 0 | 0 |
| Patients stuck at week 0 | 0 | 0 |

Two retention numbers are reported because they answer different questions. *Observed* retention is what the system can see: a patient silent for 42 days is marked lost to follow-up whether or not they are still injecting. *Ground truth* is what the simulated patient actually did. The gap between them — 12.5 points in control, 9.8 in intervention — is the population still on therapy that the program has lost contact with, and shrinking it is itself part of what the interventions do.

**What this does and does not show.** It shows that the scheduler reaches the right patients on the right day at cohort scale, that the guardrails hold under a quarter million message decisions, that silence produces escalation instead of a frozen week-0 row, and that the care team queue drains rather than growing without bound (it peaks at 283 open tasks in the first weeks as the whole cohort is scored for the first time, then settles around 40). It does **not** show that a cost-navigation text resolves a coverage barrier 22% of the time. Those effect sizes are assumptions declared in `EFFECTS` at the top of `simulation/patient_behavior.py`. The retention gap is a consequence of them, not evidence for them. Treat `EFFECTS` as the dial to argue about, and replace it with measured effects when you have them.

## Scheduling in production

The API starts an APScheduler job on boot that ticks hourly. Control it with:

```bash
ENABLE_SCHEDULER=true          # default
SCHEDULER_INTERVAL_MINUTES=60
```

**Render's free tier sleeps idle instances**, which means an in-process scheduler stops running exactly when nobody is looking at the dashboard. The reliable path is to disable it and point a free external cron at the endpoint instead:

```bash
ENABLE_SCHEDULER=false
```

Then create a job on [cron-job.org](https://cron-job.org) or GitHub Actions that hits the tick hourly:

```bash
curl -X POST https://your-app.onrender.com/scheduler/tick
```

The request also wakes the sleeping instance, so the cron does double duty. The tick is idempotent with respect to cadence — it only contacts patients whose `next_checkin_due` has passed — so a missed hour or a duplicate call cannot double-message anyone.

## Sharing a live demo URL

Install [ngrok](https://ngrok.com) (free, no credit card), then:

```bash
ngrok http 8501
```

Share the generated URL.

## Production deployment (no credit card required)

**Backend — [Render](https://render.com) free tier**

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
- Add `GROQ_API_KEY` in the Render environment variables

The build artefacts (`synthetic_patients.csv`, `model.joblib`, `chroma_db/`) are gitignored, so either commit them for deployment or append the three generation steps to the build command.

**Dashboard — [Hugging Face Spaces](https://huggingface.co/spaces)**

- Create a new Space and select the Streamlit SDK
- Upload `dashboard/app.py` as `app.py`
- Add an `API_BASE_URL` secret pointing at your Render backend URL

**Real SMS.** `services/sms_sender.py` is the only file that touches the transport. Replace the body of `send_sms()` with a Twilio call and point your Twilio number's inbound webhook at `POST /webhook/sms`; the route already accepts Twilio's `From` and `Body` form fields.

## Architecture

Two entry points, one engine. The scheduler tick and the inbound webhook both assemble the same features, score them, snapshot the risk, run the same policy, and reschedule by tier.

```
APScheduler (hourly)          Patient reply
external cron                 POST /webhook/sms
        |                             |
        v                             v
run_due_checkins(now, db)     process_reply(db, ...)
        |                             |
        +-------------+---------------+
                      |
                      v
        services/risk_scorer.py  (XGBoost + SHAP, batched)
                      |
                      v
        services/rules.py  (declarative policy)
                      |
        +-------------+--------------+
        |                            |
        v                            v
   guardrails: weekly cap,      Task -> care team queue
   cooldowns, dedup,
   send window
        |
        +--> plateau branch --> Chroma retrieval --> Groq llama3-8b-8192
        |
        v
   OutboundMessage + CheckIn + RiskSnapshot  (SQLite)
        |
        v
   GET /tasks, /cohort/metrics, /patients  -->  Streamlit dashboard
```

`CheckIn` records what the patient said. `OutboundMessage` records what we sent, which is what makes cooldowns and response rates computable. `RiskSnapshot` records risk over time, which matters because non-response now moves risk without producing a `CheckIn` at all.

### API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/scheduler/tick` | Run one scheduling pass. The cron target. |
| `GET` | `/scheduler/status` | What the next tick would pick up, without sending |
| `GET` | `/tasks` | Work queue, ranked by priority then risk |
| `POST` | `/tasks/{id}/ack` | Claim a task |
| `POST` | `/tasks/{id}/resolve` | Close a task |
| `GET` | `/cohort/metrics` | Tier mix, engagement, work queue, retention curve |
| `GET` | `/patients` | Roster with `tier`, `status`, `silent`, `due`, `search`, `sort`, `limit`, `offset` |
| `GET` | `/patients/{id}` | Replies, outbound messages, tasks and risk history |
| `POST` | `/webhook/sms` | Twilio-shaped inbound reply |
| `POST` | `/send-checkin/{id}` | Manual override, guardrails still apply |
| `GET` | `/simulation/results` | The JSON written by the harness |

`GET /patients` returns `{total, limit, offset, items}` rather than a bare list, because a thousand-row cohort needs a count to page through.

### How risk becomes a barrier

`score_patient()` returns a dropout probability and the full per-feature SHAP vector. The barrier is read off the highest-magnitude SHAP feature among the *actionable* ones:

| Dominant feature | Barrier | Intervention |
| --- | --- | --- |
| `weight_change_slope`, `consecutive_reply_3`, `consecutive_no_reply` | `plateau` | Retrieval-grounded plateau message |
| `gi_event_flag` | `side_effect` | Side-effect guidance, care team notified |
| `income_quintile`, `prior_pa_denial`, `insurance_type_*` | `cost` | Cost-navigation SMS and a benefits check |

`consecutive_no_reply` sits in the plateau family: a patient who has stopped answering has usually stopped seeing a reason to.

Fixed patient attributes (`indication`, `weeks_on_therapy`, `baseline_bmi`) are excluded from that ranking. They frequently dominate the SHAP magnitudes but point at nothing the care team can act on; `top_shap_feature` still reports the true global maximum for transparency.

Risk tiers: `green` below 0.35, `amber` through 0.60, `red` above.

## Notes on the demo build

- **`weight_change_slope` is a proxy.** There is no scale integration, so the reply stands in for the weight trend (reply 1 = losing, 3 = stalled, 2 = roughly flat). Replace it with measured weights in production. See `weight_change_slope_proxy()` in `services/scheduling.py`.
- **Labels are synthetic and noisy by construction.** `discontinued_90d` is a Bernoulli draw from a per-patient probability, which caps how well *any* model can score. On the 5,000-row cohort the Bayes-optimal AUC — scoring the labels with the exact probability that generated them — is 0.703. The shipped model reaches 0.700 on held-out data, so it is at the noise floor and there is nothing left to tune. Training size is a separate knob from cohort size: `N_PATIENTS` in `data/generate_synthetic.py` controls the training set, `--patients` controls the simulated cohort.
- **Simulated effect sizes are assumptions.** See the note under the results table above. `EFFECTS` in `simulation/patient_behavior.py` is the honest place to argue with this project.
- **The care team is simulated too, and it is bounded.** 25 tasks a day with a 2-day turnaround. Without a cap the queue is free labour and the intervention arm wins on volume rather than on targeting.
- **Graceful degradation everywhere.** A missing Groq key, an unbuilt vectorstore, or a missing model file each fall back rather than failing the request, and `/webhook/sms` always returns parseable JSON so the simulator never breaks.

## Tests

```bash
python -m scripts.smoke_test
```

Boots the real app against a throwaway database and asserts the things most likely to break quietly: that a new patient enters the loop and gets rescheduled, that a second tick is a no-op, that a reply clears the silence streak, that the weekly cap actually blocks a manual send, that filters and pagination behave, and that a patient who never replies still ages, still accrues a streak, raises an outreach task, and is eventually marked discontinued.

## Data sources for the knowledge base

- **STEP 1** — Wilding JPH et al. *N Engl J Med.* 2021;384:989-1002
- **STEP 4** — Rubino D et al. *JAMA.* 2021;325(14):1414-1425
- **STEP 1 extension** — Rubino S et al. *Diabetes Obes Metab.* 2022
- **SURMOUNT-1** — Jastreboff AM et al. *N Engl J Med.* 2022;387:205-216
- **SURMOUNT-4** — Aronne LJ et al. *JAMA.* 2024;331(1):38-48

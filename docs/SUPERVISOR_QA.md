# GoaLPost¹ — Supervisor Q&A prep

Use this as talking notes. Speak in your own words; do not read verbatim.

---

## 1. “How did you do it?” (the Cursor / Opus answer)

### Short version (30 seconds)

> We designed the product around one decision loop: who is due, how risky they are, what to do, then reschedule. I used Cursor with Claude Opus as a pair programmer to implement that design across the API, rules, dashboard, and simulation. I directed the architecture, reviewed the logic, ran the simulations, and fixed what the runs exposed (like the weekly send-cap leak and the task-queue backlog). The clinical idea and the evaluation story are ours; the tooling sped up the coding.

### Longer version (2 minutes)

**What we decided before / while building**

1. Replace the manual “Send Check-in” button with an automatic scheduler.
2. Make silence a first-class signal (non-response raises risk and can create outreach work).
3. Keep the intervention policy in one readable file so a clinician could review it.
4. Prove the system with a control vs intervention simulation that calls the *same* code path as production.

**How Cursor / Opus fit in**

- I worked in Cursor and used Claude Opus as an implementation partner: explore the existing codebase, propose the schema and services, write the scheduler / rules / sim / dashboard routes, and iterate when tests failed.
- That is normal modern software practice: AI assists with boilerplate and first drafts; the human owns product intent, review, and verification.
- Concrete human ownership examples you can name:
  - We require one shared function (`run_due_checkins`) for both live ticks and the simulator.
  - Effect sizes in the simulation are declared assumptions, not claimed clinical evidence.
  - The 1,000-patient × 26-week runs found real bugs (cap not seeing uncommitted messages; task queue not draining). We fixed those and re-ran.
  - Model AUC sits near the Bayes ceiling of *synthetic* labels (~0.70 vs ~0.70); we did not pretend we “solved prediction.”

**What not to say**

- Don’t say “Opus built the whole product and I didn’t look.”
- Don’t say “I typed every line by hand” if that isn’t true.
- Do say: AI-assisted implementation under a clear design, with verification via smoke tests and cohort simulation.

---

## 2. “What does the product actually do?”

> Patients get a simple SMS check-in (reply 1 / 2 / 3). Behind that, a timer periodically finds who is due for contact, estimates dropout risk and a likely barrier (plateau, side effects, or cost), then either sends a targeted message or opens a care-team task. Higher-risk patients are contacted more often. People who stop answering are treated as high signal, not as missing data.

---

## 3. “Walk me through the pipeline” (plain English)

1. **Timer fires** (hourly, or an external cron if the host sleeps).
2. **Who is due?** Anyone whose next check-in time has already passed.
3. **Update tenure and silence.** Weeks on therapy come from the start date (so silent patients still age). Missed prompts increase a no-reply streak.
4. **Score risk.** Produce a probability, a green/amber/red tier, and a likely barrier.
5. **Apply the playbook.** Written rules decide text and/or human task.
6. **Guardrails.** Max 2 texts/week, daytime sends only, cooldowns, no duplicate bodies.
7. **Reschedule.** Red ~3 days, amber ~7, green ~14; first 4 weeks capped at weekly.

When someone *replies*, we skip “who is due” and go straight to score → playbook → reschedule.

---

## 4. “What is the risk score / model?”

> It’s a forecast: probability the patient stops therapy within about 90 days. We trained a gradient-boosted classifier on synthetic patient data that encodes known GLP-1 dropout drivers. An explanation layer (SHAP) points at which factors drove *this* patient’s score so we can map to a barrier: plateau, side effects, or cost.

**If they push on accuracy**

> Labels are synthetic Bernoulli draws, so there’s a hard ceiling. On 5,000 training patients our held-out AUC is about 0.70 against a Bayes ceiling of about 0.70. We’re at the noise floor of *this* dataset. Raising N helped; fancier models won’t invent signal that isn’t there. Real performance needs real outcomes.

**Features (say a few)**

- Weeks on therapy, weight-trend proxy from reply, GI flag, insurance/income, streak of “not seeing results,” **consecutive unanswered check-ins**.

---

## 5. “Why silence?”

> In the first version, week count only moved when someone replied, so non-responders looked stuck at week 0 and invisible. Clinically, people who stop answering often stop refilling. We now advance tenure from the calendar, feed missed check-ins into the model, nudge after one miss, escalate after two, and can mark prolonged silence as lost to follow-up.

---

## 6. “What are the rules / how do interventions work?”

> They’re an explicit priority list in one file (`services/rules.py`), not buried if/else. Examples: plateau + elevated risk → evidence-based plateau SMS; side effects → guidance and possible GI escalation; cost barrier → navigation SMS + benefits task; sustained red → nurse call; silence → nudge then outreach. Guardrails apply centrally so individual rules can’t spam.

**Plateau messages**

> We retrieve short passages from published STEP/SURMOUNT trial summaries and (optionally) ask an LLM to write a short SMS. If the API key is missing, we fall back to a safe static template. In cohort simulations we use offline templates so we don’t call the LLM thousands of times.

---

## 7. “How did you prove it works?”

> We ran 1,000 patients for 26 weeks in two arms that share the production scheduler.

| Arm | What happens |
|---|---|
| Control | Still gets check-in prompts and scoring; interventions suppressed |
| Intervention | Full playbook |

**Headline numbers (under declared assumptions)**

- Observed retention ~40% control vs ~62% intervention
- Weekly cap held (max 2, zero violations)
- No overnight texts
- No silent patients frozen at week 0

**Say this clearly**

> How much each message “helps” is an assumption in the simulator. The run proves the machinery: right patients, right day, guardrails, queue behavior. It does *not* prove clinical effect sizes. Those need a pilot.

---

## 8. “Is this production-ready / HIPAA / real SMS?”

> This is a demo build. SMS is logged to the console, not Twilio. Auth on the dashboard is not hardened. For production we’d swap the SMS transport, add proper auth and audit logs, and run a small prospective pilot. Render free tier sleeps, so we also support an external cron hitting `POST /scheduler/tick`.

---

## 9. “Why not just use ChatGPT for everything?”

> Risk stratification and escalation need to be auditable and consistent. A clinician should be able to read the playbook. We use a model for *risk and barrier*, rules for *what to do*, and language generation only for the plateau copy. That separation is intentional.

---

## 10. “What would Round 2 be?”

Prioritize:

1. Live Twilio on one number  
2. Clinician review of green/amber/red thresholds and cadence  
3. Replace assumed effect sizes with literature or advisor estimates; sensitivity analysis  
4. Real weight/lab inputs when available  
5. Auth + audit trail; sketch a 90-day persistence pilot endpoint  

Deprioritize: bigger models on synthetic labels, UI polish before real SMS.

---

## 11. “Who is this for?”

> Obesity / T2D care teams managing GLP-1 panels: nurses, care navigators, clinicians who need a prioritized queue of who needs a human today, with automated check-ins for everyone else.

---

## 12. “Tech stack?” (if asked)

Keep it light unless they want depth:

- FastAPI + SQLite (API and data)
- Streamlit (care-team dashboard)
- XGBoost + SHAP (risk + explanation)
- Declarative rules + APScheduler / cron (automation)
- Chroma + optional Groq (plateau evidence + wording)
- Simulation harness for control vs intervention

---

## 13. Hard questions — honest answers

| Question | Answer |
|---|---|
| Did AI write the code? | Assisted, yes. Design, review, and verification were human-led. |
| Are the retention gains real? | Real *under declared sim assumptions*. Not clinical evidence. |
| Is the weight trend real? | No scale yet; reply proxies slope in the demo. |
| Why amber-heavy tiers? | Thresholds were set earlier; with current score distribution many land amber. Tuning with a clinician is Round 2. |
| Can this replace clinicians? | No. It reserves humans for escalations; most contact is automated check-ins. |
| What’s the novel part? | Silence as a first-class risk signal + shared prod/sim tick + explicit policy with guardrails + care-team queue as the product surface. |

---

## 14. Opening line if they ask “how did *you* build this with AI?”

> I used Cursor with Opus the way I’d use a strong junior engineer: I specified the architecture (one scheduler for live and sim, silence in the model, rules in one file, care-team queue first), had it implement against that spec, then I ran the smoke tests and the thousand-patient simulation, fixed the failures those runs found, and kept the claims honest about what’s assumed versus what’s verified.

---

## 15. Demo order (if they say “show me”)

1. Work queue → acknowledge / resolve  
2. Scheduler tick (second tick is a no-op)  
3. Simulate reply 3 → risk, barrier, message  
4. Optional reply 2  
5. Simulation chart + caveat  

Files to know: dashboard `localhost:8501`, slides `docs/GoaLPost_Walkthrough.pptx`, results under `simulation/results/`.

# GoaLPost-1 — Final demo script (~2 min)

Speak in your own words. Numbers below match a bootstrapped live panel (`bootstrap_live --weeks 13`); yours may differ slightly.

---

## Before you record (5 minutes)

**Terminal 1 — API**
```bash
cd glp1-sms-intervention
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
```

**Terminal 2 — Bootstrap live panel (once, or to reset)**
```bash
source .venv/bin/activate
python -m simulation.bootstrap_live --weeks 13
```
This seeds 1,000 patients and fast-forwards **13 weeks of real scheduler + simulated SMS** into `GoaLPost¹.db`. Virtual time ends near today.

**Terminal 3 — Dashboard**
```bash
source .venv/bin/activate
streamlit run dashboard/app.py --server.port 8501
```

Open http://localhost:8501 · hard refresh if stale.

**Handoff:** Your teammate’s clip shows **Maria Alvarez** getting her **first check-in SMS** on her phone. **Cut straight to the dashboard** — Maria is a **fresh enroll (week 0)**; the rest of the panel has been running for ~13 weeks.

**Optional before recording:** `python -m simulation.demo_maria` resets Maria to today without re-bootstrapping the whole panel.

---

## The story in one sentence

> Patients reply 1 / 2 / 3 by text; a scheduler finds who is due, scores dropout risk, runs a readable rules playbook, and puts the few who need a human on a **work queue** — and we proved the machinery in a 1,000-patient simulation where intervention beat control on retention.

---

## Script (~2:00)

### 0:00 — Handoff → Overview

*[After Maria SMS clip]*

> This is the **care-team dashboard** for that same program — not the patient phone. One thousand GLP-1 patients, mid-program.

**Point at KPI row:**

> **Enrolled** — panel size. **Open tasks** — humans needed today. **High risk** — red tier. **Silent** — missed two or more prompts in a row; that is a first-class signal, not missing data. **Response rate** — prompts answered. **Retention** — headline: share still **active in the program today**. That top number is the one to trust.

**Point at retention panel (right):**

> Retention **by enrollment age** — older enrollments have had more time to drop off, so bars step down. This is the **live panel** with staggered enrollments, not the controlled experiment.

**Point at risk chart (left):**

> Risk tiers from the model — green, amber, red — updated as people text back. Barriers come from **SHAP**: plateau, side effects, or cost. They get meaningful once there is SMS history.

*(~25 sec)*

---

### 0:25 — Work queue

**Click Work queue.**

> This is the product surface: **who needs a human today**, ranked by priority and risk. Most rows are **benefits check** — the model flagged a **cost barrier** and the rules engine opened a task instead of only sending another text. Acknowledge or resolve here; that is the workflow.

*(~20 sec)*

---

### 0:45 — Patients

**Click Patients.**

> Full roster. Search **Maria Alvarez** — fresh enroll from the clip, **week 0**. Run **scheduler tick** on Operations first if she has no messages yet. Everyone else on the panel has been on the program longer.

*(~20 sec)*

---

### 1:05 — Outcomes

**Click Outcomes.**

> **Separate from the live panel** — this is a finished **26-week experiment**: 1,000 patients, everyone enrolled the **same day**, two arms, same scheduler code. **Control** ~40% still active · **Intervention** ~56% — acting on the risk signal, not just texting. These curves are the formal comparison. The Overview KPI is “where we are today on a rolling clinic panel”; Outcomes is “did the playbook help under controlled assumptions.”

*(~25 sec)*

---

### 1:30 — Operations (live beat, optional)

**Click Operations.**

> **Run scheduler tick** — one pass of the production job: who is due, score, rules, reschedule. Safe to press twice; second time is a no-op. **Simulate a reply** — posts through the real webhook: watch risk, barrier, rule fired, SMS body, any new task. This is the same path Maria’s “3” would take — plateau messaging fires on **reply 3**, not from the queue automatically.

*(~20 sec)*

---

### 1:50 — Close

> GoaLPost-1 automates the check-in loop, makes **silence visible**, keeps the playbook in one auditable file, and gives the team a **prioritized queue**. The simulation proves the **machinery** at scale; clinical effect sizes are assumptions until a real pilot.

---

## Cheat sheet — two data worlds

| | **Overview / Queue / Patients / Operations** | **Outcomes** |
|---|---|---|
| **What it is** | Live SQLite DB (`GoaLPost¹.db`) | Frozen JSON from `run_simulation.py` |
| **Cohort** | Rolling panel, staggered enrollments | 1,000 enroll same day |
| **Time** | Bootstrapped + you can tick forward | Fixed 26 virtual weeks |
| **Retention** | KPI = active ÷ enrolled **today** | Control ~40% vs intervention ~56% at week 26 |
| **Use for** | “What does the team see Monday morning?” | “Did intervention beat control?” |

---

## Mechanics worth knowing (if asked)

**Scheduler tick** — `run_due_checkins()`: refresh tenure → count missed prompts → score batch → rules → reschedule (red ~3d, amber ~7d, green ~14d).

**Replies 1 / 2 / 3** — 1 going well · 2 side effects · 3 not seeing results (plateau). Reply path: score → rules → SMS and/or task.

**42 days** — discontinued in the **program** after prolonged silence (since last reply, or since enroll if never replied), once they have been prompted at least once.

**13-week bootstrap** — one shared clock advanced 13 weeks; patients were seeded with 1–52 weeks on therapy already, so enrollment ages today span ~13–66 weeks.

**Control arm** — still prompted and scored; **interventions suppressed**. Comparison isolates acting on risk vs contact alone.

---

## Demo moves that land well

1. Work queue → open a **benefits check** → acknowledge.
2. Patients → search **Maria Alvarez**.
3. Operations → simulate **3 — Not seeing results** on a high-risk patient → show plateau SMS.
4. Outcomes → intervention vs control retention at week 26.

---

## Do not say

- “The chart at week 65 is our retention” (old KM curve — removed for clarity).
- “964 plateau means 964 patients plateaued” (barrier = model attribution, strongest after replies).
- “The simulation proves clinical efficacy” (proves **machinery** under **declared** effect sizes).
- “Opus built this and I didn’t review it.”

---

## Reset / troubleshoot

| Problem | Fix |
|---|---|
| Blank panel (0 check-ins) | `python -m simulation.bootstrap_live --weeks 13` |
| Stale UI | Hard refresh; restart Streamlit |
| All risk unscored | Re-run bootstrap or scheduler tick |
| Outcomes empty | `python -m simulation.run_simulation --arm control --weeks 26` then intervention |

---

## Related files

- Supervisor Q&A: `docs/SUPERVISOR_QA.md`
- Slides: `docs/GoaLPost_Walkthrough.pptx`
- API smoke test: `python -m scripts.smoke_test`

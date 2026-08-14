# GoaLPost-1 — Demo script (~2 min)

Talk like a person. Don’t read every KPI. Teammate’s Maria phone clip → you take the dashboard.

**Prep (before recording):** API + dashboard up · `bootstrap_live` done · `demo_maria` so Maria is week 0 · hard refresh.

---

## Script

### After the phone clip → Overview  
*[~20 sec]*

Okay — that was Maria’s phone. This is the care team side of the same thing.

We’ve got about a thousand GLP-1 patients on a rolling panel. Maria just joined. Everybody else has already been in the program for a while.

Up top, retention is who’s still *in the program* today — still reachable. Roughly half. Open tasks is how many people need a human right now. Silent means they ignored the last couple of check-ins — we treat that as a warning, not “no data.”

Risk is green / amber / red: chance they drop in the next few months, plus *why* — plateau, side effects, or cost.

---

### Work queue  
*[click Work queue · ~25 sec]*

This is the actual product. Not a pretty chart — a to-do list.

If the model says cost is the problem, we don’t spam another text. We open a benefits check for a navigator. If someone’s stuck high-risk, nurse call. If they go quiet, outreach.

Most of these rows are benefits checks. Cost doesn’t show up in a 1-2-3 reply. The model catches it from coverage and income, and the playbook says: give that to a person.

---

### Patients → search Maria Alvarez  
*[~15 sec]*

Maria from the clip. Week zero. Blank next check-in means she’s never been scheduled yet — first tick picks her up and sends that first text you just saw.

Everyone else on this roster is further along. Some already dropped out of the program.

---

### Demo simulation  
*[click Demo simulation · ~30 sec · turn on tiny “Sim” checkbox under the nav if the tab is hidden]*

Different page, different story. This is a finished experiment — same thousand people, all started the same day, twenty-six weeks, same code we just walked through.

Control still gets texts and scores, but we *don’t act* on the score. Intervention runs the full playbook. Control ends around forty percent still in. Intervention around fifty-six.

That gap is “we did something about the risk,” not “we texted people.” And fair warning — how much each message helps is an assumption in the sim. What we actually proved is the machinery works at scale: right people, right day, caps on spam, queue doesn’t blow up.

---

### Close  
*[~10 sec]*

So: patients text 1, 2, or 3. We score risk, pick a barrier, text when that’s enough, escalate when it isn’t. Maria is day one. The panel’s mid-flight. Demo simulation is the controlled “does acting help” run.

Happy to dig into the model or the rules if you want.

---

## Timing

| Block        | ~time |
|--------------|-------|
| Overview     | 0:20  |
| Work queue   | 0:25  |
| Maria        | 0:15  |
| Demo sim     | 0:30  |
| Close        | 0:10  |
| **Total**    | **~1:40** |

Leave ~20 sec slack for clicks / breathing. Skip Work queue acknowledge or Maria detail if you’re running long.

**Don’t do Operations live** unless they ask — it eats the clock. If asked: tick once for Maria’s first text; reply 3 fires a plateau SMS (Groq if key is set), not a nurse task.

---

## One-liners if interrupted

- **50% vs 56%?** Live panel = mixed ages today. Demo simulation = one cohort, day 1 → week 26.
- **Built with AI?** Helped write code. Design and verification were ours.
- **Is the lift real?** Under declared sim assumptions. Not a clinical trial.

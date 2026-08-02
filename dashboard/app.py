"""GoalPost¹ care team dashboard.

Ordered by what a care team actually does with it. The work queue comes first
because it is the only part that asks for someone's time; the cohort view and
the roster are there to justify and audit the queue, not to be browsed.
"""

import os

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = 60
PAGE_SIZE = 25

RED_THRESHOLD = 0.60
AMBER_THRESHOLD = 0.35

TASK_LABELS = {
    "nurse_call": "Nurse call",
    "outreach_call": "Outreach call",
    "benefits_check": "Benefits check",
    "gi_escalation": "GI escalation",
}

TIER_COLOURS = {"red": "#b91c1c", "amber": "#c2410c", "green": "#15803d"}

st.set_page_config(page_title="GoalPost¹", page_icon="signal", layout="wide")


# ----------------------------------------------------------------- transport


def api_get(path: str, params: dict | None = None):
    try:
        response = requests.get(
            f"{API_BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        st.session_state["api_error"] = f"{path}: {exc}"
        return None


def api_post(path: str, **kwargs):
    try:
        response = requests.post(
            f"{API_BASE_URL}{path}", timeout=REQUEST_TIMEOUT, **kwargs
        )
        return response
    except Exception as exc:
        st.error(f"Could not reach the API: {exc}")
        return None


def titleise(value) -> str:
    return str(value or "").replace("_", " ").title()


def _percent(value) -> str:
    """Render a rate, distinguishing a real zero from no data at all."""
    return "—" if value is None else f"{value:.0%}"


# -------------------------------------------------------------------- header

st.title("GoalPost¹")
st.caption("Autonomous GLP-1 check-in engine — risk-stratified cadence, "
           "declarative intervention policy, care team work queue")

metrics = api_get("/cohort/metrics")

if metrics is None:
    st.error(f"Could not reach the GoalPost¹ API at {API_BASE_URL}.")
    st.code("uvicorn api.main:app --reload --port 8000")
    st.stop()

tiers = metrics["tiers"]
engagement = metrics["engagement"]
retention = metrics["retention"]

head = st.columns(6)
head[0].metric("Enrolled", metrics["total_patients"])
head[1].metric("Open tasks", metrics["work_queue"]["open_tasks"])
head[2].metric("Red tier", tiers.get("red", 0))
head[3].metric(
    "Silent (2+ missed)", engagement["silent_two_or_more"]
)
head[4].metric("Response rate", _percent(engagement["response_rate"]))
head[5].metric("Retention", _percent(retention["rate"]))

st.divider()

# --------------------------------------------------------------- work queue

st.subheader("Needs a human today")
st.caption(
    "Raised by the rules engine, ranked by task priority then by current risk. "
    "Every row is a patient the model believes is leaving for a reason someone "
    "can still do something about."
)

queue_cols = st.columns([2, 2, 6])
queue_status = queue_cols[0].selectbox(
    "Status", ["open", "acknowledged", "resolved", "all"], key="queue_status"
)
kind_options = ["all"] + sorted(metrics["work_queue"]["by_kind"].keys())
queue_kind = queue_cols[1].selectbox("Type", kind_options, key="queue_kind")

queue_params = {"status": queue_status, "limit": PAGE_SIZE}
if queue_kind != "all":
    queue_params["kind"] = queue_kind

queue = api_get("/tasks", queue_params) or {"items": [], "total": 0}

if not queue["items"]:
    st.success("Queue is clear. Nothing needs a human right now.")
else:
    st.caption(f"Showing {len(queue['items'])} of {queue['total']}")

    for task in queue["items"]:
        tier = task.get("risk_tier") or "unscored"
        colour = TIER_COLOURS.get(tier, "#6b7280")
        risk = task.get("risk_score")

        with st.container(border=True):
            row = st.columns([4, 2, 2, 1.4, 1.4])

            row[0].markdown(
                f"**{task['patient_name']}** &nbsp; "
                f"<span style='color:{colour};font-weight:600'>"
                f"{tier.upper()}</span>"
                f"{f' · {risk:.2f}' if risk is not None else ''}",
                unsafe_allow_html=True,
            )
            row[0].caption(task.get("reason") or "")

            row[1].markdown(
                f"**{TASK_LABELS.get(task['kind'], titleise(task['kind']))}**"
            )
            row[1].caption(f"priority {task['priority']} · {task['status']}")

            row[2].caption(
                f"Week {task.get('weeks_on_therapy', '—')} · "
                f"{titleise(task.get('barrier_type')) or 'no barrier'}\n\n"
                f"Missed check-ins: {task.get('consecutive_no_reply', 0)}"
            )

            if task["status"] != "resolved":
                if row[3].button("Acknowledge", key=f"ack{task['id']}"):
                    api_post(f"/tasks/{task['id']}/ack")
                    st.rerun()
                if row[4].button("Resolve", key=f"res{task['id']}", type="primary"):
                    api_post(f"/tasks/{task['id']}/resolve")
                    st.rerun()
            else:
                row[4].caption(f"closed by {task.get('resolved_by') or '—'}")

st.divider()

# ------------------------------------------------------------ cohort metrics

st.subheader("Cohort")

left, right = st.columns([1, 1])

with left:
    st.markdown("**Risk distribution**")
    tier_frame = pd.DataFrame(
        {
            "tier": ["red", "amber", "green", "unscored"],
            "patients": [
                tiers.get("red", 0),
                tiers.get("amber", 0),
                tiers.get("green", 0),
                tiers.get("unscored", 0),
            ],
        }
    )
    st.bar_chart(tier_frame.set_index("tier"), height=240)

    barriers = metrics.get("barriers") or {}
    if barriers:
        st.caption(
            "Attributed barriers: "
            + " · ".join(f"{titleise(k)} {v}" for k, v in sorted(barriers.items()))
        )

with right:
    st.markdown("**Retention since enrollment**")
    curve = retention.get("curve") or []
    if len(curve) > 1:
        frame = pd.DataFrame(curve).set_index("week")[["retention"]]
        st.line_chart(frame, height=240)
        st.caption(
            f"Week {curve[-1]['week']}: {curve[-1]['retention']:.1%} retained "
            f"of {curve[-1]['at_risk']} patients followed that long."
        )
    else:
        st.info(
            "The curve needs at least two weeks of history. Seed a cohort and "
            "run the simulation, or let the scheduler run."
        )

detail = st.columns(4)
detail[0].metric("Messages last 7 days", engagement["messages_last_7_days"])
detail[1].metric("Check-ins logged", engagement["check_ins"])
detail[2].metric("Due for check-in", metrics["scheduler"]["due_now"])
detail[3].metric(
    "Mean risk",
    "—" if metrics["mean_risk_score"] is None else f"{metrics['mean_risk_score']:.2f}",
)

st.divider()

# ---------------------------------------------------- simulation comparison

sim = api_get("/simulation/results") or {"available": [], "results": {}}

if len(sim.get("available", [])) >= 1:
    st.subheader("Simulation: control vs intervention")
    st.caption(
        "Both arms receive cadence prompts and are scored identically. The "
        "control arm suppresses every intervention, so the gap isolates acting "
        "on the risk signal from merely being contacted."
    )

    results = sim["results"]
    series = {}
    for arm, payload in results.items():
        weekly = payload.get("weekly", [])
        if weekly:
            series[arm] = {row["week"]: row["retention"] for row in weekly}

    if series:
        curve_frame = pd.DataFrame(series)
        curve_frame.index.name = "week"
        st.line_chart(curve_frame, height=280)

    summary_rows = []
    for arm, payload in results.items():
        totals = payload.get("totals", {})
        guards = payload.get("guardrails", {})
        truth = payload.get("ground_truth", {})
        summary_rows.append(
            {
                "Arm": arm,
                "Patients": payload.get("patients"),
                "Weeks": payload.get("weeks"),
                "Retention": totals.get("final_retention"),
                "On therapy (truth)": truth.get("on_therapy"),
                "Msgs / patient": totals.get("messages_per_patient"),
                "Response rate": totals.get("response_rate"),
                "Tasks": totals.get("tasks_created"),
                "Max msgs / 7d": guards.get("max_messages_in_any_7_days"),
                "Cap violations": guards.get("cap_violations"),
            }
        )
    if summary_rows:
        st.dataframe(
            pd.DataFrame(summary_rows),
            hide_index=True,
            width="stretch",
            column_config={
                "Retention": st.column_config.NumberColumn(format="%.1f%%"),
                "Response rate": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

    if {"control", "intervention"} <= set(results):
        control = results["control"]["totals"]["final_retention"]
        treated = results["intervention"]["totals"]["final_retention"]
        st.metric(
            "Retention difference (intervention − control)",
            f"{(treated - control) * 100:+.1f} pts",
        )

    st.divider()

# ----------------------------------------------------------- patient roster

st.subheader("Patient roster")

filters = st.columns([1.4, 1.4, 1.4, 1.4, 2.4])
tier_filter = filters[0].selectbox("Tier", ["all", "red", "amber", "green"])
status_filter = filters[1].selectbox(
    "Status", ["all", "active", "paused", "discontinued"]
)
sort_by = filters[2].selectbox(
    "Sort by", ["risk", "silence", "due", "weeks", "name"]
)
only_silent = filters[3].checkbox("Silent only")
search = filters[4].text_input("Search name", placeholder="Start typing a name")

page = st.number_input("Page", min_value=1, value=1, step=1)

params = {
    "limit": PAGE_SIZE,
    "offset": (int(page) - 1) * PAGE_SIZE,
    "sort": sort_by,
    "order": "asc" if sort_by == "name" else "desc",
}
if tier_filter != "all":
    params["tier"] = tier_filter
if status_filter != "all":
    params["status"] = status_filter
if only_silent:
    params["silent"] = True
if search:
    params["search"] = search

roster = api_get("/patients", params) or {"items": [], "total": 0}

if not roster["items"]:
    st.info("No patients match these filters.")
else:
    total_pages = max(1, -(-roster["total"] // PAGE_SIZE))
    st.caption(
        f"{roster['total']} patients · page {int(page)} of {total_pages}"
    )

    table = pd.DataFrame(
        [
            {
                "Name": p.get("name"),
                "Week": p.get("weeks_on_therapy"),
                "Status": titleise(p.get("status")),
                "Risk": p.get("risk_score"),
                "Tier": (p.get("risk_tier") or "").upper() or None,
                "Barrier": titleise(p.get("barrier_type")) or None,
                "Missed": p.get("consecutive_no_reply"),
                "Last reply": p.get("last_reply_at"),
                "Next due": p.get("next_checkin_due"),
            }
            for p in roster["items"]
        ]
    )
    table["Last reply"] = pd.to_datetime(table["Last reply"], errors="coerce")
    table["Next due"] = pd.to_datetime(table["Next due"], errors="coerce")

    def risk_style(value) -> str:
        if value is None or pd.isna(value):
            return ""
        if value > RED_THRESHOLD:
            return "background-color: #fca5a5; color: #7f1d1d;"
        if value >= AMBER_THRESHOLD:
            return "background-color: #fdba74; color: #7c2d12;"
        return "background-color: #86efac; color: #14532d;"

    st.dataframe(
        table.style.map(risk_style, subset=["Risk"]),
        width="stretch",
        hide_index=True,
        column_config={
            "Risk": st.column_config.NumberColumn("Risk", format="%.3f"),
            "Last reply": st.column_config.DatetimeColumn(
                "Last reply", format="MMM D, HH:mm"
            ),
            "Next due": st.column_config.DatetimeColumn(
                "Next due", format="MMM D, HH:mm"
            ),
        },
    )

st.divider()

# ------------------------------------------------------------- control panel

st.subheader("Controls")

tick_col, sim_col = st.columns(2)

with tick_col:
    st.markdown("**Scheduler**")
    st.caption(
        "The same tick APScheduler runs hourly. It contacts only patients whose "
        "cadence has come due, so pressing it twice does nothing the second time."
    )
    if st.button("Run scheduler tick", type="primary"):
        response = api_post("/scheduler/tick")
        if response is not None and response.status_code == 200:
            outcome = response.json()
            st.success(
                f"Considered {outcome['considered']} · "
                f"messaged {outcome['messaged']} · "
                f"tasks {outcome['tasks_created']} · "
                f"discontinued {outcome['discontinued']}"
            )
            if outcome.get("by_rule"):
                st.caption(
                    "Rules fired: "
                    + ", ".join(f"{k} ×{v}" for k, v in outcome["by_rule"].items())
                )
        else:
            st.error("Tick failed.")

with sim_col:
    st.markdown("**Cohort simulation**")
    st.caption(
        "Runs months of virtual time against the same scheduler. Too long for a "
        "web request, so it runs from the command line and publishes JSON the "
        "chart above reads."
    )
    st.code(
        "python -m simulation.run_simulation --arm control      "
        "--patients 1000 --weeks 26\n"
        "python -m simulation.run_simulation --arm intervention "
        "--patients 1000 --weeks 26",
        language="bash",
    )

with st.expander("Simulate an inbound reply"):
    st.caption("Runs one patient through the live webhook pipeline.")
    reply_pool = api_get("/patients", {"limit": 200, "sort": "risk"}) or {"items": []}
    if not reply_pool["items"]:
        st.info("Enroll a patient first.")
    else:
        options = {
            f"{p['name']} (week {p['weeks_on_therapy']})": p["phone_number"]
            for p in reply_pool["items"]
        }
        chosen = st.selectbox("Patient", list(options))
        reply_map = {
            "1 — Going well": "1",
            "2 — Having side effects": "2",
            "3 — Not seeing results": "3",
        }
        chosen_reply = st.radio("Reply", list(reply_map), horizontal=True)

        if st.button("Send reply"):
            with st.spinner("Running the pipeline..."):
                response = api_post(
                    "/webhook/sms",
                    data={"From": options[chosen], "Body": reply_map[chosen_reply]},
                )
            if response is not None and response.status_code == 200:
                result = response.json()
                if result.get("error"):
                    st.warning(f"{result['error']}: {result.get('message', '')}")
                else:
                    cols = st.columns(4)
                    cols[0].metric("Risk", round(result.get("risk_score", 0), 3))
                    cols[1].metric("Tier", (result.get("risk_tier") or "-").upper())
                    cols[2].metric("Barrier", titleise(result.get("barrier_type")))
                    cols[3].metric("Rule", result.get("intervention_fired", "none"))

                    if result.get("intervention_message"):
                        st.markdown("**Sent to patient:**")
                        st.info(result["intervention_message"])
                    if result.get("tasks_created"):
                        st.warning(
                            "Task raised: "
                            + ", ".join(
                                TASK_LABELS.get(k, titleise(k))
                                for k in result["tasks_created"]
                            )
                        )
                    if result.get("suppressed"):
                        st.caption(
                            "Suppressed by guardrails: "
                            + ", ".join(
                                f"{s['rule']} ({s['reason']})"
                                for s in result["suppressed"]
                            )
                        )
                    st.caption(
                        f"Top SHAP feature: `{result.get('top_shap_feature', '-')}` · "
                        f"next check-in {result.get('next_checkin_due', '—')}"
                    )
            elif response is not None:
                st.error(f"API error: {response.status_code}")

with st.expander("Enroll new patient"):
    with st.form("enroll_form"):
        name = st.text_input("Full name")
        phone = st.text_input("Phone number", placeholder="+1XXXXXXXXXX")
        indication = st.selectbox("Indication", ["AOM", "T2D"])
        insurance = st.selectbox(
            "Insurance", ["commercial", "medicaid", "medicare", "uninsured"]
        )
        quintile = st.slider("Income quintile", 1, 5, 3)
        bmi = st.number_input(
            "Baseline BMI", min_value=27.0, max_value=70.0, value=38.0, step=0.1
        )
        submitted = st.form_submit_button("Enroll")

    if submitted:
        response = api_post(
            "/patients",
            json={
                "name": name,
                "phone_number": phone,
                "indication": indication,
                "insurance_type": insurance,
                "income_quintile": quintile,
                "baseline_bmi": bmi,
            },
        )
        if response is not None and response.status_code == 200:
            st.success(f"Enrolled {name}. The next tick will pick them up.")
            st.rerun()
        elif response is not None:
            try:
                st.error(response.json().get("detail", response.text))
            except Exception:
                st.error(response.text)

st.divider()
st.button("Refresh", on_click=st.rerun)

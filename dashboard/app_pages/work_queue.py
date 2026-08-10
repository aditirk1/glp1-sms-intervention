"""Work queue — patients who need a human today."""

import streamlit as st

from common import (
    PAGE_SIZE,
    TASK_LABELS,
    api_get,
    api_post,
    patient_heading_html,
    require_metrics,
    titleise,
)
from styles import page_header

page_header(
    "Work queue",
    "Rules-engine escalations, ranked by priority then current risk.",
)

metrics = require_metrics()

filters = st.columns([1.4, 1.4, 3])
queue_status = filters[0].selectbox(
    "Status",
    ["open", "acknowledged", "resolved", "all"],
    key="queue_status",
)
kind_options = ["all"] + sorted(metrics["work_queue"]["by_kind"].keys())
queue_kind = filters[1].selectbox("Type", kind_options, key="queue_kind")

queue_params = {"status": queue_status, "limit": PAGE_SIZE}
if queue_kind != "all":
    queue_params["kind"] = queue_kind

queue = api_get("/tasks", queue_params) or {"items": [], "total": 0}

summary = st.columns(3)
summary[0].metric("Showing", len(queue["items"]))
summary[1].metric("In filter", queue["total"])
summary[2].metric("Open overall", metrics["work_queue"]["open_tasks"])

st.write("")

if not queue["items"]:
    st.success("Queue is clear. Nothing needs a human right now.")
else:
    for task in queue["items"]:
        tier = task.get("risk_tier") or "unscored"
        risk = task.get("risk_score")

        with st.container(border=True):
            row = st.columns([4.2, 2.2, 2.4, 1.4, 1.4], gap="small")

            row[0].markdown(
                patient_heading_html(task["patient_name"], tier, risk),
                unsafe_allow_html=True,
            )
            row[0].caption(task.get("reason") or "No reason recorded.")

            row[1].markdown(
                f"**{TASK_LABELS.get(task['kind'], titleise(task['kind']))}**"
            )
            row[1].caption(f"Priority {task['priority']} · {task['status']}")

            row[2].caption(
                f"Week {task.get('weeks_on_therapy', '—')} · "
                f"{titleise(task.get('barrier_type')) or 'no barrier'}\n\n"
                f"Missed check-ins: {task.get('consecutive_no_reply', 0)}"
            )

            if task["status"] != "resolved":
                if row[3].button(
                    "Acknowledge",
                    key=f"ack{task['id']}",
                    width="stretch",
                ):
                    api_post(f"/tasks/{task['id']}/ack")
                    st.rerun()
                if row[4].button(
                    "Resolve",
                    key=f"res{task['id']}",
                    type="primary",
                    width="stretch",
                ):
                    api_post(f"/tasks/{task['id']}/resolve")
                    st.rerun()
            else:
                row[4].caption(f"Closed by {task.get('resolved_by') or '—'}")

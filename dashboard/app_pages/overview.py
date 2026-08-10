"""Cohort overview — KPIs, risk mix, and live retention."""

import pandas as pd
import streamlit as st

from common import percent, require_metrics, titleise
from styles import page_header

page_header(
    "Overview",
    "Live cohort pulse — risk mix, retention, and engagement at a glance.",
)

metrics = require_metrics()
tiers = metrics["tiers"]
engagement = metrics["engagement"]
retention = metrics["retention"]

kpis = st.columns(6)
kpis[0].metric("Enrolled", metrics["total_patients"])
kpis[1].metric("Open tasks", metrics["work_queue"]["open_tasks"])
kpis[2].metric("High risk", tiers.get("red", 0))
kpis[3].metric("Silent (2+)", engagement["silent_two_or_more"])
kpis[4].metric("Response rate", percent(engagement["response_rate"]))
kpis[5].metric("Retention", percent(retention["rate"]))

st.write("")

left, right = st.columns(2, gap="large")

with left:
    with st.container(border=True):
        st.markdown("#### Risk distribution")
        st.caption("Current denormalized tier on every active patient.")
        tier_frame = pd.DataFrame(
            {
                "Tier": ["High", "Medium", "Lower", "Unscored"],
                "Patients": [
                    tiers.get("red", 0),
                    tiers.get("amber", 0),
                    tiers.get("green", 0),
                    tiers.get("unscored", 0),
                ],
            }
        ).set_index("Tier")
        st.bar_chart(tier_frame, height=280, color="#0093D0")
        st.caption("High / medium / lower dropout risk.")

        barriers = metrics.get("barriers") or {}
        if barriers:
            st.caption(
                "Attributed barriers · "
                + " · ".join(
                    f"{titleise(k)} {v}" for k, v in sorted(barriers.items())
                )
            )

with right:
    with st.container(border=True):
        st.markdown("#### Retention since enrollment")
        st.caption("Share of the cohort still active by weeks since enroll.")
        curve = retention.get("curve") or []
        if len(curve) > 1:
            frame = pd.DataFrame(curve).set_index("week")[["retention"]]
            frame.columns = ["Retention"]
            st.line_chart(frame, height=280, color="#5B2D8E")
            st.caption(
                f"Week {curve[-1]['week']}: {curve[-1]['retention']:.1%} retained "
                f"of {curve[-1]['at_risk']} patients followed that long."
            )
        else:
            st.info(
                "Live retention builds as patients age in this database. "
                "A brand-new seed looks flat at 100% until people are marked "
                "discontinued. For the 26-week dropout story, open Outcomes."
            )

st.write("")

detail = st.columns(4)
detail[0].metric("Messages · 7 days", engagement["messages_last_7_days"])
detail[1].metric("Check-ins logged", engagement["check_ins"])
detail[2].metric("Due for check-in", metrics["scheduler"]["due_now"])
detail[3].metric(
    "Mean risk",
    "—"
    if metrics["mean_risk_score"] is None
    else f"{metrics['mean_risk_score']:.2f}",
)

statuses = metrics.get("statuses") or {}
if statuses:
    st.caption(
        "Status mix · "
        + " · ".join(f"{titleise(k)} {v}" for k, v in statuses.items() if v)
    )

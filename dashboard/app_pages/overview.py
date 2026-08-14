"""Cohort overview — KPIs, risk mix, and live retention."""

import streamlit as st

from charts import program_status_chart, retention_tenure_chart, risk_tier_chart
from common import percent, require_metrics, sentence_case
from styles import page_header, page_shell

with page_shell():
    page_header(
        "Overview",
        "Live cohort pulse — risk mix, retention, and engagement at a glance.",
    )

    metrics = require_metrics()
    tiers = metrics["tiers"]
    engagement = metrics["engagement"]
    retention = metrics["retention"]

    check_ins = engagement.get("check_ins") or 0
    if check_ins:
        st.caption(
            f"Live panel · {check_ins:,} check-ins logged · "
            "continue from Operations (scheduler tick, reply simulator)."
        )
    else:
        st.info(
            "Blank panel — no SMS history yet. Run "
            "`python -m simulation.bootstrap_live --weeks 13` or use "
            "Operations → scheduler tick to start."
        )

    kpis = st.columns(6)
    kpis[0].metric("Enrolled", metrics["total_patients"])
    kpis[1].metric("Open tasks", metrics["work_queue"]["open_tasks"])
    kpis[2].metric("High risk", tiers.get("red", 0))
    kpis[3].metric("Silent (2+)", engagement["silent_two_or_more"])
    kpis[4].metric("Response rate", percent(engagement["response_rate"]))
    kpis[5].metric(
        "Retention",
        percent(retention["rate"]),
        help="Active patients ÷ total enrolled today. This is the headline number.",
    )

    st.write("")

    left, right = st.columns(2, gap="large")

    with left:
        with st.container(border=True):
            st.markdown("#### Risk distribution")
            st.caption("Current denormalized tier on every active patient.")
            st.altair_chart(risk_tier_chart(tiers), width="stretch")
            st.caption("High / medium / low dropout risk.")

            barriers = metrics.get("barriers") or {}
            if barriers:
                st.caption(
                    "Attributed barriers · "
                    + " · ".join(
                        f"{sentence_case(k)} {v}" for k, v in sorted(barriers.items())
                    )
                )

    with right:
        with st.container(border=True):
            st.markdown("#### Retention by enrollment age")
            st.caption(
                "Share still active among patients who enrolled "
                "that long ago. Adds up to the headline Retention KPI above."
            )
            by_tenure = retention.get("by_tenure") or []
            if by_tenure:
                st.altair_chart(retention_tenure_chart(by_tenure), width="stretch")
                parts = [
                    f"{row['bucket']}: {row['active']}/{row['total']} "
                    f"({row['retention']:.0%})"
                    for row in by_tenure
                ]
                st.caption(" · ".join(parts))
            else:
                st.info("Not enough enrollment history yet.")

            st.markdown("##### Program status today")
            st.write("")
            active = retention.get("active") or 0
            discontinued = retention.get("discontinued") or 0
            status_cols = st.columns([1.15, 1], gap="medium")
            with status_cols[0]:
                st.altair_chart(
                    program_status_chart(active, discontinued),
                    width="stretch",
                )
            with status_cols[1]:
                st.metric("Active", active)
                st.metric("Discontinued", discontinued)
                total = active + discontinued
                if total:
                    st.caption(f"{active / total:.0%} still in program")

            st.caption(
                "For the controlled 26-week intervention vs control experiment, "
                "open **Demo simulation** — that cohort all enrolled on the same day."
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
            + " · ".join(f"{sentence_case(k)} {v}" for k, v in statuses.items() if v)
        )

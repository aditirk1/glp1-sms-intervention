"""26-week simulation outcomes — control vs intervention."""

import pandas as pd
import streamlit as st

from common import api_get, sentence_case
from styles import page_header, page_shell

with page_shell():
    page_header(
        "Outcomes",
        "Pre-computed 26-week experiment (control vs intervention). "
        "This is not the live patient panel: DEMO Purpose Only",
    )

    sim = api_get("/simulation/results") or {"available": [], "results": {}}
    results = sim.get("results") or {}
    available = sim.get("available") or []

    if not available:
        st.info(
            "No simulation results yet. After you run the 26-week arms once, "
            "this page fills in automatically from saved results."
        )
        st.stop()

    # ----- headline KPIs -----

    summary_cols = st.columns(len(available) + (1 if len(available) >= 2 else 0))
    arm_retention = {}
    for i, arm in enumerate(available):
        payload = results[arm]
        totals = payload.get("totals") or {}
        retention = totals.get("final_retention")
        arm_retention[arm] = retention
        patients = payload.get("patients") or totals.get("final_active")
        weeks = payload.get("weeks")
        summary_cols[i].metric(
            sentence_case(arm),
            f"{100 * retention:.1f}% retained" if retention is not None else "—",
            help=f"{patients} patients · {weeks} weeks",
        )

    if {"control", "intervention"} <= set(available):
        control = arm_retention.get("control") or 0
        treated = arm_retention.get("intervention") or 0
        summary_cols[-1].metric(
            "Lift (intervention − control)",
            f"{(treated - control) * 100:+.1f} pts",
        )

    st.write("")

    # ----- retention curves -----

    series = {}
    truth_series = {}
    for arm, payload in results.items():
        weekly = payload.get("weekly") or []
        if not weekly:
            continue
        series[arm] = {row["week"]: row.get("retention") for row in weekly}
        if any("ground_truth_retention" in row for row in weekly):
            truth_series[arm] = {
                row["week"]: row.get("ground_truth_retention") for row in weekly
            }

    left, right = st.columns(2, gap="large")

    with left:
        with st.container(border=True):
            st.markdown("#### Observed retention")
            st.caption(
                "Share still active in the program (not lost to follow-up). "
                "This is what the care team can see."
            )
            if series:
                frame = pd.DataFrame(series)
                frame.index.name = "Week"
                st.line_chart(frame, height=320)
            else:
                st.info("No weekly series in the results file.")

    with right:
        with st.container(border=True):
            st.markdown("#### Still on therapy (ground truth)")
            st.caption(
                "Share still injecting in the simulation. Some patients quit "
                "quietly while still marked active — that gap is lost contact."
            )
            if truth_series:
                frame = pd.DataFrame(truth_series)
                frame.index.name = "Week"
                st.line_chart(frame, height=320)
            else:
                st.info("Ground-truth series not present in these results.")

    st.write("")

    # ----- comparison table -----

    rows = []
    for arm, payload in results.items():
        totals = payload.get("totals") or {}
        guards = payload.get("guardrails") or {}
        truth = payload.get("ground_truth") or {}
        n = payload.get("patients") or 0
        on_therapy = truth.get("on_therapy")
        on_therapy_pct = (
            round(100 * on_therapy / n, 1) if on_therapy is not None and n else None
        )
        rows.append(
            {
                "Arm": sentence_case(arm),
                "Patients": n or None,
                "Weeks": payload.get("weeks"),
                "Retained %": round(100 * (totals.get("final_retention") or 0), 1),
                "On therapy %": on_therapy_pct,
                "Msgs / patient": totals.get("messages_per_patient"),
                "Response %": round(100 * (totals.get("response_rate") or 0), 1),
                "Tasks": totals.get("tasks_created"),
                "Cap violations": guards.get("cap_violations"),
            }
        )

    with st.container(border=True):
        st.markdown("#### Arm comparison")
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            width="stretch",
            column_config={
                "Retained %": st.column_config.NumberColumn(format="%.1f"),
                "On therapy %": st.column_config.NumberColumn(format="%.1f"),
                "Response %": st.column_config.NumberColumn(format="%.1f"),
                "Msgs / patient": st.column_config.NumberColumn(format="%.1f"),
            },
        )

    st.caption(
        "Both arms receive cadence prompts and are scored the same way. "
        "Control suppresses interventions, so the gap isolates acting on the "
        "risk signal. Effect sizes in the patient simulator are assumptions — "
        "this shows the engine and guardrails at cohort scale."
    )

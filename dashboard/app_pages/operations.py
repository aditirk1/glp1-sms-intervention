"""Operational controls — scheduler, reply simulator, enrollment."""

import streamlit as st

from common import TASK_LABELS, TIER_LABELS, api_get, api_post, sentence_case, tier_dot_html
from styles import page_header, page_shell

with page_shell():
    page_header(
        "Operations",
        "Drive the live pipeline — scheduler, reply simulator, and enrollment.",
    )

    left, right = st.columns(2, gap="large")

    with left:
        with st.container(border=True):
            st.markdown("#### Scheduler")
            st.caption(
                "Runs one due-check-in pass — the same job the background scheduler "
                "would run. Safe to press twice; only due patients are contacted."
            )
            if st.button("Run scheduler tick", type="primary", width="stretch"):
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
                            + ", ".join(
                                f"{k} ×{v}" for k, v in outcome["by_rule"].items()
                            )
                        )
                else:
                    st.error("Tick failed.")

    with right:
        with st.container(border=True):
            st.markdown("#### Enroll patient")
            st.caption("Adds someone to the live loop. The next tick picks them up.")
            with st.form("enroll_form"):
                name = st.text_input("Full name")
                phone = st.text_input("Phone number", placeholder="+1XXXXXXXXXX")
                indication = st.selectbox("Indication", ["AOM", "T2D"])
                insurance = st.selectbox(
                    "Insurance",
                    ["commercial", "medicaid", "medicare", "uninsured"],
                    format_func=sentence_case,
                )
                quintile = st.slider("Income quintile", 1, 5, 3)
                bmi = st.number_input(
                    "Baseline BMI",
                    min_value=27.0,
                    max_value=70.0,
                    value=38.0,
                    step=0.1,
                )
                submitted = st.form_submit_button("Enroll", type="primary")

            if submitted:
                if not (name or "").strip() or not (phone or "").strip():
                    st.error("Name and phone number are required.")
                else:
                    response = api_post(
                        "/patients",
                        json={
                            "name": name.strip(),
                            "phone_number": phone.strip(),
                            "indication": indication,
                            "insurance_type": insurance,
                            "income_quintile": quintile,
                            "baseline_bmi": bmi,
                        },
                    )
                    if response is not None and response.status_code == 200:
                        st.success(
                            f"Enrolled {name.strip()}. The next tick will pick them up."
                        )
                        st.rerun()
                    elif response is not None:
                        try:
                            st.error(response.json().get("detail", response.text))
                        except Exception:
                            st.error(response.text)

    st.write("")

    with st.container(border=True):
        st.markdown("#### Simulate an inbound reply")
        st.caption(
            "Posts through the live webhook so you see score, rules, and SMS "
            "without a physical phone. Search by name — the default list is "
            "only the highest-risk patients."
        )
        reply_search = st.text_input(
            "Find patient",
            placeholder="e.g. Maria Alvarez",
            key="reply_patient_search",
        )
        params = {"limit": 200, "sort": "risk", "status": "active"}
        if (reply_search or "").strip():
            params = {
                "limit": 50,
                "sort": "name",
                "order": "asc",
                "status": "active",
                "search": reply_search.strip(),
            }
        reply_pool = api_get("/patients", params) or {"items": []}
        if not reply_pool["items"]:
            st.info(
                "No matches. Try a different name, or enroll a patient first."
                if (reply_search or "").strip()
                else "Enroll a patient first."
            )
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
            chosen_reply = st.segmented_control(
                "Reply",
                options=list(reply_map),
                default=list(reply_map)[0],
            )

            if st.button("Send reply", type="primary"):
                if not chosen_reply:
                    st.warning("Choose a reply first.")
                else:
                    with st.spinner("Running the pipeline..."):
                        response = api_post(
                            "/webhook/sms",
                            data={
                                "From": options[chosen],
                                "Body": reply_map[chosen_reply],
                            },
                        )
                    if response is not None and response.status_code == 200:
                        result = response.json()
                        if result.get("error"):
                            st.warning(
                                f"{result['error']}: {result.get('message', '')}"
                            )
                        else:
                            cols = st.columns(4)
                            cols[0].metric(
                                "Risk", round(result.get("risk_score", 0), 3)
                            )
                            tier_key = (result.get("risk_tier") or "unscored").lower()
                            cols[1].markdown(
                                "Risk level<br>"
                                + tier_dot_html(tier_key, size="0.75rem")
                                + f"<strong>{TIER_LABELS.get(tier_key, 'Not scored')}</strong>",
                                unsafe_allow_html=True,
                            )
                            cols[2].metric(
                                "Barrier", sentence_case(result.get("barrier_type"))
                            )
                            cols[3].metric(
                                "Rule", result.get("intervention_fired", "none")
                            )

                            if result.get("intervention_message"):
                                st.markdown("**Sent to patient**")
                                st.info(result["intervention_message"])
                            else:
                                suppressed = result.get("suppressed") or []
                                if (
                                    suppressed
                                    or result.get("intervention_fired") == "none"
                                ):
                                    reasons = (
                                        ", ".join(
                                            f"{s['rule']} ({s['reason']})"
                                            for s in suppressed
                                        )
                                        or "no matching send"
                                    )
                                    st.warning(
                                        "No SMS was sent. "
                                        f"Guardrails or policy blocked it: {reasons}."
                                    )

                            if result.get("tasks_created"):
                                st.warning(
                                    "Task raised: "
                                    + ", ".join(
                                        TASK_LABELS.get(k, sentence_case(k))
                                        for k in result["tasks_created"]
                                    )
                                )

                            if (
                                result.get("suppressed")
                                and result.get("intervention_message")
                            ):
                                st.caption(
                                    "Also suppressed: "
                                    + ", ".join(
                                        f"{s['rule']} ({s['reason']})"
                                        for s in result["suppressed"]
                                    )
                                )

                            shap = result.get("top_shap_feature") or "-"
                            if shap == "unavailable":
                                st.error(
                                    "Risk model fell back to a neutral score "
                                    "(SHAP unavailable). Check the API console, "
                                    "then restart uvicorn."
                                )
                            st.caption(
                                f"Top SHAP feature: `{shap}` · "
                                f"next check-in {result.get('next_checkin_due', '-')}"
                            )
                    elif response is not None:
                        st.error(f"API error: {response.status_code}")

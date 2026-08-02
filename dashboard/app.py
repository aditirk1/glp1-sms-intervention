"""GoalPost¹ care team dashboard.

Shows who is at risk of dropping off GLP-1 therapy, what barrier the model
attributed it to, and which intervention fired. The simulator runs a live
inbound reply through the real API pipeline.
"""

import os
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = 60

RED_THRESHOLD = 0.60
AMBER_THRESHOLD = 0.35

st.set_page_config(page_title="GoalPost¹", page_icon="signal", layout="wide")


def fetch_patients() -> list[dict]:
    try:
        response = requests.get(f"{API_BASE_URL}/patients", timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        st.error(f"Could not reach the GoalPost¹ API at {API_BASE_URL}: {exc}")
        st.caption("Start it with: uvicorn api.main:app --reload --port 8000")
        return []


def risk_score_style(value) -> str:
    """Background colour for the Risk Score cell."""
    if value is None or pd.isna(value) or value == 0:
        return ""
    if value > RED_THRESHOLD:
        return "background-color: #fca5a5; color: #7f1d1d;"
    if value >= AMBER_THRESHOLD:
        return "background-color: #fdba74; color: #7c2d12;"
    return "background-color: #86efac; color: #14532d;"


def is_today(iso_timestamp: str | None) -> bool:
    if not iso_timestamp:
        return False
    try:
        stamp = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return False
    # Check-ins are stored as naive UTC.
    return stamp.date() == datetime.now(timezone.utc).date()


# SECTION 1: HEADER
st.title("GoalPost¹")
st.caption("GLP-1 retention monitoring — SMS check-in backbone")

patients = fetch_patients()

total_enrolled = len(patients)
at_risk = sum(
    1
    for p in patients
    if (p.get("last_risk_score") or 0) > RED_THRESHOLD
)
interventions_today = sum(
    1
    for p in patients
    if p.get("last_intervention") and is_today(p.get("last_checkin_at"))
)

col1, col2, col3 = st.columns(3)
col1.metric("Total Enrolled", total_enrolled)
col2.metric("At Risk (Red)", at_risk)
col3.metric("Interventions Today", interventions_today)

st.divider()

# SECTION 2: PATIENT TABLE
st.subheader("Patient Overview")

if not patients:
    st.info("No patients enrolled yet. Use the Enroll New Patient form below.")
else:
    table = pd.DataFrame(
        [
            {
                "Name": p.get("name"),
                "Weeks": p.get("weeks_on_therapy"),
                "Indication": p.get("indication"),
                "Last Reply": p.get("last_reply"),
                "Risk Score": p.get("last_risk_score"),
                "Risk Tier": (p.get("last_risk_tier") or "").upper() or None,
                "Barrier": (p.get("last_barrier_type") or "").replace("_", " ").title()
                or None,
                "Last Intervention": (p.get("last_intervention") or "")
                .replace("_", " ")
                .title()
                or None,
                "Last Check-in": p.get("last_checkin_at"),
            }
            for p in patients
        ]
    )

    table["Last Check-in"] = pd.to_datetime(table["Last Check-in"], errors="coerce")
    table = table.sort_values(
        "Risk Score", ascending=False, key=lambda s: s.fillna(0)
    ).reset_index(drop=True)

    st.dataframe(
        table.style.map(risk_score_style, subset=["Risk Score"]),
        width="stretch",
        hide_index=True,
        column_config={
            "Risk Score": st.column_config.NumberColumn("Risk Score", format="%.3f"),
            "Last Check-in": st.column_config.DatetimeColumn(
                "Last Check-in", format="MMM D, HH:mm"
            ),
        },
    )

st.divider()

# SECTION 3: PATIENT SIMULATOR
st.subheader("Patient Simulator")
st.caption("Simulate an inbound reply to run the full pipeline live.")

if not patients:
    st.info("Enroll a patient first.")
else:
    patient_options = {p["name"]: p["phone_number"] for p in patients}
    selected_name = st.selectbox("Select patient", list(patient_options.keys()))
    selected_phone = patient_options[selected_name]

    reply_map = {
        "1 - Going well": "1",
        "2 - Having side effects": "2",
        "3 - Not seeing results": "3",
    }
    selected_reply_label = st.radio("Patient reply", list(reply_map.keys()))
    selected_reply = reply_map[selected_reply_label]

    if st.button("Simulate Reply", type="primary"):
        with st.spinner("Running pipeline..."):
            try:
                response = requests.post(
                    f"{API_BASE_URL}/webhook/sms",
                    data={"From": selected_phone, "Body": selected_reply},
                    timeout=REQUEST_TIMEOUT,
                )
            except Exception as exc:
                st.error(f"Could not reach the API: {exc}")
                response = None

        if response is not None and response.status_code == 200:
            result = response.json()
            if result.get("error"):
                st.warning(f"{result['error']}: {result.get('message', '')}")
            else:
                st.success("Pipeline complete")

                mcol1, mcol2, mcol3 = st.columns(3)
                mcol1.metric("Risk Score", round(result.get("risk_score", 0), 3))
                mcol2.metric("Risk Tier", result.get("risk_tier", "-").upper())
                mcol3.metric(
                    "Barrier Type",
                    result.get("barrier_type", "-").replace("_", " ").title(),
                )

                st.caption(
                    f"Intervention fired: "
                    f"`{result.get('intervention_fired', 'none')}`  ·  "
                    f"Top SHAP feature: `{result.get('top_shap_feature', '-')}`"
                )

                if result.get("intervention_message"):
                    st.markdown("**Message that would be sent to patient:**")
                    st.info(result["intervention_message"])
                else:
                    st.write(
                        "No intervention triggered for this reply/risk combination."
                    )
        elif response is not None:
            st.error(f"API error: {response.status_code} - {response.text}")

st.divider()

# SECTION 4: ENROLL PATIENT
with st.expander("Enroll New Patient"):
    with st.form("enroll_form"):
        name = st.text_input("Full Name")
        phone = st.text_input("Phone Number", placeholder="+1XXXXXXXXXX")
        indication = st.selectbox("Indication", ["AOM", "T2D"])
        insurance = st.selectbox(
            "Insurance Type", ["commercial", "medicaid", "medicare", "uninsured"]
        )
        quintile = st.slider("Income Quintile", 1, 5, 3)
        bmi = st.number_input(
            "Baseline BMI", min_value=27.0, max_value=70.0, value=38.0, step=0.1
        )
        submitted = st.form_submit_button("Enroll Patient")

    if submitted:
        payload = {
            "name": name,
            "phone_number": phone,
            "indication": indication,
            "insurance_type": insurance,
            "income_quintile": quintile,
            "baseline_bmi": bmi,
        }
        try:
            r = requests.post(
                f"{API_BASE_URL}/patients", json=payload, timeout=REQUEST_TIMEOUT
            )
            if r.status_code == 200:
                st.success(f"Enrolled {name} successfully.")
                st.rerun()
            else:
                try:
                    detail = r.json().get("detail", r.text)
                except Exception:
                    detail = r.text
                st.error(f"Error: {detail}")
        except Exception as exc:
            st.error(f"Could not reach the API: {exc}")

# SECTION 5: MANUAL CHECK-IN TRIGGER
with st.expander("Send Check-in Message"):
    if patients:
        patient_names = {p["name"]: p["id"] for p in patients}
        selected = st.selectbox(
            "Select patient for check-in",
            list(patient_names.keys()),
            key="checkin_select",
        )
        if st.button("Send Check-in"):
            pid = patient_names[selected]
            try:
                r = requests.post(
                    f"{API_BASE_URL}/send-checkin/{pid}", timeout=REQUEST_TIMEOUT
                )
                if r.status_code == 200:
                    result = r.json()
                    st.success("Check-in triggered.")
                    st.markdown("**Message generated:**")
                    st.code(result.get("message_sent", ""))
                else:
                    st.error("Failed to send check-in.")
            except Exception as exc:
                st.error(f"Could not reach the API: {exc}")
    else:
        st.info("Enroll a patient first.")

st.divider()
st.button("Refresh Data", on_click=st.rerun)

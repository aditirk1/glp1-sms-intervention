"""GoaLPost-1 care team dashboard — multipage entrypoint."""

from pathlib import Path

import streamlit as st

from styles import inject_theme, render_chrome

st.set_page_config(
    page_title="GoaLPost-1",
    page_icon=":material/vital_signs:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_theme()

PAGES = Path(__file__).parent / "app_pages"

overview = st.Page(
    PAGES / "overview.py",
    title="Overview",
    icon=":material/dashboard:",
    default=True,
)
work_queue = st.Page(
    PAGES / "work_queue.py",
    title="Work queue",
    icon=":material/assignment:",
)
patients = st.Page(
    PAGES / "patients.py",
    title="Patients",
    icon=":material/groups:",
)
outcomes = st.Page(
    PAGES / "outcomes.py",
    title="Outcomes",
    icon=":material/monitoring:",
)
operations = st.Page(
    PAGES / "operations.py",
    title="Operations",
    icon=":material/tune:",
)

# Hide Streamlit's default top tabs — we render an elegant branded nav instead.
page = st.navigation(
    [overview, work_queue, patients, outcomes, operations],
    position="hidden",
)

render_chrome(
    [
        (overview, "Overview", ":material/dashboard:"),
        (work_queue, "Work queue", ":material/assignment:"),
        (patients, "Patients", ":material/groups:"),
        (outcomes, "Outcomes", ":material/monitoring:"),
        (operations, "Operations", ":material/tune:"),
    ],
    active=page,
)

page.run()

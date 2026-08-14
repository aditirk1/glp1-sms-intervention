"""GoaLPost-1 care team dashboard — multipage entrypoint."""

from pathlib import Path

import streamlit as st

from styles import inject_theme, render_chrome

st.set_page_config(
    page_title="GoaLPost-1",
    page_icon=str(Path(__file__).parent / "assets" / "goalpost1-logo-circle.png"),
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
demo_simulation = st.Page(
    PAGES / "outcomes.py",
    title="Demo simulation",
    icon=":material/monitoring:",
)
operations = st.Page(
    PAGES / "operations.py",
    title="Operations",
    icon=":material/tune:",
)

# Default on so the demo script still finds the tab; uncheck "Sim" to hide it.
if "show_demo_sim" not in st.session_state:
    st.session_state.show_demo_sim = True

nav_pages = [overview, work_queue, patients]
nav_labels = [
    (overview, "Overview", ":material/dashboard:"),
    (work_queue, "Work queue", ":material/assignment:"),
    (patients, "Patients", ":material/groups:"),
]
if st.session_state.show_demo_sim:
    nav_pages.append(demo_simulation)
    nav_labels.append(
        (demo_simulation, "Demo simulation", ":material/monitoring:")
    )
nav_pages.append(operations)
nav_labels.append((operations, "Operations", ":material/tune:"))

# Hide Streamlit's default top tabs — we render an elegant branded nav instead.
page = st.navigation(nav_pages, position="hidden")

render_chrome(nav_labels, active=page)

page.run()

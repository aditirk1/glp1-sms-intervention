"""Patient roster with filters and risk-aware table styling."""

import pandas as pd
import streamlit as st

from common import (
    AMBER_THRESHOLD,
    PAGE_SIZE,
    RED_THRESHOLD,
    api_get,
    titleise,
)
from styles import page_header

page_header("Patients", "Browse, filter, and triage the enrolled cohort.")

filters = st.columns([1.3, 1.3, 1.3, 1.2, 2.4])
tier_filter = filters[0].selectbox(
    "Risk",
    ["all", "high", "medium", "lower"],
    format_func=lambda v: {
        "all": "All",
        "high": "High",
        "medium": "Medium",
        "lower": "Lower",
    }[v],
)
status_filter = filters[1].selectbox(
    "Status", ["all", "active", "paused", "discontinued"]
)
sort_by = filters[2].selectbox(
    "Sort by", ["risk", "silence", "due", "weeks", "name"]
)
only_silent = filters[3].checkbox("Silent only", value=False)
search = filters[4].text_input(
    "Search name", placeholder="Start typing a name"
)

page = st.number_input("Page", min_value=1, value=1, step=1)

params = {
    "limit": PAGE_SIZE,
    "offset": (int(page) - 1) * PAGE_SIZE,
    "sort": sort_by,
    "order": "asc" if sort_by == "name" else "desc",
}
if tier_filter != "all":
    params["tier"] = {"high": "red", "medium": "amber", "lower": "green"}[
        tier_filter
    ]
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
    st.caption(f"{roster['total']} patients · page {int(page)} of {total_pages}")

    table = pd.DataFrame(
        [
            {
                "Name": p.get("name"),
                "Week": p.get("weeks_on_therapy"),
                "Status": titleise(p.get("status")),
                "Risk": p.get("risk_score"),
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
            return "background-color: #fecaca; color: #7f1d1d;"
        if value >= AMBER_THRESHOLD:
            return "background-color: #fed7aa; color: #7c2d12;"
        return "background-color: #a7f3d0; color: #064e3b;"

    with st.container(border=True):
        st.dataframe(
            table.style.map(risk_style, subset=["Risk"]),
            width="stretch",
            hide_index=True,
            height=520,
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

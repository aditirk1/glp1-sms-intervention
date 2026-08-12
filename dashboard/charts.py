"""Altair charts styled for the GoaLPost-1 dashboard."""

from __future__ import annotations

import altair as alt
import pandas as pd

alt.data_transformers.disable_max_rows()

TIER_ORDER = ["High", "Medium", "Low", "Unscored"]
TIER_COLORS = {
    "High": "#dc2626",
    "Medium": "#f59e0b",
    "Low": "#16a34a",
    "Unscored": "#94a3b8",
}
STATUS_COLORS = {"Active": "#0093D0", "Discontinued": "#cbd5e1"}
RETENTION_PURPLE = "#5b2d8e"


def _themed(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure_view(strokeWidth=0, fill="transparent")
        .configure_axis(
            gridColor="rgba(0, 147, 208, 0.10)",
            domainColor="rgba(11, 27, 63, 0.12)",
            tickColor="rgba(11, 27, 63, 0.12)",
            labelColor="#475569",
            titleColor="#0b1b3f",
            labelFont="Inter, sans-serif",
            titleFont="DM Sans, sans-serif",
        )
        .configure_legend(
            labelColor="#475569",
            titleColor="#0b1b3f",
            labelFont="Inter, sans-serif",
            titleFont="DM Sans, sans-serif",
        )
    )


def risk_tier_chart(tiers: dict) -> alt.Chart:
    frame = pd.DataFrame(
        {
            "Tier": TIER_ORDER,
            "Patients": [
                tiers.get("red", 0),
                tiers.get("amber", 0),
                tiers.get("green", 0),
                tiers.get("unscored", 0),
            ],
        }
    )
    chart = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6, stroke="#ffffff", strokeWidth=1.5)
        .encode(
            x=alt.X("Tier:N", sort=TIER_ORDER, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Patients:Q", title="Patients", scale=alt.Scale(nice=True)),
            color=alt.Color(
                "Tier:N",
                sort=TIER_ORDER,
                scale=alt.Scale(
                    domain=TIER_ORDER,
                    range=[TIER_COLORS[t] for t in TIER_ORDER],
                ),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("Tier:N", title="Tier"),
                alt.Tooltip("Patients:Q", title="Patients", format=","),
            ],
        )
        .properties(height=260)
    )
    return _themed(chart)


def retention_tenure_chart(rows: list[dict]) -> alt.Chart:
    frame = pd.DataFrame(rows)
    frame["pct"] = (frame["retention"] * 100).round(1)
    frame["label"] = frame["bucket"]

    area = (
        alt.Chart(frame)
        .mark_area(opacity=0.18, color=RETENTION_PURPLE, interpolate="monotone")
        .encode(
            x=alt.X("label:N", sort=frame["label"].tolist(), title=None),
            y=alt.Y("pct:Q", title="Still active (%)", scale=alt.Scale(domain=[0, 100])),
        )
    )
    line = (
        alt.Chart(frame)
        .mark_line(color=RETENTION_PURPLE, strokeWidth=3, interpolate="monotone")
        .encode(
            x=alt.X("label:N", sort=frame["label"].tolist()),
            y="pct:Q",
        )
    )
    points = (
        alt.Chart(frame)
        .mark_circle(color=RETENTION_PURPLE, size=90, stroke="#ffffff", strokeWidth=2)
        .encode(
            x=alt.X("label:N", sort=frame["label"].tolist()),
            y="pct:Q",
            tooltip=[
                alt.Tooltip("label:N", title="Enrolled"),
                alt.Tooltip("pct:Q", title="Still active", format=".1f"),
                alt.Tooltip("active:Q", title="Active"),
                alt.Tooltip("total:Q", title="In bucket"),
            ],
        )
    )
    return _themed((area + line + points).properties(height=220))


def program_status_chart(active: int, discontinued: int) -> alt.Chart:
    frame = pd.DataFrame(
        {
            "Status": ["Active", "Discontinued"],
            "Patients": [active, discontinued],
        }
    )
    total = active + discontinued or 1
    frame["Share"] = frame["Patients"] / total
    chart = (
        alt.Chart(frame)
        .mark_arc(
            innerRadius=42,
            outerRadius=68,
            cornerRadius=4,
            stroke="#ffffff",
            strokeWidth=2,
            padAngle=0.02,
        )
        .encode(
            theta=alt.Theta("Patients:Q", stack=True),
            color=alt.Color(
                "Status:N",
                scale=alt.Scale(
                    domain=["Active", "Discontinued"],
                    range=[STATUS_COLORS["Active"], STATUS_COLORS["Discontinued"]],
                ),
                legend=alt.Legend(
                    orient="bottom",
                    direction="horizontal",
                    title=None,
                    offset=4,
                ),
            ),
            tooltip=[
                alt.Tooltip("Status:N"),
                alt.Tooltip("Patients:Q", title="Patients", format=","),
                alt.Tooltip("Share:Q", title="Share", format=".1%"),
            ],
        )
        .properties(
            height=230,
            padding={"top": 28, "bottom": 8, "left": 12, "right": 12},
        )
    )
    return _themed(chart).configure_view(strokeWidth=0, fill="transparent", clip=False)

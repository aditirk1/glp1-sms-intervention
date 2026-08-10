"""Shared helpers for the GoaLPost-1 care team dashboard."""

from __future__ import annotations

import os

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = 60
PAGE_SIZE = 25

RED_THRESHOLD = 0.60
AMBER_THRESHOLD = 0.35

TASK_LABELS = {
    "nurse_call": "Nurse call",
    "outreach_call": "Outreach call",
    "benefits_check": "Benefits check",
    "gi_escalation": "GI escalation",
}

TIER_COLOURS = {
    "red": "#c81e1e",
    "amber": "#c2410c",
    "green": "#0f766e",
    "unscored": "#64748b",
}

TIER_LABELS = {
    "red": "High risk",
    "amber": "Medium risk",
    "green": "Lower risk",
    "unscored": "Not scored",
}


def tier_dot_html(tier: str | None, *, size: str = "0.65rem") -> str:
    """Colored status dot — preferred over printing RED/AMBER as text."""
    key = (tier or "unscored").lower()
    colour = TIER_COLOURS.get(key, TIER_COLOURS["unscored"])
    label = TIER_LABELS.get(key, "Not scored")
    return (
        f'<span title="{label}" aria-label="{label}" '
        f'style="display:inline-block;width:{size};height:{size};'
        f'border-radius:50%;background:{colour};'
        f'margin-right:0.5rem;vertical-align:middle;'
        f'box-shadow:0 0 0 2px rgba(255,255,255,0.9);"></span>'
    )


def patient_heading_html(
    name: str, tier: str | None, risk: float | None = None
) -> str:
    """Name with a risk-status dot; score only, never the word RED/AMBER."""
    score = f" · {risk:.2f}" if risk is not None else ""
    return (
        f"{tier_dot_html(tier)}"
        f"<strong>{name}</strong>"
        f"<span style='color:#64748b;font-weight:500'>{score}</span>"
    )


def api_get(path: str, params: dict | None = None):
    try:
        response = requests.get(
            f"{API_BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        st.session_state["api_error"] = f"{path}: {exc}"
        return None


def api_post(path: str, **kwargs):
    try:
        return requests.post(
            f"{API_BASE_URL}{path}", timeout=REQUEST_TIMEOUT, **kwargs
        )
    except Exception as exc:
        st.error(f"Could not reach the API: {exc}")
        return None


def titleise(value) -> str:
    return str(value or "").replace("_", " ").title()


def percent(value) -> str:
    return "—" if value is None else f"{value:.0%}"


def require_metrics():
    """Fetch cohort metrics or stop the page with a clear connection message."""
    metrics = api_get("/cohort/metrics")
    if metrics is None:
        st.error(f"Could not reach the GoaLPost-1 API at `{API_BASE_URL}`.")
        st.info("Start the API, then refresh this page.")
        st.stop()
    return metrics



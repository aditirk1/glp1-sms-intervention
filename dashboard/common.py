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
    "red": "#dc2626",
    "amber": "#f59e0b",
    "green": "#16a34a",
    "unscored": "#94a3b8",
}

TIER_LABELS = {
    "red": "High risk",
    "amber": "Medium risk",
    "green": "Low risk",
    "unscored": "Not scored",
}


def tier_dot_html(tier: str | None, *, size: str = "0.65rem") -> str:
    """Colored status dot — preferred over printing RED/AMBER as text.

    Uses CSS classes (gp-dot-red / amber / green) so Streamlit theme CSS
    cannot collapse every tier into one color. Inline background is a fallback.
    """
    key = (tier or "unscored").lower()
    if key not in TIER_COLOURS:
        key = "unscored"
    colour = TIER_COLOURS[key]
    label = TIER_LABELS.get(key, "Not scored")
    size_class = " gp-dot-lg" if size not in ("0.65rem", "0.7rem") else ""
    return (
        f'<span class="gp-dot gp-dot-{key}{size_class}" title="{label}" '
        f'aria-label="{label}" '
        f'style="display:inline-block;width:{size};height:{size};'
        f'border-radius:50%;background-color:{colour} !important;'
        f'background:{colour} !important;'
        f'margin-right:0.5rem;vertical-align:middle;"></span>'
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


def sentence_case(value) -> str:
    """First letter capital, rest lower — for dropdown and status labels."""
    text = str(value or "").replace("_", " ").strip()
    if not text:
        return ""
    text = text.lower()
    return text[0].upper() + text[1:]


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



"""Pfizer-inspired visual shell for the GoaLPost-1 care team dashboard."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

_LOGO_PATH = Path(__file__).parent / "assets" / "goalpost1-logo-circle.png"


@lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    return "data:image/png;base64," + base64.b64encode(_LOGO_PATH.read_bytes()).decode(
        "ascii"
    )

# Light theme. Keep motion light — heavy background-size / transform animations
# previously crashed Safari.
_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,500&family=Inter:ital,wght@0,400;0,500;0,600;1,400&family=Space+Grotesk:wght@500;600;700&display=swap');

:root {
  --gp-navy: #00005a;
  --gp-blue: #0093d0;
  --gp-blue-deep: #005eb8;
  --gp-violet: #5b2d8e;
  --gp-card: rgba(255, 255, 255, 0.72);
  --gp-stroke: rgba(0, 147, 208, 0.18);
  --gp-text: #0b1b3f;
  --gp-muted: #475569;
  --gp-font-display: "DM Sans", "Segoe UI", sans-serif;
  --gp-font-body: "Inter", "Segoe UI", sans-serif;
  --gp-font-metric: "Space Grotesk", "DM Sans", sans-serif;
  --gp-on-dark: #ffffff;
  --gp-on-dark-muted: #f5f5f5;
  --gp-risk-red: #dc2626;
  --gp-risk-amber: #f59e0b;
  --gp-risk-green: #16a34a;
  --gp-risk-unscored: #94a3b8;
}

html, body, [data-testid="stAppViewContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stCaption"],
label, .stSelectbox, .stTextInput, .stNumberInput {
  font-family: var(--gp-font-body) !important;
  color: var(--gp-text);
}

html, body, [data-testid="stAppViewContainer"], .stApp {
  overflow-x: hidden !important;
}

h1, h2, h3, h4, h5, h6,
.gp-page-title,
.gp-brand-text h1,
.st-key-gp_chrome [data-testid="stPageLink"] a {
  font-family: var(--gp-font-display) !important;
}

/* Continuous light gradient — full viewport */
html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stApp"],
section.main,
[data-testid="stMain"] {
  background:
    radial-gradient(ellipse 55% 45% at 8% 12%, rgba(0, 147, 208, 0.28), transparent 55%),
    radial-gradient(ellipse 50% 40% at 92% 8%, rgba(91, 45, 142, 0.22), transparent 50%),
    radial-gradient(ellipse 45% 40% at 78% 92%, rgba(0, 94, 184, 0.16), transparent 55%),
    linear-gradient(160deg, #eaf3ff 0%, #f4efff 48%, #e8f7ff 100%) !important;
  background-attachment: fixed !important;
  background-color: #eaf3ff !important;
}

[data-testid="stSidebar"] {
  display: none !important;
}

/* Kill Streamlit chrome that leaves a thin bar / gap above our header */
header[data-testid="stHeader"],
[data-testid="stHeader"],
.stAppHeader,
header.stAppHeader,
[data-testid="stToolbar"],
div[data-testid="stDecoration"],
div[data-testid="stStatusWidget"],
[data-testid="stAppToolbar"],
[data-testid="stToolbarActions"],
#MainMenu,
footer,
.stDeployButton,
div[data-testid="stSidebarCollapsedControl"] {
  display: none !important;
  visibility: hidden !important;
  height: 0 !important;
  min-height: 0 !important;
  max-height: 0 !important;
  opacity: 0 !important;
  pointer-events: none !important;
  margin: 0 !important;
  padding: 0 !important;
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
}

/* Pull main content flush to the top of the viewport */
section.main,
[data-testid="stAppViewContainer"] > .main,
[data-testid="stMain"],
[data-testid="stAppViewContainer"] {
  padding: 0 !important;
  margin: 0 !important;
}

div.block-container,
[data-testid="stMainBlockContainer"],
section.main > div.block-container {
  max-width: none !important;
  width: 100% !important;
  padding-top: 0 !important;
  padding-left: 0 !important;
  padding-right: 0 !important;
  padding-bottom: 1rem !important;
  margin: 0 !important;
}

/* Streamlit sometimes reserves header height on the app shell */
.stApp > div:first-child,
.stApp [data-testid="stHeader"] + div,
[data-testid="stAppViewContainer"] > section {
  margin-top: 0 !important;
  padding-top: 0 !important;
}

.st-key-gp_chrome,
.st-key-gp_page,
div[class*="st-key-gp_chrome"],
div[class*="st-key-gp_page"] {
  width: 100% !important;
  max-width: none !important;
  box-sizing: border-box !important;
}

.st-key-gp_page {
  padding: 1.25rem 2.5rem 2.25rem !important;
  animation: gp-page-enter 0.42s ease both;
}

@media (max-width: 1024px) {
  .st-key-gp_page { padding: 1.1rem 1.5rem 1.75rem !important; }
}

@media (max-width: 768px) {
  .st-key-gp_page { padding: 1rem 1rem 1.5rem !important; }
}

@keyframes gp-page-enter {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes gp-tab-pop {
  0% { transform: scale(0.97); }
  55% { transform: scale(1.025); }
  100% { transform: scale(1); }
}

/* ----- Header: square, flush, full width (no 100vw bleed / no curved sides) ----- */

.st-key-gp_chrome {
  background:
    linear-gradient(90deg, rgba(0, 147, 208, 0.22) 0%, transparent 42%),
    linear-gradient(180deg, #00004a 0%, #00005a 38%, #1a1a6e 100%);
  border-radius: 0 !important;
  width: 100% !important;
  max-width: 100% !important;
  margin: 0 !important;
  padding: 1.1rem 2.5rem 0.95rem !important;
  box-shadow: none !important;
  position: relative;
  overflow: hidden;
  box-sizing: border-box !important;
  border-bottom: 3px solid #0093d0 !important;
}

.st-key-gp_chrome::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 40% 80% at 100% 0%, rgba(91, 45, 142, 0.45), transparent 70%),
    radial-gradient(ellipse 35% 60% at 0% 100%, rgba(0, 147, 208, 0.25), transparent 65%);
  pointer-events: none;
  z-index: 0;
}

.st-key-gp_chrome::after {
  content: none !important;
}

@media (max-width: 1024px) {
  .st-key-gp_chrome { padding: 1.1rem 1.5rem 0.95rem !important; }
}

@media (max-width: 768px) {
  .st-key-gp_chrome { padding: 1rem 1rem 0.9rem !important; }
}

/* Force white / near-white text on every dark header surface */
.st-key-gp_chrome,
.st-key-gp_chrome p,
.st-key-gp_chrome span,
.st-key-gp_chrome div,
.st-key-gp_chrome a,
.st-key-gp_chrome label,
.st-key-gp_chrome h1,
.st-key-gp_chrome h2,
.st-key-gp_chrome h3,
.st-key-gp_chrome [data-testid="stMarkdownContainer"],
.st-key-gp_chrome [data-testid="stMarkdownContainer"] *,
.st-key-gp_chrome [data-testid="stPageLink"],
.st-key-gp_chrome [data-testid="stPageLink"] *,
.st-key-gp_chrome [data-testid="stWidgetLabel"],
.st-key-gp_chrome [data-testid="stCaption"] {
  color: var(--gp-on-dark) !important;
}

.st-key-gp_chrome [data-testid="stPageLink"] svg,
.st-key-gp_chrome [data-testid="stPageLink"] svg * {
  fill: var(--gp-on-dark) !important;
  color: var(--gp-on-dark) !important;
  stroke: var(--gp-on-dark) !important;
}

.st-key-gp_chrome [data-testid="stVerticalBlock"],
.st-key-gp_chrome [data-testid="stHorizontalBlock"],
.st-key-gp_chrome [data-testid="element-container"],
.st-key-gp_page [data-testid="stVerticalBlock"],
.st-key-gp_page [data-testid="stHorizontalBlock"],
.st-key-gp_page [data-testid="stVerticalBlockBorderWrapper"],
.st-key-gp_page [data-testid="element-container"] {
  width: 100% !important;
  max-width: none !important;
}

/* Brand row + tab row — keep tight */
.st-key-gp_chrome [data-testid="stVerticalBlock"] {
  gap: 0.35rem !important;
}

.st-key-gp_chrome [data-testid="stVerticalBlock"] > div {
  margin: 0 !important;
  padding: 0 !important;
}

/* Brand markdown sits in an element-container — collapse its padding */
.st-key-gp_chrome [data-testid="element-container"],
.st-key-gp_chrome [data-testid="stMarkdownContainer"] {
  margin: 0 !important;
  padding: 0 !important;
}

.st-key-gp_chrome [data-testid="stHorizontalBlock"] {
  gap: 0.55rem !important;
  position: relative;
  z-index: 1;
  margin: 0 !important;
  align-items: center !important;
}

/* Brand row — single HTML flex block (no st.columns / st.image gap) */
.gp-brand-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin: 0 0 0.55rem 0 !important;
  padding: 0 !important;
  position: relative;
  z-index: 1;
}

.gp-brand-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.gp-logo-slot {
  width: 4.75rem;
  height: 4.75rem;
  min-width: 4.75rem;
  flex-shrink: 0;
  background-color: transparent !important;
  background-size: 100% 100% !important;
  background-position: center !important;
  background-repeat: no-repeat !important;
}

.gp-brand-text {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.18rem;
  min-width: 0;
  padding: 0 !important;
  margin: 0 !important;
}

.gp-brand-kicker {
  margin: 0 !important;
  color: #ffffff !important;
  font-family: var(--gp-font-display) !important;
  font-size: clamp(1.55rem, 2.4vw, 1.85rem) !important;
  font-weight: 700 !important;
  letter-spacing: -0.01em;
  line-height: 1.2;
}

.gp-brand-tagline {
  margin: 0 !important;
  color: #f5f5f5 !important;
  font-family: var(--gp-font-body) !important;
  font-size: 0.9rem !important;
  font-weight: 400 !important;
  line-height: 1.35;
  opacity: 0.9;
}

.gp-pill-wrap {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-shrink: 0;
}

.gp-pill {
  display: inline-flex;
  align-items: center;
  padding: 0.35rem 0.8rem;
  border-radius: 4px;
  font-family: var(--gp-font-body) !important;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.28);
  color: #ffffff !important;
}

.gp-nav-label {
  display: none !important;
}

.st-key-gp_chrome [data-testid="stPageLink"] {
  width: 100%;
}

.st-key-gp_chrome [data-testid="stPageLink"] a {
  display: flex !important;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  width: 100%;
  min-height: 2.65rem;
  padding: 0.5rem 0.75rem !important;
  border-radius: 6px !important;
  background: rgba(255, 255, 255, 0.08) !important;
  border: 1px solid rgba(255, 255, 255, 0.2) !important;
  color: #ffffff !important;
  font-weight: 600 !important;
  font-size: 0.92rem !important;
  text-decoration: none !important;
  box-shadow: none !important;
  transition:
    background 0.2s ease,
    border-color 0.2s ease,
    transform 0.2s ease !important;
}

.st-key-gp_chrome [data-testid="stPageLink"] a span,
.st-key-gp_chrome [data-testid="stPageLink"] a p,
.st-key-gp_chrome [data-testid="stPageLink"] a div {
  color: #ffffff !important;
}

.st-key-gp_chrome [data-testid="stPageLink"] a:hover {
  background: rgba(255, 255, 255, 0.18) !important;
  border-color: rgba(255, 255, 255, 0.4) !important;
  transform: translateY(-1px);
}

/* Active tab: light pill, dark text (override the white-text blanket) */
.st-key-gp_chrome [data-testid="stPageLink"] a[aria-current="page"],
.st-key-gp_chrome [class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a,
div[class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a {
  background: #ffffff !important;
  color: #00005a !important;
  border-color: #ffffff !important;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18) !important;
  animation: gp-tab-pop 0.34s ease both;
}

.st-key-gp_chrome [data-testid="stPageLink"] a[aria-current="page"] span,
.st-key-gp_chrome [data-testid="stPageLink"] a[aria-current="page"] p,
.st-key-gp_chrome [data-testid="stPageLink"] a[aria-current="page"] div,
.st-key-gp_chrome [class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a span,
.st-key-gp_chrome [class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a p,
.st-key-gp_chrome [class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a div,
div[class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a span,
div[class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a p,
div[class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a div {
  color: #00005a !important;
}

.st-key-gp_chrome [data-testid="stPageLink"] a[aria-current="page"] svg,
.st-key-gp_chrome [data-testid="stPageLink"] a[aria-current="page"] svg *,
.st-key-gp_chrome [class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a svg,
.st-key-gp_chrome [class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a svg *,
div[class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a svg,
div[class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a svg * {
  fill: #00005a !important;
  color: #00005a !important;
  stroke: #00005a !important;
}

/* Risk status dots — class-based so colors cannot collapse to one shade */
.gp-dot {
  display: inline-block !important;
  width: 0.7rem !important;
  height: 0.7rem !important;
  border-radius: 50% !important;
  margin-right: 0.5rem !important;
  vertical-align: middle !important;
  flex-shrink: 0 !important;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.95) !important;
  border: 1px solid rgba(0, 0, 0, 0.08) !important;
}

.gp-dot-red {
  background: var(--gp-risk-red) !important;
  background-color: #dc2626 !important;
}

.gp-dot-amber {
  background: var(--gp-risk-amber) !important;
  background-color: #f59e0b !important;
}

.gp-dot-green {
  background: var(--gp-risk-green) !important;
  background-color: #16a34a !important;
}

.gp-dot-unscored {
  background: var(--gp-risk-unscored) !important;
  background-color: #94a3b8 !important;
}

.gp-dot-lg {
  width: 0.85rem !important;
  height: 0.85rem !important;
}

/* Light glass cards */
div[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--gp-card) !important;
  border: 1px solid var(--gp-stroke) !important;
  border-radius: 16px !important;
  box-shadow: 0 12px 28px rgba(0, 0, 90, 0.07) !important;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  position: relative;
  overflow: hidden;
  padding: 0.35rem 0.15rem !important;
}

div[data-testid="stVerticalBlockBorderWrapper"]::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, #0093d0, #6b2d8b);
  pointer-events: none;
}

div[data-testid="stMetric"] {
  background: var(--gp-card) !important;
  border: 1px solid var(--gp-stroke) !important;
  border-radius: 14px !important;
  padding: 0.95rem 1rem !important;
  box-shadow: 0 8px 20px rgba(0, 94, 184, 0.07) !important;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  position: relative;
  overflow: hidden;
}

div[data-testid="stMetric"]::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, #0093d0, #6b2d8b);
  pointer-events: none;
}

div[data-testid="stMetric"] label {
  color: rgba(0, 94, 184, 0.72) !important;
  font-family: var(--gp-font-body) !important;
  font-size: 0.72rem !important;
  font-weight: 600 !important;
  letter-spacing: 0.06em !important;
  text-transform: uppercase !important;
}

div[data-testid="stMetric"] [data-testid="stMetricValue"] {
  color: var(--gp-navy) !important;
  font-family: var(--gp-font-metric) !important;
  font-weight: 700 !important;
}

[data-testid="stDataFrame"],
[data-testid="stArrowVegaLiteChart"] {
  background: transparent !important;
  border-radius: 12px;
  padding: 0.25rem;
}

/* Primary / gradient buttons — force white label (Streamlit theme text is dark) */
.stButton > button[kind="primary"],
.stButton button[data-testid="stBaseButton-primary"],
button[data-testid="stBaseButton-primary"],
button[data-testid="stBaseButton-primaryFormSubmit"],
.stFormSubmitButton button,
.stFormSubmitButton > button,
div[data-testid="stFormSubmitButton"] button {
  background: linear-gradient(135deg, var(--gp-blue), var(--gp-violet)) !important;
  border: none !important;
  color: #ffffff !important;
  font-family: var(--gp-font-display) !important;
  font-weight: 650 !important;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.stButton > button[kind="primary"] *,
.stButton button[data-testid="stBaseButton-primary"] *,
button[data-testid="stBaseButton-primary"] *,
button[data-testid="stBaseButton-primaryFormSubmit"] *,
.stFormSubmitButton button *,
.stFormSubmitButton > button *,
div[data-testid="stFormSubmitButton"] button * {
  color: #ffffff !important;
  fill: #ffffff !important;
  -webkit-text-fill-color: #ffffff !important;
}

.stButton > button[kind="primary"]:hover,
.stButton button[data-testid="stBaseButton-primary"]:hover,
button[data-testid="stBaseButton-primary"]:hover,
button[data-testid="stBaseButton-primaryFormSubmit"]:hover,
.stFormSubmitButton button:hover,
div[data-testid="stFormSubmitButton"] button:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 18px rgba(0, 94, 184, 0.28);
  color: #ffffff !important;
}

.stButton > button[kind="primary"]:hover *,
.stButton button[data-testid="stBaseButton-primary"]:hover *,
button[data-testid="stBaseButton-primary"]:hover *,
button[data-testid="stBaseButton-primaryFormSubmit"]:hover *,
.stFormSubmitButton button:hover *,
div[data-testid="stFormSubmitButton"] button:hover * {
  color: #ffffff !important;
  fill: #ffffff !important;
  -webkit-text-fill-color: #ffffff !important;
}

.stButton > button[kind="secondary"],
button[data-testid="stBaseButton-secondary"] {
  border-color: rgba(0, 94, 184, 0.35);
  color: var(--gp-navy);
  font-family: var(--gp-font-body) !important;
}

.gp-page-title {
  margin: 0.1rem 0 0.15rem 0;
  font-size: 1.45rem;
  font-weight: 700;
  color: var(--gp-navy);
  letter-spacing: -0.02em;
}

.gp-page-sub {
  margin: 0 0 1rem 0;
  color: var(--gp-muted);
  font-family: var(--gp-font-body) !important;
  font-size: 0.95rem;
}

.st-key-gp_page h4,
.st-key-gp_page [data-testid="stMarkdownContainer"] h4 {
  font-family: var(--gp-font-display) !important;
  color: var(--gp-navy) !important;
  font-size: 1.25rem !important;
  font-weight: 700 !important;
}

hr {
  border-color: rgba(0, 94, 184, 0.12) !important;
}
</style>
"""


def inject_theme() -> None:
    logo_css = f"""
<style>
.gp-logo-slot {{
  background-image: url("{_logo_data_uri()}") !important;
}}
</style>
"""
    st.markdown(_THEME_CSS + logo_css, unsafe_allow_html=True)


def render_chrome(nav_items: list[tuple], active=None) -> None:
    """Full-bleed brand bar flush to the top of the viewport."""
    with st.container(key="gp_chrome"):
        st.markdown(
            """
            <div class="gp-brand-row">
              <div class="gp-brand-left">
                <div class="gp-logo-slot" role="img" aria-label="GoaLPost-1"></div>
                <div class="gp-brand-text">
                  <p class="gp-brand-kicker">GoaLPost-1 Dashboard</p>
                  <p class="gp-brand-tagline">Risk-stratified GLP-1 check-ins for the care team</p>
                </div>
              </div>
              <div class="gp-pill-wrap"><span class="gp-pill">Care team</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        cols = st.columns(len(nav_items), gap="small")
        active_title = getattr(active, "title", None)
        for col, (page, label, icon) in zip(cols, nav_items):
            with col:
                slug = label.lower().replace(" ", "_")
                is_on = active_title == getattr(page, "title", None) or page is active
                key = f"nav_{slug}_on" if is_on else f"nav_{slug}"
                with st.container(key=key):
                    st.page_link(page, label=label, icon=icon, width="stretch")


def page_shell():
    """Padded animated body under the full-bleed chrome."""
    return st.container(key="gp_page")


def page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f'<p class="gp-page-title">{title}</p>'
        f'<p class="gp-page-sub">{subtitle}</p>',
        unsafe_allow_html=True,
    )

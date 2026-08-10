"""Pfizer-inspired visual shell for the GoaLPost-1 care team dashboard."""

from __future__ import annotations

import streamlit as st

# Avoid heavy backdrop-filter / background-size animation — those have crashed
# Safari with "This webpage was reloaded because a problem occurred."
_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&display=swap');

:root {
  --gp-navy: #00005a;
  --gp-blue: #0093d0;
  --gp-blue-deep: #005eb8;
  --gp-violet: #5b2d8e;
  --gp-card: rgba(255, 255, 255, 0.94);
  --gp-stroke: rgba(0, 94, 184, 0.14);
  --gp-text: #0b1b3f;
  --gp-muted: #475569;
}

html, body, [data-testid="stAppViewContainer"] {
  font-family: "DM Sans", "Segoe UI", sans-serif !important;
  color: var(--gp-text);
}

[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(ellipse 55% 45% at 8% 12%, rgba(0, 147, 208, 0.26), transparent 55%),
    radial-gradient(ellipse 50% 40% at 92% 8%, rgba(91, 45, 142, 0.22), transparent 50%),
    radial-gradient(ellipse 45% 40% at 78% 92%, rgba(0, 94, 184, 0.16), transparent 55%),
    linear-gradient(160deg, #eaf3ff 0%, #f4efff 48%, #e8f7ff 100%);
}

[data-testid="stHeader"] {
  background: transparent;
}

[data-testid="stToolbar"] {
  right: 0.75rem;
  top: 0.35rem;
}

section.main > div {
  padding-top: 0.6rem;
}

/* ----- branded chrome (keyed container) ----- */

.st-key-gp_chrome {
  background: linear-gradient(
    118deg,
    #00005a 0%,
    #005eb8 48%,
    #5b2d8e 100%
  );
  border-radius: 22px;
  padding: 1.2rem 1.25rem 1.1rem;
  margin: 0 0 1.35rem 0;
  box-shadow: 0 18px 40px rgba(0, 0, 90, 0.18);
}

.st-key-gp_chrome [data-testid="stMarkdownContainer"] p,
.st-key-gp_chrome [data-testid="stMarkdownContainer"] h1 {
  color: #fff;
}

.gp-brand-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  margin-bottom: 0.15rem;
}

.gp-brand-left {
  display: flex;
  align-items: center;
  gap: 0.85rem;
}

.gp-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.45rem;
  height: 2.45rem;
  border-radius: 12px;
  background: linear-gradient(145deg, #3db8ea, #a78bfa);
  color: white;
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  box-shadow: 0 8px 18px rgba(0, 0, 0, 0.18);
}

.gp-brand-text h1 {
  margin: 0;
  font-size: 1.55rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: #fff !important;
  line-height: 1.1;
}

.gp-brand-text p {
  margin: 0.18rem 0 0 0;
  color: rgba(255, 255, 255, 0.78) !important;
  font-size: 0.88rem;
}

.gp-pill {
  display: inline-flex;
  align-items: center;
  padding: 0.3rem 0.75rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.22);
  color: #fff !important;
}

.gp-nav-label {
  margin: 0.85rem 0 0.45rem 0 !important;
  color: rgba(255, 255, 255, 0.58) !important;
  font-size: 0.72rem !important;
  font-weight: 600 !important;
  letter-spacing: 0.08em;
  text-transform: uppercase;
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
  min-height: 2.75rem;
  padding: 0.55rem 0.8rem !important;
  border-radius: 14px !important;
  background: rgba(255, 255, 255, 0.12) !important;
  border: 1px solid rgba(255, 255, 255, 0.18) !important;
  color: rgba(255, 255, 255, 0.95) !important;
  font-weight: 600 !important;
  font-size: 0.93rem !important;
  text-decoration: none !important;
  box-shadow: none !important;
}

.st-key-gp_chrome [data-testid="stPageLink"] a:hover {
  background: rgba(255, 255, 255, 0.22) !important;
  border-color: rgba(255, 255, 255, 0.38) !important;
}

.st-key-gp_chrome [data-testid="stPageLink"] a[aria-current="page"],
.st-key-gp_chrome [class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a,
div[class*="st-key-nav_"][class$="_on"] [data-testid="stPageLink"] a {
  background: #ffffff !important;
  color: #00005a !important;
  border-color: transparent !important;
  box-shadow: 0 8px 18px rgba(0, 0, 0, 0.16) !important;
}

.st-key-gp_chrome [data-testid="stPageLink"] span,
.st-key-gp_chrome [data-testid="stPageLink"] p,
.st-key-gp_chrome [data-testid="stPageLink"] svg {
  color: inherit !important;
  fill: currentColor !important;
}

/* cards / metrics */
div[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--gp-card);
  border: 1px solid var(--gp-stroke);
  border-radius: 18px;
  box-shadow: 0 12px 28px rgba(0, 0, 90, 0.07);
}

div[data-testid="stMetric"] {
  background: var(--gp-card);
  border: 1px solid var(--gp-stroke);
  border-radius: 16px;
  padding: 0.9rem 1rem;
  box-shadow: 0 8px 20px rgba(0, 94, 184, 0.07);
}

div[data-testid="stMetric"] label {
  color: var(--gp-blue-deep) !important;
  font-weight: 600 !important;
}

div[data-testid="stMetric"] [data-testid="stMetricValue"] {
  color: var(--gp-navy) !important;
  font-weight: 700 !important;
}

[data-testid="stDataFrame"],
[data-testid="stArrowVegaLiteChart"] {
  background: var(--gp-card);
  border-radius: 14px;
  padding: 0.35rem;
  border: 1px solid var(--gp-stroke);
}

.stButton > button[kind="primary"] {
  background: linear-gradient(135deg, var(--gp-blue), var(--gp-violet));
  border: none;
  color: white;
  font-weight: 650;
}

.stButton > button[kind="secondary"] {
  border-color: rgba(0, 94, 184, 0.35);
  color: var(--gp-navy);
}

.gp-page-title {
  margin: 0.1rem 0 0.15rem 0;
  font-size: 1.35rem;
  font-weight: 700;
  color: var(--gp-navy);
  letter-spacing: -0.02em;
}

.gp-page-sub {
  margin: 0 0 1rem 0;
  color: var(--gp-muted);
  font-size: 0.95rem;
}

hr {
  border-color: rgba(0, 94, 184, 0.12) !important;
}
</style>
"""


def inject_theme() -> None:
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def render_chrome(nav_items: list[tuple], active=None) -> None:
    """Brand bar + elegant page links inside one visual shell."""
    with st.container(key="gp_chrome"):
        st.markdown(
            """
            <div class="gp-brand-row">
              <div class="gp-brand-left">
                <span class="gp-mark">G-1</span>
                <div class="gp-brand-text">
                  <h1>GoaLPost-1</h1>
                  <p>Risk-stratified GLP-1 check-ins for the care team</p>
                </div>
              </div>
              <span class="gp-pill">Care team</span>
            </div>
            <p class="gp-nav-label">Navigate</p>
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


def page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f'<p class="gp-page-title">{title}</p>'
        f'<p class="gp-page-sub">{subtitle}</p>',
        unsafe_allow_html=True,
    )

"""UI style helpers for Vanguard Streamlit dashboard."""

from __future__ import annotations

import streamlit as st


def inject_global_styles() -> None:
    """Inject global dashboard CSS for enterprise glassmorphism look."""
    st.markdown(
        """
<style>
:root {
  --bg-main: #060b17;
  --bg-accent: #0d1b2d;
  --card-bg: rgba(20, 33, 56, 0.55);
  --card-border: rgba(148, 163, 184, 0.25);
  --text-primary: #e2e8f0;
  --text-muted: #93a4bf;
  --ok: #22c55e;
  --warn: #f59e0b;
  --danger: #ef4444;
}

.stApp {
  background: radial-gradient(1200px 700px at 15% 10%, #14294a 0%, var(--bg-main) 45%, #050814 100%);
  color: var(--text-primary);
}

section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, rgba(9, 18, 35, 0.95) 0%, rgba(6, 11, 23, 0.95) 100%);
  border-right: 1px solid var(--card-border);
}

.glass-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 14px;
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  padding: 14px 16px;
  box-shadow: 0 10px 35px rgba(2, 6, 23, 0.4);
}

.metric-label {
  font-size: 0.76rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.metric-value {
  margin-top: 6px;
  font-size: 1.35rem;
  font-weight: 650;
  color: var(--text-primary);
}

.status-ok { color: var(--ok); font-weight: 600; }
.status-warn { color: var(--warn); font-weight: 600; }
.status-danger { color: var(--danger); font-weight: 600; }

.panel-title {
  font-size: 0.78rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.panel-main {
  margin-top: 6px;
  font-size: 1.05rem;
  font-weight: 620;
}

.pill {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--card-border);
  background: rgba(15, 25, 45, 0.65);
  color: var(--text-muted);
  font-size: 0.75rem;
}
</style>
        """,
        unsafe_allow_html=True,
    )

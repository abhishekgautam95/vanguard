"""Streamlit dashboard for Vanguard route risk and alert telemetry."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

try:
    from .config import Settings
except ImportError:  # Streamlit script mode fallback
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from vanguard.config import Settings


def _require_dashboard_login(expected_password: str) -> bool:
    """Basic password gate for dashboard access."""
    if not expected_password:
        st.warning("DASHBOARD_PASSWORD is not set. Dashboard access is disabled.")
        return False

    if st.session_state.get("is_authenticated"):
        return True

    st.subheader("Dashboard Login")
    password = st.text_input("Enter dashboard password", type="password")
    if st.button("Login"):
        if password == expected_password:
            st.session_state["is_authenticated"] = True
            st.rerun()
        else:
            st.error("Invalid password.")
    return False


async def _fetch_dashboard_data(database_url: str) -> tuple[list[dict], list[dict], list[dict]]:
    conn = await asyncpg.connect(database_url)
    try:
        route_trend_rows = await conn.fetch(
            """
            SELECT
                route,
                date_trunc('hour', event_time) AS bucket,
                round(avg(severity)::numeric, 2) AS avg_severity,
                count(*) AS events
            FROM risk_events
            WHERE event_time > NOW() - interval '48 hours'
            GROUP BY route, bucket
            ORDER BY bucket DESC
            LIMIT 200
            """
        )

        latest_events_rows = await conn.fetch(
            """
            SELECT
                route,
                event_type,
                geo_location,
                severity,
                confidence,
                description,
                event_time
            FROM risk_events
            ORDER BY event_time DESC
            LIMIT 50
            """
        )

        alert_rows = await conn.fetch(
            """
            SELECT
                route,
                recipient,
                status,
                risk_bucket,
                attempt_number,
                created_at,
                error_message
            FROM alert_dispatch_log
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
    finally:
        await conn.close()

    return [dict(row) for row in route_trend_rows], [dict(row) for row in latest_events_rows], [dict(row) for row in alert_rows]


@st.cache_data(ttl=90, show_spinner=False)
def get_dashboard_data(database_url: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Cached wrapper to reduce repetitive DB query load."""
    return asyncio.run(_fetch_dashboard_data(database_url))


def _render_summary(alerts: list[dict]) -> None:
    sent = len([row for row in alerts if row.get("status") == "sent"])
    failed = len([row for row in alerts if row.get("status") == "failed"])
    dry_run = len([row for row in alerts if row.get("status") == "dry_run"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Alerts Sent", sent)
    c2.metric("Alerts Failed", failed)
    c3.metric("Dry Run Alerts", dry_run)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    settings = Settings.from_env()

    st.set_page_config(page_title="Vanguard Control Room", layout="wide")
    st.title("Project Vanguard: Supply Chain Control Room")
    st.caption(f"UTC Snapshot: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    if not _require_dashboard_login(settings.dashboard_password):
        return

    try:
        trend, events, alerts = get_dashboard_data(settings.database_url)
    except Exception as exc:
        st.error(f"Database fetch failed: {exc}")
        return

    _render_summary(alerts)

    st.subheader("Route Risk Trend (48h)")
    if trend:
        trend_df = pd.DataFrame(trend)
        st.line_chart(
            data=trend_df,
            x="bucket",
            y="avg_severity",
            color="route",
            use_container_width=True,
        )
    else:
        st.info("No route trend data available yet.")

    left, right = st.columns(2)
    with left:
        st.subheader("Latest Risk Events")
        st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)

    with right:
        st.subheader("Alert Dispatch Log")
        st.dataframe(pd.DataFrame(alerts), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()

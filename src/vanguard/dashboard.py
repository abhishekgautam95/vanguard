"""Streamlit command center dashboard for Vanguard."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import asyncpg
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

try:
    import plotly.express as px
except ImportError:  # optional runtime dependency
    px = None

try:
    from .actions import build_cost_benefit_analysis
    from .config import Settings
    from .styles import inject_global_styles
except ImportError:  # Streamlit script mode fallback
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from vanguard.actions import build_cost_benefit_analysis
    from vanguard.config import Settings
    from vanguard.styles import inject_global_styles


def _require_dashboard_login(expected_password: str) -> bool:
    """Basic password gate for dashboard access."""
    if not expected_password:
        st.warning("DASHBOARD_PASSWORD is not set. Dashboard access is disabled.")
        return False

    if st.session_state.get("is_authenticated"):
        return True

    st.subheader("Secure Access")
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
            WHERE event_time > NOW() - interval '7 days'
            GROUP BY route, bucket
            ORDER BY bucket DESC
            LIMIT 600
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
                source,
                event_time
            FROM risk_events
            ORDER BY event_time DESC
            LIMIT 250
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
                decision_payload,
                created_at,
                error_message
            FROM alert_dispatch_log
            ORDER BY created_at DESC
            LIMIT 200
            """
        )
    finally:
        await conn.close()

    return [dict(row) for row in route_trend_rows], [dict(row) for row in latest_events_rows], [dict(row) for row in alert_rows]


async def _probe_ollama(base_url: str, model: str) -> tuple[str, str]:
    """Return ollama health label and detail string."""
    url = f"{base_url.rstrip('/')}/api/tags"
    timeout = aiohttp.ClientTimeout(total=6)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return "degraded", f"HTTP {resp.status}"
                payload = await resp.json()
                names = {
                    str(item.get("name", "")).split(":")[0]
                    for item in payload.get("models", [])
                    if isinstance(item, dict)
                }
                want = model.split(":")[0]
                if want not in names:
                    return "degraded", f"model_missing:{model}"
                return "healthy", "online"
    except Exception as exc:
        return "down", str(exc)[:80]


def _tail_activity(log_path: Path, lines: int = 50) -> list[str]:
    if not log_path.exists():
        return ["No activity log found yet."]
    data = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not data:
        return ["No activity events yet."]
    return data[-lines:]


@st.cache_data(ttl=60, show_spinner=False)
def get_dashboard_data(database_url: str) -> tuple[list[dict], list[dict], list[dict]]:
    return asyncio.run(_fetch_dashboard_data(database_url))


@st.cache_data(ttl=30, show_spinner=False)
def get_ollama_status(base_url: str, model: str) -> tuple[str, str]:
    return asyncio.run(_probe_ollama(base_url, model))


def _status_class(status: str) -> str:
    if status == "healthy":
        return "status-ok"
    if status == "degraded":
        return "status-warn"
    return "status-danger"


def _render_metrics_ribbon(
    routes_count: int,
    active_risks: int,
    avg_risk: float,
    health_label: str,
) -> None:
    cols = st.columns(4)
    cards = [
        ("Total Routes Monitored", str(routes_count), ""),
        ("Active Risks", str(active_risks), ""),
        ("Avg Risk Score", f"{avg_risk:.1f}", ""),
        ("System Health (Ollama)", health_label, _status_class(health_label)),
    ]
    for col, (label, value, value_class) in zip(cols, cards):
        klass = f"metric-value {value_class}".strip()
        col.markdown(
            f"""
            <div class="glass-card">
              <div class="metric-label">{label}</div>
              <div class="{klass}">{value}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_risk_trend(trend_df: pd.DataFrame) -> None:
    st.subheader("Route Risk Timeline")
    if trend_df.empty:
        st.info("No trend data available yet.")
        return

    if px is None:
        st.warning("Plotly is not installed. Showing fallback chart.")
        st.line_chart(
            trend_df.sort_values("bucket"),
            x="bucket",
            y="avg_severity",
            color="route",
            use_container_width=True,
        )
        return

    fig = px.line(
        trend_df.sort_values("bucket"),
        x="bucket",
        y="avg_severity",
        color="route",
        markers=True,
        template="plotly_dark",
        title="Risk Intensity by Route (7 days)",
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend_title_text="Route",
        margin=dict(l=20, r=20, t=45, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_heatmap(trend_df: pd.DataFrame) -> None:
    st.subheader("Risk Intensity Heatmap")
    if trend_df.empty:
        st.info("No heatmap data available yet.")
        return

    heat = (
        trend_df.assign(hour_bucket=lambda df: pd.to_datetime(df["bucket"]).dt.strftime("%m-%d %H:00"))
        .pivot_table(
            index="route",
            columns="hour_bucket",
            values="avg_severity",
            aggfunc="mean",
        )
        .fillna(0)
    )
    if heat.empty:
        st.info("No heatmap values available.")
        return

    if px is None:
        st.warning("Plotly is not installed. Showing fallback table heat view.")
        st.dataframe(heat, use_container_width=True)
        return

    fig = px.imshow(
        heat,
        aspect="auto",
        color_continuous_scale="RdYlGn_r",
        labels={"x": "Time", "y": "Route", "color": "Risk"},
        template="plotly_dark",
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=20, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_cost_benefit_panel(alerts_df: pd.DataFrame) -> None:
    st.subheader("Cost-Benefit Command Split")
    cba = build_cost_benefit_analysis()
    if not alerts_df.empty and "decision_payload" in alerts_df.columns:
        for payload in alerts_df["decision_payload"]:
            if isinstance(payload, dict) and payload.get("cost_benefit"):
                cba = payload["cost_benefit"]
                break

    options = {str(item.get("option")): item for item in cba.get("options", [])}
    wait = options.get("wait", {})
    reroute = options.get("reroute_now", {})
    recommended = str(cba.get("recommendation", "wait_3_days"))

    left, right = st.columns(2)
    left_badge = "status-ok" if recommended.startswith("wait") else "status-danger"
    right_badge = "status-ok" if recommended == "reroute_now" else "status-warn"

    left.markdown(
        f"""
        <div class="glass-card">
          <div class="panel-title">🟢 Wait Strategy</div>
          <div class="panel-main">ETA: {wait.get('eta_days', 'n/a')} days</div>
          <div class="panel-main">Cost: ${wait.get('cost_per_container_usd', 'n/a')} / container</div>
          <div class="pill {left_badge}">Decision Bias: WAIT</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    right.markdown(
        f"""
        <div class="glass-card">
          <div class="panel-title">🔴 Reroute Strategy</div>
          <div class="panel-main">ETA: {reroute.get('eta_days', 'n/a')} days</div>
          <div class="panel-main">Cost: ${reroute.get('cost_per_container_usd', 'n/a')} / container</div>
          <div class="pill {right_badge}">Decision Bias: REROUTE</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_live_activity(log_path: Path) -> None:
    st.subheader("Live Activity Stream")
    entries = _tail_activity(log_path, lines=60)
    stream_text = "\n".join(f"- {line}" for line in reversed(entries))
    st.markdown(
        f"""
        <div class="glass-card" style="max-height:340px; overflow-y:auto; white-space:pre-wrap; font-family:monospace; font-size:0.82rem;">
        {stream_text}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_dashboard(settings: Settings, trend: list[dict], events: list[dict], alerts: list[dict]) -> None:
    trend_df = pd.DataFrame(trend)
    events_df = pd.DataFrame(events)
    alerts_df = pd.DataFrame(alerts)
    ollama_status, ollama_detail = get_ollama_status(settings.ollama_base_url, settings.ollama_model)

    active_risks = 0
    avg_risk = 0.0
    if not events_df.empty:
        active_risks = int((events_df["severity"] >= 70).sum())
    if not trend_df.empty:
        avg_risk = float(trend_df["avg_severity"].mean())

    _render_metrics_ribbon(
        routes_count=len(settings.monitor_routes),
        active_risks=active_risks,
        avg_risk=avg_risk,
        health_label=ollama_status,
    )
    st.caption(f"Ollama Detail: {ollama_detail} | Provider: {settings.llm_provider}")

    left, right = st.columns([2.3, 1.2])
    with left:
        _render_risk_trend(trend_df)
        _render_heatmap(trend_df)
        _render_cost_benefit_panel(alerts_df)
    with right:
        _render_live_activity(Path(__file__).resolve().parents[2] / "logs" / "vanguard_cron.log")


def _render_historical_data(events: list[dict], alerts: list[dict]) -> None:
    st.subheader("Historical Data")
    st.markdown("Event and dispatch records from PostgreSQL.")
    left, right = st.columns(2)
    with left:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.caption("Risk Events")
        st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.caption("Alert Dispatch Log")
        st.dataframe(pd.DataFrame(alerts), use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)


def _render_simulation_mode() -> None:
    st.subheader("Simulation Mode")
    st.markdown(
        """
        Use synthetic events to test agent behavior without real-world disruption:
        """,
    )
    st.code(
        "./simulate_crisis.sh --route \"Singapore Strait -> India\" --headline \"Major storm in Singapore\"",
        language="bash",
    )
    st.caption("Default is safe dry-run dispatch. Add --dispatch-live to send real notifications.")


def _render_settings(settings: Settings) -> None:
    st.subheader("Settings")
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.json(settings.redacted_snapshot())
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    settings = Settings.from_env()

    st.set_page_config(
        page_title="Vanguard Command Center",
        page_icon="🛰️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_global_styles()

    st.title("Vanguard Logistics Command Center")
    st.caption(f"UTC Snapshot: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    if not _require_dashboard_login(settings.dashboard_password):
        return

    with st.sidebar:
        st.markdown("### Navigation")
        section = st.radio(
            "Sections",
            options=[
                "📡 Dashboard",
                "🗃️ Historical Data",
                "🧪 Simulation Mode",
                "⚙️ Settings",
            ],
            label_visibility="collapsed",
        )

    try:
        trend, events, alerts = get_dashboard_data(settings.database_url)
    except Exception as exc:
        st.error(f"Database fetch failed: {exc}")
        return

    if section == "📡 Dashboard":
        _render_dashboard(settings, trend=trend, events=events, alerts=alerts)
    elif section == "🗃️ Historical Data":
        _render_historical_data(events=events, alerts=alerts)
    elif section == "🧪 Simulation Mode":
        _render_simulation_mode()
    else:
        _render_settings(settings)


if __name__ == "__main__":
    main()

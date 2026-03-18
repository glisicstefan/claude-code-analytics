"""Overview dashboard component.

Renders platform-wide KPI cards and a daily activity line chart.
All data is fetched via :mod:`src.analytics.queries` — no direct DB access here.
"""

import logging
from typing import Any, Dict

import plotly.graph_objects as go
import streamlit as st

from src.analytics.queries import get_daily_activity, get_overview_stats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cached data loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def _load_overview_stats() -> Dict[str, Any]:
    """Load platform-wide KPI stats and return as a plain dict."""
    df = get_overview_stats()
    row = df.iloc[0]
    return {
        "total_sessions": int(row["total_sessions"]),
        "total_cost_usd": float(row["total_cost_usd"]),
        "total_tokens": int(row["total_tokens"]),
        "active_users": int(row["active_users"]),
    }


@st.cache_data(ttl=300)
def _load_daily_activity():
    """Load daily activity DataFrame."""
    return get_daily_activity()


# ---------------------------------------------------------------------------
# Internal render helpers
# ---------------------------------------------------------------------------


def _render_kpi_cards(stats: Dict[str, Any]) -> None:
    """Render four metric cards in a single row."""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Sessions", f"{stats['total_sessions']:,}")
    c2.metric("Total Cost", f"${stats['total_cost_usd']:,.2f}")
    c3.metric("Total Tokens", f"{stats['total_tokens']:,}")
    c4.metric("Active Users", f"{stats['active_users']:,}")


def _render_daily_chart(filters: Dict[str, Any]) -> None:
    """Render a dual-axis line chart: sessions (left) and cost (right)."""
    df = _load_daily_activity()

    if df.empty:
        st.info("No daily activity data available.")
        return

    # Client-side date filter
    date_from = str(filters["date_from"])
    date_to = str(filters["date_to"])
    df = df[(df["date"] >= date_from) & (df["date"] <= date_to)]

    if df.empty:
        st.info("No activity in the selected date range.")
        return

    n = df["session_count"].sum()
    st.markdown(f"**Daily Activity** (n={n:,} sessions in range)")

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["session_count"],
            name="Sessions",
            line={"color": "#636EFA"},
            yaxis="y1",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["total_cost_usd"],
            name="Cost (USD)",
            line={"color": "#EF553B", "dash": "dot"},
            yaxis="y2",
        )
    )

    fig.update_layout(
        template="plotly_dark",
        xaxis={"title": "Date"},
        yaxis={"title": "Sessions", "side": "left"},
        yaxis2={
            "title": "Cost (USD)",
            "side": "right",
            "overlaying": "y",
            "tickformat": "$.2f",
        },
        legend={"x": 0, "y": 1.1, "orientation": "h"},
        margin={"t": 40, "b": 40},
        height=380,
    )

    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render(filters: Dict[str, Any]) -> None:
    """Render the Overview page.

    Args:
        filters: Global filter dict from the sidebar with keys
            ``date_from``, ``date_to``, ``practices``, ``levels``, ``locations``.
    """
    st.header("Overview")

    try:
        stats = _load_overview_stats()
        _render_kpi_cards(stats)
    except Exception:
        logger.exception("Failed to load overview stats")
        st.error("Could not load KPI stats. Check that the database is populated.")

    st.divider()

    try:
        _render_daily_chart(filters)
    except Exception:
        logger.exception("Failed to render daily activity chart")
        st.error("Could not render daily activity chart.")

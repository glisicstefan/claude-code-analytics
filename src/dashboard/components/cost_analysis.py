"""Usage Patterns dashboard component.

Renders a peak usage heatmap (hour × day-of-week) and a sessions-per-user
histogram to distinguish power users from casual users.
All data is fetched via :mod:`src.analytics.queries` — no direct DB access here.
"""

import logging
from typing import Any, Dict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analytics.queries import get_peak_usage_heatmap, get_sessions_per_user

logger = logging.getLogger(__name__)

# Day-of-week mapping: SQLite strftime('%w') returns "0"=Sunday … "6"=Saturday
_DOW_LABELS: Dict[str, str] = {
    "0": "Sun",
    "1": "Mon",
    "2": "Tue",
    "3": "Wed",
    "4": "Thu",
    "5": "Fri",
    "6": "Sat",
}

_DOW_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------------------
# Cached data loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def _load_peak_usage():
    """Load peak usage heatmap DataFrame."""
    return get_peak_usage_heatmap()


@st.cache_data(ttl=300)
def _load_sessions_per_user():
    """Load sessions-per-user DataFrame."""
    return get_sessions_per_user()


# ---------------------------------------------------------------------------
# Internal render helpers
# ---------------------------------------------------------------------------


def _render_heatmap() -> None:
    """Render a 24×7 heatmap of API request counts by hour and day of week."""
    df = _load_peak_usage()

    if df.empty:
        st.info("No usage heatmap data available.")
        return

    total = df["request_count"].sum()
    st.markdown(f"**Peak Usage Heatmap — Hour × Day of Week** (n={total:,} requests)")

    # Map numeric day strings to labels
    df["day_label"] = df["day_of_week"].map(_DOW_LABELS)

    # Build a full 24 × 7 pivot (fill missing slots with 0)
    all_hours = [f"{h:02d}" for h in range(24)]
    pivot = (
        df.pivot_table(
            index="day_label",
            columns="hour_of_day",
            values="request_count",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(index=_DOW_ORDER, fill_value=0)
        .reindex(columns=all_hours, fill_value=0)
    )

    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns.tolist(),
            y=pivot.index.tolist(),
            colorscale="Blues",
            colorbar={"title": "Requests"},
            hovertemplate="Hour: %{x}:00<br>Day: %{y}<br>Requests: %{z}<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        xaxis={"title": "Hour of Day (UTC)", "tickmode": "linear", "dtick": 2},
        yaxis_title="Day of Week",
        margin={"t": 30, "b": 60},
        height=380,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_sessions_histogram() -> None:
    """Render a histogram of session counts per user."""
    df = _load_sessions_per_user()

    if df.empty:
        st.info("No sessions-per-user data available.")
        return

    n_users = len(df)
    median_sessions = int(df["session_count"].median())
    st.markdown(
        f"**Sessions per User Distribution** "
        f"(n={n_users} users, median={median_sessions} sessions)"
    )

    fig = go.Figure(
        go.Histogram(
            x=df["session_count"],
            nbinsx=20,
            marker_color="#EF553B",
            hovertemplate="Sessions: %{x}<br>Users: %{y}<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        xaxis_title="Number of Sessions",
        yaxis_title="Number of Users",
        margin={"t": 30, "b": 60},
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render(filters: Dict[str, Any]) -> None:
    """Render the Usage Patterns page.

    Args:
        filters: Global filter dict from the sidebar. Usage pattern charts are
            not filtered by practice/level/location (data is aggregate), but
            the dict is accepted for interface consistency.
    """
    st.header("Usage Patterns")

    try:
        _render_heatmap()
    except Exception:
        logger.exception("Failed to render peak usage heatmap")
        st.error("Could not render usage heatmap.")

    st.divider()

    try:
        _render_sessions_histogram()
    except Exception:
        logger.exception("Failed to render sessions per user histogram")
        st.error("Could not render sessions histogram.")

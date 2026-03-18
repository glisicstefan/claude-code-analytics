"""Errors dashboard component.

Renders an error trend line chart and an error breakdown table.
All data is fetched via :mod:`src.analytics.queries` — no direct DB access here.
"""

import logging
from typing import Any, Dict

import plotly.graph_objects as go
import streamlit as st

from src.analytics.queries import get_error_breakdown, get_error_trend

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cached data loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def _load_error_trend():
    """Load error trend DataFrame."""
    return get_error_trend()


@st.cache_data(ttl=300)
def _load_error_breakdown():
    """Load error breakdown DataFrame."""
    return get_error_breakdown()


# ---------------------------------------------------------------------------
# Internal render helpers
# ---------------------------------------------------------------------------


def _render_error_trend(filters: Dict[str, Any]) -> None:
    """Render line chart of daily error counts with optional date filter."""
    df = _load_error_trend()

    if df.empty:
        st.info("No error data available.")
        return

    # Client-side date filter
    date_from = str(filters["date_from"])
    date_to = str(filters["date_to"])
    df = df[(df["date"] >= date_from) & (df["date"] <= date_to)]

    if df.empty:
        st.info("No errors in the selected date range.")
        return

    total = df["error_count"].sum()
    st.markdown(f"**Error Trend** (n={total:,} errors in range)")

    fig = go.Figure(
        go.Scatter(
            x=df["date"],
            y=df["error_count"],
            mode="lines+markers",
            line={"color": "#EF553B"},
            marker={"size": 6},
            hovertemplate="Date: %{x}<br>Errors: %{y}<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        xaxis_title="Date",
        yaxis_title="Error Count",
        margin={"t": 30, "b": 40},
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_error_breakdown() -> None:
    """Render error breakdown table grouped by message and status code."""
    df = _load_error_breakdown()

    if df.empty:
        st.info("No error breakdown data available.")
        return

    total = df["count"].sum()
    st.markdown(f"**Error Breakdown by Type & Status Code** (n={total:,} total errors)")

    display = df.rename(
        columns={
            "error_message": "Error Message",
            "status_code": "Status Code",
            "count": "Count",
        }
    )
    st.dataframe(display, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render(filters: Dict[str, Any]) -> None:
    """Render the Errors page.

    Args:
        filters: Global filter dict from the sidebar with keys
            ``date_from``, ``date_to``, ``practices``, ``levels``, ``locations``.
            Only ``date_from`` / ``date_to`` are applied here.
    """
    st.header("Errors")

    try:
        _render_error_trend(filters)
    except Exception:
        logger.exception("Failed to render error trend")
        st.error("Could not render error trend chart.")

    st.divider()

    try:
        _render_error_breakdown()
    except Exception:
        logger.exception("Failed to render error breakdown")
        st.error("Could not render error breakdown table.")

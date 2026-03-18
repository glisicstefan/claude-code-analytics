"""Tool Analysis dashboard component.

Renders tool usage frequency, tool success rates, and decision source breakdown.
All data is fetched via :mod:`src.analytics.queries` — no direct DB access here.
"""

import logging
from typing import Any, Dict

import plotly.graph_objects as go
import streamlit as st

from src.analytics.queries import (
    get_tool_decision_breakdown,
    get_tool_frequency,
    get_tool_success_rates,
)

logger = logging.getLogger(__name__)

# Thresholds for success-rate colour coding
_GREEN_THRESHOLD = 80.0
_YELLOW_THRESHOLD = 50.0


# ---------------------------------------------------------------------------
# Cached data loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def _load_tool_frequency():
    """Load tool usage frequency DataFrame."""
    return get_tool_frequency()


@st.cache_data(ttl=300)
def _load_tool_success_rates():
    """Load tool success rates DataFrame."""
    return get_tool_success_rates()


@st.cache_data(ttl=300)
def _load_tool_decision_breakdown():
    """Load tool decision source breakdown DataFrame."""
    return get_tool_decision_breakdown()


# ---------------------------------------------------------------------------
# Internal render helpers
# ---------------------------------------------------------------------------


def _render_tool_frequency() -> None:
    """Render horizontal bar chart: tool usage count, sorted descending."""
    df = _load_tool_frequency()

    if df.empty:
        st.info("No tool event data available.")
        return

    n = df["usage_count"].sum()
    st.markdown(f"**Tool Usage Frequency** (n={n:,} events)")

    # Sort ascending so the longest bar appears at the top in a horizontal chart
    df = df.sort_values("usage_count", ascending=True)

    fig = go.Figure(
        go.Bar(
            x=df["usage_count"],
            y=df["tool_name"],
            orientation="h",
            marker_color="#636EFA",
            text=df["usage_count"].apply(lambda v: f"{v:,}"),
            textposition="auto",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        xaxis_title="Usage Count",
        yaxis_title="Tool",
        margin={"t": 30, "b": 40},
        height=max(300, len(df) * 35 + 60),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_tool_success_rates() -> None:
    """Render horizontal bar chart: success rate per tool, colour-coded by threshold."""
    df = _load_tool_success_rates()

    if df.empty:
        st.info("No tool success-rate data available.")
        return

    # Drop tools with no recorded results
    df = df.dropna(subset=["success_rate"])

    if df.empty:
        st.info("No tools with known success/failure outcomes.")
        return

    df = df.sort_values("success_rate", ascending=True)

    def _colour(rate: float) -> str:
        if rate >= _GREEN_THRESHOLD:
            return "#00CC96"
        if rate >= _YELLOW_THRESHOLD:
            return "#FECB52"
        return "#EF553B"

    colours = [_colour(r) for r in df["success_rate"]]
    n = df["rows_with_result"].sum()
    st.markdown(f"**Tool Success Rates** (n={n:,} events with outcome)")

    fig = go.Figure(
        go.Bar(
            x=df["success_rate"],
            y=df["tool_name"],
            orientation="h",
            marker_color=colours,
            text=df["success_rate"].apply(lambda v: f"{v:.1f}%"),
            textposition="auto",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        xaxis={"title": "Success Rate (%)", "range": [0, 100]},
        yaxis_title="Tool",
        margin={"t": 30, "b": 40},
        height=max(300, len(df) * 35 + 60),
    )

    # Legend annotation
    fig.add_annotation(
        text="Green ≥80% | Yellow ≥50% | Red <50%",
        xref="paper", yref="paper",
        x=1, y=-0.12,
        showarrow=False,
        font={"size": 11, "color": "#aaa"},
        align="right",
    )

    st.plotly_chart(fig, use_container_width=True)


def _render_decision_breakdown() -> None:
    """Render bar chart: tool event counts by decision_source."""
    df = _load_tool_decision_breakdown()

    if df.empty:
        st.info("No decision source data available.")
        return

    n = df["count"].sum()
    st.markdown(f"**Decision Source Breakdown** (n={n:,} events)")

    fig = go.Figure(
        go.Bar(
            x=df["decision_source"],
            y=df["count"],
            marker_color="#AB63FA",
            text=df["count"].apply(lambda v: f"{v:,}"),
            textposition="auto",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        xaxis_title="Decision Source",
        yaxis_title="Count",
        margin={"t": 30, "b": 60},
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render(filters: Dict[str, Any]) -> None:
    """Render the Tool Analysis page.

    Args:
        filters: Global filter dict from the sidebar. Tool analysis does not
            directly filter by practice/level/location, but the dict is
            accepted for interface consistency.
    """
    st.header("Tool Analysis")

    col_left, col_right = st.columns(2)

    with col_left:
        try:
            _render_tool_frequency()
        except Exception:
            logger.exception("Failed to render tool frequency")
            st.error("Could not render tool frequency chart.")

    with col_right:
        try:
            _render_tool_success_rates()
        except Exception:
            logger.exception("Failed to render tool success rates")
            st.error("Could not render tool success rates chart.")

    st.divider()

    try:
        _render_decision_breakdown()
    except Exception:
        logger.exception("Failed to render decision breakdown")
        st.error("Could not render decision source breakdown.")

"""Token & Cost dashboard component.

Renders token consumption breakdowns, model distribution, top users by cost,
and cache hit rate analysis.
All data is fetched via :mod:`src.analytics.queries` — no direct DB access here.
"""

import logging
from typing import Any, Dict, List

import plotly.graph_objects as go
import streamlit as st

from src.analytics.queries import (
    get_cache_hit_rate,
    get_cost_per_user,
    get_model_distribution,
    get_tokens_by_level,
    get_tokens_by_practice,
)

logger = logging.getLogger(__name__)

# Level sort order: L1 → L10
_LEVEL_ORDER: List[str] = [f"L{i}" for i in range(1, 11)]


# ---------------------------------------------------------------------------
# Cached data loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def _load_tokens_by_practice():
    """Load token consumption by practice."""
    return get_tokens_by_practice()


@st.cache_data(ttl=300)
def _load_tokens_by_level():
    """Load token consumption by seniority level."""
    return get_tokens_by_level()


@st.cache_data(ttl=300)
def _load_cost_per_user():
    """Load top-10 users by cost."""
    return get_cost_per_user()


@st.cache_data(ttl=300)
def _load_model_distribution():
    """Load model distribution."""
    return get_model_distribution()


@st.cache_data(ttl=300)
def _load_cache_hit_rate():
    """Load cache hit rate overall and by practice."""
    return get_cache_hit_rate()


# ---------------------------------------------------------------------------
# Internal render helpers
# ---------------------------------------------------------------------------


def _render_tokens_by_practice(filters: Dict[str, Any]) -> None:
    """Render horizontal bar chart: total tokens by practice."""
    df = _load_tokens_by_practice()

    if df.empty:
        st.info("No token data by practice available.")
        return

    selected = filters["practices"]
    if selected:
        df = df[df["practice"].isin(selected)]

    if df.empty:
        st.info("No data for the selected practices.")
        return

    n = len(df)
    st.markdown(f"**Tokens by Practice** (n={n})")

    fig = go.Figure(
        go.Bar(
            x=df["total_tokens"],
            y=df["practice"],
            orientation="h",
            marker_color="#636EFA",
            text=df["total_tokens"].apply(lambda v: f"{v:,}"),
            textposition="auto",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        xaxis_title="Total Tokens",
        yaxis_title="Practice",
        margin={"t": 30, "b": 40},
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_tokens_by_level(filters: Dict[str, Any]) -> None:
    """Render horizontal bar chart: total tokens by seniority level (L1→L10)."""
    df = _load_tokens_by_level()

    if df.empty:
        st.info("No token data by level available.")
        return

    selected = filters["levels"]
    if selected:
        df = df[df["level"].isin(selected)]

    # Sort levels L1 → L10
    df["_sort"] = df["level"].apply(
        lambda lvl: _LEVEL_ORDER.index(lvl) if lvl in _LEVEL_ORDER else 999
    )
    df = df.sort_values("_sort").drop(columns=["_sort"])

    if df.empty:
        st.info("No data for the selected levels.")
        return

    n = len(df)
    st.markdown(f"**Tokens by Seniority Level** (n={n})")

    fig = go.Figure(
        go.Bar(
            x=df["total_tokens"],
            y=df["level"],
            orientation="h",
            marker_color="#EF553B",
            text=df["total_tokens"].apply(lambda v: f"{v:,}"),
            textposition="auto",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        xaxis_title="Total Tokens",
        yaxis_title="Level",
        margin={"t": 30, "b": 40},
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_top_users() -> None:
    """Render top-10 users by cost as a styled dataframe."""
    df = _load_cost_per_user()

    if df.empty:
        st.info("No cost data per user available.")
        return

    n = len(df)
    st.markdown(f"**Top Users by Cost** (n={n})")

    display = df[["full_name", "user_email", "practice", "total_cost_usd"]].copy()
    display = display.rename(
        columns={
            "full_name": "Name",
            "user_email": "Email",
            "practice": "Practice",
            "total_cost_usd": "Cost (USD)",
        }
    )
    display["Cost (USD)"] = display["Cost (USD)"].apply(lambda v: f"${v:,.2f}")
    st.dataframe(display, use_container_width=True, hide_index=True)


def _render_model_distribution() -> None:
    """Render pie chart: API request share by model."""
    df = _load_model_distribution()

    if df.empty:
        st.info("No model distribution data available.")
        return

    total = df["request_count"].sum()
    st.markdown(f"**Model Distribution** (n={total:,} requests)")

    fig = go.Figure(
        go.Pie(
            labels=df["model"],
            values=df["request_count"],
            customdata=df["total_cost_usd"],
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Requests: %{value:,}<br>"
                "Cost: $%{customdata:.2f}<extra></extra>"
            ),
            textinfo="label+percent",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        margin={"t": 30, "b": 10},
        height=350,
        showlegend=True,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_cache_hit_rate(filters: Dict[str, Any]) -> None:
    """Render overall cache hit rate metric and by-practice bar chart."""
    data = _load_cache_hit_rate()
    overall = data["overall"]
    by_practice = data["by_practice"]

    col_metric, col_chart = st.columns([1, 2])

    with col_metric:
        if not overall.empty:
            rate = overall.iloc[0]["cache_hit_rate"]
            total_read = overall.iloc[0]["total_cache_read"]
            rate_pct = f"{rate * 100:.1f}%" if rate is not None else "N/A"
            st.metric("Overall Cache Hit Rate", rate_pct)
            st.caption(f"Cache read tokens: {int(total_read):,}")
        else:
            st.info("No cache data available.")

    with col_chart:
        if by_practice.empty:
            st.info("No cache data by practice.")
            return

        selected = filters["practices"]
        df = by_practice.copy()
        if selected:
            df = df[df["practice"].isin(selected)]

        if df.empty:
            st.info("No cache data for the selected practices.")
            return

        n = len(df)
        st.markdown(f"**Cache Hit Rate by Practice** (n={n})")

        df["rate_pct"] = (df["cache_hit_rate"] * 100).round(1)

        fig = go.Figure(
            go.Bar(
                x=df["rate_pct"],
                y=df["practice"],
                orientation="h",
                marker_color="#00CC96",
                text=df["rate_pct"].apply(lambda v: f"{v:.1f}%"),
                textposition="auto",
            )
        )
        fig.update_layout(
            template="plotly_dark",
            xaxis={"title": "Cache Hit Rate (%)", "range": [0, 100]},
            yaxis_title="Practice",
            margin={"t": 30, "b": 40},
            height=300,
        )
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render(filters: Dict[str, Any]) -> None:
    """Render the Token & Cost page.

    Args:
        filters: Global filter dict from the sidebar with keys
            ``date_from``, ``date_to``, ``practices``, ``levels``, ``locations``.
    """
    st.header("Token & Cost")

    # Row 1: tokens by practice + tokens by level
    col_left, col_right = st.columns(2)
    with col_left:
        try:
            _render_tokens_by_practice(filters)
        except Exception:
            logger.exception("Failed to render tokens by practice")
            st.error("Could not render tokens by practice.")

    with col_right:
        try:
            _render_tokens_by_level(filters)
        except Exception:
            logger.exception("Failed to render tokens by level")
            st.error("Could not render tokens by level.")

    st.divider()

    # Row 2: top users table + model distribution pie
    col_left, col_right = st.columns(2)
    with col_left:
        try:
            _render_top_users()
        except Exception:
            logger.exception("Failed to render top users")
            st.error("Could not render top users table.")

    with col_right:
        try:
            _render_model_distribution()
        except Exception:
            logger.exception("Failed to render model distribution")
            st.error("Could not render model distribution chart.")

    st.divider()

    # Row 3: cache hit rate
    st.subheader("Cache Hit Rate")
    try:
        _render_cache_hit_rate(filters)
    except Exception:
        logger.exception("Failed to render cache hit rate")
        st.error("Could not render cache hit rate.")

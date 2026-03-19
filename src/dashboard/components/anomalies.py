"""Anomaly Detection dashboard component.

Surfaces users flagged as behavioural outliers by the Isolation Forest model
in :mod:`src.analytics.anomaly`.  Shows a KPI card, a scatter plot, and a
detailed table of flagged users.
"""

import logging
from typing import Any, Dict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analytics.anomaly import detect_user_anomalies
from src.analytics.queries import _query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANOMALY_COLOR: str = "#EF553B"   # red — flagged users
NORMAL_COLOR: str = "#636EFA"    # blue — normal users

TABLE_COLS: list[str] = [
    "user_email",
    "practice",
    "anomaly_score",
    "total_cost_usd",
    "total_tokens",
    "avg_session_duration_min",
    "error_rate",
    "total_sessions",
]

# ---------------------------------------------------------------------------
# Cached data loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def _load_anomalies() -> pd.DataFrame:
    """Run Isolation Forest and return the full per-user DataFrame."""
    return detect_user_anomalies()


@st.cache_data(ttl=300)
def _load_practice_map() -> pd.DataFrame:
    """Return a DataFrame mapping user_email → practice from the employees table."""
    sql = """
        SELECT email AS user_email, practice
        FROM employees
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("_load_practice_map failed")
        raise


# ---------------------------------------------------------------------------
# Internal render helpers
# ---------------------------------------------------------------------------


def _render_kpi_card(df: pd.DataFrame) -> None:
    """Render a single metric card: anomalies detected / total users."""
    total_users = len(df)
    total_anomalies = int(df["is_anomaly"].sum())

    c1, *_ = st.columns(4)
    c1.metric(
        label="Anomalies Detected",
        value=f"{total_anomalies} / {total_users}",
        help="Users flagged as outliers by Isolation Forest (contamination=5 %)",
    )


def _render_scatter(df: pd.DataFrame) -> None:
    """Render cost vs tokens scatter plot, coloured by anomaly label."""
    normal = df[~df["is_anomaly"]]
    flagged = df[df["is_anomaly"]]

    n = len(df)
    st.markdown(f"**Cost vs Token Consumption** (n={n:,} users)")

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=normal["total_cost_usd"],
            y=normal["total_tokens"],
            mode="markers",
            name="Normal",
            marker={"color": NORMAL_COLOR, "size": 8, "opacity": 0.7},
            customdata=normal[["user_email", "practice"]].values,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Practice: %{customdata[1]}<br>"
                "Cost: $%{x:,.4f}<br>"
                "Tokens: %{y:,}<extra></extra>"
            ),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=flagged["total_cost_usd"],
            y=flagged["total_tokens"],
            mode="markers",
            name="Anomaly",
            marker={
                "color": ANOMALY_COLOR,
                "size": 12,
                "symbol": "x",
                "opacity": 0.9,
                "line": {"width": 1, "color": "#fff"},
            },
            customdata=flagged[["user_email", "practice"]].values,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Practice: %{customdata[1]}<br>"
                "Cost: $%{x:,.4f}<br>"
                "Tokens: %{y:,}<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        template="plotly_dark",
        xaxis={"title": "Total Cost (USD)"},
        yaxis={"title": "Total Tokens"},
        legend={"x": 0, "y": 1.1, "orientation": "h"},
        margin={"t": 40, "b": 40},
        height=420,
    )

    st.plotly_chart(fig, use_container_width=True)


def _render_flagged_table(df: pd.DataFrame) -> None:
    """Render a sortable table of anomalous users."""
    flagged = df[df["is_anomaly"]].copy()

    if flagged.empty:
        st.info("No anomalies detected in the current dataset.")
        return

    n = len(flagged)
    st.markdown(f"**Flagged Users** (n={n:,})")

    display_cols = [c for c in TABLE_COLS if c in flagged.columns]
    display = flagged[display_cols].copy()

    display["anomaly_score"] = display["anomaly_score"].round(4)
    display["total_cost_usd"] = display["total_cost_usd"].round(4)
    display["avg_session_duration_min"] = display["avg_session_duration_min"].round(2)
    display["error_rate"] = display["error_rate"].round(4)

    st.dataframe(
        display.sort_values("anomaly_score", ascending=False).reset_index(drop=True),
        use_container_width=True,
        hide_index=True,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render(filters: Dict[str, Any]) -> None:
    """Render the Anomaly Detection page.

    Args:
        filters: Global filter dict from the sidebar (currently unused —
            anomaly detection runs across all users for statistical validity).
    """
    st.header("Anomaly Detection")
    st.caption(
        "Isolation Forest trained on 5 features: total cost, total tokens, "
        "avg session duration, error rate, total sessions.  "
        "Contamination threshold: 5 %."
    )

    try:
        df = _load_anomalies()
        practice_map = _load_practice_map()
    except Exception:
        logger.exception("Failed to load anomaly data")
        st.error("Could not load anomaly data. Check that the database is populated.")
        return

    if df.empty:
        st.warning("No user data found. Run the ingestion pipeline first.")
        return

    df = df.merge(practice_map, on="user_email", how="left")
    df["practice"] = df["practice"].fillna("Unknown")

    _render_kpi_card(df)

    st.divider()

    try:
        _render_scatter(df)
    except Exception:
        logger.exception("Failed to render anomaly scatter plot")
        st.error("Could not render scatter plot.")

    st.divider()

    try:
        _render_flagged_table(df)
    except Exception:
        logger.exception("Failed to render flagged users table")
        st.error("Could not render flagged users table.")

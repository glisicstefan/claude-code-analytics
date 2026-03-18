"""Streamlit entry point for the Claude Code Analytics dashboard.

Run with::

    streamlit run src/dashboard/app.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st
from sqlalchemy.engine import Engine

from src.db.schema import make_engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "analytics.db"

PRACTICES: List[str] = [
    "Platform Engineering",
    "Data Engineering",
    "ML Engineering",
    "Backend Engineering",
    "Frontend Engineering",
]

LEVELS: List[str] = [f"L{i}" for i in range(1, 11)]

LOCATIONS: List[str] = [
    "New York",
    "San Francisco",
    "Austin",
    "Chicago",
    "Seattle",
    "Boston",
    "Remote",
]

PAGE_OVERVIEW = "Overview"
PAGE_TOKEN_COST = "Token & Cost"
PAGE_TOOL_ANALYSIS = "Tool Analysis"
PAGE_USAGE_PATTERNS = "Usage Patterns"
PAGE_ERRORS = "Errors"
PAGE_ANOMALIES = "Anomalies"

PAGES = [PAGE_OVERVIEW, PAGE_TOKEN_COST, PAGE_TOOL_ANALYSIS, PAGE_USAGE_PATTERNS, PAGE_ERRORS, PAGE_ANOMALIES]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@st.cache_resource
def _get_engine() -> Engine:
    """Return a cached SQLAlchemy engine for the analytics DB."""
    return make_engine(str(DB_PATH))


@st.cache_data(ttl=300)
def _load_filter_options() -> Dict[str, List[str]]:
    """Query distinct practices, levels, and locations from the employees table.

    Falls back to the module-level constants if the DB is not yet populated.

    Returns:
        Dict with keys ``"practices"``, ``"levels"``, ``"locations"``.
    """
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            practices = pd.read_sql(
                "SELECT DISTINCT practice FROM employees WHERE practice IS NOT NULL ORDER BY practice",
                conn,
            )["practice"].tolist()
            levels = pd.read_sql(
                "SELECT DISTINCT level FROM employees WHERE level IS NOT NULL ORDER BY level",
                conn,
            )["level"].tolist()
            locations = pd.read_sql(
                "SELECT DISTINCT location FROM employees WHERE location IS NOT NULL ORDER BY location",
                conn,
            )["location"].tolist()
        return {
            "practices": practices or PRACTICES,
            "levels": levels or LEVELS,
            "locations": locations or LOCATIONS,
        }
    except Exception:
        logger.warning("Could not load filter options from DB — using defaults.")
        return {"practices": PRACTICES, "levels": LEVELS, "locations": LOCATIONS}


@st.cache_data(ttl=300)
def _load_date_bounds() -> Dict[str, Optional[date]]:
    """Query the earliest and latest timestamps in api_requests.

    Returns:
        Dict with keys ``"min_date"`` and ``"max_date"`` (Python :class:`date` or ``None``).
    """
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            row = pd.read_sql(
                "SELECT DATE(MIN(timestamp)) AS min_dt, DATE(MAX(timestamp)) AS max_dt FROM api_requests",
                conn,
            ).iloc[0]
        min_dt = date.fromisoformat(row["min_dt"]) if row["min_dt"] else None
        max_dt = date.fromisoformat(row["max_dt"]) if row["max_dt"] else None
        return {"min_date": min_dt, "max_date": max_dt}
    except Exception:
        logger.warning("Could not load date bounds from DB.")
        return {"min_date": None, "max_date": None}


# ---------------------------------------------------------------------------
# Sidebar — global filters
# ---------------------------------------------------------------------------


def _render_sidebar() -> Dict[str, Any]:
    """Render the global filter sidebar and return the selected filter values.

    Returns:
        Dict with keys:
            ``"date_from"`` (date): start of selected date range.
            ``"date_to"`` (date): end of selected date range.
            ``"practices"`` (list[str]): selected practices (empty = all).
            ``"levels"`` (list[str]): selected levels (empty = all).
            ``"locations"`` (list[str]): selected locations (empty = all).
    """
    st.sidebar.title("Filters")

    bounds = _load_date_bounds()
    options = _load_filter_options()

    today = date.today()
    default_from = bounds["min_date"] or (today - timedelta(days=30))
    default_to = bounds["max_date"] or today

    st.sidebar.markdown("### Date Range")
    date_from: date = st.sidebar.date_input(
        "From",
        value=default_from,
        min_value=bounds["min_date"] or date(2020, 1, 1),
        max_value=default_to,
        key="filter_date_from",
    )
    date_to: date = st.sidebar.date_input(
        "To",
        value=default_to,
        min_value=date_from,
        max_value=bounds["max_date"] or today,
        key="filter_date_to",
    )

    st.sidebar.markdown("### Practice")
    selected_practices: List[str] = st.sidebar.multiselect(
        "Practice",
        options=options["practices"],
        default=[],
        placeholder="All practices",
        key="filter_practice",
        label_visibility="collapsed",
    )

    st.sidebar.markdown("### Level")
    selected_levels: List[str] = st.sidebar.multiselect(
        "Level",
        options=options["levels"],
        default=[],
        placeholder="All levels",
        key="filter_level",
        label_visibility="collapsed",
    )

    st.sidebar.markdown("### Location")
    selected_locations: List[str] = st.sidebar.multiselect(
        "Location",
        options=options["locations"],
        default=[],
        placeholder="All locations",
        key="filter_location",
        label_visibility="collapsed",
    )

    st.sidebar.divider()
    st.sidebar.caption("Empty multiselect = no filter applied (show all).")

    return {
        "date_from": date_from,
        "date_to": date_to,
        "practices": selected_practices,
        "levels": selected_levels,
        "locations": selected_locations,
    }


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


def _render_nav() -> str:
    """Render top-of-sidebar page navigation and return the selected page name."""
    st.sidebar.markdown("## Navigation")
    return st.sidebar.radio(
        "Go to",
        options=PAGES,
        key="nav_page",
        label_visibility="collapsed",
    )


# ---------------------------------------------------------------------------
# Page dispatch
# ---------------------------------------------------------------------------


def _render_page(page: str, filters: Dict[str, Any]) -> None:
    """Import and call the render function for the selected page.

    Each component module must expose a ``render(filters: dict) -> None`` function.

    Args:
        page: One of the :data:`PAGES` constants.
        filters: Global filter dict produced by :func:`_render_sidebar`.
    """
    if page == PAGE_OVERVIEW:
        from src.dashboard.components.overview import render
    elif page == PAGE_TOKEN_COST:
        from src.dashboard.components.token_usage import render
    elif page == PAGE_TOOL_ANALYSIS:
        from src.dashboard.components.tool_analysis import render
    elif page == PAGE_USAGE_PATTERNS:
        from src.dashboard.components.cost_analysis import render
    elif page == PAGE_ERRORS:
        from src.dashboard.components.errors import render
    elif page == PAGE_ANOMALIES:
        from src.dashboard.components.anomalies import render
    else:
        st.error(f"Unknown page: {page}")
        return

    render(filters)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Configure Streamlit and run the dashboard application."""
    st.set_page_config(
        layout="wide",
        page_title="Claude Code Analytics",
        page_icon="📊",
    )

    st.title("📊 Claude Code Analytics")

    page = _render_nav()
    filters = _render_sidebar()

    _render_page(page, filters)


if __name__ == "__main__":
    main()

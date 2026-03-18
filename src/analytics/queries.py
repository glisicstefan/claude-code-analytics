"""
Analytics query functions for the Claude Code Analytics dashboard.

Every public function connects to the SQLite database, executes a named-column
SQL query, and returns the result as a :class:`pandas.DataFrame`.

Usage::

    from src.analytics.queries import get_overview_stats
    df = get_overview_stats()
"""

import logging
from pathlib import Path
from typing import Dict

import pandas as pd
from sqlalchemy.engine import Engine

from src.db.schema import make_engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "analytics.db"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_engine() -> Engine:
    """Return a SQLAlchemy engine pointed at :data:`DB_PATH`."""
    return make_engine(str(DB_PATH))


def _query(sql: str) -> pd.DataFrame:
    """Execute *sql* and return a DataFrame. Raises on connection errors."""
    engine = _get_engine()
    with engine.connect() as conn:
        return pd.read_sql(sql, conn)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def get_overview_stats() -> pd.DataFrame:
    """Return a single-row summary of platform-wide activity.

    Columns:
        total_sessions (int): distinct session count.
        total_cost_usd (float): sum of all API request costs.
        total_tokens (int): sum of input + output + cache_read + cache_create tokens.
        active_users (int): distinct user count with at least one API request.

    Returns:
        Single-row :class:`pandas.DataFrame`.
    """
    sql = """
        SELECT
            COUNT(DISTINCT session_id)                                          AS total_sessions,
            ROUND(SUM(cost_usd),2)                                              AS total_cost_usd,
            SUM(
                COALESCE(input_tokens, 0)
                + COALESCE(output_tokens, 0)
                + COALESCE(cache_read_tokens, 0)
                + COALESCE(cache_create_tokens, 0)
            )                                                                   AS total_tokens,
            COUNT(DISTINCT user_email)                                          AS active_users
        FROM api_requests
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("get_overview_stats failed")
        raise


# ---------------------------------------------------------------------------
# Daily activity
# ---------------------------------------------------------------------------


def get_daily_activity() -> pd.DataFrame:
    """Return sessions and cost aggregated by calendar date.

    Columns:
        date (str): ISO date string (YYYY-MM-DD).
        session_count (int): distinct sessions that had at least one API request.
        total_cost_usd (float): total spend on that date.

    Returns:
        :class:`pandas.DataFrame` ordered by date ascending.
    """
    sql = """
        SELECT
            DATE(timestamp)             AS date,
            COUNT(DISTINCT session_id)  AS session_count,
            SUM(cost_usd)               AS total_cost_usd
        FROM api_requests
        GROUP BY DATE(timestamp)
        ORDER BY date
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("get_daily_activity failed")
        raise


# ---------------------------------------------------------------------------
# Token usage by practice
# ---------------------------------------------------------------------------


def get_tokens_by_practice() -> pd.DataFrame:
    """Return total token consumption broken down by employee practice.

    Joins ``api_requests`` with ``employees`` on ``user_email = email``.

    Columns:
        practice (str): e.g. ``ML Engineering``, ``Backend Engineering``.
        total_tokens (int): sum of all four token columns.

    Returns:
        :class:`pandas.DataFrame` ordered by total_tokens descending.
    """
    sql = """
        SELECT
            e.practice,
            SUM(
                COALESCE(r.input_tokens, 0)
                + COALESCE(r.output_tokens, 0)
                + COALESCE(r.cache_read_tokens, 0)
                + COALESCE(r.cache_create_tokens, 0)
            ) AS total_tokens
        FROM api_requests AS r
        LEFT JOIN employees AS e ON r.user_email = e.email
        GROUP BY e.practice
        ORDER BY total_tokens DESC
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("get_tokens_by_practice failed")
        raise


# ---------------------------------------------------------------------------
# Token usage by seniority level
# ---------------------------------------------------------------------------


def get_tokens_by_level() -> pd.DataFrame:
    """Return total token consumption broken down by employee seniority level.

    Joins ``api_requests`` with ``employees`` on ``user_email = email``.

    Columns:
        level (str): e.g. ``L1``, ``L5``, ``L10``.
        total_tokens (int): sum of all four token columns.

    Returns:
        :class:`pandas.DataFrame` ordered by total_tokens descending.
    """
    sql = """
        SELECT
            e.level,
            SUM(
                COALESCE(r.input_tokens, 0)
                + COALESCE(r.output_tokens, 0)
                + COALESCE(r.cache_read_tokens, 0)
                + COALESCE(r.cache_create_tokens, 0)
            ) AS total_tokens
        FROM api_requests AS r
        LEFT JOIN employees AS e ON r.user_email = e.email
        GROUP BY e.level
        ORDER BY total_tokens DESC
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("get_tokens_by_level failed")
        raise


# ---------------------------------------------------------------------------
# Cost per user (top 10)
# ---------------------------------------------------------------------------


def get_cost_per_user() -> pd.DataFrame:
    """Return the top 10 users ranked by total API cost.

    Joins ``api_requests`` with ``employees`` to enrich with name and practice.

    Columns:
        user_email (str): user identifier.
        full_name (str): employee display name.
        practice (str): employee practice area.
        total_cost_usd (float): sum of all API request costs.

    Returns:
        :class:`pandas.DataFrame` with at most 10 rows, ordered by cost descending.
    """
    sql = """
        SELECT
            r.user_email,
            e.full_name,
            e.practice,
            ROUND(SUM(r.cost_usd), 2) AS total_cost_usd
        FROM api_requests AS r
        LEFT JOIN employees AS e ON r.user_email = e.email
        GROUP BY r.user_email, e.full_name, e.practice
        ORDER BY total_cost_usd DESC
        LIMIT 10
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("get_cost_per_user failed")
        raise


# ---------------------------------------------------------------------------
# Model distribution
# ---------------------------------------------------------------------------


def get_model_distribution() -> pd.DataFrame:
    """Return request count and total cost grouped by Claude model variant.

    Columns:
        model (str): model identifier string.
        request_count (int): number of API requests using that model.
        total_cost_usd (float): total spend attributed to that model.

    Returns:
        :class:`pandas.DataFrame` ordered by request_count descending.
    """
    sql = """
        SELECT
            model,
            COUNT(*)                    AS request_count,
            ROUND(SUM(cost_usd), 2)     AS total_cost_usd
        FROM api_requests
        GROUP BY model
        ORDER BY request_count DESC
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("get_model_distribution failed")
        raise


# ---------------------------------------------------------------------------
# Cache hit rate
# ---------------------------------------------------------------------------


def get_cache_hit_rate() -> Dict[str, pd.DataFrame]:
    """Return cache hit rates overall and broken down by practice.

    Cache hit rate is defined as::

        cache_read_tokens / (input_tokens + cache_read_tokens + cache_create_tokens)

    A ``NULLIF`` guard prevents division by zero when the denominator is 0.

    Returns:
        dict with two keys:

        ``"overall"``
            Single-row DataFrame with columns ``cache_hit_rate`` and ``total_cache_read``.

        ``"by_practice"``
            Multi-row DataFrame with columns ``practice`` and ``cache_hit_rate``,
            ordered by cache_hit_rate descending.
    """
    sql_overall = """
        WITH stats AS (    
            SELECT
                SUM(COALESCE(cache_read_tokens, 0))                        AS total_cache_read,
                SUM(
                    COALESCE(input_tokens, 0)
                    + COALESCE(cache_read_tokens, 0)
                    + COALESCE(cache_create_tokens, 0)
                )                                                           AS total_input,
                CAST(SUM(COALESCE(cache_read_tokens, 0)) AS REAL)
                    / NULLIF(
                        SUM(
                            COALESCE(input_tokens, 0)
                            + COALESCE(cache_read_tokens, 0)
                            + COALESCE(cache_create_tokens, 0)
                        ), 0
                    )                                                       AS cache_hit_rate
            FROM api_requests
        )
        SELECT
            total_cache_read,
            total_input,
            ROUND(cache_hit_rate, 2) AS cache_hit_rate
        FROM stats
    """

    sql_by_practice = """
        WITH stats AS (
            SELECT
                e.practice                                                  AS practice,
                CAST(SUM(COALESCE(r.cache_read_tokens, 0)) AS REAL)
                    / NULLIF(
                        SUM(
                            COALESCE(r.input_tokens, 0)
                            + COALESCE(r.cache_read_tokens, 0)
                            + COALESCE(r.cache_create_tokens, 0)
                        ), 0
                    )                                                       AS cache_hit_rate
            FROM api_requests AS r
            LEFT JOIN employees AS e ON r.user_email = e.email
            GROUP BY e.practice
            ORDER BY cache_hit_rate DESC
        )
        SELECT
            practice,
            ROUND(cache_hit_rate, 2) AS cache_hit_rate
        FROM stats
    """

    try:
        return {
            "overall": _query(sql_overall),
            "by_practice": _query(sql_by_practice),
        }
    except Exception:
        logger.exception("get_cache_hit_rate failed")
        raise


# ---------------------------------------------------------------------------
# Peak usage heatmap
# ---------------------------------------------------------------------------


def get_peak_usage_heatmap() -> pd.DataFrame:
    """Return API request counts grouped by hour of day and day of week.

    Useful for rendering a heatmap of peak usage times.

    Columns:
        hour_of_day (str): zero-padded hour, ``"00"`` through ``"23"``.
        day_of_week (str): SQLite ``strftime('%w', ...)`` value — ``"0"`` (Sunday)
            through ``"6"`` (Saturday).
        request_count (int): number of API requests in that slot.

    Returns:
        :class:`pandas.DataFrame` ordered by day_of_week, hour_of_day ascending.
    """
    sql = """
        SELECT
            strftime('%H', timestamp) AS hour_of_day,
            strftime('%w', timestamp) AS day_of_week,
            COUNT(*)                  AS request_count
        FROM api_requests
        GROUP BY hour_of_day, day_of_week
        ORDER BY day_of_week, hour_of_day
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("get_peak_usage_heatmap failed")
        raise


# ---------------------------------------------------------------------------
# Tool analysis
# ---------------------------------------------------------------------------


def get_tool_frequency() -> pd.DataFrame:
    """Return tool usage counts sorted from most to least used.

    Columns:
        tool_name (str): name of the tool.
        usage_count (int): total number of tool_events rows for that tool.

    Returns:
        :class:`pandas.DataFrame` ordered by usage_count descending.
    """
    sql = """
        SELECT
            tool_name,
            COUNT(*) AS usage_count
        FROM tool_events
        GROUP BY tool_name
        ORDER BY usage_count DESC
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("get_tool_frequency failed")
        raise


def get_tool_success_rates() -> pd.DataFrame:
    """Return success rate per tool, considering only rows where success is known.

    The ``success`` column is ``1`` (success) or ``0`` (failure); rows where
    ``success IS NULL`` (tool_decision rows that have no result yet) are excluded
    from the rate calculation but counted separately.

    Columns:
        tool_name (str): name of the tool.
        total (int): total rows for this tool in tool_events.
        rows_with_result (int): rows where success is not NULL.
        success_rate (float): percentage of successful executions (0–100), or NULL
            if no result rows exist for this tool.

    Returns:
        :class:`pandas.DataFrame` ordered by success_rate descending.
    """
    sql = """
        SELECT
            tool_name,
            COUNT(*)                                    AS total,
            COUNT(success)                              AS rows_with_result,
            AVG(CAST(success AS REAL)) * 100            AS success_rate
        FROM tool_events
        GROUP BY tool_name
        ORDER BY success_rate DESC
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("get_tool_success_rates failed")
        raise


# ---------------------------------------------------------------------------
# Error analysis
# ---------------------------------------------------------------------------


def get_error_trend() -> pd.DataFrame:
    """Return error counts grouped by calendar date.

    Columns:
        date (str): ISO date string (YYYY-MM-DD).
        error_count (int): number of API errors recorded on that date.

    Returns:
        :class:`pandas.DataFrame` ordered by date ascending.
    """
    sql = """
        SELECT
            DATE(timestamp) AS date,
            COUNT(*)        AS error_count
        FROM api_errors
        GROUP BY DATE(timestamp)
        ORDER BY date
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("get_error_trend failed")
        raise


def get_error_breakdown() -> pd.DataFrame:
    """Return error counts grouped by error message and HTTP status code.

    Columns:
        error_message (str): the error description string.
        status_code (str): HTTP status code as a string (e.g. ``"429"``).
        count (int): number of occurrences of this error/status combination.

    Returns:
        :class:`pandas.DataFrame` ordered by count descending.
    """
    sql = """
        SELECT
            error_message,
            status_code,
            COUNT(*) AS count
        FROM api_errors
        GROUP BY error_message, status_code
        ORDER BY count DESC
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("get_error_breakdown failed")
        raise

"""
Bulk-insert logic for loading parsed telemetry data into SQLite.

Load order respects FK constraints:
  1. employees  (no dependencies)
  2. sessions   (derived from events; references employees)
  3. api_requests, tool_events, api_errors  (reference sessions + employees)
"""

import logging
from pathlib import Path

import pandas as pd
from sqlalchemy.engine import Engine

from db.schema import (
    api_errors,
    api_requests,
    create_all_tables,
    employees,
    make_engine,
    sessions,
    tool_events,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "analytics.db"

# Chunk size for bulk inserts — keeps memory flat for large tables
INSERT_CHUNK_SIZE = 10_000

# Event type identifiers (mirrors parser constants)
EVT_API_REQUEST = "claude_code.api_request"
EVT_API_ERROR = "claude_code.api_error"
EVT_TOOL_DECISION = "claude_code.tool_decision"
EVT_TOOL_RESULT = "claude_code.tool_result"
EVT_USER_PROMPT = "claude_code.user_prompt"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _chunked_insert(
    engine: Engine,
    table,
    df: pd.DataFrame,
    table_name: str,
    on_conflict_ignore: bool = False,
) -> None:
    """
    Insert *df* into *table* in chunks.

    Args:
        engine: Active SQLAlchemy engine.
        table: SQLAlchemy Table object.
        df: DataFrame whose columns match the table columns.
        table_name: Human-readable label for log messages.
        on_conflict_ignore: If True, emit ``INSERT OR IGNORE`` so that rows
            whose primary key already exists are silently skipped rather than
            raising an :class:`~sqlalchemy.exc.IntegrityError`.  Use this for
            idempotent re-runs on tables with a natural PK (e.g. ``employees``).
    """
    total = len(df)
    inserted = 0

    stmt = table.insert()
    if on_conflict_ignore:
        stmt = stmt.prefix_with("OR IGNORE")

    with engine.begin() as conn:
        for start in range(0, total, INSERT_CHUNK_SIZE):
            chunk = df.iloc[start : start + INSERT_CHUNK_SIZE]
            conn.execute(stmt, chunk.to_dict(orient="records"))
            inserted += len(chunk)
            logger.debug("  [%s] inserted %d/%d rows", table_name, inserted, total)

    logger.info("[%s] inserted %d rows total", table_name, total)


def _safe_int(series: pd.Series) -> pd.Series:
    """Convert a float Series to nullable Int64, preserving NaN as pd.NA."""
    return series.astype("Int64")


# ---------------------------------------------------------------------------
# Per-table transform functions
# ---------------------------------------------------------------------------

def _build_employees(csv_path: Path) -> pd.DataFrame:
    """
    Load and normalise the employees CSV.

    Args:
        csv_path: Path to employees.csv.

    Returns:
        DataFrame with columns matching the ``employees`` table.

    Raises:
        FileNotFoundError: If the CSV does not exist.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"employees.csv not found at {csv_path}")

    df = pd.read_csv(csv_path, dtype=str)
    df.columns = df.columns.str.strip()

    # Rename to match schema columns
    column_map = {
        "email": "email",
        "full_name": "full_name",
        "practice": "practice",
        "level": "level",
        "location": "location",
    }
    df = df.rename(columns=column_map)[list(column_map.values())]
    df = df.drop_duplicates(subset=["email"])

    logger.info("[employees] prepared %d rows", len(df))
    return df


def _build_sessions(events_df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive one row per unique session from the combined events DataFrame.

    - started_at / ended_at   → min / max timestamp across all events for that session
    - total_turns             → count of user_prompt events (one per conversation turn)
    - total_cost_usd          → sum of cost_usd from api_request events

    Args:
        events_df: Full combined events DataFrame from the parser.

    Returns:
        DataFrame with columns matching the ``sessions`` table.
    """
    # started_at / ended_at from all events
    time_agg = (
        events_df.groupby("session_id")["timestamp"]
        .agg(started_at="min", ended_at="max")
        .reset_index()
    )

    # total_turns from user_prompt events
    prompts = events_df[events_df["event_type"] == EVT_USER_PROMPT]
    turn_counts = (
        prompts.groupby("session_id")
        .size()
        .rename("total_turns")
        .reset_index()
    )

    # total_cost_usd from api_request events
    api_reqs = events_df[events_df["event_type"] == EVT_API_REQUEST]
    cost_sums = (
        api_reqs.groupby("session_id")["cost_usd"]
        .sum()
        .rename("total_cost_usd")
        .reset_index()
    )

    # user_email: take the first non-null email per session
    email_map = (
        events_df.dropna(subset=["user_email"])
        .groupby("session_id")["user_email"]
        .first()
        .reset_index()
    )

    df = (
        time_agg
        .merge(email_map, on="session_id", how="left")
        .merge(turn_counts, on="session_id", how="left")
        .merge(cost_sums, on="session_id", how="left")
    )

    df["total_turns"] = _safe_int(df["total_turns"].fillna(0))
    df["total_cost_usd"] = df["total_cost_usd"].fillna(0.0)

    logger.info("[sessions] prepared %d rows", len(df))
    return df


def _build_api_requests(events_df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract and normalise api_request events.

    Args:
        events_df: Full combined events DataFrame from the parser.

    Returns:
        DataFrame with columns matching the ``api_requests`` table.
    """
    cols = [
        "session_id", "user_email", "timestamp",
        "model", "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_create_tokens",
        "cost_usd", "duration_ms",
    ]
    df = events_df[events_df["event_type"] == EVT_API_REQUEST][cols].copy()

    for col in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_create_tokens", "duration_ms"):
        df[col] = _safe_int(df[col])

    logger.info("[api_requests] prepared %d rows", len(df))
    return df


def _build_tool_events(events_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge tool_decision and tool_result events into a single tool_events table.

    tool_decision provides: tool_name, decision, decision_source
    tool_result   provides: tool_name, decision_source, success, duration_ms

    Rows from both event types are unioned; columns absent in each type are NaN.

    Args:
        events_df: Full combined events DataFrame from the parser.

    Returns:
        DataFrame with columns matching the ``tool_events`` table.
    """
    # Final column order for tool_events table
    final_cols = ["session_id", "user_email", "timestamp", "tool_name",
                  "decision", "decision_source", "duration_ms", "success"]

    shared_cols = ["session_id", "user_email", "timestamp", "tool_name", "decision_source"]

    decisions = events_df[events_df["event_type"] == EVT_TOOL_DECISION][shared_cols + ["decision"]].copy()
    decisions["duration_ms"] = pd.Series(pd.NA, index=decisions.index, dtype="Int64")
    decisions["success"] = pd.Series(pd.NA, index=decisions.index, dtype="Int64")
    decisions["decision"] = decisions["decision"].astype("string")

    results = events_df[events_df["event_type"] == EVT_TOOL_RESULT][shared_cols + ["duration_ms", "success"]].copy()
    results["decision"] = pd.Series(pd.NA, index=results.index, dtype="string")
    results["duration_ms"] = _safe_int(results["duration_ms"])
    results["success"] = _safe_int(results["success"])

    # Both frames now share identical dtypes — concat is warning-free
    df = pd.concat([decisions[final_cols], results[final_cols]], ignore_index=True)

    logger.info("[tool_events] prepared %d rows (%d decisions + %d results)",
                len(df), len(decisions), len(results))
    return df


def _build_api_errors(events_df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract and normalise api_error events.

    Args:
        events_df: Full combined events DataFrame from the parser.

    Returns:
        DataFrame with columns matching the ``api_errors`` table.
    """
    cols = ["session_id", "user_email", "timestamp", "model", "error_message", "status_code"]
    df = events_df[events_df["event_type"] == EVT_API_ERROR][cols].copy()

    logger.info("[api_errors] prepared %d rows", len(df))
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_all(
    events_df: pd.DataFrame,
    employees_csv: Path,
    db_path: Path = DB_PATH,
) -> Engine:
    """
    Full pipeline: create schema, transform DataFrames, bulk-insert everything.

    Load order respects FK constraints:
    employees → sessions → api_requests / tool_events / api_errors

    Args:
        events_df:     Combined events DataFrame from :func:`ingest.parser.parse_jsonl`.
        employees_csv: Path to the employees CSV file.
        db_path:       Path for the SQLite database file (created if absent).

    Returns:
        The :class:`~sqlalchemy.engine.Engine` pointing at *db_path*, so callers
        can run queries without creating a second connection.

    Raises:
        FileNotFoundError: If *employees_csv* does not exist.
        ValueError: If *events_df* is empty.
    """
    if events_df.empty:
        raise ValueError("events_df is empty — nothing to load")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(str(db_path))
    create_all_tables(engine)
    logger.info("Schema ready at %s", db_path)

    # Truncate autoincrement tables so re-runs don't accumulate duplicates.
    # employees and sessions use OR IGNORE instead — their natural PKs prevent
    # duplicates without losing existing rows that may not be in the current batch.
    with engine.begin() as conn:
        for tbl in (api_errors, tool_events, api_requests):
            conn.execute(tbl.delete())
    logger.info("Truncated api_requests, tool_events, api_errors")

    # 1. employees
    emp_df = _build_employees(employees_csv)
    _chunked_insert(engine, employees, emp_df, "employees", on_conflict_ignore=True)

    # 2. sessions (must exist before FK-dependent tables)
    sess_df = _build_sessions(events_df)
    _chunked_insert(engine, sessions, sess_df, "sessions", on_conflict_ignore=True)

    # 3. detail tables (order among these doesn't matter)
    _chunked_insert(engine, api_requests, _build_api_requests(events_df), "api_requests")
    _chunked_insert(engine, tool_events,  _build_tool_events(events_df),  "tool_events")
    _chunked_insert(engine, api_errors,   _build_api_errors(events_df),   "api_errors")

    logger.info("Load complete — database at %s", db_path)
    return engine

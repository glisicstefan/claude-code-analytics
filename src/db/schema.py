"""
SQLAlchemy table definitions for the Claude Code analytics database.

Five tables:
  - employees      : reference data loaded from employees.csv
  - sessions       : one row per unique session, derived from events
  - api_requests   : one row per claude_code.api_request event
  - tool_events    : one row per claude_code.tool_decision / tool_result event
  - api_errors     : one row per claude_code.api_error event
"""

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    event,
)
from sqlalchemy import DateTime as SADateTime
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

# Single shared metadata object — import this everywhere
metadata = MetaData()

# ---------------------------------------------------------------------------
# employees
# ---------------------------------------------------------------------------

employees = Table(
    "employees",
    metadata,
    Column("email", String, primary_key=True),
    Column("full_name", String, nullable=True),
    Column("practice", String, nullable=True),   # Platform/Data/ML/Backend/Frontend Engineering
    Column("level", String, nullable=True),       # L1–L10
    Column("location", String, nullable=True),
)

# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

sessions = Table(
    "sessions",
    metadata,
    Column("session_id", String, primary_key=True),
    Column("user_email", String, ForeignKey("employees.email"), nullable=True),
    Column("started_at", SADateTime(timezone=True), nullable=True),
    Column("ended_at", SADateTime(timezone=True), nullable=True),
    Column("total_turns", Integer, nullable=True),
    Column("total_cost_usd", Float, nullable=True),
    Index("ix_sessions_user_email", "user_email"),
    Index("ix_sessions_started_at", "started_at"),
)

# ---------------------------------------------------------------------------
# api_requests
# ---------------------------------------------------------------------------

api_requests = Table(
    "api_requests",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String, ForeignKey("sessions.session_id"), nullable=True),
    Column("user_email", String, ForeignKey("employees.email"), nullable=True),
    Column("timestamp", SADateTime(timezone=True), nullable=False),
    Column("model", String, nullable=True),
    Column("input_tokens", Integer, nullable=True),
    Column("output_tokens", Integer, nullable=True),
    Column("cache_read_tokens", Integer, nullable=True),
    Column("cache_create_tokens", Integer, nullable=True),
    Column("cost_usd", Float, nullable=True),
    Column("duration_ms", Integer, nullable=True),
    Index("ix_api_requests_session_id", "session_id"),
    Index("ix_api_requests_user_email", "user_email"),
    Index("ix_api_requests_timestamp", "timestamp"),
)

# ---------------------------------------------------------------------------
# tool_events  (covers both tool_decision and tool_result event types)
# ---------------------------------------------------------------------------

tool_events = Table(
    "tool_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String, ForeignKey("sessions.session_id"), nullable=True),
    Column("user_email", String, ForeignKey("employees.email"), nullable=True),
    Column("timestamp", SADateTime(timezone=True), nullable=False),
    Column("tool_name", String, nullable=True),
    Column("decision", String, nullable=True),    # accept / reject / NULL for tool_result
    Column("decision_source", String, nullable=True),
    Column("duration_ms", Integer, nullable=True),
    Column("success", Integer, nullable=True),    # 0 or 1; NULL for tool_decision rows
    Index("ix_tool_events_session_id", "session_id"),
    Index("ix_tool_events_user_email", "user_email"),
    Index("ix_tool_events_tool_name", "tool_name"),
)

# ---------------------------------------------------------------------------
# api_errors
# ---------------------------------------------------------------------------

api_errors = Table(
    "api_errors",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String, ForeignKey("sessions.session_id"), nullable=True),
    Column("user_email", String, ForeignKey("employees.email"), nullable=True),
    Column("timestamp", SADateTime(timezone=True), nullable=False),
    Column("model", String, nullable=True),
    Column("error_message", Text, nullable=True),
    Column("status_code", String, nullable=True),
    Index("ix_api_errors_session_id", "session_id"),
    Index("ix_api_errors_user_email", "user_email"),
    Index("ix_api_errors_timestamp", "timestamp"),
)


# ---------------------------------------------------------------------------
# Engine factory & WAL pragma
# ---------------------------------------------------------------------------

def make_engine(db_path: str) -> Engine:
    """
    Create a SQLite engine for *db_path* and enable WAL mode for
    better concurrent read performance.

    Args:
        db_path: Absolute path to the SQLite file, e.g. ``"/data/analytics.db"``.

    Returns:
        A configured :class:`sqlalchemy.engine.Engine`.
    """
    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    @event.listens_for(engine, "connect")
    def _set_wal(dbapi_conn, _connection_record) -> None:  # type: ignore[type-arg]
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def create_all_tables(engine: Engine) -> None:
    """
    Create all tables in the database if they do not already exist.

    Args:
        engine: SQLAlchemy engine returned by :func:`make_engine`.
    """
    metadata.create_all(engine)

"""
JSONL telemetry parser for Claude Code analytics.

Parses triple-nested log structure:
  JSONL line -> batch -> logEvents[] -> message (JSON string) -> {body, attributes, ...}

Produces one flat pandas DataFrame per event type, with normalized column names.
"""

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Common attributes present in every event type
COMMON_ATTRS = [
    "event.timestamp",
    "session.id",
    "user.email",
    "organization.id",
    "terminal.type",
]

# Per-event-type attribute maps: attribute_key -> normalized_column_name
_API_REQUEST_ATTRS: dict[str, str] = {
    "model": "model",
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_creation_tokens": "cache_create_tokens",
    "cache_read_tokens": "cache_read_tokens",
    "cost_usd": "cost_usd",
    "duration_ms": "duration_ms",
}

_API_ERROR_ATTRS: dict[str, str] = {
    "model": "model",
    "error": "error_message",
    "status_code": "status_code",
    "duration_ms": "duration_ms",
    "attempt": "attempt",
}

_TOOL_DECISION_ATTRS: dict[str, str] = {
    "tool_name": "tool_name",
    "decision": "decision",
    "source": "decision_source",
}

_TOOL_RESULT_ATTRS: dict[str, str] = {
    "tool_name": "tool_name",
    "decision_type": "decision",
    "decision_source": "decision_source",
    "success": "success",
    "duration_ms": "duration_ms",
    "tool_result_size_bytes": "tool_result_size_bytes",
}

_USER_PROMPT_ATTRS: dict[str, str] = {
    "prompt_length": "prompt_length",
}

EVENT_ATTR_MAP: dict[str, dict[str, str]] = {
    "claude_code.api_request": _API_REQUEST_ATTRS,
    "claude_code.api_error": _API_ERROR_ATTRS,
    "claude_code.tool_decision": _TOOL_DECISION_ATTRS,
    "claude_code.tool_result": _TOOL_RESULT_ATTRS,
    "claude_code.user_prompt": _USER_PROMPT_ATTRS,
}

# Numeric columns that need type coercion after parsing
NUMERIC_COLUMNS = {
    "input_tokens", "output_tokens", "cache_create_tokens", "cache_read_tokens",
    "duration_ms", "cost_usd", "prompt_length", "attempt",
    "tool_result_size_bytes",
}

# Boolean-string columns: "true"/"false" -> 1/0
BOOLEAN_STRING_COLUMNS = {"success"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_common(attrs: dict) -> dict:
    """Extract fields that are present in every event type."""
    return {
        "event_type": None,          # filled by caller
        "timestamp": attrs.get("event.timestamp"),
        "session_id": attrs.get("session.id"),
        "user_email": attrs.get("user.email"),
        "organization_id": attrs.get("organization.id"),
        "terminal_type": attrs.get("terminal.type"),
    }


def _parse_message(raw_message: str) -> dict | None:
    """
    Parse a single logEvent.message JSON string into a flat record dict.
    Returns None if the message cannot be parsed or has an unknown body.
    """
    try:
        msg = json.loads(raw_message)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse logEvent message as JSON: %s", exc)
        return None

    body: str = msg.get("body", "")
    attrs: dict = msg.get("attributes", {})
    resource: dict = msg.get("resource", {})

    extra_attr_map = EVENT_ATTR_MAP.get(body)
    if extra_attr_map is None:
        logger.debug("Unknown event body '%s' — skipping", body)
        return None

    record = _extract_common(attrs)
    record["event_type"] = body

    # Event-specific attributes
    for src_key, dst_col in extra_attr_map.items():
        record[dst_col] = attrs.get(src_key)

    # Resource fields (OS / version metadata)
    record["os_type"] = resource.get("os.type")
    record["os_version"] = resource.get("os.version")
    record["service_version"] = resource.get("service.version")

    return record


def _coerce_numerics(df: pd.DataFrame) -> pd.DataFrame:
    """Cast numeric-ish columns from string to the appropriate numeric dtype."""
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_jsonl(path: Path) -> pd.DataFrame:
    """
    Parse a JSONL telemetry file and return a flat DataFrame of all events.

    Each row corresponds to one telemetry event. Columns that are not
    applicable to a given event type are filled with NaN.

    Args:
        path: Absolute path to the .jsonl file.

    Returns:
        A pandas DataFrame with one row per event.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is empty or no valid events were found.
    """
    if not path.exists():
        raise FileNotFoundError(f"Telemetry file not found: {path}")

    records: list[dict] = []
    total_lines = 0
    skipped_lines = 0

    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            total_lines += 1

            try:
                batch = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                logger.warning("Line %d: failed to parse batch JSON: %s", line_no, exc)
                skipped_lines += 1
                continue

            log_events: list[dict] = batch.get("logEvents", [])

            for event in log_events:
                raw_msg = event.get("message", "")
                record = _parse_message(raw_msg)
                if record is not None:
                    records.append(record)

    logger.info(
        "Parsed %d JSONL lines (%d skipped), extracted %d events",
        total_lines,
        skipped_lines,
        len(records),
    )

    if not records:
        raise ValueError(f"No valid events found in {path}")

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = _coerce_numerics(df)

    # Normalise boolean-string columns ("true"/"false") to Int64 (1/0/NaN)
    for col in BOOLEAN_STRING_COLUMNS:
        if col in df.columns:
            df[col] = (
                df[col]
                .map({"true": 1, "false": 0, True: 1, False: 0})
                .astype("Int64")
            )

    logger.info("DataFrame shape: %s  |  event types: %s", df.shape, df["event_type"].value_counts().to_dict())
    return df


def split_by_event_type(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Split the combined DataFrame into one sub-DataFrame per event type,
    dropping columns that are entirely NaN for that subset.

    Args:
        df: Full DataFrame produced by :func:`parse_jsonl`.

    Returns:
        Dict mapping event-type string (e.g. ``"claude_code.api_request"``)
        to a cleaned DataFrame.
    """
    result: dict[str, pd.DataFrame] = {}
    for event_type, group in df.groupby("event_type"):
        result[str(event_type)] = group.dropna(axis=1, how="all").reset_index(drop=True)
    return result

"""
Data validation and quality checks for parsed telemetry DataFrames.

Validates that critical fields are present and logs warnings for any
rows that fail the checks. Does NOT drop rows — callers decide what
to do with the quality report.
"""

import logging
from dataclasses import dataclass, field

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — critical fields per event type
# ---------------------------------------------------------------------------

CRITICAL_FIELDS_BY_EVENT: dict[str, list[str]] = {
    "claude_code.api_request": [
        "timestamp", "session_id", "user_email",
        "model", "input_tokens", "output_tokens", "cost_usd",
    ],
    "claude_code.api_error": [
        "timestamp", "session_id", "user_email",
        "model", "error_message",
    ],
    "claude_code.tool_decision": [
        "timestamp", "session_id", "user_email",
        "tool_name", "decision",
    ],
    "claude_code.tool_result": [
        "timestamp", "session_id", "user_email",
        "tool_name", "success",
    ],
    "claude_code.user_prompt": [
        "timestamp", "session_id", "user_email",
    ],
}

# Fields that must be critical across ALL event types (regardless of type)
UNIVERSAL_CRITICAL_FIELDS: list[str] = ["event_type", "timestamp", "session_id", "user_email"]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class FieldQualityReport:
    """Null-count summary for a single field."""
    field: str
    null_count: int
    total_count: int

    @property
    def null_rate(self) -> float:
        """Fraction of rows where this field is null."""
        return self.null_count / self.total_count if self.total_count else 0.0

    def __str__(self) -> str:
        return (
            f"{self.field}: {self.null_count}/{self.total_count} null "
            f"({self.null_rate:.1%})"
        )


@dataclass
class ValidationReport:
    """Aggregated validation results for a DataFrame or event-type subset."""
    event_type: str
    total_rows: int
    issues: list[FieldQualityReport] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    @property
    def rows_with_any_null(self) -> int:
        """Number of rows that have at least one null in a critical field."""
        return sum(r.null_count for r in self.issues)

    def __str__(self) -> str:
        if not self.has_issues:
            return f"[{self.event_type}] OK — {self.total_rows} rows, no critical nulls"
        lines = [f"[{self.event_type}] {self.total_rows} rows — {len(self.issues)} field(s) with nulls:"]
        for issue in self.issues:
            lines.append(f"  • {issue}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

def _check_fields(df: pd.DataFrame, fields: list[str], event_type: str) -> ValidationReport:
    """
    Check each field in *fields* for null values in *df*.

    Args:
        df: DataFrame to inspect (may be a subset for one event type).
        fields: Column names to validate.
        event_type: Label used in the report.

    Returns:
        A :class:`ValidationReport` summarising any issues found.
    """
    total = len(df)
    report = ValidationReport(event_type=event_type, total_rows=total)

    for col in fields:
        if col not in df.columns:
            # Column entirely absent — treat every row as null
            fqr = FieldQualityReport(field=col, null_count=total, total_count=total)
            report.issues.append(fqr)
            logger.warning(
                "[%s] Critical column '%s' is MISSING from DataFrame", event_type, col
            )
            continue

        null_count = int(df[col].isna().sum())
        if null_count > 0:
            fqr = FieldQualityReport(field=col, null_count=null_count, total_count=total)
            report.issues.append(fqr)
            logger.warning(
                "[%s] Critical field '%s' has %d/%d null values (%.1f%%)",
                event_type,
                col,
                null_count,
                total,
                fqr.null_rate * 100,
            )

    return report


def validate_universal(df: pd.DataFrame) -> ValidationReport:
    """
    Validate fields that must be non-null for every row regardless of event type.

    Args:
        df: Full combined DataFrame from the parser.

    Returns:
        A :class:`ValidationReport` for the whole DataFrame.
    """
    report = _check_fields(df, UNIVERSAL_CRITICAL_FIELDS, event_type="ALL")
    if not report.has_issues:
        logger.info("Universal validation passed — %d rows, no critical nulls", len(df))
    return report


def validate_by_event_type(df: pd.DataFrame) -> dict[str, ValidationReport]:
    """
    Validate each event-type subset against its own set of critical fields.

    Args:
        df: Full combined DataFrame from the parser.

    Returns:
        Dict mapping event-type string to its :class:`ValidationReport`.
    """
    reports: dict[str, ValidationReport] = {}

    for event_type, critical_fields in CRITICAL_FIELDS_BY_EVENT.items():
        subset = df[df["event_type"] == event_type]

        if subset.empty:
            logger.warning("No rows found for event type '%s'", event_type)
            reports[event_type] = ValidationReport(
                event_type=event_type, total_rows=0
            )
            continue

        report = _check_fields(subset, critical_fields, event_type)
        reports[event_type] = report

    return reports


def validate(df: pd.DataFrame) -> tuple[ValidationReport, dict[str, ValidationReport]]:
    """
    Run all validation checks and return a summary.

    Logs a WARNING for each quality issue found and an INFO summary at the end.

    Args:
        df: Full combined DataFrame from the parser.

    Returns:
        A tuple of:
        - universal_report: cross-event validation results
        - per_type_reports: dict[event_type, ValidationReport]
    """
    logger.info("Starting validation on DataFrame with %d rows", len(df))

    universal = validate_universal(df)
    per_type = validate_by_event_type(df)

    total_issues = sum(len(r.issues) for r in per_type.values()) + len(universal.issues)

    if total_issues == 0:
        logger.info("Validation complete — no issues found")
    else:
        logger.warning("Validation complete — %d issue(s) found across all checks", total_issues)
        for report in [universal, *per_type.values()]:
            if report.has_issues:
                logger.warning(str(report))

    return universal, per_type

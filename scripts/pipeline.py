"""
Full ingestion pipeline: generate (optional) → parse → validate → load.

Usage:
    python scripts/pipeline.py                   # uses default paths
    python scripts/pipeline.py --db data/custom.db
    python scripts/pipeline.py --skip-validation

Exit codes:
    0  success
    1  validation found critical issues (--fail-on-validation-error)
    2  unrecoverable error (file not found, parse failure, DB error)
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — allow running as  python scripts/pipeline.py  from the
# project root without installing the package.
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ingest.parser import parse_jsonl
from ingest.validator import validate
from db.loader import load_all
from db.schema import make_engine

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

DEFAULT_JSONL = PROJECT_ROOT / "data" / "output" / "telemetry_logs.jsonl"
DEFAULT_EMPLOYEES = PROJECT_ROOT / "data" / "output" / "employees.csv"
DEFAULT_DB = PROJECT_ROOT / "data" / "analytics.db"

TABLES = ("employees", "sessions", "api_requests", "tool_events", "api_errors")

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _configure_logging(verbose: bool) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Silence noisy SQLAlchemy engine logs unless verbose
    if not verbose:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    return logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def _step(log: logging.Logger, name: str):
    """Context manager that logs step start/end and elapsed time."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        log.info("━━━  %s  ━━━", name)
        t0 = time.perf_counter()
        yield
        elapsed = time.perf_counter() - t0
        log.info("✓  %s  (%.1fs)", name, elapsed)

    return _ctx()


def _row_counts(db_path: Path, log: logging.Logger) -> None:
    """Query and log row counts for all five tables."""
    from sqlalchemy import text

    engine = make_engine(str(db_path))
    log.info("Row counts in %s:", db_path.name)
    with engine.connect() as conn:
        for table in TABLES:
            n = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            log.info("  %-20s %s rows", table, f"{n:,}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(
    jsonl_path: Path,
    employees_path: Path,
    db_path: Path,
    skip_validation: bool,
    fail_on_validation_error: bool,
    log: logging.Logger,
) -> int:
    """
    Execute all pipeline stages and return an exit code.

    Args:
        jsonl_path:                Path to telemetry_logs.jsonl.
        employees_path:            Path to employees.csv.
        db_path:                   Destination SQLite file.
        skip_validation:           If True, skip the validation stage entirely.
        fail_on_validation_error:  If True, return exit code 1 when validation
                                   finds critical nulls.
        log:                       Logger for pipeline-level messages.

    Returns:
        Integer exit code (0 = success, 1 = validation issues, 2 = error).
    """
    total_start = time.perf_counter()

    # ------------------------------------------------------------------
    # 1. Parse
    # ------------------------------------------------------------------
    try:
        with _step(log, "PARSE"):
            events_df = parse_jsonl(jsonl_path)
            log.info(
                "Parsed %s events across %d sessions",
                f"{len(events_df):,}",
                events_df["session_id"].nunique(),
            )
            log.info(
                "Event type breakdown:\n%s",
                events_df["event_type"]
                .value_counts()
                .rename("count")
                .to_string(),
            )
    except FileNotFoundError as exc:
        log.error("Parse failed — file not found: %s", exc)
        return 2
    except ValueError as exc:
        log.error("Parse failed — %s", exc)
        return 2

    # ------------------------------------------------------------------
    # 2. Validate
    # ------------------------------------------------------------------
    if skip_validation:
        log.info("Validation skipped (--skip-validation)")
    else:
        with _step(log, "VALIDATE"):
            universal, per_type = validate(events_df)

        total_issues = (
            len(universal.issues)
            + sum(len(r.issues) for r in per_type.values())
        )
        if total_issues == 0:
            log.info("Validation passed — no critical nulls found")
        else:
            log.warning("Validation found %d issue(s)", total_issues)
            if fail_on_validation_error:
                log.error("Aborting due to --fail-on-validation-error")
                return 1

    # ------------------------------------------------------------------
    # 3. Load
    # ------------------------------------------------------------------
    try:
        with _step(log, "LOAD"):
            load_all(
                events_df=events_df,
                employees_csv=employees_path,
                db_path=db_path,
            )
    except FileNotFoundError as exc:
        log.error("Load failed — file not found: %s", exc)
        return 2
    except Exception as exc:
        log.error("Load failed — unexpected error: %s", exc, exc_info=True)
        return 2

    # ------------------------------------------------------------------
    # 4. Summary
    # ------------------------------------------------------------------
    _row_counts(db_path, log)

    total_elapsed = time.perf_counter() - total_start
    log.info("Pipeline complete in %.1fs  →  %s", total_elapsed, db_path)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Claude Code analytics ingestion pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--jsonl",
        type=Path,
        default=DEFAULT_JSONL,
        metavar="PATH",
        help="Path to telemetry_logs.jsonl",
    )
    p.add_argument(
        "--employees",
        type=Path,
        default=DEFAULT_EMPLOYEES,
        metavar="PATH",
        help="Path to employees.csv",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        metavar="PATH",
        help="Destination SQLite database file",
    )
    p.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip the data validation stage",
    )
    p.add_argument(
        "--fail-on-validation-error",
        action="store_true",
        help="Exit with code 1 if validation finds critical nulls",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()
    log = _configure_logging(args.verbose)

    log.info("Claude Code Analytics — ingestion pipeline")
    log.info("  JSONL      : %s", args.jsonl)
    log.info("  Employees  : %s", args.employees)
    log.info("  Database   : %s", args.db)

    sys.exit(
        run(
            jsonl_path=args.jsonl,
            employees_path=args.employees,
            db_path=args.db,
            skip_validation=args.skip_validation,
            fail_on_validation_error=args.fail_on_validation_error,
            log=log,
        )
    )


if __name__ == "__main__":
    main()

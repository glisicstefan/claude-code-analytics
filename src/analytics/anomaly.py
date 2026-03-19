"""
Anomaly detection for Claude Code Analytics.

Uses scikit-learn's Isolation Forest to identify users whose behaviour
deviates significantly from the rest of the population.  Five per-user
features are extracted from the database, scaled with StandardScaler, and
fed to the model.  The public function :func:`detect_user_anomalies` returns
a :class:`pandas.DataFrame` with all users, their features, and anomaly
labels/scores.
"""

import logging

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from src.analytics.queries import _query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTAMINATION: float = 0.05  # expected fraction of anomalous users

FEATURE_COLS: list[str] = [
    "total_cost_usd",
    "total_tokens",
    "avg_session_duration_min",
    "error_rate",
    "total_sessions",
]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_user_features() -> pd.DataFrame:
    """Fetch per-user aggregated features from the database.

    Executes a single SQL query that LEFT JOINs api_requests, sessions, and
    api_errors so every user appears even if they have no errors.

    Returns:
        DataFrame with columns: user_email, total_cost_usd, total_tokens,
        avg_session_duration_min, error_rate, total_sessions.
    """
    sql = """
        SELECT
            ar.user_email                                                   AS user_email,
            ROUND(SUM(ar.cost_usd), 4)                                      AS total_cost_usd,
            SUM(
                COALESCE(ar.input_tokens, 0)
                + COALESCE(ar.output_tokens, 0)
                + COALESCE(ar.cache_read_tokens, 0)
                + COALESCE(ar.cache_create_tokens, 0)
            )                                                               AS total_tokens,
            AVG(
                (julianday(s.ended_at) - julianday(s.started_at)) * 1440.0
            )                                                               AS avg_session_duration_min,
            CAST(COUNT(DISTINCT ae.id) AS REAL)
                / NULLIF(COUNT(ar.id), 0)                                   AS error_rate,
            COUNT(DISTINCT ar.session_id)                                   AS total_sessions
        FROM api_requests ar
        LEFT JOIN sessions s
            ON ar.session_id = s.session_id
        LEFT JOIN api_errors ae
            ON ar.user_email = ae.user_email
        GROUP BY ar.user_email
    """
    try:
        return _query(sql)
    except Exception:
        logger.exception("_get_user_features failed")
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_user_anomalies() -> pd.DataFrame:
    """Detect anomalous users using Isolation Forest.

    Fetches per-user aggregated features from the database, scales them with
    StandardScaler, and fits an IsolationForest with contamination=5 %.

    Returns:
        DataFrame sorted by anomaly_score descending with columns:

        - user_email (str): user identifier.
        - total_cost_usd (float): total spend across all API requests.
        - total_tokens (int): total tokens consumed (input + output + cache).
        - avg_session_duration_min (float): average session length in minutes.
        - error_rate (float): API errors divided by API requests (0–1).
        - total_sessions (int): distinct session count.
        - is_anomaly (bool): True when Isolation Forest labels the user as an outlier.
        - anomaly_score (float): higher values indicate stronger anomaly signal.

    Raises:
        Exception: re-raises any database or sklearn error after logging it.
    """
    try:
        df = _get_user_features()

        if df.empty:
            logger.warning("detect_user_anomalies: no user data found — returning empty DataFrame")
            for col in [*FEATURE_COLS, "is_anomaly", "anomaly_score"]:
                df[col] = pd.Series(dtype=float)
            return df

        feature_matrix = df[FEATURE_COLS].copy()
        feature_matrix = feature_matrix.fillna(0.0)

        scaler = StandardScaler()
        scaled: np.ndarray = scaler.fit_transform(feature_matrix)

        model = IsolationForest(contamination=CONTAMINATION, random_state=42)
        predictions: np.ndarray = model.fit_predict(scaled)

        df["is_anomaly"] = predictions == -1
        df["anomaly_score"] = -model.score_samples(scaled)

        return df.sort_values("anomaly_score", ascending=False).reset_index(drop=True)

    except Exception:
        logger.exception("detect_user_anomalies failed")
        raise

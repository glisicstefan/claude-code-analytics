"""Anomaly Detection dashboard component — placeholder.

A full implementation using Isolation Forest will surface unusual token/cost
spikes per user or session. See :mod:`src.analytics.anomaly` for the planned
model layer.
"""

import logging
from typing import Any, Dict

import streamlit as st

logger = logging.getLogger(__name__)


def render(filters: Dict[str, Any]) -> None:
    """Render the Anomaly Detection placeholder page.

    Args:
        filters: Global filter dict from the sidebar (unused at this stage).
    """
    st.header("Anomaly Detection")
    st.info(
        "Coming soon — Isolation Forest model will surface unusual token/cost spikes "
        "per user or session."
    )

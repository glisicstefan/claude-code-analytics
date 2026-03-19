"""FastAPI application exposing Claude Code Analytics metrics via REST endpoints."""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from src.analytics.anomaly import detect_user_anomalies
from src.analytics.queries import (
    get_cost_per_user,
    get_error_breakdown,
    get_overview_stats,
    get_tokens_by_level,
    get_tokens_by_practice,
    get_tool_success_rates,
)

app = FastAPI(title="Claude Code Analytics API", version="1.0.0")
logger = logging.getLogger(__name__)


@app.get("/health")
async def health() -> JSONResponse:
    """Health check endpoint. Returns 200 with status ok when the service is running."""
    return JSONResponse(content={"status": "ok"})


@app.get("/overview")
async def overview() -> JSONResponse:
    """Return top-level platform stats: total sessions, cost, tokens, and active users."""
    try:
        df = get_overview_stats()
        return JSONResponse(content=df.to_dict(orient="records")[0])
    except Exception as exc:
        logger.exception("Failed to fetch overview stats")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/users/top-cost")
async def top_cost_users() -> JSONResponse:
    """Return the top 10 users ranked by total cost in USD."""
    try:
        df = get_cost_per_user()
        return JSONResponse(content=df.to_dict(orient="records"))
    except Exception as exc:
        logger.exception("Failed to fetch top-cost users")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/tokens/by-practice")
async def tokens_by_practice() -> JSONResponse:
    """Return token consumption aggregated by engineering practice (ML, Backend, etc.)."""
    try:
        df = get_tokens_by_practice()
        return JSONResponse(content=df.to_dict(orient="records"))
    except Exception as exc:
        logger.exception("Failed to fetch tokens by practice")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/tokens/by-level")
async def tokens_by_level() -> JSONResponse:
    """Return token consumption aggregated by seniority level (L1–L10)."""
    try:
        df = get_tokens_by_level()
        return JSONResponse(content=df.to_dict(orient="records"))
    except Exception as exc:
        logger.exception("Failed to fetch tokens by level")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/tools/success-rates")
async def tool_success_rates() -> JSONResponse:
    """Return success rates per tool (e.g. Bash, Read, Edit) across all sessions."""
    try:
        df = get_tool_success_rates()
        return JSONResponse(content=df.to_dict(orient="records"))
    except Exception as exc:
        logger.exception("Failed to fetch tool success rates")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/errors/breakdown")
async def error_breakdown() -> JSONResponse:
    """Return error counts grouped by error message and HTTP status code."""
    try:
        df = get_error_breakdown()
        return JSONResponse(content=df.to_dict(orient="records"))
    except Exception as exc:
        logger.exception("Failed to fetch error breakdown")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/anomalies")
async def anomalies() -> JSONResponse:
    """Return users flagged as anomalies by the Isolation Forest model.

    Only users where is_anomaly is True are included, sorted by anomaly_score descending.
    """
    try:
        df = detect_user_anomalies()
        flagged = df[df["is_anomaly"]].to_dict(orient="records")
        return JSONResponse(content=flagged)
    except Exception as exc:
        logger.exception("Failed to run anomaly detection")
        raise HTTPException(status_code=500, detail=str(exc))

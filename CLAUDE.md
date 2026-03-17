# CLAUDE.md — Claude Code Analytics Platform

## Project Overview

This is an **end-to-end analytics platform** that ingests synthetic Claude Code telemetry data,
stores it in a structured database, and surfaces insights through an interactive Streamlit dashboard.

**Internship assignment for Provectus.** Quality, clean architecture, and professional patterns matter.

---

## Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | Type hints everywhere |
| Database | SQLite (via SQLAlchemy) | Simple, no infra needed |
| Dashboard | Streamlit | Fast, clean, stakeholder-friendly |
| Data processing | pandas + duckdb | DuckDB for fast JSONL querying |
| Visualization | Plotly (via st.plotly_chart) | Interactive charts |
| API (bonus) | FastAPI | Optional endpoints layer |
| Anomaly detection (bonus) | scikit-learn | Isolation Forest |

---

## Project Structure

```
claude-code-analytics/
├── CLAUDE.md                  # This file
├── README.md                  # Setup & architecture docs
├── requirements.txt
├── .gitignore
│
├── data/
│   ├── generate_fake_data.py  # Provided data generator
│   └── output/                # Generated data (gitignored)
│       ├── telemetry_logs.jsonl
│       └── employees.csv
│
├── src/
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── parser.py          # JSONL parsing & flattening
│   │   └── validator.py       # Data validation & quality checks
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.py          # SQLAlchemy table definitions
│   │   └── loader.py          # Bulk insert logic
│   │
│   ├── analytics/
│   │   ├── __init__.py
│   │   ├── queries.py         # All analytical SQL queries
│   │   └── anomaly.py         # Isolation Forest anomaly detection (bonus)
│   │
│   └── dashboard/
│       ├── __init__.py
│       ├── app.py             # Streamlit entry point
│       └── components/        # One file per dashboard section
│           ├── overview.py
│           ├── token_usage.py
│           ├── tool_analysis.py
│           ├── cost_analysis.py
│           └── anomalies.py
│
├── api/                       # Bonus FastAPI layer
│   ├── __init__.py
│   └── main.py
│
├── scripts/
│   └── pipeline.py            # One-shot: generate → ingest → load
│
└── tests/
    ├── test_parser.py
    └── test_queries.py
```

---

## Database Schema

Four main tables — keep it normalized, not a flat blob.

### `employees`
```sql
email TEXT PRIMARY KEY,
full_name TEXT,
practice TEXT,       -- Platform/Data/ML/Backend/Frontend Engineering
level TEXT,          -- L1–L10
location TEXT
```

### `sessions`
Derived from events — one row per unique session_id.
```sql
session_id TEXT PRIMARY KEY,
user_email TEXT REFERENCES employees(email),
started_at TIMESTAMP,
ended_at TIMESTAMP,
total_turns INTEGER,
total_cost_usd REAL
```

### `api_requests`
One row per `claude_code.api_request` event.
```sql
id INTEGER PRIMARY KEY,
session_id TEXT,
user_email TEXT,
timestamp TIMESTAMP,
model TEXT,
input_tokens INTEGER,
output_tokens INTEGER,
cache_read_tokens INTEGER,
cache_create_tokens INTEGER,
cost_usd REAL,
duration_ms INTEGER
```

### `tool_events`
One row per `claude_code.tool_decision` event.
```sql
id INTEGER PRIMARY KEY,
session_id TEXT,
user_email TEXT,
timestamp TIMESTAMP,
tool_name TEXT,
decision TEXT,        -- accept / reject
duration_ms INTEGER,
success INTEGER       -- 0 or 1
```

### `api_errors`
One row per `claude_code.api_error` event.
```sql
id INTEGER PRIMARY KEY,
session_id TEXT,
user_email TEXT,
timestamp TIMESTAMP,
model TEXT,
error_message TEXT,
status_code TEXT
```

---

## Parsing Logic

The JSONL structure is **triple-nested** — handle carefully:

```
JSONL line
  └─ batch (JSON object)
       └─ logEvents[]
            └─ message (JSON string — parse again!)
                 └─ { body, attributes, scope, resource }
```

Key fields to extract from `attributes`:
- `event.timestamp` → ISO string, convert to datetime
- `session_id`, `user_email`
- Model/token/cost fields (api_request)
- `tool_name`, `decision`, `success` (tool events)

Key fields from `resource`:
- `os.type`, `terminal`, version info

---

## Analytics — Key Metrics to Surface

### Overview
- Total sessions, total cost, total tokens, active users
- Daily activity trend (sessions + cost over time)

### Token & Cost Analysis
- Token consumption by **practice** (ML/Backend/etc.)
- Token consumption by **seniority level** (L1–L10)
- Cost per user (top 10 most expensive users)
- Model usage distribution (Haiku vs Sonnet vs Opus)
- Cache hit rate (cache_read / total input) — important metric!

### Usage Patterns
- Peak usage hours (heatmap: hour × day-of-week)
- Sessions per user distribution (power users vs casual)
- Average session length (turns, duration)

### Tool Analysis
- Tool usage frequency (bar chart)
- Tool success rates (Bash fails more than Read — show this)
- Tool decision breakdown: config vs user_temporary vs user_reject

### Errors
- Error rate over time
- Error breakdown by type and status code
- Users/models with highest error rates

---

## Code Style Rules

- **Type hints on all functions** — no bare `def foo(x):`
- **Docstrings** on every module and public function
- **No hardcoded paths** — use `pathlib.Path` and config constants
- **Error handling** — wrap DB operations and file I/O in try/except with meaningful messages
- **No magic numbers** — named constants at top of file
- **pandas** for data manipulation in analytics layer, not raw Python loops
- **f-strings** only, no `.format()` or `%`

---

## Streamlit Dashboard Guidelines

- Use `st.set_page_config(layout="wide")`
- Sidebar for global filters: date range, practice, level, location
- Each page = one component file in `dashboard/components/`
- Use `@st.cache_data` on all DB query functions
- Plotly charts only — no matplotlib (interactive > static)
- Dark theme preferred: `plotly.graph_objects` with `template="plotly_dark"`
- Always show the count (n=X) on charts so context is clear

---

## What NOT to Do

- Do not put all logic in `app.py` — use the component structure
- Do not query the DB inside Streamlit render functions — query in `analytics/queries.py`
- Do not commit the generated data files (`output/` is gitignored)
- Do not use `print()` for logging — use Python `logging` module
- Do not use `SELECT *` in queries — always name columns explicitly
- Do not ignore NULL / missing values silently — validate in `validator.py`

---

## LLM Usage Log

Track all significant AI assistance here for the deliverable.

| # | Tool | Task | Prompt summary | Validation method |
|---|---|---|---|---|
| 1 | Claude Code | ... | ... | ... |

---

## Current Status

- [ ] Data generated
- [ ] Parser implemented
- [ ] DB schema created and loaded
- [ ] Analytics queries written
- [ ] Dashboard running locally
- [ ] README complete
- [ ] Anomaly detection (bonus)
- [ ] FastAPI endpoints (bonus)
- [ ] Presentation slides

# Database Index Advisor

Database Index Advisor is a workload-aware index recommendation platform for PostgreSQL.

It connects to a PostgreSQL database, reads real query activity from `pg_stat_statements`, analyzes expensive queries, generates index candidates, validates them with `HypoPG`, and presents actionable recommendations through a web dashboard.

The goal is simple:

> Help DBAs and developers find the indexes that actually matter based on real workload evidence, not guesses.

---

## Project Layout

The project is now engine-ready instead of PostgreSQL-package-only:

```text
backend/
  index_advisor/
    api/                  # FastAPI app and routers
    storage/              # Product storage DB schema, migrations, settings, retention
    targets/
      base.py             # Common database-engine adapter contract
      registry.py         # Engine registry and UI metadata
      postgres/           # PostgreSQL collector/analyzer implementation
    utils/
frontend/                 # React/Vite UI for development; built into backend/index_advisor/web for packaging
backend/index_advisor/web # Production React build served by FastAPI after npm run build
config/                   # Optional development runtime config when INDEX_ADVISOR_CONFIG_DIR=./config
main.py                   # Convenience CLI wrapper that loads backend/
run_app.py                # Production/local launcher for packaged client installs
packaging/                # Build helpers for React build + PyInstaller packaging
```

PostgreSQL is the only available engine in this version. MSSQL and Oracle are represented in the registry and setup UI as `coming_soon`, so adding them later is a new adapter/target implementation instead of another product rewrite.

## Table of Contents

- [What It Does](#what-it-does)
- [Why It Is Special](#why-it-is-special)
- [Architecture](#architecture)
- [Main Components](#main-components)
- [Storage Database Architecture](#storage-database-architecture)
- [Requirements](#requirements)
- [Required PostgreSQL Extensions](#required-postgresql-extensions)
- [How to Run the Backend](#how-to-run-the-backend)
- [How to Run the Frontend](#how-to-run-the-frontend)
- [Packaging and End-User Mode](#packaging-and-end-user-mode)
- [How to Add a Database Target](#how-to-add-a-database-target)
- [How Recommendations Work](#how-recommendations-work)
- [Current Recommendations](#current-recommendations)
- [Recommendation History](#recommendation-history)
- [Applying Recommendations](#applying-recommendations)
- [Recommended Workflow](#recommended-workflow)
- [Troubleshooting](#troubleshooting)
- [Future Roadmap](#future-roadmap)

---

## What It Does

Database Index Advisor analyzes a PostgreSQL workload and recommends indexes that can improve query performance.

It collects real workload statistics from `pg_stat_statements`, parses expensive queries, generates possible indexes, checks existing indexes, validates candidates with hypothetical indexes, and shows the best recommendations in a dashboard.

The product helps answer questions like:

- Which queries are expensive?
- Which tables are being scanned heavily?
- Which index would help this query?
- Is a composite index better than a single-column index?
- Does an index already exist that solves the problem?
- What improvement does the optimizer estimate with the index?
- Which recommendations are still current?
- Which recommendations were already resolved historically?

---

## Why It Is Special

Many simple index advisors stop at this logic:

```text
This query has a WHERE condition, so create an index.
```

Database Index Advisor goes further.

It is designed around real DBA thinking:

- Recommendations are based on real workload data, not isolated query text.
- Candidate indexes are validated with `HypoPG` before being recommended.
- Parameterized queries are supported through sample-based validation.
- Existing indexes are detected to avoid duplicate recommendations.
- The advisor understands composite index patterns.
- The advisor can recommend indexes for `ORDER BY + LIMIT` patterns.
- The advisor can detect useful indexes for joins and LATERAL queries.
- Recommendations are separated into current actionable recommendations and historical recommendations.
- The product shows alternative index options when relevant.

Example:

```sql
SELECT
    c.customer_id,
    c.email,
    latest_order.order_id,
    latest_order.order_date
FROM customers c
JOIN LATERAL (
    SELECT o.order_id, o.order_date
    FROM orders o
    WHERE o.customer_id = c.customer_id
    ORDER BY o.order_date DESC
    LIMIT 1
) latest_order ON true
WHERE c.country = $1
LIMIT 100;
```

A naive advisor might only notice `customers.country`.

This advisor can recognize that the inner LATERAL query benefits from:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS "idx_advisor_orders_customer_id_order_date_desc"
ON "public"."orders" ("customer_id", "order_date" DESC);
```

Why this matters:

- `customer_id` supports the lookup for each customer.
- `order_date DESC` supports newest-order-first access.
- `LIMIT 1` means PostgreSQL can stop after finding the first matching row.

In testing, this type of recommendation reduced a query from several seconds to a few milliseconds.

---

## Architecture

High-level architecture:

```text
Target PostgreSQL Database
        |
        v
Collector Layer
        |
        v
Storage Database
        |
        v
Analyzer Layer
        |
        v
FastAPI Backend
        |
        v
React Frontend Dashboard
```

The product separates the target database from the storage database.

- The target database is the database being analyzed.
- The storage database stores the advisor's internal state, collection runs, query stats, recommendations, and validation evidence.

---

## Main Components

### 1. Target Database

The PostgreSQL database being analyzed.

The advisor connects to this database to collect:

- `pg_stat_statements` workload data
- table statistics
- index statistics
- query metadata
- safe execution plans when possible

The target database must have the required extensions installed.

---

### 2. Storage Database

The storage database stores the advisor's data.

It stores:

- configured database targets
- collection runs
- query statistics
- table statistics
- index statistics
- query plans
- recommendations
- recommendation validations
- lifecycle state

This keeps the product metadata separate from the database being analyzed.

---

### 3. Collector

The collector reads workload and metadata from the target database.

It collects:

- top queries from `pg_stat_statements`
- calls
- total execution time
- mean execution time
- table scan/write statistics
- existing index definitions
- execution plans for safe non-parameterized queries

Parameterized queries are detected and skipped by direct plan capture because they need real bind values. They are later handled by the analyzer through sample validation.

---

### 4. Analyzer

The analyzer is the brain of the product.

It:

1. Loads the latest completed collection run.
2. Parses expensive queries.
3. Extracts tables, aliases, predicates, joins, order-by columns, and limit patterns.
4. Generates candidate indexes.
5. Checks whether matching indexes already exist.
6. Validates candidates using `HypoPG`.
7. Scores the results.
8. Stores the best recommendation and alternative options.

The analyzer can detect patterns such as:

- equality filters
- multi-column filters
- join lookups
- `ORDER BY + LIMIT`
- equality plus range predicates
- LATERAL latest-row lookups
- covering index opportunities with `INCLUDE`

---

### 5. FastAPI Backend

The backend exposes the API used by the frontend.

It handles:

- setup status
- database target management
- collect/analyze execution
- current recommendations
- recommendation history
- recommendation details
- query stats
- table stats
- user revalidation with real parameter values

---

### 6. React Frontend

The frontend provides the user interface.

It includes pages for:

- Dashboard
- Current Recommendations
- Recommendation History
- Analysis Runs
- Query Stats
- Table Stats
- Database Target Setup
- About

---

## Storage Database Architecture

The storage schema is created under:

```text
index_advisor
```

Important tables:

### `database_targets`

Stores the database targets configured by the user.

Each target represents one PostgreSQL database that can be analyzed.

---

### `collection_runs`

Each collect/analyze execution creates a collection run.

This allows the product to track what happened in every analysis cycle.

---

### `query_stats`

Stores queries collected from `pg_stat_statements`.

Includes:

- query id
- normalized query text
- calls
- total execution time
- mean execution time
- capture time

---

### `table_stats`

Stores table-level statistics.

Used to understand table access patterns and write pressure.

---

### `index_stats`

Stores existing index definitions from the target database.

Used to avoid recommending indexes that already exist or are already covered by a stronger existing index.

---

### `query_plans`

Stores execution plans captured by the collector.

This table is for collector-captured original plans only.

Validation plans are stored separately in `recommendation_validations`.

---

### `recommendations`

Stores the main recommendation summary.

Includes:

- collection run id
- query id
- schema name
- table name
- recommended columns
- recommended index SQL
- score
- reason
- validation type
- cost comparison
- improvement percentage
- status

---

### `recommendation_validations`

Stores detailed validation evidence.

Includes:

- validation type
- selected option
- index SQL
- sampled bind values
- rendered query text
- original cost
- hypothetical cost
- improvement percentage
- original plan JSON
- hypothetical plan JSON

This keeps the `recommendations` table clean while preserving detailed proof.

---

## Requirements

### Software

- Python 3.12+
- Node.js 18+
- npm
- PostgreSQL 14+
- FastAPI
- React / Vite
- psycopg
- sqlglot
- pg_stat_statements
- HypoPG

---

## Required PostgreSQL Extensions

The target PostgreSQL database should have:

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS hypopg;
```

---

## About `pg_stat_statements`

`pg_stat_statements` is used to collect real query workload statistics.

It may require adding this to `postgresql.conf`:

```conf
shared_preload_libraries = 'pg_stat_statements'
```

Then restart PostgreSQL.

After restart, connect to the target database and run:

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

Verify it:

```sql
SELECT *
FROM pg_extension
WHERE extname = 'pg_stat_statements';
```

To reset workload statistics before a clean test:

```sql
SELECT pg_stat_statements_reset();
```

---

## About `HypoPG`

`HypoPG` allows PostgreSQL to test hypothetical indexes without physically creating them.

This is important because the advisor can estimate the benefit of an index without changing the target database.

Install the HypoPG package for your PostgreSQL version, then run:

```sql
CREATE EXTENSION IF NOT EXISTS hypopg;
```

Verify it:

```sql
SELECT *
FROM pg_extension
WHERE extname = 'hypopg';
```

---

## How to Run the Backend

From the project root:

```bash
cd index_rec_app
PYTHONPATH=backend python -m index_advisor.main api --reload
```

The backend should start on:

```text
http://127.0.0.1:8000
```

Health check:

```text
http://127.0.0.1:8000/health
```

---


## Product Settings, Scheduler, and Retention

Manual runs are still available, but the backend also starts an in-process scheduler when the FastAPI API starts.

By default, the scheduler runs collect + analyze twice per day using the backend server local time:

```env
SCHEDULER_ENABLED=true
SCHEDULER_RUN_TIMES=06:00,20:00
STORAGE_RETENTION_DAYS=30
```

After setup, end users can edit these values from the frontend **Settings** page. The values are saved in `index_advisor.app_settings` inside `storage_db`; users do not need to edit environment variables. Environment variables are only defaults/fallbacks before storage is configured.

At each scheduled time, the scheduler:

1. Finds all active database targets.
2. Runs collect + analyze for each target sequentially.
3. Runs storage retention cleanup after the scheduled cycle.
4. Skips the scheduled run if another collect/analyze job is already running.

Storage retention deletes old `collection_runs` older than `storage_retention_days`. PostgreSQL foreign keys with `ON DELETE CASCADE` remove the dependent query stats, table stats, index stats, query plans, recommendations, and recommendation validations.

Settings API:

```text
GET /settings
PUT /settings
GET /scheduler/status
```

Example update:

```json
{
  "scheduler_enabled": true,
  "scheduler_run_times": ["07:00", "21:30"],
  "storage_retention_days": 14
}
```

If storage is not configured yet, the scheduler stays enabled but skips work until setup is completed from the frontend. The scheduler polls settings regularly, so schedule changes take effect without restarting the backend.

---

## How to Run the Frontend

Open another terminal:

```bash
cd index_rec_app/frontend
npm install
npm run dev
```

The frontend should start on:

```text
http://localhost:5173
```

---

## Typical Local Development Flow

Terminal 1:

```bash
cd index_rec_app
PYTHONPATH=backend python -m index_advisor.main api --reload
```

Terminal 2:

```bash
cd index_rec_app/frontend
npm run dev
```

Open:

```text
http://localhost:5173
```

---


---

## Packaging and End-User Mode

The project supports two modes:

```text
Development mode:
  React/Vite: http://localhost:5173
  FastAPI:    http://localhost:8000

Production/package mode:
  FastAPI serves both the React UI and the API from one local server.
```

In development, keep using two terminals exactly as before:

```bash
python main.py api
cd frontend
npm run dev
```

For production/package mode, build the React app and copy it into the backend:

```bash
python packaging/build_release.py
```

This runs `npm run build` and copies `frontend/dist` into:

```text
backend/index_advisor/web/
```

FastAPI then serves the built UI directly. The end user does not need Node.js,
Vite, or `npm run dev`.

The packaging launcher is:

```bash
python run_app.py
```

It starts the local FastAPI server and opens the browser automatically. This is
the entry point intended for PyInstaller/Nuitka packaging.

To build a PyInstaller one-folder executable on the current OS:

```bash
pip install -r requirements.txt
pip install -r packaging/requirements-build.txt
python packaging/build_release.py --pyinstaller
```

Build Windows packages on Windows and Linux packages on Linux. Do not ship
`node_modules`, `__pycache__`, `.git`, or runtime secrets.

Runtime secrets are stored per user, not inside the installed application folder:

```text
Windows: %APPDATA%\IndexAdvisor
Linux/macOS: ~/.config/index-advisor
```

For development only, you can force the old local project config behavior:

```env
INDEX_ADVISOR_CONFIG_DIR=./config
```

## How to Add a Database Target

In the UI:

1. Open the app.
2. Click **Add Database**.
3. Enter the database connection details:
   - name
   - host
   - port
   - database name
   - username
   - password
   - SSL mode
4. Test the connection.
5. Check required extensions.
6. Save the target.

Example:

```text
Name: Fake DB
Host: localhost
Port: 5432
Database name: fake_db
Username: postgres
Password: ********
SSL mode: prefer
```

---

## Recommended Target User Permissions

For the best experience, the database user should be able to:

- read `pg_stat_statements`
- read table and index metadata
- run `EXPLAIN`
- use `hypopg`
- create extensions during setup, if allowed

In production, it may be better to install extensions manually using a privileged user and then use a controlled application user for the advisor.

---

## Extension Setup Failure

If the app cannot install extensions automatically, install them manually.

Run as a privileged PostgreSQL user:

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS hypopg;
```

If `pg_stat_statements` is not available, make sure PostgreSQL was started with:

```conf
shared_preload_libraries = 'pg_stat_statements'
```

Then restart PostgreSQL.

---

## How Recommendations Work

The recommendation flow:

```text
1. User runs analysis.
2. Collector reads pg_stat_statements and database metadata.
3. Analyzer parses expensive queries.
4. Analyzer generates candidate indexes.
5. Existing indexes are checked.
6. HypoPG validates candidate indexes.
7. Best index is selected.
8. Recommendation is stored.
9. Frontend shows it in Current Recommendations.
```

---

## Recommendation Validation

The advisor can create several validation types.

### `VALIDATED`

The query was validated directly using HypoPG.

### `SAMPLE_VALIDATED`

The original query used bind parameters, so the advisor sampled example values from the database and validated a rendered query.

Example original query:

```sql
SELECT *
FROM customers
WHERE email = $1;
```

Sampled query:

```sql
SELECT *
FROM customers
WHERE email = 'user_123@example.com';
```

### `USER_VALIDATED`

The user manually entered real parameter values and the advisor revalidated the recommendation.

### `HEURISTIC_ONLY`

The advisor generated the recommendation based on query structure but could not validate it with HypoPG.

---

## Current Recommendations

Current Recommendations shows only what the user should act on now.

It means:

```text
Latest analysis run
+ active recommendations
+ no matching existing index detected
```

If the user creates the recommended index and runs analysis again, the recommendation should disappear from Current Recommendations.

That is expected behavior.

It means the advisor detected that the problem is already solved.

---

## Recommendation History

Recommendation History shows recommendations from all analysis runs.

It is used for audit and tracking.

It helps answer:

- What did the advisor recommend before?
- Which recommendations were later resolved?
- Which indexes were applied?
- Did the same recommendation appear multiple times?
- What changed between analysis runs?

Current Recommendations is for action.

Recommendation History is for context.

---

## Recommendation Statuses

Recommendations may have statuses such as:

```text
ACTIVE
APPLIED
RESOLVED_BY_EXISTING_INDEX
IGNORED
STALE
```

### `ACTIVE`

The recommendation is currently relevant and no matching index was detected.

### `APPLIED`

The recommended index now exists.

### `RESOLVED_BY_EXISTING_INDEX`

The recommendation is no longer needed because an existing index covers it.

### `IGNORED`

The user chose not to act on the recommendation.

### `STALE`

The recommendation came from an older workload and is no longer seen in the latest run.

---

## Example Recommendation

Query:

```sql
SELECT order_id, customer_id, order_status, order_date, total_amount
FROM orders
WHERE customer_id = $1
ORDER BY order_date DESC
LIMIT $2;
```

Recommended index:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS "idx_advisor_orders_customer_id_order_date_desc"
ON "public"."orders" ("customer_id", "order_date" DESC);
```

Why:

```text
customer_id supports the lookup.
order_date DESC supports the ordering.
LIMIT allows PostgreSQL to stop early after reading the newest rows.
```

---

## Alternative Index Options

For some queries, the advisor may test several index options.

Example:

```text
Option 1:
orders(customer_id, order_date DESC)

Option 2:
orders(customer_id, order_date DESC) INCLUDE (order_id)

Option 3:
orders(customer_id)
```

The selected option is the advisor's preferred recommendation.

Alternative options are shown so the DBA can understand the tradeoffs.

---

## Applying Recommendations

The recommended SQL uses:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS
```

Example:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS "idx_advisor_customers_email"
ON "public"."customers" ("email");
```

`CONCURRENTLY` helps reduce blocking on production systems.

Important PostgreSQL rule:

```text
CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
```

Do not run it inside:

```sql
BEGIN;
CREATE INDEX CONCURRENTLY ...;
COMMIT;
```

Run it directly from a SQL client.

---

## After Applying an Index

After creating a recommended index:

1. Run the workload again.
2. Run analysis again.
3. Check Current Recommendations.

Expected result:

```text
The recommendation disappears from Current Recommendations.
```

Then check Recommendation History.

Expected result:

```text
The old recommendation remains visible as historical context.
```

---

## Before / After Example

In a test workload, the advisor recommended:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS "idx_advisor_orders_customer_id_order_date_desc"
ON "public"."orders" ("customer_id", "order_date" DESC);
```

For a LATERAL latest-order query.

Before index:

```text
~3,500ms to ~4,500ms
```

After index:

```text
~1ms to ~4ms
```

This proves that the advisor can produce meaningful, workload-based performance improvements.

---

## Frontend Pages

### Dashboard

Shows a high-level overview of the selected database target.

Includes latest run information and recommendation summaries.

---

### Current Recommendations

Shows actionable recommendations from the latest analysis run only.

This page is intentionally clean.

If it says:

```text
No current recommendations
```

that usually means one of the following:

- no useful recommendations were found
- recommended indexes already exist
- the latest workload does not need new indexes
- the current target is not the database you expected

---

### Recommendation History

Shows historical recommendations across analysis runs.

Use it for audit and tracking.

---

### Analysis Runs

Shows previous collection/analyze runs.

Useful for debugging and checking when data was collected.

---

### Query Stats

Shows expensive queries collected from `pg_stat_statements`.

Useful for understanding workload behavior.

---

### Table Stats

Shows table-level statistics such as scans and writes.

Useful for evaluating write pressure before creating indexes.

---

## Backend API Overview

Common endpoints:

```text
GET  /health
GET  /setup/status
GET  /targets
POST /targets
POST /runs/manual
GET  /runs/latest
GET  /recommendations
GET  /recommendations/history
GET  /recommendations/{id}
POST /recommendations/{id}/revalidate
GET  /query-stats
GET  /table-stats
```

---

## Revalidating With Real Parameter Values

For parameterized queries, the app may validate using sampled values.

A DBA can provide real parameter values and revalidate.

Example request body:

```json
{
  "$1": "France",
  "$2": "ACTIVE"
}
```

The app renders the query safely and reruns HypoPG validation.

This creates a `USER_VALIDATED` validation entry.

---

## Recommended Workflow

Recommended DBA workflow:

```text
1. Add a database target.
2. Run workload or wait for workload to accumulate.
3. Run analysis.
4. Review Current Recommendations.
5. Open recommendation details.
6. Review the query, reason, alternatives, and plans.
7. Apply the index manually if it makes sense.
8. Run workload again.
9. Run analysis again.
10. Confirm the recommendation is gone from Current Recommendations.
11. Review Recommendation History for audit context.
```

---

## Best Practices

Do not blindly apply every recommendation.

Before creating an index, review:

- query importance
- improvement percentage
- table size
- write pressure
- existing indexes
- whether a similar index already exists
- whether the index is too wide
- whether an `INCLUDE` version is worth the extra size
- whether the query is important enough to justify write overhead

---

## Current Limitations

This project is an MVP and still has room to grow.

Known limitations:

- PostgreSQL only
- recommendations depend on available workload in `pg_stat_statements`
- sampled bind values may not represent all production values
- some aggregation-heavy queries require deeper analysis
- partition-aware recommendations are not fully implemented
- partial indexes are not fully implemented
- expression indexes are not fully implemented
- automatic index application is not the main workflow
- index size estimation can be improved
- write overhead scoring can be improved

---

## Troubleshooting

### Frontend opens but shows no data

Check that the backend is running:

```text
http://127.0.0.1:8000/health
```

---

### No recommendations appear

Possible reasons:

- no workload in `pg_stat_statements`
- wrong database target selected
- required extensions are missing
- queries are not expensive enough
- matching indexes already exist
- latest analysis has no active recommendations

Try resetting workload stats:

```sql
SELECT pg_stat_statements_reset();
```

Then run workload again and rerun analysis.

---

### `pg_stat_statements` is not working

Check:

```sql
SHOW shared_preload_libraries;
```

If `pg_stat_statements` is missing, add it to `postgresql.conf`:

```conf
shared_preload_libraries = 'pg_stat_statements'
```

Restart PostgreSQL.

Then run:

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

---

### `hypopg` is missing

Install the HypoPG package for your PostgreSQL version.

Then run:

```sql
CREATE EXTENSION IF NOT EXISTS hypopg;
```

---

### `CREATE INDEX CONCURRENTLY` fails

Make sure you are not running it inside a transaction.

Wrong:

```sql
BEGIN;
CREATE INDEX CONCURRENTLY ...;
COMMIT;
```

Correct:

```sql
CREATE INDEX CONCURRENTLY ...;
```

---

## Development Commands

Compile Python:

```bash
PYTHONPATH=backend python -m compileall backend/index_advisor
```

Run tests, if available:

```bash
pytest -q
```

Run backend:

```bash
PYTHONPATH=backend python -m index_advisor.main api --reload
```

Run frontend:

```bash
cd frontend
npm run dev
```

---

## Project Status

Current status:

```text
MVP working
```

Implemented:

- setup flow
- multiple database targets
- workload collection
- query analysis
- HypoPG validation
- parameterized query sampling
- current recommendations
- recommendation history
- lifecycle detection
- frontend dashboard

---

## Future Roadmap

Possible future improvements:

- automatic before/after benchmark capture
- index size estimation
- better write overhead modeling
- partition-aware recommendations
- duplicate/overlapping index cleanup suggestions
- partial index recommendations
- expression index recommendations
- BRIN index recommendations
- multi-database fleet view
- Oracle support
- SQL Server support
- exportable recommendation reports
- richer DBA explanations
- production deployment with Docker/OpenShift

---

## Portfolio Description

Built a Database Index Advisor that analyzes `pg_stat_statements`, detects expensive query patterns, generates candidate indexes, validates them using HypoPG, and tracks recommendation lifecycle across analysis runs.

In a test workload, the advisor reduced a LATERAL latest-row query from approximately 3.5-4.5 seconds to around 1-4 milliseconds using a generated composite index on:

```sql
(customer_id, order_date DESC)
```

---

## Short Description

Database Index Advisor is a workload-aware index recommendation platform for PostgreSQL that analyzes real query activity, validates candidate indexes with HypoPG, and helps DBAs safely improve query performance.



## Storage database setup

For normal end-user installs, `STORAGE_DATABASE_URL` is optional. If it is not set, the backend starts in first-time setup mode and the frontend setup page asks the user for PostgreSQL connection details. When the user submits the setup form, the app creates/connects to a `storage_db` database on that same PostgreSQL host and applies the storage schema migrations.

After successful setup, the backend writes the storage connection to local user config `storage.env`. This lets the product reconnect to `storage_db` after backend restart without asking the user to manually create environment variables. The file contains database credentials, is ignored by source control/ZIP packaging, and should not be shared.

No global `~/.index_rec_advisor/storage.json` file is read or written.

Configuration priority:

1. OS/environment `STORAGE_DATABASE_URL` — advanced/dev override.
2. Local user config `storage.env` — created by frontend setup.
3. Frontend setup mode — used when neither exists.

The user/role used during first setup must be able to connect to the maintenance database, usually `postgres`, and must have permission to create a database.

Optional settings:

```env
STORAGE_DATABASE_NAME=storage_db
STORAGE_MAINTENANCE_DB=postgres
```

---

## Local Security Model

This version is designed for local installation on DBA/developer machines.
Dangerous write endpoints are protected by a local admin token:

- `POST /targets`
- `PUT /targets/{id}`
- `DELETE /targets/{id}`
- `POST /targets/{id}/test-connection`
- `POST /targets/{id}/check-extensions`
- `POST /runs/manual`
- `POST /recommendations/{id}/revalidate`
- `POST /recommendations/{id}/apply`
- `PUT /settings`

On first backend startup, the app creates:

```text
config/admin_token.env
config/credential.key
```

`admin_token.env` is used for local admin authorization. The React frontend creates a local HttpOnly admin cookie through `/auth/local-session`, so normal local UI usage does not require manually copying the token.

Scripts or future installer tools can also send:

```text
X-Index-Advisor-Token: <value from config/admin_token.env>
```

Target database passwords are encrypted before being stored in the storage database. The encryption key is kept locally in the local config `credential.key`, not in the storage DB. Existing legacy plaintext rows remain readable for backward compatibility, but new/updated targets are saved encrypted.

Do not share or commit files from `config/`. They are ignored by `.gitignore`.

## Architecture Refactor Notes

The API is now split more clearly:

```text
api/routers/             thin FastAPI endpoints
services/                business workflows
storage/repositories/    SQL/read-write access for storage DB
security/                local token auth + credential encryption
```

The PostgreSQL analyzer was intentionally not rewritten in this refactor.

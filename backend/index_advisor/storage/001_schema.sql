-- Full schema for the index_advisor storage database.
-- This file is idempotent: safe to run on a fresh database or an existing one.
--
-- Migration tracking: applied migrations are recorded in
-- index_advisor.schema_migrations so that future migrations run exactly once.

BEGIN;

-- ──────────────────────────────────────────
-- Schema
-- ──────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS index_advisor;

-- ──────────────────────────────────────────
-- Migration tracking
-- ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS index_advisor.schema_migrations (
  version     text        PRIMARY KEY,
  applied_at  timestamptz NOT NULL DEFAULT now()
);

-- ──────────────────────────────────────────
-- Application settings
-- ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS index_advisor.app_settings (
  key        text    PRIMARY KEY,
  value      jsonb   NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Product settings defaults. These are editable from the frontend Settings page.
INSERT INTO index_advisor.app_settings(key, value, updated_at)
VALUES
  ('scheduler_enabled', 'true'::jsonb, now()),
  ('scheduler_run_times', '["06:00", "20:00"]'::jsonb, now()),
  ('storage_retention_days', '30'::jsonb, now())
ON CONFLICT (key) DO NOTHING;

-- ──────────────────────────────────────────
-- Database targets
-- ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS index_advisor.database_targets (
  id                        bigserial   PRIMARY KEY,
  name                      text        NOT NULL,
  engine                    text        NOT NULL DEFAULT 'postgres',
  host                      text        NOT NULL,
  port                      integer     NOT NULL DEFAULT 5432,
  database_name             text        NOT NULL,
  username                  text        NOT NULL,
  password                  text        NULL,
  sslmode                   text        NOT NULL DEFAULT 'prefer',
  is_active                 boolean     NOT NULL DEFAULT true,
  is_default                boolean     NOT NULL DEFAULT false,
  setup_status              text        NOT NULL DEFAULT 'PENDING',
  last_connection_check_at  timestamptz NULL,
  last_connection_error     text        NULL,
  last_extension_check_at   timestamptz NULL,
  last_extension_error      text        NULL,
  pg_stat_statements_ok     boolean     NOT NULL DEFAULT false,
  hypopg_ok                 boolean     NOT NULL DEFAULT false,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name),
  CONSTRAINT ck_database_targets_engine CHECK (engine IN ('postgres', 'mssql', 'oracle'))
);


-- Existing installations created before multi-engine support need this column too.
ALTER TABLE index_advisor.database_targets
  ADD COLUMN IF NOT EXISTS engine text NOT NULL DEFAULT 'postgres';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ck_database_targets_engine'
      AND conrelid = 'index_advisor.database_targets'::regclass
  ) THEN
    ALTER TABLE index_advisor.database_targets
      ADD CONSTRAINT ck_database_targets_engine CHECK (engine IN ('postgres', 'mssql', 'oracle'));
  END IF;
END $$;

-- Only one target may be the default at a time.
CREATE INDEX IF NOT EXISTS idx_database_targets_engine
  ON index_advisor.database_targets(engine);

CREATE UNIQUE INDEX IF NOT EXISTS ux_database_targets_default
  ON index_advisor.database_targets (is_default)
  WHERE is_default;

-- ──────────────────────────────────────────
-- Collection runs
-- ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS index_advisor.collection_runs (
  id            uuid        PRIMARY KEY,
  target_id     bigint      NULL REFERENCES index_advisor.database_targets(id),
  started_at    timestamptz NOT NULL,
  completed_at  timestamptz NULL,
  status        text        NOT NULL,
  error_message text        NULL
);

CREATE INDEX IF NOT EXISTS idx_collection_runs_target_id
  ON index_advisor.collection_runs(target_id);
CREATE INDEX IF NOT EXISTS idx_collection_runs_started_at
  ON index_advisor.collection_runs(started_at);

-- ──────────────────────────────────────────
-- Query statistics (from pg_stat_statements)
-- ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS index_advisor.query_stats (
  id                bigserial   PRIMARY KEY,
  collection_run_id uuid        NOT NULL REFERENCES index_advisor.collection_runs(id) ON DELETE CASCADE,
  queryid           text        NOT NULL,
  query_text        text        NOT NULL,
  calls             bigint      NOT NULL,
  mean_exec_time    double precision NOT NULL,
  total_exec_time   double precision NOT NULL,
  captured_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_query_stats_run_id
  ON index_advisor.query_stats(collection_run_id);
CREATE INDEX IF NOT EXISTS idx_query_stats_total_exec_time_desc
  ON index_advisor.query_stats(total_exec_time DESC);

-- ──────────────────────────────────────────
-- Table statistics (from pg_stat_user_tables)
-- ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS index_advisor.table_stats (
  id                bigserial   PRIMARY KEY,
  collection_run_id uuid        NOT NULL REFERENCES index_advisor.collection_runs(id) ON DELETE CASCADE,
  schemaname        text        NOT NULL,
  table_name        text        NOT NULL,
  seq_scan          bigint      NOT NULL,
  idx_scan          bigint      NOT NULL,
  n_tup_ins         bigint      NOT NULL,
  n_tup_upd         bigint      NOT NULL,
  n_tup_del         bigint      NOT NULL,
  writes            bigint      NOT NULL,
  n_live_tup        bigint      NOT NULL,
  captured_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_table_stats_run_id
  ON index_advisor.table_stats(collection_run_id);

-- ──────────────────────────────────────────
-- Index statistics (from pg_stat_user_indexes)
-- ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS index_advisor.index_stats (
  id                bigserial   PRIMARY KEY,
  collection_run_id uuid        NOT NULL REFERENCES index_advisor.collection_runs(id) ON DELETE CASCADE,
  schemaname        text        NOT NULL,
  table_name        text        NOT NULL,
  index_name        text        NOT NULL,
  idx_scan          bigint      NOT NULL,
  idx_tup_read      bigint      NOT NULL,
  idx_tup_fetch     bigint      NOT NULL,
  indexdef          text        NOT NULL,
  captured_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_index_stats_run_id
  ON index_advisor.index_stats(collection_run_id);

-- ──────────────────────────────────────────
-- Query execution plans (captured at collection time)
-- Validation plans live in recommendation_validations, not here.
-- ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS index_advisor.query_plans (
  id                bigserial   PRIMARY KEY,
  collection_run_id uuid        NOT NULL REFERENCES index_advisor.collection_runs(id) ON DELETE CASCADE,
  queryid           text        NOT NULL,
  query_text        text        NOT NULL,
  plan              jsonb       NOT NULL,
  captured_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_query_plans_run_id
  ON index_advisor.query_plans(collection_run_id);
CREATE INDEX IF NOT EXISTS idx_query_plans_run_queryid
  ON index_advisor.query_plans(collection_run_id, queryid);

-- ──────────────────────────────────────────
-- Index recommendations
-- ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS index_advisor.recommendations (
  id                      bigserial   PRIMARY KEY,
  collection_run_id       uuid        NOT NULL REFERENCES index_advisor.collection_runs(id) ON DELETE CASCADE,
  queryid                 text        NOT NULL,
  schemaname              text        NOT NULL,
  table_name              text        NOT NULL,
  columns                 text[]      NOT NULL,
  recommended_index_sql   text        NOT NULL,
  score                   numeric     NOT NULL,
  reason                  text        NOT NULL,
  validated               boolean     NOT NULL DEFAULT false,
  original_cost           numeric     NULL,
  hypothetical_cost       numeric     NULL,
  improvement_pct         numeric     NULL,
  alternative_options_json jsonb      NOT NULL DEFAULT '[]'::jsonb,
  validation_type         text        NOT NULL DEFAULT 'HEURISTIC_ONLY',
  parameterized_query     boolean     NOT NULL DEFAULT false,
  sampled_validation      boolean     NOT NULL DEFAULT false,
  normalized_query_text   text        NULL,
  sampled_query_text      text        NULL,
  status                  text        NOT NULL DEFAULT 'ACTIVE',
  status_reason           text        NULL,
  status_updated_at       timestamptz NOT NULL DEFAULT now(),
  created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_recommendations_run_id
  ON index_advisor.recommendations(collection_run_id);
CREATE INDEX IF NOT EXISTS idx_recommendations_score_desc
  ON index_advisor.recommendations(score DESC);
CREATE INDEX IF NOT EXISTS idx_recommendations_validation_type
  ON index_advisor.recommendations(validation_type);
CREATE INDEX IF NOT EXISTS idx_recommendations_status
  ON index_advisor.recommendations(status);

-- ──────────────────────────────────────────
-- Recommendation validations
-- Stores per-validation evidence: bind values, rendered query, execution plans.
-- ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS index_advisor.recommendation_validations (
  id                      bigserial   PRIMARY KEY,
  recommendation_id       bigint      NOT NULL REFERENCES index_advisor.recommendations(id) ON DELETE CASCADE,
  validation_type         text        NOT NULL,
  option_rank             integer     NULL,
  is_selected_option      boolean     NOT NULL DEFAULT false,
  index_sql               text        NULL,
  bind_values_json        jsonb       NULL,
  rendered_query_text     text        NULL,
  original_cost           numeric     NULL,
  hypothetical_cost       numeric     NULL,
  improvement_pct         numeric     NULL,
  original_plan_json      jsonb       NULL,
  hypothetical_plan_json  jsonb       NULL,
  created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_recommendation_validations_recommendation_id
  ON index_advisor.recommendation_validations(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_recommendation_validations_type
  ON index_advisor.recommendation_validations(validation_type);


-- Composite indexes for the API's most common read paths.
CREATE INDEX IF NOT EXISTS idx_database_targets_active_default
  ON index_advisor.database_targets(is_active, is_default DESC, id);

CREATE INDEX IF NOT EXISTS idx_collection_runs_target_status_completed
  ON index_advisor.collection_runs(target_id, status, completed_at DESC, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_query_stats_run_total_exec_time
  ON index_advisor.query_stats(collection_run_id, total_exec_time DESC);

CREATE INDEX IF NOT EXISTS idx_table_stats_run_seq_scan
  ON index_advisor.table_stats(collection_run_id, seq_scan DESC);

CREATE INDEX IF NOT EXISTS idx_index_stats_run_idx_scan
  ON index_advisor.index_stats(collection_run_id, idx_scan DESC);

CREATE INDEX IF NOT EXISTS idx_recommendations_run_status_score
  ON index_advisor.recommendations(collection_run_id, status, score DESC, improvement_pct DESC);

-- Record this migration as applied.
INSERT INTO index_advisor.schema_migrations (version)
VALUES ('001_schema')
ON CONFLICT (version) DO NOTHING;

COMMIT;

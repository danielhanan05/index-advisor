-- Incremental migration for installations that already applied 001_schema.
-- Fresh installations also get these objects from 001_schema; all statements are idempotent.

BEGIN;

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

INSERT INTO index_advisor.schema_migrations (version)
VALUES ('002_security_architecture_indexes')
ON CONFLICT (version) DO NOTHING;

COMMIT;

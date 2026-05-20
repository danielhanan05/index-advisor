TOP_QUERIES_SQL = """
SELECT
  queryid::text AS queryid,
  query AS query,
  calls,
  mean_exec_time,
  total_exec_time
FROM pg_stat_statements
WHERE query IS NOT NULL
  AND calls > 0
  AND total_exec_time IS NOT NULL
  -- Exclude very common internal noise / session management statements
  AND query !~* '^\\s*(BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE|SET|SHOW|DISCARD|DEALLOCATE|PREPARE|EXECUTE)\\b'
  AND query !~* '^\\s*EXPLAIN\\b'
  AND query !~* '\\b(?:pg_catalog|information_schema|pg_toast|index_advisor|pg_stat_statements|pg_stat_activity|pg_stat_user_tables|pg_stat_user_indexes|pg_indexes|pg_extension|pg_database|pg_show_all_settings|hypopg|current_setting)\\b'
ORDER BY total_exec_time DESC
LIMIT %(limit)s;
"""


TABLE_STATS_SQL = """
SELECT
  schemaname,
  relname,
  COALESCE(seq_scan, 0) AS seq_scan,
  COALESCE(idx_scan, 0) AS idx_scan,
  COALESCE(n_tup_ins, 0) AS n_tup_ins,
  COALESCE(n_tup_upd, 0) AS n_tup_upd,
  COALESCE(n_tup_del, 0) AS n_tup_del,
  (COALESCE(n_tup_ins, 0) + COALESCE(n_tup_upd, 0) + COALESCE(n_tup_del, 0)) AS writes,
  COALESCE(n_live_tup, 0) AS n_live_tup
FROM pg_stat_user_tables;
"""


INDEX_STATS_SQL = """
SELECT
  s.schemaname,
  s.relname,
  s.indexrelname,
  COALESCE(s.idx_scan, 0) AS idx_scan,
  COALESCE(s.idx_tup_read, 0) AS idx_tup_read,
  COALESCE(s.idx_tup_fetch, 0) AS idx_tup_fetch,
  i.indexdef
FROM pg_stat_user_indexes s
JOIN pg_indexes i
  ON i.schemaname = s.schemaname
 AND i.tablename  = s.relname
 AND i.indexname  = s.indexrelname;
"""


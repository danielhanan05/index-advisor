import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { api } from '../api/client'
import { useApi } from '../utils/useApi'
import { formatDate, formatNumber, formatDuration } from '../utils/format'
import { LoadingSpinner, ErrorState, EmptyState, RefreshButton, SqlBlock, Badge } from '../components/ui'
import { PageHeader } from '../components/Layout'
import { ExecutionPlanViewer } from '../components/ExecutionPlanViewer'

export function QueryStatsPage({ selectedTargetId }) {
  const { data, loading, error, refresh } = useApi(() => api.queryStats({ limit: 100, target_id: selectedTargetId }), [selectedTargetId])
  const [expanded, setExpanded] = useState({})

  const items = data?.items || []

  const toggle = (id) => setExpanded(e => ({ ...e, [id]: !e[id] }))

  return (
    <div>
      <PageHeader
        title="Query Stats"
        subtitle="Top queries by total execution time from pg_stat_statements"
        action={<RefreshButton onClick={refresh} loading={loading} />}
      />
      <div className="p-8">
        {loading && <LoadingSpinner />}
        {error && <ErrorState message={error} onRetry={refresh} />}
        {!loading && !error && items.length === 0 && <EmptyState />}
        {!loading && !error && items.length > 0 && (
          <div className="bg-bg-surface border border-bg-border rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-bg-border">
                    <th className="w-8" />
                    {[
                      'Query ID', 'Calls', 'Mean Time', 'Total Time', 'Plan', 'Captured'
                    ].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-mono text-text-muted uppercase tracking-wider whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((row, i) => (
                    <>
                      <tr
                        key={row.id || i}
                        className="border-b border-bg-border/50 hover:bg-bg-hover cursor-pointer transition-colors"
                        onClick={() => toggle(row.id || i)}
                      >
                        <td className="pl-3 pr-1 py-3">
                          <span className="text-text-muted">
                            {expanded[row.id || i] ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-text-muted">{row.queryid ?? '—'}</td>
                        <td className="px-4 py-3 font-mono text-sm text-text-secondary">{formatNumber(row.calls)}</td>
                        <td className="px-4 py-3 font-mono text-sm text-amber-400">{formatDuration(row.mean_exec_time)}</td>
                        <td className="px-4 py-3 font-mono text-sm text-text-primary font-semibold">{formatDuration(row.total_exec_time)}</td>
                        <td className="px-4 py-3">
                          {row.collected_plan_json
                            ? <Badge className="text-green-400 bg-green-dim border-green-600">Captured</Badge>
                            : <Badge className="text-text-muted bg-bg-surface border-bg-border">No plan</Badge>}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-text-muted whitespace-nowrap">{formatDate(row.captured_at)}</td>
                      </tr>
                      {expanded[row.id || i] && (
                        <tr key={`${row.id || i}-exp`} className="bg-bg-base border-b border-bg-border/50">
                          <td />
                          <td colSpan={6} className="px-4 py-4 space-y-4">
                            <div>
                              <p className="text-xs font-mono text-text-muted uppercase tracking-wider mb-2">Query Text</p>
                              <SqlBlock sql={row.query_text} />
                            </div>
                            <ExecutionPlanViewer
                              title="Collected Execution Plan"
                              plan={row.collected_plan_json}
                              emptyMessage="No collected execution plan exists for this query. This usually happens when the query used bind parameters or the collector skipped EXPLAIN for safety."
                            />
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

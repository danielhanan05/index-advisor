import { api } from '../api/client'
import { useApi } from '../utils/useApi'
import { formatDate, formatNumber } from '../utils/format'
import { LoadingSpinner, ErrorState, EmptyState, RefreshButton } from '../components/ui'
import { PageHeader } from '../components/Layout'

export function TableStatsPage({ selectedTargetId }) {
  const { data, loading, error, refresh } = useApi(() => api.tableStats({ target_id: selectedTargetId }), [selectedTargetId])

  const items = data?.items || []

  return (
    <div>
      <PageHeader
        title="Table Stats"
        subtitle="Sequential and index scan activity per table"
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
                    {['Schema', 'Table', 'Seq Scans', 'Idx Scans', 'Writes', 'Live Rows', 'Captured'].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-mono text-text-muted uppercase tracking-wider whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((row, i) => {
                    const seqHeavy = (row.seq_scan ?? 0) > (row.idx_scan ?? 0)
                    return (
                      <tr key={i} className="border-b border-bg-border/50 hover:bg-bg-hover transition-colors">
                        <td className="px-4 py-3 font-mono text-xs text-text-muted">{row.schemaname}</td>
                        <td className="px-4 py-3 font-mono text-sm text-text-primary font-medium">{row.table_name}</td>
                        <td className={`px-4 py-3 font-mono text-sm ${seqHeavy ? 'text-amber-400 font-semibold' : 'text-text-secondary'}`}>
                          {formatNumber(row.seq_scan)}
                        </td>
                        <td className="px-4 py-3 font-mono text-sm text-green-400">{formatNumber(row.idx_scan)}</td>
                        <td className="px-4 py-3 font-mono text-sm text-text-secondary">{formatNumber(row.writes ?? row.n_tup_upd)}</td>
                        <td className="px-4 py-3 font-mono text-sm text-text-secondary">{formatNumber(row.n_live_tup)}</td>
                        <td className="px-4 py-3 font-mono text-xs text-text-muted whitespace-nowrap">{formatDate(row.captured_at)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {!loading && !error && items.length > 0 && (
          <p className="text-xs font-mono text-text-muted mt-3">
            * Amber seq_scan values indicate tables where sequential scans outnumber index scans — prime candidates for index recommendations.
          </p>
        )}
      </div>
    </div>
  )
}

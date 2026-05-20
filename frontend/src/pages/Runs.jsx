import { useState } from 'react'
import { ChevronDown, ChevronUp, AlertCircle, Lightbulb, BarChart2, Table2, Layers, TrendingUp } from 'lucide-react'
import { api } from '../api/client'
import { useApi } from '../utils/useApi'
import { formatDate, statusColor, validationTypeColor, formatScore, formatPercent, scoreColor } from '../utils/format'
import { Badge, LoadingSpinner, ErrorState, EmptyState, RefreshButton, SqlBlock } from '../components/ui'
import { PageHeader } from '../components/Layout'
import { RecommendationModal } from '../components/RecommendationModal'

function RunDetail({ runId }) {
  const { data, loading, error } = useApi(() => api.run(runId), [runId])
  const { data: recs, loading: rLoading } = useApi(() => api.runRecommendations(runId, { limit: 50 }), [runId])
  const [selectedRecId, setSelectedRecId] = useState(null)

  if (loading || rLoading) return <LoadingSpinner />
  if (error) return <ErrorState message={error} />

  const counts = data?.counts || {}
  const recItems = recs?.items || []

  return (
    <div className="p-4 space-y-4">
      {/* Counts */}
      <div className="grid grid-cols-5 gap-3">
        {[
          { label: 'Recommendations', key: 'recommendations', icon: Lightbulb },
          { label: 'Query Stats', key: 'query_stats', icon: BarChart2 },
          { label: 'Table Stats', key: 'table_stats', icon: Table2 },
          { label: 'Index Stats', key: 'index_stats', icon: Layers },
          { label: 'Query Plans', key: 'query_plans', icon: TrendingUp },
        ].map(({ label, key, icon: Icon }) => (
          <div key={key} className="bg-bg-base border border-bg-border rounded-lg p-3 flex items-center gap-3">
            <Icon size={14} className="text-text-muted" />
            <div>
              <p className="text-lg font-display font-bold text-text-primary">{counts[key] ?? 0}</p>
              <p className="text-xs font-mono text-text-muted">{label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Recommendations for this run */}
      {recItems.length > 0 && (
        <div>
          <p className="text-xs font-mono text-text-muted uppercase tracking-wider mb-2">Recommendations</p>
          <div className="bg-bg-base border border-bg-border rounded-lg divide-y divide-bg-border/50">
            {recItems.map(rec => (
              <div
                key={rec.id}
                className="px-4 py-3 hover:bg-bg-hover cursor-pointer transition-colors flex items-center gap-3"
                onClick={() => setSelectedRecId(rec.id)}
              >
                <Badge className={scoreColor(rec.score)}>{formatScore(rec.score)}</Badge>
                <Badge className={validationTypeColor(rec.validation_type)}>{rec.validation_type}</Badge>
                <span className="text-xs font-mono text-text-secondary">{rec.table_name}</span>
                <span className="text-xs font-mono text-text-muted flex-1 truncate">{rec.columns}</span>
                {rec.improvement_pct != null && (
                  <span className="text-xs font-mono text-green-400">{formatPercent(rec.improvement_pct)}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {selectedRecId && (
        <RecommendationModal id={selectedRecId} onClose={() => setSelectedRecId(null)} />
      )}
    </div>
  )
}

export function RunsPage({ selectedTargetId }) {
  const { data, loading, error, refresh } = useApi(() => api.runs({ limit: 50, target_id: selectedTargetId }), [selectedTargetId])
  const [expanded, setExpanded] = useState({})

  const runs = data?.items || []

  const toggle = (id) => setExpanded(e => ({ ...e, [id]: !e[id] }))

  return (
    <div>
      <PageHeader
        title="Analysis Runs"
        subtitle="History of collect + analyze pipeline executions"
        action={<RefreshButton onClick={refresh} loading={loading} />}
      />
      <div className="p-8">
        {loading && <LoadingSpinner />}
        {error && <ErrorState message={error} onRetry={refresh} />}
        {!loading && !error && runs.length === 0 && (
          <EmptyState message="No runs found. Trigger an analysis from the Dashboard." />
        )}
        {!loading && !error && runs.length > 0 && (
          <div className="bg-bg-surface border border-bg-border rounded-xl overflow-hidden">
            {runs.map((run) => (
              <div key={run.id} className="border-b border-bg-border/50 last:border-0">
                <div
                  className="flex items-center gap-4 px-5 py-4 hover:bg-bg-hover cursor-pointer transition-colors"
                  onClick={() => toggle(run.id)}
                >
                  <div className="shrink-0">
                    {expanded[run.id] ? <ChevronUp size={14} className="text-text-muted" /> : <ChevronDown size={14} className="text-text-muted" />}
                  </div>
                  <Badge className={statusColor(run.status)}>{run.status}</Badge>
                  <span className="text-xs font-mono text-text-muted flex-1 truncate">{run.id}</span>
                  <span className="text-xs font-mono text-text-secondary whitespace-nowrap">{formatDate(run.started_at)}</span>
                  <span className="text-xs font-mono text-text-muted whitespace-nowrap">
                    → {run.completed_at ? formatDate(run.completed_at) : '…'}
                  </span>
                  {run.error_message && (
                    <AlertCircle size={14} className="text-red-400 shrink-0" title={run.error_message} />
                  )}
                </div>
                {expanded[run.id] && (
                  <div className="bg-bg-base border-t border-bg-border/50">
                    {run.error_message && (
                      <div className="px-5 py-3 text-sm font-mono text-red-400 bg-red-dim border-b border-bg-border/50">
                        Error: {run.error_message}
                      </div>
                    )}
                    <RunDetail runId={run.id} />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

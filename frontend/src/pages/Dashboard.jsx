import { useState } from 'react'
import { Play, CheckCircle, AlertCircle, Lightbulb, BarChart2, Table2, Layers, TrendingUp, Zap } from 'lucide-react'
import { api } from '../api/client'
import { useApi } from '../utils/useApi'
import { formatDate, formatPercent, formatScore, scoreColor, validationTypeColor, statusColor } from '../utils/format'
import {
  Card, CardHeader, CardTitle, StatCard, Badge, SqlBlock,
  LoadingSpinner, ErrorState, EmptyState, ValidationExplainer,
} from '../components/ui'
import { PageHeader } from '../components/Layout'

function RunButton({ onSuccess, selectedTargetId }) {
  const [state, setState] = useState('idle') // idle | loading | success | error
  const [msg, setMsg] = useState('')

  const trigger = async () => {
    setState('loading')
    try {
      const r = await api.triggerRun(selectedTargetId)
      setMsg(r.message || 'Run started.')
      setState('success')
      setTimeout(() => { setState('idle'); onSuccess?.() }, 3000)
    } catch (e) {
      setMsg(e.message)
      setState('error')
      setTimeout(() => setState('idle'), 4000)
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        onClick={trigger}
        disabled={state === 'loading' || state === 'success'}
        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-mono font-medium transition-all border ${
          state === 'success' ? 'bg-green-dim text-green-400 border-green-600/50' :
          state === 'error' ? 'bg-red-dim text-red-400 border-red-600/50' :
          'bg-green-dim text-green-400 border-green-600/40 hover:border-green-500 hover:bg-green-600/20'
        } disabled:opacity-60`}
      >
        {state === 'loading' ? <><Zap size={14} className="animate-pulse" /> Running…</> :
         state === 'success' ? <><CheckCircle size={14} /> Accepted</> :
         state === 'error' ? <><AlertCircle size={14} /> Failed</> :
         <><Play size={14} /> Run Analysis Now</>}
      </button>
      {msg && <p className={`text-xs font-mono ${state === 'error' ? 'text-red-400' : 'text-text-muted'}`}>{msg}</p>}
    </div>
  )
}

function RunCountsCard({ latest }) {
  const { data: runDetail } = useApi(() => api.run(latest.id), [latest.id])
  const counts = runDetail?.counts || {}

  return (
    <Card>
      <CardHeader>
        <CardTitle>Latest Run Counts</CardTitle>
        <div className="flex items-center gap-2">
          <Badge className={statusColor(latest.status)}>{latest.status}</Badge>
          <span className="text-xs font-mono text-text-muted truncate max-w-xs">{latest.id}</span>
        </div>
      </CardHeader>
      <div className="grid grid-cols-5 divide-x divide-bg-border">
        {[
          { label: 'Recommendations', key: 'recommendations', icon: Lightbulb },
          { label: 'Query Stats', key: 'query_stats', icon: BarChart2 },
          { label: 'Table Stats', key: 'table_stats', icon: Table2 },
          { label: 'Index Stats', key: 'index_stats', icon: Layers },
          { label: 'Query Plans', key: 'query_plans', icon: TrendingUp },
        ].map(({ label, key, icon: Icon }) => (
          <div key={label} className="flex flex-col items-center py-5 gap-1">
            <Icon size={14} className="text-text-muted mb-1" />
            <p className="text-xl font-display font-bold text-text-primary">{counts[key] ?? '—'}</p>
            <p className="text-xs font-mono text-text-muted text-center">{label}</p>
          </div>
        ))}
      </div>
    </Card>
  )
}

export function DashboardPage({ setPage, selectedTargetId }) {
  const { data, loading, error, refresh } = useApi(() => api.summary(selectedTargetId), [selectedTargetId])
  const { refresh: refreshRun } = useApi(() => api.latestRun(true, selectedTargetId), [selectedTargetId])

  const handleRunSuccess = () => { refresh(); refreshRun() }

  if (loading) return <LoadingSpinner label="Loading dashboard…" />
  if (error) return (
    <div>
      <PageHeader title="Dashboard" subtitle="PostgreSQL workload analysis & index recommendations" action={<RunButton onSuccess={handleRunSuccess} selectedTargetId={selectedTargetId} />} />
      <div className="p-8">
        <div className="mb-4 rounded-lg border border-red-600/40 bg-red-dim p-4 text-sm text-red-400 font-mono">
          Unable to connect to backend service.
        </div>
        <ErrorState message={error} onRetry={refresh} />
      </div>
    </div>
  )

  const latest = data?.latest_run
  const topRecs = data?.top_recommendations || []
  const recCounts = data?.recommendation_counts || []

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="PostgreSQL workload analysis & index recommendations"
        action={<RunButton onSuccess={handleRunSuccess} selectedTargetId={selectedTargetId} />}
      />
      <div className="p-8 space-y-8">

        {/* Run status */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <StatCard
            label="Latest Run"
            value={latest?.status ?? 'N/A'}
            sub={latest ? formatDate(latest.started_at) : 'No runs yet'}
            icon={Play}
            accent={latest?.status === 'COMPLETED'}
          />
          <StatCard
            label="Recommendations"
            value={recCounts.reduce((s, c) => s + (c.count || 0), 0)}
            sub="in latest run"
            icon={Lightbulb}
            accent
          />
          <StatCard
            label="Completed At"
            value={latest?.completed_at ? formatDate(latest.completed_at).split(',')[0] : '—'}
            sub={latest?.completed_at ? formatDate(latest.completed_at).split(',')[1]?.trim() : ''}
            icon={TrendingUp}
          />
        </div>

        {latest && <RunCountsCard latest={latest} />}

        {recCounts.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>By Validation Type</CardTitle>
            </CardHeader>
            <div className="p-5 space-y-4">
              <ValidationExplainer />
              <div className="flex gap-4 pt-2">
                {recCounts.map((r) => (
                  <div key={r.validation_type} className="flex items-center gap-2">
                    <Badge className={validationTypeColor(r.validation_type)}>{r.validation_type}</Badge>
                    <span className="text-sm font-mono text-text-primary font-semibold">{r.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Top Recommendations by Score</CardTitle>
            <button
              onClick={() => setPage('recommendations')}
              className="text-xs font-mono text-text-muted hover:text-green-400 transition-colors"
            >
              View all →
            </button>
          </CardHeader>
          {topRecs.length === 0 ? (
            <EmptyState message="No recommendations in latest run." />
          ) : (
            <div className="divide-y divide-bg-border/50">
              {topRecs.map((rec) => (
                <div key={rec.id} className="px-5 py-4 hover:bg-bg-hover transition-colors">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2 flex-wrap">
                        <Badge className={scoreColor(rec.score)}>{formatScore(rec.score)}</Badge>
                        <Badge className={validationTypeColor(rec.validation_type)}>{rec.validation_type}</Badge>
                        {rec.user_validation_improvement_pct != null && (
                          <Badge className="text-blue-400 bg-blue-dim border-blue-600">USER_VALIDATED</Badge>
                        )}
                        <span className="text-xs font-mono text-text-secondary">{rec.table_name}</span>
                        {rec.columns && (
                          <span className="text-xs font-mono text-text-muted">({rec.columns})</span>
                        )}
                      </div>
                      <SqlBlock sql={rec.recommended_index_sql} className="mt-2" />
                    </div>
                    <div className="text-right shrink-0">
                      {rec.improvement_pct != null && (
                        <p className="text-green-400 font-mono font-semibold text-sm">{formatPercent(rec.improvement_pct)}</p>
                      )}
                      <p className="text-xs text-text-muted mt-0.5">improvement</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

      </div>
    </div>
  )
}

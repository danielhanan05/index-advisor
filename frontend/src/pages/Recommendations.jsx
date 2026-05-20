import { useState } from 'react'
import { AlertTriangle, ArrowUpDown, History } from 'lucide-react'
import { api } from '../api/client'
import { useApi } from '../utils/useApi'
import { formatDate, formatPercent, formatScore, scoreColor, validationTypeColor, recommendationStatusColor, recommendationStatusLabel, truncate } from '../utils/format'
import { Badge, LoadingSpinner, ErrorState, EmptyState, RefreshButton, CopyButton, ValidationExplainer } from '../components/ui'
import { PageHeader } from '../components/Layout'
import { RecommendationModal } from '../components/RecommendationModal'

const VALIDATION_TYPES = ['', 'VALIDATED', 'SAMPLE_VALIDATED', 'USER_VALIDATED', 'HEURISTIC_ONLY']
const HISTORY_STATUS_FILTERS = ['', 'ACTIVE', 'RESOLVED_BY_EXISTING_INDEX', 'IGNORED', 'APPLIED', 'STALE', 'REJECTED']

function RecommendationsTable({
  items,
  sortField,
  sortDir,
  toggleSort,
  onSelect,
  showStatus = true,
  showRun = false,
}) {
  const sorted = [...items].sort((a, b) => {
    const v = sortDir === 'asc' ? 1 : -1
    if (sortField === 'score') return v * ((a.score ?? 0) - (b.score ?? 0))
    if (sortField === 'improvement_pct') return v * ((a.improvement_pct ?? 0) - (b.improvement_pct ?? 0))
    if (sortField === 'created_at') return v * (new Date(a.created_at || 0) - new Date(b.created_at || 0))
    return 0
  })

  const columns = [
    { key: 'score', label: 'Score', sortable: true },
    { key: 'table_name', label: 'Table' },
    { key: 'columns', label: 'Columns' },
    { key: 'improvement_pct', label: 'Improvement', sortable: true },
    { key: 'validation_type', label: 'Type' },
    ...(showStatus ? [{ key: 'status', label: 'Status' }] : []),
    { key: 'parameterized_query', label: 'Query' },
    { key: 'sampled_validation', label: 'Sampled' },
    { key: 'user_validated_at', label: 'User Validated' },
    ...(showRun ? [{ key: 'collection_run_id', label: 'Run' }] : []),
    { key: 'created_at', label: 'Created', sortable: true },
    { key: 'actions', label: '' },
  ]

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-bg-border">
            {columns.map(col => (
              <th
                key={col.key}
                className={`px-4 py-3 text-left text-xs font-mono text-text-muted uppercase tracking-wider whitespace-nowrap ${col.sortable ? 'cursor-pointer hover:text-text-primary' : ''}`}
                onClick={col.sortable ? () => toggleSort(col.key) : undefined}
              >
                <span className="flex items-center gap-1">
                  {col.label}
                  {col.sortable && <ArrowUpDown size={10} />}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((rec) => (
            <tr
              key={rec.id}
              className="border-b border-bg-border/50 hover:bg-bg-hover cursor-pointer transition-colors"
              onClick={() => onSelect(rec.id)}
            >
              <td className="px-4 py-3 whitespace-nowrap">
                <Badge className={scoreColor(rec.score)}>{formatScore(rec.score)}</Badge>
              </td>
              <td className="px-4 py-3 font-mono text-xs text-text-secondary whitespace-nowrap">{rec.table_name}</td>
              <td className="px-4 py-3 font-mono text-xs text-text-muted max-w-[160px] truncate">{rec.columns}</td>
              <td className="px-4 py-3 font-mono text-xs text-green-400 whitespace-nowrap">
                {rec.improvement_pct != null ? formatPercent(rec.improvement_pct) : '—'}
              </td>
              <td className="px-4 py-3 whitespace-nowrap">
                <div className="flex items-center gap-1">
                  {rec.validation_type === 'SAMPLE_VALIDATED' && (
                    <AlertTriangle size={12} className="text-amber-400" />
                  )}
                  <Badge className={validationTypeColor(rec.validation_type)}>
                    {rec.validation_type}
                  </Badge>
                  {rec.user_validated_at && (
                    <Badge className="text-blue-400 bg-blue-dim border-blue-600">USER_VALIDATED</Badge>
                  )}
                </div>
              </td>
              {showStatus && (
                <td className="px-4 py-3 whitespace-nowrap">
                  <Badge className={recommendationStatusColor(rec.status)}>
                    {recommendationStatusLabel(rec.status)}
                  </Badge>
                </td>
              )}
              <td className="px-4 py-3 font-mono text-xs text-text-muted max-w-[240px]">
                <span className="truncate block">{truncate(rec.normalized_query_text || rec.sampled_query_text || rec.queryid, 70)}</span>
              </td>
              <td className="px-4 py-3">
                {rec.sampled_validation ? (
                  <span className="text-xs font-mono text-amber-400">yes</span>
                ) : (
                  <span className="text-xs font-mono text-text-muted">no</span>
                )}
              </td>
              <td className="px-4 py-3">
                {rec.user_validated_at ? (
                  <span className="text-xs font-mono text-blue-400">yes</span>
                ) : (
                  <span className="text-xs font-mono text-text-muted">no</span>
                )}
              </td>
              {showRun && (
                <td className="px-4 py-3 font-mono text-[10px] text-text-muted max-w-[120px] truncate" title={rec.collection_run_id}>
                  {truncate(rec.collection_run_id, 12)}
                </td>
              )}
              <td className="px-4 py-3 font-mono text-xs text-text-muted whitespace-nowrap">
                {formatDate(rec.created_at)}
              </td>
              <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <CopyButton text={rec.recommended_index_sql} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RecommendationFilters({ filters, setFilters, historyMode = false, resultCount = 0 }) {
  return (
    <div className="flex gap-3 flex-wrap">
      <select
        value={filters.validation_type}
        onChange={(e) => setFilters(f => ({ ...f, validation_type: e.target.value }))}
        className="bg-bg-elevated border border-bg-border rounded-lg px-3 py-2 text-sm font-mono text-text-secondary focus:outline-none focus:border-green-600"
      >
        {VALIDATION_TYPES.map(t => <option key={t} value={t}>{t || 'All Types'}</option>)}
      </select>

      {historyMode && (
        <select
          value={filters.status}
          onChange={(e) => setFilters(f => ({ ...f, status: e.target.value }))}
          className="bg-bg-elevated border border-bg-border rounded-lg px-3 py-2 text-sm font-mono text-text-secondary focus:outline-none focus:border-green-600"
        >
          {HISTORY_STATUS_FILTERS.map(s => <option key={s || 'ALL'} value={s}>{s ? recommendationStatusLabel(s) : 'All Statuses'}</option>)}
        </select>
      )}

      <input
        type="text"
        placeholder="Filter by table name…"
        value={filters.table_name}
        onChange={(e) => setFilters(f => ({ ...f, table_name: e.target.value }))}
        className="bg-bg-elevated border border-bg-border rounded-lg px-3 py-2 text-sm font-mono text-text-secondary placeholder:text-text-muted focus:outline-none focus:border-green-600 w-52"
      />
      <input
        type="number"
        placeholder="Min score (0–100)"
        value={filters.min_score}
        onChange={(e) => setFilters(f => ({ ...f, min_score: e.target.value }))}
        min="0" max="100" step="1"
        className="bg-bg-elevated border border-bg-border rounded-lg px-3 py-2 text-sm font-mono text-text-secondary placeholder:text-text-muted focus:outline-none focus:border-green-600 w-44"
      />
      <span className="text-xs font-mono text-text-muted self-center ml-auto">{resultCount} results</span>
    </div>
  )
}

function RecommendationsListPage({
  selectedTargetId,
  historyMode = false,
}) {
  const [filters, setFilters] = useState({
    validation_type: '',
    status: '',
    table_name: '',
    min_score: '',
  })
  const [selectedId, setSelectedId] = useState(null)
  const [sortField, setSortField] = useState(historyMode ? 'created_at' : 'score')
  const [sortDir, setSortDir] = useState('desc')

  const params = {
    validation_type: filters.validation_type || undefined,
    table_name: filters.table_name || undefined,
    min_score: filters.min_score !== '' ? parseFloat(filters.min_score) : undefined,
    limit: historyMode ? 500 : 200,
    target_id: selectedTargetId,
  }

  if (historyMode && filters.status) params.status = filters.status
  if (!historyMode) params.status = 'ACTIVE'

  const { data, loading, error, refresh } = useApi(
    () => historyMode ? api.recommendationHistory(params) : api.recommendations(params),
    [historyMode, filters, selectedTargetId]
  )

  const items = data?.items || []

  const toggleSort = (field) => {
    if (sortField === field) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortField(field); setSortDir('desc') }
  }

  return (
    <div>
      <PageHeader
        title={historyMode ? 'Recommendation History' : 'Current Recommendations'}
        subtitle={historyMode
          ? 'Historical recommendations from all analysis runs for the selected database.'
          : 'Actionable index recommendations from the latest analysis run only.'}
        action={<RefreshButton onClick={refresh} loading={loading} />}
      />
      <div className="p-8 space-y-6">
        {!historyMode && <ValidationExplainer />}

        {historyMode ? (
          <div className="rounded-xl border border-bg-border bg-bg-surface p-4 flex gap-3 text-sm text-text-secondary">
            <History size={18} className="text-text-muted shrink-0 mt-0.5" />
            <div>
              <p className="font-medium text-text-primary">History keeps audit context without cluttering the current recommendation list.</p>
              <p className="mt-1">Recommendations that were resolved by an existing index, ignored, or created in older runs appear here. The Current Recommendations page stays focused on what should be reviewed now.</p>
            </div>
          </div>
        ) : null}

        <RecommendationFilters
          filters={filters}
          setFilters={setFilters}
          historyMode={historyMode}
          resultCount={items.length}
        />

        {loading && <LoadingSpinner />}
        {error && <ErrorState message={error} onRetry={refresh} />}
        {!loading && !error && (
          <div className="bg-bg-surface border border-bg-border rounded-xl overflow-hidden">
            {items.length === 0 ? (
              <EmptyState message={historyMode ? 'No historical recommendations match your filters.' : 'No current recommendations. If you recently created indexes, this is expected.'} />
            ) : (
              <RecommendationsTable
                items={items}
                sortField={sortField}
                sortDir={sortDir}
                toggleSort={toggleSort}
                onSelect={setSelectedId}
                showStatus={historyMode}
                showRun={historyMode}
              />
            )}
          </div>
        )}
      </div>

      {selectedId != null && (
        <RecommendationModal id={selectedId} onClose={() => setSelectedId(null)} />
      )}
    </div>
  )
}

export function RecommendationsPage({ selectedTargetId }) {
  return <RecommendationsListPage selectedTargetId={selectedTargetId} historyMode={false} />
}

export function RecommendationHistoryPage({ selectedTargetId }) {
  return <RecommendationsListPage selectedTargetId={selectedTargetId} historyMode={true} />
}

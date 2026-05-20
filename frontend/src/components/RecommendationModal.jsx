import { useMemo, useState } from 'react'
import { X, AlertTriangle, CheckCircle, Loader2 } from 'lucide-react'
import { useApi } from '../utils/useApi'
import { api } from '../api/client'
import { formatDate, formatPercent, formatScore, formatCost, scoreColor, validationTypeColor, recommendationStatusColor, recommendationStatusLabel } from '../utils/format'
import { Badge, SqlBlock, LoadingSpinner, ErrorState, SampleValidatedWarning, UserValidatedWarning, CopyButton } from '../components/ui'
import { ExecutionPlanViewer } from './ExecutionPlanViewer'

function Row({ label, value }) {
  return (
    <div className="flex gap-4 py-2.5 border-b border-bg-border/50 last:border-0">
      <dt className="text-xs font-mono text-text-muted uppercase tracking-wider w-40 shrink-0 pt-0.5">{label}</dt>
      <dd className="text-sm text-text-secondary break-all">{value ?? '—'}</dd>
    </div>
  )
}

function extractPlaceholders(queryText) {
  if (!queryText) return []
  const found = new Set()
  const dollarMatches = [...queryText.matchAll(/\$(\d+)\b/g)]
    .map((m) => `$${m[1]}`)
    .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)))
  dollarMatches.forEach((p) => found.add(p))

  const qmarkCount = (queryText.match(/\?/g) || []).length
  for (let i = 1; i <= qmarkCount; i += 1) found.add(`?${i}`)

  return [...found]
}

function parseBindValue(raw) {
  const value = String(raw ?? '').trim()
  if (value === '') return ''
  if (/^(true|false)$/i.test(value)) return value.toLowerCase() === 'true'
  if (/^null$/i.test(value)) return null
  if (/^-?\d+(\.\d+)?$/.test(value)) return Number(value)
  return value
}

function UserValidationResult({ result }) {
  if (!result) return null

  const queryText = result.query_text || result.rendered_query_text || result.user_validation_query_text
  const bindValues = result.bind_values || result.bind_values_json || result.user_validation_values_json
  const originalCost = result.original_cost ?? result.user_validation_original_cost
  const hypotheticalCost = result.hypothetical_cost ?? result.user_validation_hypothetical_cost
  const improvement = result.improvement_pct ?? result.user_validation_improvement_pct
  const originalPlan = result.original_plan_json ?? result.user_validation_original_plan_json
  const hypotheticalPlan = result.hypothetical_plan_json ?? result.user_validation_hypothetical_plan_json

  return (
    <div className="space-y-4 border border-blue-600/40 bg-blue-dim/20 rounded-lg p-4">
      <div className="flex items-center gap-2">
        <Badge className="text-blue-400 bg-blue-dim border-blue-600">USER_VALIDATED</Badge>
        <span className="text-xs font-mono text-text-muted">Revalidated with user-provided bind values</span>
      </div>
      <UserValidatedWarning />

      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Improvement', value: formatPercent(improvement) },
          { label: 'Original Cost', value: formatCost(originalCost) },
          { label: 'Hypo Cost', value: formatCost(hypotheticalCost) },
        ].map(({ label, value }) => (
          <div key={label} className="bg-bg-base border border-bg-border rounded-lg p-3">
            <p className="text-xs font-mono text-text-muted mb-1">{label}</p>
            <p className="text-sm font-mono font-medium text-text-primary">{value}</p>
          </div>
        ))}
      </div>

      {queryText && (
        <div>
          <p className="text-xs font-mono text-text-muted uppercase tracking-wider mb-2">User-Validated Query</p>
          <SqlBlock sql={queryText} />
        </div>
      )}

      {bindValues && (
        <div>
          <p className="text-xs font-mono text-text-muted uppercase tracking-wider mb-2">User Bind Values</p>
          <div className="relative group">
            <pre className="bg-bg-base border border-bg-border rounded-lg p-4 text-xs font-mono text-blue-400 overflow-x-auto whitespace-pre-wrap break-all">
              {typeof bindValues === 'string' ? bindValues : JSON.stringify(bindValues, null, 2)}
            </pre>
            <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
              <CopyButton text={typeof bindValues === 'string' ? bindValues : JSON.stringify(bindValues, null, 2)} />
            </div>
          </div>
        </div>
      )}

      <details className="bg-bg-base border border-bg-border rounded-lg p-4">
        <summary className="cursor-pointer text-sm font-medium text-text-primary">User Validation Execution Plans</summary>
        <div className="mt-4 space-y-4">
          <ExecutionPlanViewer
            title="User Validation Original Plan"
            plan={originalPlan}
            emptyMessage="No user-validation original plan is available yet."
          />
          <ExecutionPlanViewer
            title="User Validation Hypothetical Plan"
            plan={hypotheticalPlan}
            emptyMessage="No user-validation hypothetical plan is available yet."
          />
        </div>
      </details>
    </div>
  )
}

function RevalidateSection({ rec, onValidated }) {
  const placeholders = useMemo(() => extractPlaceholders(rec.normalized_query_text), [rec.normalized_query_text])
  const [values, setValues] = useState(() => Object.fromEntries(placeholders.map((p) => [p, ''])))
  const [state, setState] = useState('idle')
  const [message, setMessage] = useState('')

  if (!placeholders.length) return null

  const canSubmit = placeholders.every((p) => String(values[p] ?? '').trim() !== '') && state !== 'loading'

  const submit = async () => {
    setState('loading')
    setMessage('')
    try {
      const bindValues = Object.fromEntries(
        placeholders.map((p) => [p, parseBindValue(values[p])])
      )
      const result = await api.revalidateRecommendation(rec.id, bindValues)
      setState('success')
      setMessage('Revalidation completed successfully.')
      onValidated?.(result)
    } catch (e) {
      setState('error')
      setMessage(e.message || 'Revalidation failed.')
    }
  }

  return (
    <div className="border border-bg-border rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-bg-border bg-bg-base flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-mono text-text-muted uppercase tracking-wider">Revalidate with Real Values</p>
          <p className="text-xs text-text-secondary mt-1">
            Enter real bind values to rerun EXPLAIN + HypoPG validation without changing the target database.
          </p>
        </div>
        {state === 'success' && <CheckCircle size={16} className="text-green-400" />}
        {state === 'error' && <AlertTriangle size={16} className="text-red-400" />}
      </div>

      <div className="p-4 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {placeholders.map((ph) => (
            <label key={ph} className="space-y-1.5">
              <span className="text-xs font-mono text-text-muted">{ph}</span>
              <input
                value={values[ph] ?? ''}
                onChange={(e) => setValues((prev) => ({ ...prev, [ph]: e.target.value }))}
                placeholder={`Value for ${ph}`}
                className="w-full bg-bg-elevated border border-bg-border rounded-lg px-3 py-2 text-sm font-mono text-text-primary placeholder:text-text-muted focus:outline-none focus:border-blue-600"
              />
            </label>
          ))}
        </div>

        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-text-muted font-mono">
            Values are sent to the API and rendered safely as PostgreSQL literals before validation.
          </p>
          <button
            onClick={submit}
            disabled={!canSubmit}
            className="shrink-0 inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-blue-600/50 bg-blue-dim text-blue-400 hover:bg-blue-600/20 disabled:opacity-50 disabled:cursor-not-allowed text-xs font-mono transition-colors"
          >
            {state === 'loading' && <Loader2 size={13} className="animate-spin" />}
            Revalidate
          </button>
        </div>

        {message && (
          <p className={`text-xs font-mono ${state === 'error' ? 'text-red-400' : 'text-green-400'}`}>{message}</p>
        )}
      </div>
    </div>
  )
}

function latestValidation(validations, type) {
  if (!Array.isArray(validations)) return null
  return validations.find((v) => v.validation_type === type) || null
}

function selectedValidation(validations) {
  if (!Array.isArray(validations)) return null
  return validations.find((v) => v.is_selected_option && v.validation_type !== 'USER_VALIDATION')
    || validations.find((v) => v.validation_type !== 'USER_VALIDATION')
    || null
}

export function RecommendationModal({ id, onClose }) {
  const { data: rec, loading, error } = useApi(() => api.recommendation(id), [id])
  const [userValidation, setUserValidation] = useState(null)

  const selectedAutoValidation = selectedValidation(rec?.validations)
  const storedUserValidation = latestValidation(rec?.validations, 'USER_VALIDATION')
  const effectiveUserValidation = userValidation || storedUserValidation

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 pt-8 pb-8 px-4 overflow-y-auto">
      <div className="w-full max-w-5xl bg-bg-surface border border-bg-border rounded-xl shadow-2xl">
        <div className="flex items-center justify-between px-6 py-5 border-b border-bg-border">
          <div className="flex items-center gap-3 flex-wrap">
            <h2 className="font-display font-bold text-base text-text-primary">Recommendation Details</h2>
            {rec && (
              <>
                <Badge className={scoreColor(rec.score)}>{formatScore(rec.score)}</Badge>
                <Badge className={validationTypeColor(rec.validation_type)}>{rec.validation_type}</Badge>
                <Badge className={recommendationStatusColor(rec.status)}>{recommendationStatusLabel(rec.status)}</Badge>
                {effectiveUserValidation && <Badge className="text-blue-400 bg-blue-dim border-blue-600">USER_VALIDATED</Badge>}
              </>
            )}
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors">
            <X size={18} />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {loading && <LoadingSpinner />}
          {error && <ErrorState message={error} />}
          {rec && (
            <>
              {rec.validation_type === 'SAMPLE_VALIDATED' && <SampleValidatedWarning />}

              <div>
                <p className="text-xs font-mono text-text-muted uppercase tracking-wider mb-2">Recommended Index SQL</p>
                <SqlBlock sql={rec.recommended_index_sql} />
              </div>

              {rec.reason && (
                <div>
                  <p className="text-xs font-mono text-text-muted uppercase tracking-wider mb-2">Reason</p>
                  <p className="text-sm text-text-secondary leading-relaxed bg-bg-elevated border border-bg-border rounded-lg p-4">{rec.reason}</p>
                </div>
              )}

              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: 'Score', value: formatScore(rec.score) },
                  { label: 'Improvement', value: formatPercent(rec.improvement_pct) },
                  { label: 'Original Cost', value: formatCost(rec.original_cost) },
                  { label: 'Hypo Cost', value: formatCost(rec.hypothetical_cost) },
                  { label: 'Validated', value: rec.validated ? 'Yes' : 'No' },
                  { label: 'Created', value: formatDate(rec.created_at) },
                  { label: 'Status', value: recommendationStatusLabel(rec.status) },
                ].map(({ label, value }) => (
                  <div key={label} className="bg-bg-base border border-bg-border rounded-lg p-3">
                    <p className="text-xs font-mono text-text-muted mb-1">{label}</p>
                    <p className="text-sm font-mono font-medium text-text-primary">{value}</p>
                  </div>
                ))}
              </div>

              {rec.status_reason && (
                <div>
                  <p className="text-xs font-mono text-text-muted uppercase tracking-wider mb-2">Status Reason</p>
                  <p className="text-sm text-text-secondary leading-relaxed bg-bg-elevated border border-bg-border rounded-lg p-4">{rec.status_reason}</p>
                </div>
              )}

              <dl>
                <Row label="Schema" value={rec.schemaname} />
                <Row label="Table" value={rec.table_name} />
                <Row label="Columns" value={Array.isArray(rec.columns) ? rec.columns.join(', ') : rec.columns} />
                <Row label="Query ID" value={rec.queryid} />
              </dl>

              {rec.normalized_query_text && (
                <div>
                  <p className="text-xs font-mono text-text-muted uppercase tracking-wider mb-2">Normalized Query</p>
                  <SqlBlock sql={rec.normalized_query_text} />
                </div>
              )}

              {rec.sampled_query_text && (
                <div>
                  <p className="text-xs font-mono text-text-muted uppercase tracking-wider mb-2">Sampled Query Text</p>
                  <SqlBlock sql={rec.sampled_query_text} />
                </div>
              )}

              {selectedAutoValidation?.bind_values_json && (
                <div>
                  <p className="text-xs font-mono text-text-muted uppercase tracking-wider mb-2">Sampled Values (JSON)</p>
                  <div className="relative group">
                    <pre className="bg-bg-base border border-bg-border rounded-lg p-4 text-xs font-mono text-blue-400 overflow-x-auto whitespace-pre-wrap break-all">
                      {typeof selectedAutoValidation.bind_values_json === 'string'
                        ? selectedAutoValidation.bind_values_json
                        : JSON.stringify(selectedAutoValidation.bind_values_json, null, 2)}
                    </pre>
                    <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <CopyButton text={typeof selectedAutoValidation.bind_values_json === 'string' ? selectedAutoValidation.bind_values_json : JSON.stringify(selectedAutoValidation.bind_values_json, null, 2)} />
                    </div>
                  </div>
                </div>
              )}

              <details className="bg-bg-elevated border border-bg-border rounded-lg p-4" open>
                <summary className="cursor-pointer text-sm font-medium text-text-primary">Execution Plans</summary>
                <div className="mt-4 space-y-4">
                  <ExecutionPlanViewer
                    title="Collected Plan"
                    plan={rec.collected_plan_json}
                    emptyMessage={rec.parameterized_query
                      ? 'No collected plan was captured because the original query used bind parameters. Use the validation plans below for the sampled/user-provided values.'
                      : 'No collected execution plan was captured for this query.'}
                  />
                  <ExecutionPlanViewer
                    title="Validation Original Plan"
                    plan={selectedAutoValidation?.original_plan_json || rec.validation_original_plan_json}
                    emptyMessage="No validation original plan is available for this recommendation."
                  />
                  <ExecutionPlanViewer
                    title="Validation Hypothetical Plan"
                    plan={selectedAutoValidation?.hypothetical_plan_json || rec.validation_hypothetical_plan_json}
                    emptyMessage="No validation hypothetical plan is available for this recommendation."
                  />
                </div>
              </details>

              {Array.isArray(rec.alternative_options_json) && rec.alternative_options_json.length > 0 && (
                <details className="bg-bg-elevated border border-bg-border rounded-lg p-4">
                  <summary className="cursor-pointer text-sm font-medium text-text-primary">
                    Tested Index Options ({rec.alternative_options_json.length})
                  </summary>
                  <div className="mt-4 space-y-4">
                    {rec.alternative_options_json.map((option, index) => {
                      const optionValidation = Array.isArray(rec.validations)
                        ? rec.validations.find((v) => v.index_sql === option.index_sql)
                        : null
                      return (
                      <div key={`${option.index_sql || index}`} className="border border-bg-border rounded-lg p-3 bg-bg-base">
                        <div className="flex items-center gap-2 mb-2 flex-wrap">
                          <Badge className={option.selected ? 'text-green-400 bg-green-dim border-green-600' : 'text-text-muted bg-bg-surface border-bg-border'}>
                            {option.selected ? 'SELECTED' : `OPTION ${option.rank || index + 1}`}
                          </Badge>
                          {option.candidate_type && <Badge>{option.candidate_type}</Badge>}
                          {option.improvement_pct != null && <span className="text-xs font-mono text-text-muted">Improvement: {formatPercent(option.improvement_pct)}</span>}
                        </div>
                        {option.reason && <p className="text-xs text-text-secondary mb-2">{option.reason}</p>}
                        <SqlBlock sql={option.index_sql || ''} />
                        {(optionValidation?.original_plan_json || optionValidation?.hypothetical_plan_json) && (
                          <details className="mt-3 border border-bg-border rounded-lg p-3 bg-bg-elevated">
                            <summary className="cursor-pointer text-xs font-mono text-text-muted uppercase tracking-wider">Option Execution Plans</summary>
                            <div className="mt-3 space-y-3">
                              <ExecutionPlanViewer title="Option Original Plan" plan={optionValidation?.original_plan_json} />
                              <ExecutionPlanViewer title="Option Hypothetical Plan" plan={optionValidation?.hypothetical_plan_json} />
                            </div>
                          </details>
                        )}
                      </div>
                      )
                    })}
                  </div>
                </details>
              )}

              <RevalidateSection rec={rec} onValidated={setUserValidation} />
              <UserValidationResult result={effectiveUserValidation} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

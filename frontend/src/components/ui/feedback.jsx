import { AlertTriangle, XCircle } from 'lucide-react'
import { getErrorDetail } from '../../utils/errors'

export function ErrorState({ message, onRetry }) {
  const detail = getErrorDetail(message)
  return (
    <div className="flex flex-col items-center gap-3 py-10 text-red-400 text-center">
      <AlertTriangle size={24} />
      {detail?.title && <p className="text-sm font-display font-semibold">{detail.title}</p>}
      <p className="text-sm font-mono">{detail?.message || String(message || 'Unknown error')}</p>
      {Array.isArray(detail?.action_items) && detail.action_items.length > 0 && (
        <ul className="max-w-xl text-left text-xs text-text-secondary space-y-1 list-disc list-inside">
          {detail.action_items.map((item, i) => <li key={i}>{item}</li>)}
        </ul>
      )}
      {onRetry && (
        <button onClick={onRetry} className="text-xs text-text-secondary hover:text-text-primary underline">
          Retry
        </button>
      )}
    </div>
  )
}

export function EmptyState({ message = 'No data available.' }) {
  return (
    <div className="flex items-center justify-center py-10 text-text-muted">
      <p className="text-sm font-mono">{message}</p>
    </div>
  )
}

export function ErrorDialog({ error, onClose, title = 'Action failed' }) {
  if (!error) return null

  const detail = error.detail || error.error_detail || error
  const dialogTitle = detail.title || title
  const message = detail.message || (typeof error === 'string' ? error : error.message) || 'An unexpected error occurred.'
  const details = detail.details || detail.raw_error || ''
  const actionItems = detail.action_items || []
  const errorType = detail.error_type

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 px-4 py-8 overflow-y-auto">
      <div className="w-full max-w-4xl rounded-xl border border-red-600/60 bg-bg-surface shadow-2xl shadow-red-950/40">
        <div className="flex items-start justify-between gap-4 border-b border-red-600/30 bg-red-dim px-5 py-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="text-red-400 shrink-0 mt-0.5" size={24} />
            <div>
              <p className="text-xs font-mono uppercase tracking-widest text-red-300">{errorType || 'ERROR'}</p>
              <h2 className="mt-1 font-display text-lg font-bold text-red-200">{dialogTitle}</h2>
              <p className="mt-2 text-sm text-red-100 leading-relaxed">{message}</p>
            </div>
          </div>
          {onClose && (
            <button onClick={onClose} className="rounded-lg p-1 text-red-200 hover:bg-red-950/40 hover:text-white">
              <XCircle size={22} />
            </button>
          )}
        </div>

        <div className="space-y-5 p-5">
          {actionItems.length > 0 && (
            <div className="rounded-lg border border-amber-600/40 bg-amber-dim p-4">
              <h3 className="mb-2 text-sm font-semibold text-amber-300">How to fix it</h3>
              <ol className="list-decimal space-y-1 pl-5 text-sm text-amber-100">
                {actionItems.map((item, i) => <li key={i}>{item}</li>)}
              </ol>
            </div>
          )}

          {details && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-text-primary">Technical details</h3>
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-bg-border bg-bg-base p-4 text-xs font-mono leading-relaxed text-red-300">
                {details}
              </pre>
            </div>
          )}

          <div className="flex justify-end">
            <button onClick={onClose} className="rounded-lg border border-bg-border bg-bg-elevated px-4 py-2 text-sm font-mono text-text-primary hover:border-red-500">
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

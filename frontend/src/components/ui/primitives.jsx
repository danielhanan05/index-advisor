import { Fragment, useState } from 'react'
import { Copy, Check, RefreshCw, Loader2, ChevronDown, ChevronUp } from 'lucide-react'
import { copyToClipboard } from '../../utils/format'

export function Badge({ children, className = '' }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-mono font-medium rounded border ${className}`}>
      {children}
    </span>
  )
}

export function Card({ children, className = '' }) {
  return <div className={`bg-bg-surface border border-bg-border rounded-lg ${className}`}>{children}</div>
}

export function CardHeader({ children, className = '' }) {
  return <div className={`px-5 py-4 border-b border-bg-border flex items-center justify-between ${className}`}>{children}</div>
}

export function CardTitle({ children, className = '' }) {
  return <h3 className={`font-display font-semibold text-sm text-text-primary tracking-wide uppercase ${className}`}>{children}</h3>
}

export function StatCard({ label, value, sub, icon: Icon, accent = false }) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-mono text-text-muted uppercase tracking-widest mb-2">{label}</p>
          <p className={`text-2xl font-display font-bold ${accent ? 'text-green-400' : 'text-text-primary'}`}>{value}</p>
          {sub && <p className="text-xs text-text-secondary mt-1">{sub}</p>}
        </div>
        {Icon && (
          <div className={`p-2 rounded-lg ${accent ? 'bg-green-dim text-green-400' : 'bg-bg-elevated text-text-muted'}`}>
            <Icon size={16} />
          </div>
        )}
      </div>
    </Card>
  )
}

export function CopyButton({ text, size = 14 }) {
  const [copied, setCopied] = useState(false)
  const handle = async () => {
    const ok = await copyToClipboard(text)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    }
  }
  return (
    <button onClick={handle} title="Copy" className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-bg-elevated transition-colors">
      {copied ? <Check size={size} className="text-green-400" /> : <Copy size={size} />}
    </button>
  )
}

export function LoadingSpinner({ label = 'Loading…' }) {
  return (
    <div className="flex items-center gap-2 text-text-muted py-8 justify-center">
      <Loader2 size={16} className="animate-spin" />
      <span className="text-sm font-mono">{label}</span>
    </div>
  )
}

export function RefreshButton({ onClick, loading }) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono text-text-secondary hover:text-text-primary bg-bg-elevated hover:bg-bg-hover border border-bg-border rounded transition-colors disabled:opacity-50"
    >
      <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
      Refresh
    </button>
  )
}

export function Table({ columns, rows, onRowClick, expandable }) {
  const [expanded, setExpanded] = useState({})

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-bg-border">
            {expandable && <th className="w-8" />}
            {columns.map((col) => (
              <th key={col.key} className="px-4 py-3 text-left text-xs font-mono text-text-muted uppercase tracking-wider whitespace-nowrap">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <Fragment key={row.id || i}>
              <tr
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={`border-b border-bg-border/50 transition-colors ${onRowClick ? 'cursor-pointer hover:bg-bg-hover' : ''}`}
              >
                {expandable && (
                  <td className="pl-3 pr-1 py-3">
                    <button
                      onClick={(e) => { e.stopPropagation(); setExpanded(prev => ({ ...prev, [i]: !prev[i] })) }}
                      className="text-text-muted hover:text-text-primary"
                    >
                      {expanded[i] ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </button>
                  </td>
                )}
                {columns.map((col) => (
                  <td key={col.key} className="px-4 py-3 text-text-secondary whitespace-nowrap">
                    {col.render ? col.render(row[col.key], row) : row[col.key] ?? '—'}
                  </td>
                ))}
              </tr>
              {expandable && expanded[i] && (
                <tr className="bg-bg-base border-b border-bg-border/50">
                  <td />
                  <td colSpan={columns.length} className="px-4 py-4">
                    {expandable(row)}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}

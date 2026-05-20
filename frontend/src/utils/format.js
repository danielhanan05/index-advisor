export function formatDate(ts) {
  if (!ts) return '—'
  const d = new Date(ts)
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
  })
}

export function formatDateShort(ts) {
  if (!ts) return '—'
  const d = new Date(ts)
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
    hour12: false,
  })
}

export function formatNumber(n) {
  if (n == null) return '—'
  return Number(n).toLocaleString()
}

export function formatPercent(n) {
  if (n == null) return '—'
  return `${Number(n).toFixed(1)}%`
}

export function formatScore(n) {
  if (n == null) return '—'
  return Number(n).toFixed(2)
}

export function formatDuration(ms) {
  if (ms == null) return '—'
  if (ms < 1) return `${(ms * 1000).toFixed(0)}µs`
  if (ms < 1000) return `${ms.toFixed(2)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function formatCost(n) {
  if (n == null) return '—'
  return Number(n).toFixed(2)
}

export function truncate(str, len = 80) {
  if (!str) return '—'
  return str.length > len ? str.slice(0, len) + '…' : str
}

export function scoreColor(score) {
  const n = Number(score ?? 0)
  if (n >= 80) return 'text-green-400 bg-green-dim border-green-600'
  if (n >= 50) return 'text-amber-400 bg-amber-dim border-amber-600'
  return 'text-red-400 bg-red-dim border-red-600'
}

export function validationTypeColor(vt) {
  switch (vt) {
    case 'VALIDATED': return 'text-green-400 bg-green-dim border-green-600'
    case 'SAMPLE_VALIDATED': return 'text-amber-400 bg-amber-dim border-amber-600'
    case 'USER_VALIDATED': return 'text-blue-400 bg-blue-dim border-blue-600'
    case 'HEURISTIC_ONLY': return 'text-text-secondary bg-bg-elevated border-bg-border'
    default: return 'text-text-muted bg-bg-elevated border-bg-border'
  }
}

export function statusColor(status) {
  switch (status) {
    case 'COMPLETED': return 'text-green-400 bg-green-dim border-green-600'
    case 'RUNNING': return 'text-blue-400 bg-blue-dim border-blue-600'
    case 'FAILED': return 'text-red-400 bg-red-dim border-red-600'
    default: return 'text-text-secondary bg-bg-elevated border-bg-border'
  }
}

export function recommendationStatusColor(status) {
  switch (status) {
    case 'ACTIVE': return 'text-green-400 bg-green-dim border-green-600'
    case 'APPLIED': return 'text-blue-400 bg-blue-dim border-blue-600'
    case 'RESOLVED_BY_EXISTING_INDEX': return 'text-purple-400 bg-purple-500/10 border-purple-600'
    case 'STALE': return 'text-amber-400 bg-amber-dim border-amber-600'
    case 'REJECTED': return 'text-red-400 bg-red-dim border-red-600'
    case 'IGNORED': return 'text-text-muted bg-bg-elevated border-bg-border'
    default: return 'text-text-secondary bg-bg-elevated border-bg-border'
  }
}

export function recommendationStatusLabel(status) {
  switch (status) {
    case 'ACTIVE': return 'Active'
    case 'APPLIED': return 'Applied'
    case 'RESOLVED_BY_EXISTING_INDEX': return 'Resolved by existing index'
    case 'STALE': return 'Not seen recently'
    case 'REJECTED': return 'Rejected'
    case 'IGNORED': return 'Ignored'
    default: return status || 'Unknown'
  }
}

export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

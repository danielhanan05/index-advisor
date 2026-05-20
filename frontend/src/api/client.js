const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''
const REQUEST_TIMEOUT_MS = 15_000
const ADMIN_TOKEN = import.meta.env.VITE_INDEX_ADVISOR_ADMIN_TOKEN || ''


const BACKEND_UNAVAILABLE_DETAIL = {
  error_type: 'BACKEND_UNAVAILABLE',
  title: 'Backend or network unavailable',
  message: 'The frontend could not reach the backend API.',
  details: 'This usually means the backend process is stopped, restarting, listening on a different port, blocked by CORS/firewall, or the network connection was interrupted.',
  action_items: [
    'In development, verify the backend is running on http://localhost:8000.',
    'Check the backend terminal for a Python traceback or startup error.',
    'In development, verify VITE_API_BASE_URL points to the correct backend URL.',
    'Check firewall, proxy, VPN, Docker, VM, or network rules if the backend is not local.',
    'Refresh the page after the backend finishes restarting.',
  ],
  raw_error: 'Failed to fetch',
}

const DB_TIMEOUT_DETAIL = {
  error_type: 'REQUEST_TIMEOUT',
  title: 'Request timed out',
  message: 'The app did not receive a response within 15 seconds.',
  details: 'The database or backend may be unavailable, unreachable, or blocked by the network.',
  action_items: [
    'Verify the PostgreSQL service is running.',
    'Check that the database host and port are correct.',
    'Check firewall, Docker, VM, VPN, or network routing rules.',
    'Verify PostgreSQL is listening on the expected address and port.',
    'Verify pg_hba.conf allows this client/user to connect.',
    'Check SSL mode if the server requires or rejects SSL connections.',
  ],
  raw_error: 'Frontend request timed out after 15 seconds.',
  context: { timeout_seconds: 15 },
}

export class ApiError extends Error {
  constructor(message, { status, detail, body } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.body = body
  }
}

function normalizeErrorDetail(status, rawBody, statusText) {
  if (!rawBody) {
    return {
      title: `HTTP ${status}`,
      message: statusText || 'Request failed',
      details: '',
      action_items: [],
      raw_error: statusText || '',
    }
  }

  try {
    const parsed = JSON.parse(rawBody)
    if (parsed && typeof parsed.detail === 'object' && parsed.detail !== null) return parsed.detail
    if (parsed && typeof parsed.detail === 'string') {
      return {
        title: `HTTP ${status}`,
        message: parsed.detail,
        details: parsed.detail,
        action_items: [],
        raw_error: parsed.detail,
      }
    }
  } catch (_) {
    // fall through to raw text
  }

  return {
    title: `HTTP ${status}`,
    message: rawBody || statusText || 'Request failed',
    details: rawBody || '',
    action_items: [],
    raw_error: rawBody || '',
  }
}

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  try {
    const res = await fetch(url, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(ADMIN_TOKEN ? { 'X-Index-Advisor-Token': ADMIN_TOKEN } : {}), ...options.headers },
      credentials: 'include',
      signal: controller.signal,
    })

    if (!res.ok) {
      const body = await res.text().catch(() => '')
      const detail = normalizeErrorDetail(res.status, body, res.statusText)
      throw new ApiError(`${detail.title || `HTTP ${res.status}`}: ${detail.message || res.statusText}`, {
        status: res.status,
        detail,
        body,
      })
    }
    return res.json()
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new ApiError(`${DB_TIMEOUT_DETAIL.title}: ${DB_TIMEOUT_DETAIL.message}`, {
        status: 0,
        detail: DB_TIMEOUT_DETAIL,
        body: DB_TIMEOUT_DETAIL.raw_error,
      })
    }
    if (error instanceof TypeError && String(error.message || '').toLowerCase().includes('failed to fetch')) {
      throw new ApiError(`${BACKEND_UNAVAILABLE_DETAIL.title}: ${BACKEND_UNAVAILABLE_DETAIL.message}`, {
        status: 0,
        detail: BACKEND_UNAVAILABLE_DETAIL,
        body: BACKEND_UNAVAILABLE_DETAIL.raw_error,
      })
    }
    throw error
  } finally {
    window.clearTimeout(timeoutId)
  }
}


async function dangerousRequest(path, options = {}) {
  // A local admin cookie can become missing/stale after backend restart, browser cleanup,
  // or token regeneration. Bootstrap it immediately before protected write endpoints.
  await request('/auth/local-session', { method: 'POST' })
  return request(path, options)
}

function withTarget(params = {}) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  })
  const qs = q.toString()
  return qs ? `?${qs}` : ''
}

export const api = {
  authSession: () => request('/auth/local-session', { method: 'POST' }),
  health: () => request('/health'),
  setupStatus: () => request('/setup/status'),
  engines: () => request('/engines'),
  targets: () => request('/targets'),
  createTarget: (payload) => dangerousRequest('/targets', { method: 'POST', body: JSON.stringify(payload) }),
  testTargetConnection: (payload) => dangerousRequest('/setup/test-target-connection', { method: 'POST', body: JSON.stringify(payload) }),
  checkTargetExtensions: (id) => dangerousRequest(`/targets/${id}/check-extensions`, { method: 'POST' }),
  settings: () => request('/settings'),
  updateSettings: (payload) => dangerousRequest('/settings', { method: 'PUT', body: JSON.stringify(payload) }),
  schedulerStatus: () => request('/scheduler/status'),

  summary: (targetId) => request(`/summary${withTarget({ target_id: targetId })}`),

  runs: (params = {}) => request(`/runs${withTarget(params)}`),
  latestRun: (completedOnly = true, targetId) =>
    request(`/runs/latest${withTarget({ completed_only: completedOnly, target_id: targetId })}`),
  run: (id) => request(`/runs/${id}`),
  runRecommendations: (runId, params = {}) => request(`/runs/${runId}/recommendations${withTarget(params)}`),
  triggerRun: (targetId) => dangerousRequest(`/runs/manual${withTarget({ target_id: targetId })}`, { method: 'POST' }),

  recommendations: (params = {}) => request(`/recommendations${withTarget(params)}`),
  recommendationHistory: (params = {}) => request(`/recommendations/history${withTarget(params)}`),
  recommendation: (id) => request(`/recommendations/${id}`),
  revalidateRecommendation: (id, bindValues) => dangerousRequest(`/recommendations/${id}/revalidate`, {
    method: 'POST',
    body: JSON.stringify({ bind_values: bindValues }),
  }),
  applyRecommendation: (id) => dangerousRequest(`/recommendations/${id}/apply`, {
    method: 'POST',
    body: JSON.stringify({ confirm: 'APPLY' }),
  }),

  queryStats: (params = {}) => request(`/query-stats${withTarget(params)}`),
  tableStats: (params = {}) => request(`/table-stats${withTarget(params)}`),
  indexStats: (params = {}) => request(`/index-stats${withTarget(params)}`),
}

export function getErrorDetail(error) {
  if (!error) return null
  if (typeof error === 'string') return { message: error, title: '', action_items: [] }
  if (error.detail) return error.detail
  return { message: error.message || 'Unknown error', title: '', action_items: [] }
}

export function getErrorMessage(error) {
  const detail = getErrorDetail(error)
  if (!detail) return ''
  return detail.message || detail.title || String(error)
}

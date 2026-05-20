import { useState, useEffect, useCallback, useRef } from 'react'

/**
 * Generic data-fetching hook.
 *
 * @param {function} fetcher  - async function that returns data; re-created when deps change
 * @param {Array}    deps     - dependency array (same semantics as useEffect/useCallback)
 *
 * The hook stores the latest fetcher in a ref so that stale-closure issues
 * (e.g. a fetcher that captures a now-outdated prop) are avoided while still
 * allowing React to track when a genuine re-fetch is needed through `deps`.
 */
export function useApi(fetcher, deps = []) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  // Always call the latest version of fetcher without adding it to deps
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await fetcherRef.current()
      setData(result)
    } catch (e) {
      setError(e)
    } finally {
      setLoading(false)
    }
  // deps intentionally drives re-fetching; fetcherRef.current handles the closure
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => { load() }, [load])

  return { data, loading, error, refresh: load }
}

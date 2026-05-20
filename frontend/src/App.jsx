import { useEffect, useState } from 'react'
import { Layout } from './components/Layout'
import { SetupPage } from './pages/Setup'
import { api } from './api/client'
import { LoadingSpinner, ErrorState } from './components/ui'
import { renderPage } from './navigation/renderPage'

export default function App() {
  const [page, setPage] = useState('dashboard')
  const [setup, setSetup] = useState(null)
  const [setupError, setSetupError] = useState(null)
  const [selectedTargetId, setSelectedTargetId] = useState(null)

  const loadSetup = async () => {
    setSetupError(null)
    try {
      // Creates the local admin cookie used for dangerous write endpoints.
      // Read-only endpoints still work without it, but setup/run/apply/settings need it.
      await api.authSession().catch((error) => {
        console.warn('Local admin session could not be created.', error)
      })
      const s = await api.setupStatus()
      setSetup(s)
      const defaultId = s.default_target?.id || s.targets?.[0]?.id || null
      setSelectedTargetId(prev => prev || defaultId)
    } catch (e) {
      setSetupError(e)
    }
  }

  useEffect(() => { loadSetup() }, [])

  if (setupError) {
    return <div className="min-h-screen bg-bg-base text-text-primary p-8"><ErrorState message={setupError} onRetry={loadSetup} /></div>
  }

  if (!setup) return <div className="min-h-screen bg-bg-base"><LoadingSpinner label="Loading setup…" /></div>

  if (!setup.setup_complete) {
    return <SetupPage setupError={setup.storage_error} onComplete={() => loadSetup()} />
  }

  const targets = setup.targets || []

  return (
    <Layout
      page={page}
      setPage={setPage}
      targets={targets}
      selectedTargetId={selectedTargetId}
      setSelectedTargetId={setSelectedTargetId}
      onTargetsChanged={loadSetup}
    >
      {renderPage({ page, selectedTargetId, setPage })}
    </Layout>
  )
}

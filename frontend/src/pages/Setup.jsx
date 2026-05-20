import { useEffect, useState } from 'react'
import { Database, CheckCircle, AlertTriangle, Loader2, Lock } from 'lucide-react'
import { api } from '../api/client'
import { Card, CardHeader, CardTitle, Badge, SqlBlock, ErrorDialog } from '../components/ui'

const initial = {
  engine: 'postgres',
  name: 'Production DB',
  host: 'localhost',
  port: 5432,
  database_name: '',
  username: '',
  password: '',
  sslmode: 'prefer',
  is_default: true,
}

export function SetupPage({ onComplete, setupError }) {
  const [form, setForm] = useState(initial)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [saveResult, setSaveResult] = useState(null)
  const [error, setError] = useState('')
  const [dialogError, setDialogError] = useState(null)
  const [engines, setEngines] = useState([
    { engine: 'postgres', display_name: 'PostgreSQL', default_port: 5432, status: 'available', description: 'Fully supported in this version.' },
    { engine: 'mssql', display_name: 'Microsoft SQL Server', default_port: 1433, status: 'coming_soon', description: 'Coming soon.' },
    { engine: 'oracle', display_name: 'Oracle Database', default_port: 1521, status: 'coming_soon', description: 'Coming soon.' },
  ])

  useEffect(() => {
    if (setupError) setDialogError(setupError)
  }, [setupError])

  useEffect(() => {
    api.engines()
      .then(result => { if (result?.items?.length) setEngines(result.items) })
      .catch(() => {})
  }, [])

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))

  const selectedEngine = engines.find(e => e.engine === form.engine) || engines[0]
  const selectedEngineAvailable = selectedEngine?.status === 'available'

  const chooseEngine = (engine) => {
    const meta = engines.find(e => e.engine === engine)
    if (!meta || meta.status !== 'available') return
    setForm(f => ({ ...f, engine, port: Number(f.port || meta.default_port || 5432) }))
  }

  const payload = () => ({ ...form, port: Number(form.port || selectedEngine?.default_port || 5432) })

  const test = async () => {
    setTesting(true); setError(''); setDialogError(null); setTestResult(null)
    try {
      const result = await api.testTargetConnection(payload())
      setTestResult(result)
      if (!result.ok) setDialogError(result.error_detail || { title: 'Connection failed', message: result.error || 'Could not connect to target database.', details: result.error })
    } catch (e) {
      setError(e.message)
      setDialogError(e.detail || { title: 'Request failed', message: e.message, details: e.body || e.stack || '' })
    } finally { setTesting(false) }
  }

  const save = async () => {
    setSaving(true); setError(''); setDialogError(null); setSaveResult(null)
    try {
      const r = await api.createTarget(payload())
      setSaveResult(r)
      if (r.connection_error) {
        setDialogError(r.connection_error_detail || {
          title: 'Target connection failed',
          message: 'The target was saved, but the app could not connect to the selected database target.',
          details: r.connection_error,
          action_items: [
            'Verify the database service is running.',
            'Check host, port, database name, username, password, and SSL mode.',
            'Check firewall, Docker, VM, VPN, or network routing rules.',
            'Verify pg_hba.conf allows this client/user to connect.',
          ],
          error_type: 'TARGET_CONNECTION_WARNING',
        })
      } else if (r.extension_status?.errors?.length > 0) {
        setDialogError({
          title: 'Database extension check needs attention',
          message: 'The target was saved, but one or more required PostgreSQL extensions are missing or not usable.',
          details: r.extension_status.errors.join('\n'),
          action_items: [
            'Review the required PostgreSQL extension setup instructions below.',
            'Install/enable pg_stat_statements and hypopg on the target PostgreSQL server/database.',
            'Run the extension check again after fixing the server configuration.',
          ],
          error_type: 'TARGET_EXTENSION_WARNING',
        })
      }
      if (r.id && !r.connection_error && !r.extension_status?.errors?.length) setTimeout(() => onComplete?.(r.id), 600)
    } catch (e) {
      setError(e.message)
      setDialogError(e.detail || { title: 'Save failed', message: e.message, details: e.body || e.stack || '' })
    } finally { setSaving(false) }
  }

  return (
    <div className="min-h-screen bg-bg-base text-text-primary flex items-center justify-center p-8">
      <ErrorDialog error={dialogError} onClose={() => setDialogError(null)} />
      <div className="w-full max-w-4xl space-y-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-green-dim border border-green-600/50 flex items-center justify-center">
            <Database className="text-green-400" size={20} />
          </div>
          <div>
            <h1 className="font-display font-bold text-xl">Database Index Advisor Setup</h1>
            <p className="text-sm text-text-secondary">Choose a database engine and add your first target. PostgreSQL is supported now; MSSQL and Oracle are prepared in the architecture and marked as coming soon.</p>
          </div>
        </div>

        <Card>
          <CardHeader><CardTitle>Database engine</CardTitle></CardHeader>
          <div className="p-5 grid grid-cols-1 md:grid-cols-3 gap-3">
            {engines.map(engine => {
              const available = engine.status === 'available'
              const active = form.engine === engine.engine
              return (
                <button
                  key={engine.engine}
                  type="button"
                  onClick={() => chooseEngine(engine.engine)}
                  disabled={!available}
                  className={`text-left rounded-xl border p-4 transition ${active ? 'border-green-600 bg-green-dim' : 'border-bg-border bg-bg-elevated'} ${available ? 'hover:border-green-600' : 'opacity-70 cursor-not-allowed'}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-display font-semibold text-sm">{engine.display_name}</div>
                    {available ? <Badge className="text-green-400 bg-green-dim border-green-600">Available</Badge> : <Badge className="text-amber-400 bg-amber-dim border-amber-600 flex items-center gap-1"><Lock size={12} /> Coming soon</Badge>}
                  </div>
                  <p className="mt-2 text-xs text-text-secondary leading-relaxed">{engine.description}</p>
                  <p className="mt-3 text-xs font-mono text-text-muted">Default port: {engine.default_port}</p>
                </button>
              )
            })}
          </div>
        </Card>

        <Card>
          <CardHeader><CardTitle>{selectedEngine?.display_name || 'Database'} connection</CardTitle></CardHeader>
          <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              ['name', 'Display name'], ['host', 'Host'], ['port', 'Port'], ['database_name', 'Database name'], ['username', 'Username'], ['password', 'Password']
            ].map(([key, label]) => (
              <label key={key} className="space-y-1">
                <span className="text-xs font-mono text-text-muted uppercase">{label}</span>
                <input
                  type={key === 'password' ? 'password' : key === 'port' ? 'number' : 'text'}
                  value={form[key]}
                  onChange={e => set(key, e.target.value)}
                  className="w-full bg-bg-elevated border border-bg-border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-600"
                />
              </label>
            ))}
            <label className="space-y-1">
              <span className="text-xs font-mono text-text-muted uppercase">SSL mode</span>
              <select value={form.sslmode} onChange={e => set('sslmode', e.target.value)} className="w-full bg-bg-elevated border border-bg-border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-600">
                {['prefer', 'disable', 'require', 'verify-ca', 'verify-full'].map(v => <option key={v}>{v}</option>)}
              </select>
            </label>
          </div>
          <div className="px-5 pb-5 flex gap-3">
            <button onClick={test} disabled={testing || !selectedEngineAvailable} className="px-4 py-2 rounded-lg border border-bg-border bg-bg-elevated text-sm font-mono hover:border-green-600 disabled:opacity-60">
              {testing ? <span className="flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Testing…</span> : 'Test connection'}
            </button>
            <button onClick={save} disabled={saving || !selectedEngineAvailable} className="px-4 py-2 rounded-lg border border-green-600/50 bg-green-dim text-green-400 text-sm font-mono hover:border-green-500 disabled:opacity-60">
              {saving ? <span className="flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Saving…</span> : 'Save database target'}
            </button>
          </div>
        </Card>

        {testResult && (
          <Card><div className="p-5 flex items-start gap-3">
            {testResult.ok ? <CheckCircle className="text-green-400" /> : <AlertTriangle className="text-red-400" />}
            <div><Badge className={testResult.ok ? 'text-green-400 bg-green-dim border-green-600' : 'text-red-400 bg-red-dim border-red-600'}>{testResult.ok ? 'CONNECTION OK' : 'CONNECTION FAILED'}</Badge>
            <p className="mt-2 text-sm text-text-secondary font-mono whitespace-pre-wrap">{testResult.version || testResult.error}</p></div>
          </div></Card>
        )}

        {saveResult && (
          <Card><div className="p-5 space-y-4">
            <div className="flex items-center gap-2"><Badge className={saveResult.setup_status === 'READY' ? 'text-green-400 bg-green-dim border-green-600' : 'text-amber-400 bg-amber-dim border-amber-600'}>{saveResult.setup_status}</Badge><span className="text-sm text-text-secondary">Target ID: {saveResult.id}</span></div>
            {saveResult.storage_bootstrapped && <p className="text-sm text-green-400 font-mono">storage_db was created/configured automatically on this PostgreSQL host.</p>}
            {saveResult.target_existed && <p className="text-sm text-green-400 font-mono">An existing target with this display name was found and reused/updated. Existing analysis history is preserved.</p>}
            {saveResult.extension_status?.errors?.length > 0 && <p className="text-sm font-mono text-amber-400 whitespace-pre-wrap">{saveResult.extension_status.errors.join('\n')}</p>}
            {saveResult.extension_status?.guide && <div className="space-y-3"><SqlBlock sql={`pg_stat_statements:\n${saveResult.extension_status.guide.pg_stat_statements}\n\nhypopg:\n${saveResult.extension_status.guide.hypopg}`} /></div>}
          </div></Card>
        )}

        {error && <div className="rounded-lg border border-red-600/40 bg-red-dim p-4 text-sm text-red-400 font-mono">{error}</div>}
      </div>
    </div>
  )
}

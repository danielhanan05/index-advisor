import { useEffect, useState } from 'react'
import { Clock, DatabaseZap, Save, RefreshCw, Plus, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { PageHeader } from '../components/Layout'
import { Card, CardHeader, CardTitle, LoadingSpinner, ErrorState, Badge } from '../components/ui'

function normalizeTimes(times) {
  const list = Array.isArray(times) && times.length ? times : ['06:00', '20:00']
  return list.map(t => String(t).slice(0, 5))
}

export function SettingsPage() {
  const [settings, setSettings] = useState(null)
  const [form, setForm] = useState({
    scheduler_enabled: true,
    scheduler_run_times: ['06:00', '20:00'],
    storage_retention_days: 30,
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const data = await api.settings()
      setSettings(data)
      setForm({
        scheduler_enabled: Boolean(data.scheduler_enabled),
        scheduler_run_times: normalizeTimes(data.scheduler_run_times),
        storage_retention_days: Number(data.storage_retention_days || 30),
      })
    } catch (e) {
      setError(e.detail?.message || e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const setTime = (index, value) => {
    setForm(prev => ({
      ...prev,
      scheduler_run_times: prev.scheduler_run_times.map((t, i) => i === index ? value : t),
    }))
  }

  const addTime = () => {
    setForm(prev => ({ ...prev, scheduler_run_times: [...prev.scheduler_run_times, '12:00'] }))
  }

  const removeTime = (index) => {
    setForm(prev => ({
      ...prev,
      scheduler_run_times: prev.scheduler_run_times.filter((_, i) => i !== index),
    }))
  }

  const save = async () => {
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const payload = {
        scheduler_enabled: form.scheduler_enabled,
        scheduler_run_times: form.scheduler_run_times.filter(Boolean),
        storage_retention_days: Number(form.storage_retention_days),
      }
      const data = await api.updateSettings(payload)
      setSettings(data)
      setForm({
        scheduler_enabled: Boolean(data.scheduler_enabled),
        scheduler_run_times: normalizeTimes(data.scheduler_run_times),
        storage_retention_days: Number(data.storage_retention_days || 30),
      })
      setSuccess('Settings saved. The scheduler will pick up the new times automatically within about 30 seconds.')
    } catch (e) {
      setError(e.detail?.message || e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="Configure automatic analyze schedule and storage retention."
        action={
          <button onClick={load} disabled={loading || saving} className="flex items-center gap-2 px-3 py-2 rounded-lg border border-bg-border bg-bg-elevated text-xs font-mono text-text-secondary hover:text-text-primary disabled:opacity-60">
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
        }
      />

      <div className="p-8 max-w-4xl space-y-6">
        {loading && <LoadingSpinner label="Loading settings…" />}
        {!loading && error && <ErrorState message={error} onRetry={load} />}

        {!loading && !error && (
          <>
            <Card>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-green-dim text-green-400 border border-green-600/30"><Clock size={16} /></div>
                  <div>
                    <CardTitle>Automatic collect + analyze</CardTitle>
                    <p className="text-xs text-text-muted mt-1">Runs for all active database targets using the backend server local time.</p>
                  </div>
                </div>
                <Badge className={form.scheduler_enabled ? 'text-green-400 border-green-600 bg-green-dim' : 'text-text-muted border-bg-border bg-bg-elevated'}>
                  {form.scheduler_enabled ? 'Enabled' : 'Disabled'}
                </Badge>
              </CardHeader>

              <div className="p-5 space-y-5">
                <label className="flex items-center justify-between gap-4 rounded-lg border border-bg-border bg-bg-base p-4">
                  <div>
                    <p className="text-sm font-medium text-text-primary">Enable scheduler</p>
                    <p className="text-xs text-text-muted mt-1">Manual runs stay available even when the scheduler is disabled.</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={form.scheduler_enabled}
                    onChange={e => setForm(prev => ({ ...prev, scheduler_enabled: e.target.checked }))}
                    className="h-5 w-5"
                  />
                </label>

                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <p className="text-sm font-medium text-text-primary">Run times</p>
                      <p className="text-xs text-text-muted mt-1">Use 24-hour HH:MM format.</p>
                    </div>
                    <button onClick={addTime} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-bg-border text-xs font-mono text-text-secondary hover:text-green-400 hover:border-green-600/50">
                      <Plus size={12} /> Add time
                    </button>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {form.scheduler_run_times.map((time, index) => (
                      <div key={`${index}-${time}`} className="flex gap-2">
                        <input
                          type="time"
                          value={time}
                          onChange={e => setTime(index, e.target.value)}
                          className="flex-1 bg-bg-elevated border border-bg-border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-600"
                        />
                        <button
                          onClick={() => removeTime(index)}
                          disabled={form.scheduler_run_times.length <= 1}
                          className="px-3 rounded-lg border border-bg-border text-text-muted hover:text-red-400 disabled:opacity-40 disabled:hover:text-text-muted"
                          title="Remove time"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                {settings?.scheduler && (
                  <div className="rounded-lg border border-bg-border bg-bg-base p-4 text-xs font-mono text-text-secondary grid grid-cols-1 md:grid-cols-2 gap-2">
                    <div>Next run: <span className="text-text-primary">{settings.scheduler.next_run_at || '—'}</span></div>
                    <div>Running now: <span className="text-text-primary">{settings.scheduler.running ? 'yes' : 'no'}</span></div>
                    <div>Last started: <span className="text-text-primary">{settings.scheduler.last_started_at || '—'}</span></div>
                    <div>Last success: <span className="text-text-primary">{settings.scheduler.last_success === null ? '—' : String(settings.scheduler.last_success)}</span></div>
                  </div>
                )}
              </div>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-blue-dim text-blue-400 border border-blue-600/30"><DatabaseZap size={16} /></div>
                  <div>
                    <CardTitle>Storage retention</CardTitle>
                    <p className="text-xs text-text-muted mt-1">Prevents storage_db metadata and recommendations from growing forever.</p>
                  </div>
                </div>
              </CardHeader>
              <div className="p-5 space-y-4">
                <label className="block max-w-xs space-y-1">
                  <span className="text-xs font-mono text-text-muted uppercase">Keep data for days</span>
                  <input
                    type="number"
                    min="1"
                    max="365"
                    value={form.storage_retention_days}
                    onChange={e => setForm(prev => ({ ...prev, storage_retention_days: e.target.value }))}
                    className="w-full bg-bg-elevated border border-bg-border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-600"
                  />
                </label>
                <p className="text-xs text-text-muted leading-relaxed">
                  Retention deletes old collection runs. Query stats, table stats, index stats, plans, recommendations,
                  and validations are deleted automatically by PostgreSQL foreign-key cascade.
                </p>
              </div>
            </Card>

            {success && <div className="rounded-lg border border-green-600/40 bg-green-dim p-4 text-sm text-green-400 font-mono">{success}</div>}

            <div className="flex justify-end">
              <button
                onClick={save}
                disabled={saving}
                className="flex items-center gap-2 px-5 py-2.5 rounded-lg border border-green-600/50 bg-green-dim text-green-400 text-sm font-mono disabled:opacity-60"
              >
                <Save size={14} /> {saving ? 'Saving…' : 'Save settings'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

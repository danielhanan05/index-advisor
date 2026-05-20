import { useState } from 'react'
import { Database, LayoutDashboard, Lightbulb, History, Play, BarChart2, Table2, Settings, Activity, Plus, X, SlidersHorizontal } from 'lucide-react'
import { api } from '../api/client'

const NAV = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'recommendations', label: 'Current Recommendations', icon: Lightbulb },
  { id: 'recommendation-history', label: 'Recommendation History', icon: History },
  { id: 'runs', label: 'Analysis Runs', icon: Play },
  { id: 'query-stats', label: 'Query Stats', icon: BarChart2 },
  { id: 'table-stats', label: 'Table Stats', icon: Table2 },
  { id: 'settings', label: 'Settings', icon: SlidersHorizontal },
  { id: 'about', label: 'About', icon: Settings },
]

function AddTargetModal({ onClose, onSaved }) {
  const [form, setForm] = useState({ name: '', host: 'localhost', port: 5432, database_name: '', username: '', password: '', sslmode: 'prefer', is_default: false })
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const save = async () => {
    setBusy(true); setError(''); setResult(null)
    try {
      const r = await api.createTarget({ ...form, port: Number(form.port || 5432) })
      setResult(r)
      onSaved?.(r.id)
      setTimeout(onClose, 700)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
      <div className="w-full max-w-2xl rounded-xl border border-bg-border bg-bg-surface shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-bg-border">
          <h2 className="font-display font-semibold">Add database target</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary"><X size={18} /></button>
        </div>
        <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
          {[
            ['name', 'Display name'], ['host', 'Host'], ['port', 'Port'], ['database_name', 'Database name'], ['username', 'Username'], ['password', 'Password']
          ].map(([key, label]) => (
            <label key={key} className="space-y-1">
              <span className="text-xs font-mono text-text-muted uppercase">{label}</span>
              <input type={key === 'password' ? 'password' : key === 'port' ? 'number' : 'text'} value={form[key]} onChange={e => set(key, e.target.value)} className="w-full bg-bg-elevated border border-bg-border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-600" />
            </label>
          ))}
          <label className="space-y-1">
            <span className="text-xs font-mono text-text-muted uppercase">SSL mode</span>
            <select value={form.sslmode} onChange={e => set('sslmode', e.target.value)} className="w-full bg-bg-elevated border border-bg-border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-green-600">
              {['prefer', 'disable', 'require', 'verify-ca', 'verify-full'].map(v => <option key={v}>{v}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 mt-6 text-sm text-text-secondary">
            <input type="checkbox" checked={form.is_default} onChange={e => set('is_default', e.target.checked)} /> Make default
          </label>
        </div>
        {error && <div className="mx-5 mb-3 rounded-lg border border-red-600/40 bg-red-dim p-3 text-xs text-red-400 font-mono">{error}</div>}
        {result && <div className="mx-5 mb-3 rounded-lg border border-bg-border bg-bg-elevated p-3 text-xs text-text-secondary font-mono">Saved target #{result.id} - {result.setup_status}</div>}
        <div className="px-5 py-4 border-t border-bg-border flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 rounded-lg border border-bg-border text-sm font-mono">Cancel</button>
          <button onClick={save} disabled={busy} className="px-4 py-2 rounded-lg border border-green-600/50 bg-green-dim text-green-400 text-sm font-mono disabled:opacity-60">{busy ? 'Saving…' : 'Save target'}</button>
        </div>
      </div>
    </div>
  )
}

export function Layout({ page, setPage, targets = [], selectedTargetId, setSelectedTargetId, onTargetsChanged, children }) {
  const [showAdd, setShowAdd] = useState(false)
  return (
    <div className="flex h-screen bg-bg-base text-text-primary overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 flex flex-col border-r border-bg-border bg-bg-surface">
        {/* Logo */}
        <div className="px-5 py-5 border-b border-bg-border">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-green-dim border border-green-600/50 flex items-center justify-center">
              <Database size={14} className="text-green-400" />
            </div>
            <div>
              <p className="font-display font-semibold text-sm text-text-primary leading-none">PG Advisor</p>
              <p className="text-xs text-text-muted mt-0.5 font-mono">Index Advisor</p>
            </div>
          </div>
        </div>

        <div className="px-3 py-3 border-b border-bg-border space-y-2">
          <label className="block text-[10px] uppercase tracking-wider font-mono text-text-muted">Database target</label>
          <select
            value={selectedTargetId || ''}
            onChange={(e) => setSelectedTargetId?.(Number(e.target.value))}
            className="w-full bg-bg-elevated border border-bg-border rounded-lg px-2 py-2 text-xs font-mono text-text-secondary focus:outline-none focus:border-green-600"
          >
            {targets.map(t => <option key={t.id} value={t.id}>{t.name} / {t.database_name}</option>)}
          </select>
          <button onClick={() => setShowAdd(true)} className="w-full flex items-center justify-center gap-2 px-2 py-2 rounded-lg border border-bg-border text-xs font-mono text-text-muted hover:text-green-400 hover:border-green-600/50">
            <Plus size={12} /> Add database
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {NAV.map(({ id, label, icon: Icon }) => {
            const active = page === id
            return (
              <button
                key={id}
                onClick={() => setPage(id)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-sans transition-colors text-left ${
                  active
                    ? 'bg-green-dim text-green-400 border border-green-600/30'
                    : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
                }`}
              >
                <Icon size={15} />
                {label}
              </button>
            )
          })}
        </nav>

        {/* Bottom */}
        <div className="px-5 py-4 border-t border-bg-border">
          <div className="flex items-center gap-2">
            <Activity size={12} className="text-text-muted" />
            <span className="text-xs font-mono text-text-muted">Local app server</span>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        {children}
      </main>
      {showAdd && <AddTargetModal onClose={() => setShowAdd(false)} onSaved={() => onTargetsChanged?.()} />}
    </div>
  )
}

export function PageHeader({ title, subtitle, action }) {
  return (
    <div className="flex items-start justify-between px-8 py-6 border-b border-bg-border bg-bg-surface sticky top-0 z-10">
      <div>
        <h1 className="font-display font-bold text-lg text-text-primary">{title}</h1>
        {subtitle && <p className="text-sm text-text-secondary mt-0.5">{subtitle}</p>}
      </div>
      {action && <div>{action}</div>}
    </div>
  )
}

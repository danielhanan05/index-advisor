import { AlertTriangle } from 'lucide-react'
import { CopyButton } from './primitives'

export function SqlBlock({ sql, className = '' }) {
  if (!sql) return null
  return (
    <div className={`relative group ${className}`}>
      <pre className="bg-bg-base border border-bg-border rounded-lg p-4 overflow-x-auto text-xs font-mono text-green-400 leading-relaxed whitespace-pre-wrap break-all">
        {sql}
      </pre>
      <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <CopyButton text={sql} />
      </div>
    </div>
  )
}

export function SampleValidatedWarning() {
  return (
    <div className="flex gap-3 p-4 bg-amber-dim border border-amber-600/40 rounded-lg text-amber-400 text-sm">
      <AlertTriangle size={16} className="shrink-0 mt-0.5" />
      <p>
        <strong className="font-semibold">Sample-Validated Warning:</strong> This recommendation was validated using sampled bind values.
        Actual production performance may vary depending on runtime parameter distribution.
      </p>
    </div>
  )
}

export function UserValidatedWarning() {
  return (
    <div className="flex gap-3 p-4 bg-blue-dim border border-blue-600/40 rounded-lg text-blue-400 text-sm">
      <AlertTriangle size={16} className="shrink-0 mt-0.5" />
      <p>
        <strong className="font-semibold">User-Validated Result:</strong> This result uses bind values entered by the user.
        It is stronger than sampled validation, but still based on planner estimates, not guaranteed runtime behavior.
      </p>
    </div>
  )
}

export function ValidationExplainer() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs">
      {[
        { type: 'VALIDATED', color: 'text-green-400 border-green-600 bg-green-dim', desc: 'Real query text + HypoPG validation' },
        { type: 'SAMPLE_VALIDATED', color: 'text-amber-400 border-amber-600 bg-amber-dim', desc: 'Parameterized query validated using sampled bind values' },
        { type: 'USER_VALIDATED', color: 'text-blue-400 border-blue-600 bg-blue-dim', desc: 'Revalidated using user-provided bind values' },
        { type: 'HEURISTIC_ONLY', color: 'text-text-secondary border-bg-border bg-bg-elevated', desc: 'Recommendation without HypoPG validation' },
      ].map(({ type, color, desc }) => (
        <div key={type} className="flex flex-col gap-1.5 p-3 bg-bg-base border border-bg-border rounded-lg">
          <span className={`inline-flex self-start px-2 py-0.5 rounded border font-mono font-medium ${color}`}>{type}</span>
          <p className="text-text-muted">{desc}</p>
        </div>
      ))}
    </div>
  )
}

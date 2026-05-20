import { useMemo, useState } from 'react'
import { CopyButton, Badge } from './ui'

function parsePlan(plan) {
  if (!plan) return null
  if (typeof plan === 'string') {
    try {
      return JSON.parse(plan)
    } catch {
      return plan
    }
  }
  return plan
}

function rootPlan(planJson) {
  const parsed = parsePlan(planJson)
  if (Array.isArray(parsed) && parsed.length > 0 && parsed[0]?.Plan) return parsed[0]
  if (parsed?.Plan) return parsed
  return parsed
}

function getNode(planJson) {
  const root = rootPlan(planJson)
  return root?.Plan || null
}

function nodeTitle(node) {
  if (!node) return 'Plan'
  const relation = node['Relation Name'] ? ` on ${node['Relation Name']}` : ''
  const index = node['Index Name'] ? ` using ${node['Index Name']}` : ''
  return `${node['Node Type'] || 'Plan Node'}${relation}${index}`
}

function PlanNode({ node, depth = 0 }) {
  if (!node) return null

  const children = Array.isArray(node.Plans) ? node.Plans : []
  const details = [
    ['Startup Cost', node['Startup Cost']],
    ['Total Cost', node['Total Cost']],
    ['Plan Rows', node['Plan Rows']],
    ['Plan Width', node['Plan Width']],
    ['Actual Rows', node['Actual Rows']],
    ['Actual Total Time', node['Actual Total Time']],
    ['Filter', node.Filter],
    ['Index Cond', node['Index Cond']],
    ['Recheck Cond', node['Recheck Cond']],
    ['Join Type', node['Join Type']],
    ['Hash Cond', node['Hash Cond']],
    ['Merge Cond', node['Merge Cond']],
    ['Sort Key', Array.isArray(node['Sort Key']) ? node['Sort Key'].join(', ') : node['Sort Key']],
    ['Group Key', Array.isArray(node['Group Key']) ? node['Group Key'].join(', ') : node['Group Key']],
  ].filter(([, value]) => value !== undefined && value !== null)

  return (
    <div className="relative">
      <div className="border border-bg-border rounded-lg bg-bg-base p-3" style={{ marginLeft: depth ? `${Math.min(depth * 18, 72)}px` : 0 }}>
        <div className="flex items-center gap-2 flex-wrap mb-2">
          <Badge className="text-green-400 bg-green-dim border-green-600">{node['Node Type'] || 'NODE'}</Badge>
          {node['Relation Name'] && <span className="text-xs font-mono text-text-secondary">{node['Relation Name']}</span>}
          {node['Index Name'] && <span className="text-xs font-mono text-blue-400">{node['Index Name']}</span>}
        </div>
        <p className="text-sm font-mono text-text-primary mb-2 break-all">{nodeTitle(node)}</p>
        {details.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1">
            {details.map(([label, value]) => (
              <div key={label} className="flex gap-2 text-xs font-mono">
                <span className="text-text-muted shrink-0">{label}:</span>
                <span className="text-text-secondary break-all">{String(value)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {children.length > 0 && (
        <div className="mt-2 space-y-2">
          {children.map((child, index) => (
            <PlanNode key={`${child['Node Type'] || 'node'}-${index}-${depth}`} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

function PlanSummary({ plan }) {
  const root = rootPlan(plan)
  const node = root?.Plan
  if (!node) return null
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {[
        ['Root Node', node['Node Type']],
        ['Startup Cost', node['Startup Cost']],
        ['Total Cost', node['Total Cost']],
        ['Plan Rows', node['Plan Rows']],
      ].map(([label, value]) => (
        <div key={label} className="bg-bg-base border border-bg-border rounded-lg p-3">
          <p className="text-xs font-mono text-text-muted mb-1">{label}</p>
          <p className="text-sm font-mono text-text-primary break-all">{value ?? '—'}</p>
        </div>
      ))}
    </div>
  )
}

export function ExecutionPlanViewer({ title = 'Execution Plan', plan, emptyMessage = 'No execution plan was captured for this query.' }) {
  const [tab, setTab] = useState('tree')
  const parsed = useMemo(() => parsePlan(plan), [plan])
  const rootNode = useMemo(() => getNode(parsed), [parsed])
  const raw = useMemo(() => (parsed ? JSON.stringify(parsed, null, 2) : ''), [parsed])

  if (!parsed) {
    return (
      <div className="border border-bg-border rounded-lg bg-bg-elevated p-4">
        <p className="text-xs font-mono text-text-muted uppercase tracking-wider mb-2">{title}</p>
        <p className="text-sm text-text-secondary">{emptyMessage}</p>
      </div>
    )
  }

  return (
    <div className="border border-bg-border rounded-lg bg-bg-elevated overflow-hidden">
      <div className="px-4 py-3 border-b border-bg-border flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-xs font-mono text-text-muted uppercase tracking-wider">{title}</p>
          <p className="text-xs text-text-secondary mt-1">Rendered from PostgreSQL EXPLAIN (FORMAT JSON).</p>
        </div>
        <div className="flex items-center gap-2">
          {['tree', 'raw'].map((name) => (
            <button
              key={name}
              onClick={() => setTab(name)}
              className={`px-3 py-1.5 rounded-md border text-xs font-mono transition-colors ${tab === name ? 'border-green-600 bg-green-dim text-green-400' : 'border-bg-border bg-bg-base text-text-muted hover:text-text-primary'}`}
            >
              {name === 'tree' ? 'Tree' : 'Raw JSON'}
            </button>
          ))}
        </div>
      </div>
      <div className="p-4 space-y-4">
        <PlanSummary plan={parsed} />
        {tab === 'tree' && (
          rootNode ? <PlanNode node={rootNode} /> : <p className="text-sm text-text-secondary">Could not render the plan tree. Raw JSON is still available.</p>
        )}
        {tab === 'raw' && (
          <div className="relative group">
            <pre className="bg-bg-base border border-bg-border rounded-lg p-4 text-xs font-mono text-green-400 overflow-x-auto whitespace-pre-wrap break-all max-h-[520px]">
              {raw}
            </pre>
            <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
              <CopyButton text={raw} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

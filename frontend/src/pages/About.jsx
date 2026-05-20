import { Card, CardHeader, CardTitle, ValidationExplainer } from '../components/ui'
import { PageHeader } from '../components/Layout'

export function AboutPage() {
  return (
    <div>
      <PageHeader title="About" subtitle="Database Index Advisor — how it works" />
      <div className="p-8 space-y-6 max-w-3xl">

        <Card>
          <CardHeader><CardTitle>How It Works</CardTitle></CardHeader>
          <div className="px-5 py-4 space-y-4 text-sm text-text-secondary leading-relaxed">
            <p>
              The <strong className="text-text-primary">Database Index Advisor</strong> analyzes workload activity from{' '}
              <code className="font-mono text-green-400 text-xs bg-bg-elevated px-1 py-0.5 rounded">pg_stat_statements</code>, samples parameterized
              query values, validates possible indexes using HypoPG, and stores recommendations.
            </p>
            <ol className="list-decimal list-inside space-y-2 text-text-muted">
              <li><strong className="text-text-secondary">Collect</strong> — harvests query stats, table stats, and index stats from the target PostgreSQL instance.</li>
              <li><strong className="text-text-secondary">Analyze</strong> — identifies candidate indexes using query structure, columns, and workload cost.</li>
              <li><strong className="text-text-secondary">Validate</strong> — uses HypoPG to create hypothetical indexes and measure cost improvement via EXPLAIN.</li>
              <li><strong className="text-text-secondary">Revalidate</strong> — lets a DBA test a recommendation with real bind values when sampled values are not enough.</li>
              <li><strong className="text-text-secondary">Score</strong> — ranks recommendations by improvement, workload frequency, execution time, and write pressure.</li>
              <li><strong className="text-text-secondary">Store</strong> — persists findings to the storage database for historical analysis.</li>
            </ol>
          </div>
        </Card>

        <Card>
          <CardHeader><CardTitle>Validation Types</CardTitle></CardHeader>
          <div className="px-5 py-5">
            <ValidationExplainer />
          </div>
        </Card>

        <Card>
          <CardHeader><CardTitle>Safety Notes</CardTitle></CardHeader>
          <div className="px-5 py-4 space-y-3 text-sm text-text-secondary leading-relaxed">
            <p>
              Recommendations are based on PostgreSQL planner estimates and workload statistics. They should be reviewed before being applied to production systems.
            </p>
            <p>
              <strong className="text-amber-400">SAMPLE_VALIDATED</strong> recommendations are validated with sampled bind values, so real production performance can vary depending on runtime parameter distribution.
            </p>
            <p>
              <strong className="text-blue-400">USER_VALIDATED</strong> results are revalidated with values entered by a DBA. They are stronger than sampled validation, but still planner estimates rather than guaranteed runtime measurements.
            </p>
          </div>
        </Card>

      </div>
    </div>
  )
}

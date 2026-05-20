import { DashboardPage } from '../pages/Dashboard'
import { RecommendationsPage, RecommendationHistoryPage } from '../pages/Recommendations'
import { RunsPage } from '../pages/Runs'
import { QueryStatsPage } from '../pages/QueryStats'
import { TableStatsPage } from '../pages/TableStats'
import { AboutPage } from '../pages/About'
import { SettingsPage } from '../pages/Settings'

const PAGE_RENDERERS = {
  dashboard: ({ selectedTargetId, setPage }) => <DashboardPage selectedTargetId={selectedTargetId} setPage={setPage} />,
  recommendations: ({ selectedTargetId }) => <RecommendationsPage selectedTargetId={selectedTargetId} />,
  'recommendation-history': ({ selectedTargetId }) => <RecommendationHistoryPage selectedTargetId={selectedTargetId} />,
  runs: ({ selectedTargetId }) => <RunsPage selectedTargetId={selectedTargetId} />,
  'query-stats': ({ selectedTargetId }) => <QueryStatsPage selectedTargetId={selectedTargetId} />,
  'table-stats': ({ selectedTargetId }) => <TableStatsPage selectedTargetId={selectedTargetId} />,
  settings: () => <SettingsPage />,
  about: () => <AboutPage />,
}

export function renderPage({ page, selectedTargetId, setPage }) {
  const renderer = PAGE_RENDERERS[page] || PAGE_RENDERERS.dashboard
  return renderer({ selectedTargetId, setPage })
}

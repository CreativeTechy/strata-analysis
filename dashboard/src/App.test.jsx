import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Outlet } from 'react-router-dom'
import App from './App'
import { useAuth } from './auth/useAuth.js'

// App.jsx statically imports every routed page. Mounting it in a test means
// every one of those imports resolves, so each is stubbed here to a trivial
// placeholder - what matters for these tests is App's own routing/guard/
// data-loading behavior, not what any individual page renders.
vi.mock('./auth/useAuth.js', () => ({ useAuth: vi.fn() }))
vi.mock('./components/AppShell', () => ({
  default: () => <div data-testid="app-shell"><Outlet /></div>,
}))
vi.mock('./components/StatsOverview', () => ({ default: () => null }))
vi.mock('./components/DashboardOverview', () => ({ default: () => <div data-testid="dashboard-overview" /> }))
vi.mock('./components/ProjectsPage', () => ({ default: () => null }))
vi.mock('./components/ProjectDetailPage', () => ({ default: () => null }))
vi.mock('./components/TopicDetailPage', () => ({ default: () => null }))
vi.mock('./components/IntelligencePage', () => ({ default: () => null }))
vi.mock('./components/CompetitorStudiesPage', () => ({ default: () => null }))
vi.mock('./components/CompetitorOnboarding', () => ({ default: () => null }))
vi.mock('./components/CompetitorWorkspace', () => ({ default: () => null }))
vi.mock('./components/CompetitorsPage', () => ({ default: () => null }))
vi.mock('./components/CompetitorEditPage', () => ({ default: () => null }))
vi.mock('./components/CompetitorReportPage', () => ({ default: () => null }))
vi.mock('./components/CompetitorPulseCard.jsx', () => ({ default: () => null }))
vi.mock('./components/PipelineRunsPage', () => ({ default: () => null }))
vi.mock('./components/PipelineRunDetailPage', () => ({ default: () => null }))
vi.mock('./components/ArticlesPage', () => ({ default: () => null }))
vi.mock('./components/AnalysisPage', () => ({ default: () => null }))
vi.mock('./components/LoginPage', () => ({ default: () => <div data-testid="login-page" /> }))
vi.mock('./components/UsersPage', () => ({ default: () => <div data-testid="users-page" /> }))
vi.mock('./components/RolesListPage', () => ({ default: () => null }))
vi.mock('./components/RoleCreatePage', () => ({ default: () => null }))
vi.mock('./components/RoleEditPage', () => ({ default: () => null }))
vi.mock('./components/ProjectLinkageListPage', () => ({ default: () => null }))
vi.mock('./components/ProjectLinkageDetailPage', () => ({ default: () => null }))
vi.mock('./components/ProjectLinkageEditPage', () => ({ default: () => null }))

function renderAppAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>
  )
}

function emptyJsonResponse(body = {}) {
  return { ok: true, json: async () => body }
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(emptyJsonResponse({ projects: [], users: [], runs: [] }))))
})

describe('App routing', () => {
  it('redirects to /login while unauthenticated', async () => {
    useAuth.mockReturnValue({ user: null, loading: false, hasPermission: () => false })
    renderAppAt('/dashboard')
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument())
  })

  it('renders the authenticated shell and dashboard at /dashboard', async () => {
    useAuth.mockReturnValue({ user: { id: 1, permissions: [] }, loading: false, hasPermission: () => true })
    renderAppAt('/dashboard')
    await waitFor(() => expect(screen.getByTestId('dashboard-overview')).toBeInTheDocument())
    expect(screen.getByTestId('app-shell')).toBeInTheDocument()
  })

  it('renders the reports view with a project scope selector and sync status at /reports', async () => {
    useAuth.mockReturnValue({ user: { id: 1, permissions: [] }, loading: false, hasPermission: () => true })
    fetch.mockImplementation((url) => {
      if (String(url).startsWith('/api/projects')) {
        return Promise.resolve(emptyJsonResponse({ projects: [{ id: 1, name: 'Acme Study', status: 'active' }] }))
      }
      return Promise.resolve(emptyJsonResponse({}))
    })
    renderAppAt('/reports')
    await waitFor(() => expect(screen.getByLabelText('Project scope for this report')).toBeInTheDocument())
    expect(screen.getByText('Up to date')).toBeInTheDocument()
  })

  it('shows "Access denied" instead of the page when the user lacks the required permission', async () => {
    useAuth.mockReturnValue({ user: { id: 1, permissions: [] }, loading: false, hasPermission: () => false })
    renderAppAt('/admin/users')
    await waitFor(() => expect(screen.getByText('Access denied')).toBeInTheDocument())
    expect(screen.queryByTestId('users-page')).not.toBeInTheDocument()
  })

  it('renders the gated page when the user has the required permission', async () => {
    useAuth.mockReturnValue({ user: { id: 1, permissions: ['users.view'] }, loading: false, hasPermission: () => true })
    renderAppAt('/admin/users')
    await waitFor(() => expect(screen.getByTestId('users-page')).toBeInTheDocument())
  })
})

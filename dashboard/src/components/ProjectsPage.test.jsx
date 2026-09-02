import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ProjectsPage from './ProjectsPage'
import { useAuth } from '../auth/useAuth.js'

vi.mock('../auth/useAuth.js', () => ({ useAuth: vi.fn() }))
vi.mock('../api/projectDocumentsApi.js', () => ({
  uploadDocuments: vi.fn(),
  deleteDocument: vi.fn(),
  listDocumentArticles: vi.fn(() => Promise.resolve({ articles: [] })),
  setDocumentArticleStatus: vi.fn(),
  approveAllDocumentArticles: vi.fn(),
  reanalyzeDocumentArticles: vi.fn(),
  pollDocumentExtraction: vi.fn(() => Promise.resolve()),
  pollArticleCandidates: vi.fn(() => Promise.resolve()),
  pollArticleAnalysis: vi.fn(() => Promise.resolve()),
}))

const PROJECTS = [
  { id: 1, name: 'Riverside Launch', status: 'active', description: 'EV rollout', keywords: ['charging'] },
  { id: 2, name: 'Downtown Survey', status: 'draft', description: 'Foot traffic', keywords: [] },
  { id: 3, name: 'Old Archive', status: 'archived', description: 'Wrapped up', keywords: [] },
]

function renderAt(path, props = {}) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects" element={<ProjectsPage projects={PROJECTS} users={[]} isLoadingProjects={false} {...props} />} />
        <Route path="/projects/new" element={<ProjectsPage projects={PROJECTS} users={[]} isLoadingProjects={false} {...props} />} />
        <Route path="/projects/:projectId/edit" element={<ProjectsPage projects={PROJECTS} users={[]} isLoadingProjects={false} {...props} />} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  useAuth.mockReturnValue({
    hasPermission: (...perms) => perms.every((p) => ['projects.create', 'projects.update', 'projects.delete'].includes(p)),
  })
})

describe('ProjectsPage list view', () => {
  it('lists every project and its status', () => {
    renderAt('/projects')
    expect(screen.getByText('Riverside Launch')).toBeInTheDocument()
    expect(screen.getByText('Downtown Survey')).toBeInTheDocument()
    expect(screen.getByText('Old Archive')).toBeInTheDocument()
  })

  it('shows the summary stat counts', () => {
    renderAt('/projects')
    // Total projects card
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('filters the list by the search box', () => {
    renderAt('/projects')
    fireEvent.change(screen.getByPlaceholderText('Search projects, dates, statuses, or keywords'), {
      target: { value: 'Riverside' },
    })
    expect(screen.getByText('Riverside Launch')).toBeInTheDocument()
    expect(screen.queryByText('Downtown Survey')).not.toBeInTheDocument()
  })

  it('filters the list by status', () => {
    renderAt('/projects')
    fireEvent.change(screen.getByDisplayValue('All statuses'), { target: { value: 'draft' } })
    expect(screen.getByText('Downtown Survey')).toBeInTheDocument()
    expect(screen.queryByText('Riverside Launch')).not.toBeInTheDocument()
  })

  it('shows the Add Project link when the user can edit', () => {
    renderAt('/projects')
    expect(screen.getByRole('link', { name: /Add Project/ })).toBeInTheDocument()
  })
})

describe('ProjectsPage create wizard', () => {
  it('starts on the basics step with Continue disabled until name and description are filled', () => {
    renderAt('/projects/new')
    expect(screen.getByText('Step 1. Project basics')).toBeInTheDocument()
    const continueBtn = screen.getByRole('button', { name: 'Continue' })
    expect(continueBtn).toBeDisabled()

    fireEvent.change(screen.getByPlaceholderText('Project name'), { target: { value: 'New Study' } })
    fireEvent.change(screen.getByPlaceholderText('Project description'), { target: { value: 'Some description' } })
    expect(continueBtn).not.toBeDisabled()
  })

  it('advances to the upload step once a project is created', async () => {
    const onCreateProject = vi.fn(() => Promise.resolve({ project: { id: 99 } }))
    renderAt('/projects/new', { onCreateProject })
    fireEvent.change(screen.getByPlaceholderText('Project name'), { target: { value: 'New Study' } })
    fireEvent.change(screen.getByPlaceholderText('Project description'), { target: { value: 'Some description' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(screen.getByText('Step 2. Upload documents')).toBeInTheDocument())
    expect(onCreateProject).toHaveBeenCalled()
  })

  it('lets the user choose an active project on the finish step', async () => {
    useAuth.mockReturnValue({ hasPermission: () => true })
    const onCreateProject = vi.fn(() => Promise.resolve({ project: { id: 99 } }))
    const onUpdateProject = vi.fn(() => Promise.resolve({ project: { id: 99 } }))
    renderAt('/projects/new', { onCreateProject, onUpdateProject })

    fireEvent.change(screen.getByPlaceholderText('Project name'), { target: { value: 'New Study' } })
    fireEvent.change(screen.getByPlaceholderText('Project description'), { target: { value: 'Some description' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    await waitFor(() => expect(screen.getByText('Step 3. Upload documents')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Skip for now' }))
    fireEvent.click(screen.getByRole('button', { name: 'Continue to finish' }))

    const statusSelect = screen.getByRole('combobox', { name: 'Project status' })
    expect(statusSelect).toHaveValue('draft')
    expect(screen.getByText('Draft projects stay marked as unfinished until you activate them.')).toBeInTheDocument()

    fireEvent.change(statusSelect, { target: { value: 'active' } })
    expect(screen.getByText('Active projects are ready to use across monitoring, analysis, and reports.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Activate and open workspace' }))

    await waitFor(() => {
      expect(onUpdateProject).toHaveBeenCalledWith(99, expect.objectContaining({ status: 'active' }))
    })
  })
})

describe('ProjectsPage edit wizard', () => {
  it('preloads the draft from the matching project', () => {
    renderAt('/projects/1/edit')
    expect(screen.getByDisplayValue('Riverside Launch')).toBeInTheDocument()
    expect(screen.getByDisplayValue('EV rollout')).toBeInTheDocument()
  })
})

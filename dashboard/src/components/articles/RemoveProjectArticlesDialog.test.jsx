import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import RemoveProjectArticlesDialog from './RemoveProjectArticlesDialog.jsx'
import { getProjectArticleRemovalPreview, removeProjectArticles } from '../../api/articlesApi.js'

vi.mock('../../api/articlesApi.js', () => ({
  getProjectArticleRemovalPreview: vi.fn(),
  removeProjectArticles: vi.fn(),
}))

const PROJECT = { id: 7, name: 'UK Oil Evidence' }
const PREVIEW = {
  project: PROJECT,
  linked_articles: 37,
  only_in_project: 30,
  shared_with_other_projects: 7,
  active_run: null,
}

function renderDialog(props = {}) {
  const onClose = vi.fn()
  const onRemoved = vi.fn()
  const utils = render(
    <MemoryRouter>
      <button type="button">Opener</button>
      <RemoveProjectArticlesDialog open project={PROJECT} onClose={onClose} onRemoved={onRemoved} {...props} />
    </MemoryRouter>,
  )
  return { ...utils, onClose, onRemoved }
}

const submitButton = () => screen.getByRole('button', { name: 'Remove articles' })
const nameInput = () => screen.getByLabelText('Type the project name to confirm:')

beforeEach(() => {
  getProjectArticleRemovalPreview.mockReset()
  removeProjectArticles.mockReset()
  getProjectArticleRemovalPreview.mockResolvedValue(PREVIEW)
})

describe('RemoveProjectArticlesDialog', () => {
  it('shows what the removal affects before anything is removed', async () => {
    renderDialog()
    expect(screen.getByRole('dialog', { name: 'Remove all articles from UK Oil Evidence?' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('37')).toBeInTheDocument())
    expect(screen.getByText('Deleted permanently').nextSibling).toHaveTextContent('30')
    expect(screen.getByText('Kept in other projects').nextSibling).toHaveTextContent('7')
    expect(getProjectArticleRemovalPreview).toHaveBeenCalledWith(7, expect.any(AbortSignal))
    expect(removeProjectArticles).not.toHaveBeenCalled()
  })

  it('opens on Cancel, the safe choice', async () => {
    renderDialog()
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })

  it('keeps Remove disabled until the exact project name is typed', async () => {
    renderDialog()
    await waitFor(() => expect(nameInput()).toBeInTheDocument())
    expect(submitButton()).toBeDisabled()

    fireEvent.change(nameInput(), { target: { value: 'uk oil evidence' } })
    expect(submitButton()).toBeDisabled()

    fireEvent.change(nameInput(), { target: { value: 'UK Oil Evidence' } })
    expect(submitButton()).toBeEnabled()
  })

  it('removes with the typed name and reports the result', async () => {
    const result = { ok: true, articles_removed: 37, articles_deleted: 30 }
    removeProjectArticles.mockResolvedValue(result)
    const { onRemoved } = renderDialog()
    await waitFor(() => expect(nameInput()).toBeInTheDocument())

    fireEvent.change(nameInput(), { target: { value: '  UK Oil Evidence ' } })
    fireEvent.click(submitButton())

    await waitFor(() => expect(onRemoved).toHaveBeenCalledWith(result, 'UK Oil Evidence'))
    expect(removeProjectArticles).toHaveBeenCalledWith(7, 'UK Oil Evidence')
  })

  it('shows a failed removal inside the dialog instead of closing it', async () => {
    const conflict = Object.assign(new Error('conflict'), { status: 409 })
    removeProjectArticles.mockRejectedValue(conflict)
    const { onRemoved, onClose } = renderDialog()
    await waitFor(() => expect(nameInput()).toBeInTheDocument())

    fireEvent.change(nameInput(), { target: { value: 'UK Oil Evidence' } })
    fireEvent.click(submitButton())

    expect(await screen.findByRole('alert')).toHaveTextContent('An analysis run started for this project')
    expect(onRemoved).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('blocks removal while an analysis run is in progress', async () => {
    getProjectArticleRemovalPreview.mockResolvedValue({
      ...PREVIEW,
      active_run: { id: 'run-9', status: 'running', articles_selected: 25, articles_analyzed: 12 },
    })
    renderDialog()
    expect(await screen.findByRole('alert')).toHaveTextContent('(12 of 25 analyzed)')
    expect(screen.getByRole('link', { name: 'Open the run' })).toHaveAttribute('href', '/pipeline-runs/run-9')
    expect(screen.queryByLabelText('Type the project name to confirm:')).not.toBeInTheDocument()
    expect(submitButton()).toBeDisabled()
  })

  it('says so when the project has no articles', async () => {
    getProjectArticleRemovalPreview.mockResolvedValue({ ...PREVIEW, linked_articles: 0, only_in_project: 0, shared_with_other_projects: 0 })
    renderDialog()
    expect(await screen.findByText('This project has no articles to remove.')).toBeInTheDocument()
    expect(submitButton()).toBeDisabled()
  })

  it('closes on Escape', async () => {
    const { onClose } = renderDialog()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('does not close on Escape while a removal is in flight', async () => {
    removeProjectArticles.mockReturnValue(new Promise(() => {}))
    const { onClose } = renderDialog()
    await waitFor(() => expect(nameInput()).toBeInTheDocument())
    fireEvent.change(nameInput(), { target: { value: 'UK Oil Evidence' } })
    fireEvent.click(submitButton())
    await waitFor(() => expect(screen.getByRole('button', { name: 'Removing…' })).toBeDisabled())

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('keeps Tab inside the dialog', async () => {
    renderDialog()
    await waitFor(() => expect(nameInput()).toBeInTheDocument())
    const close = screen.getByRole('button', { name: 'Close dialog' })
    const cancel = screen.getByRole('button', { name: 'Cancel' })
    // Remove is disabled (no name typed), so Cancel is the last focusable control.
    cancel.focus()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Tab' })
    expect(close).toHaveFocus()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Tab', shiftKey: true })
    expect(cancel).toHaveFocus()
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import i18n from '../i18n/index.js'
import CompetitorsPage from './CompetitorsPage.jsx'
import { listCompetitors } from '../api/competitorApi.js'

vi.mock('../auth/useAuth.js', () => ({ useAuth: () => ({ hasPermission: () => true }) }))
vi.mock('../useRunAnalysis.js', () => ({ useRunAnalysis: () => ({}) }))
vi.mock('./CompetitorRunAnalysis.jsx', () => ({
  RunAnalysisButton: () => null,
  RunAnalysisChoiceModal: () => null,
  RunAnalysisLog: () => null,
}))
vi.mock('../api/competitorApi.js', async (importOriginal) => ({
  ...(await importOriginal()),
  getStudy: vi.fn(async () => ({ study: { id: 5, name: 'Beirut coffee' } })),
  listCompetitors: vi.fn(),
}))

const NAMES = { ar: 'كوستا كوفي', en: 'Costa Coffee' }

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/competitors/5/manage']}>
      <Routes>
        <Route path="/competitors/:studyId/manage" element={<CompetitorsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

const lastCall = () => listCompetitors.mock.calls.at(-1)

describe('CompetitorsPage name language switch', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
    listCompetitors.mockReset()
    listCompetitors.mockImplementation(async (_id, { locale } = {}) => ({
      competitors: [{ id: 1, name: 'Costa Coffee', display_name: NAMES[locale], size_tier: 'enterprise', status: 'tracked' }],
    }))
  })

  afterEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('follows the interface language until the card is switched', async () => {
    renderPage()
    expect(await screen.findByText('Costa Coffee')).toBeInTheDocument()
    expect(lastCall()).toEqual(['5', { locale: 'en', force: false }])

    await act(() => i18n.changeLanguage('ar'))
    expect(await screen.findByText(NAMES.ar)).toBeInTheDocument()
    expect(lastCall()).toEqual(['5', { locale: 'ar', force: false }])
  })

  it('translates only the names on a card pick, forced, and keeps that pick across interface changes', async () => {
    renderPage()
    expect(await screen.findByText('Costa Coffee')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'العربية' }))
    expect(await screen.findByText(NAMES.ar)).toBeInTheDocument()
    expect(lastCall()).toEqual(['5', { locale: 'ar', force: true }])
    // The rest of the page stays in the interface language.
    expect(i18n.language).toBe('en')
    expect(screen.getByRole('button', { name: 'العربية' })).toHaveAttribute('aria-pressed', 'true')

    const callsBefore = listCompetitors.mock.calls.length
    await act(() => i18n.changeLanguage('ar'))
    await act(() => i18n.changeLanguage('en'))
    await waitFor(() => expect(screen.getByText(NAMES.ar)).toBeInTheDocument())
    expect(listCompetitors.mock.calls.length).toBe(callsBefore)
  })
})

import { useState } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { RunAnalysisButton, RunAnalysisChoiceModal } from './CompetitorRunAnalysis.jsx'

// The real `run` comes from useRunAnalysis; only the pieces the trigger and
// the dialog read are needed here.
function Harness({ runAnalysis = vi.fn() }) {
  const [showRunChoice, setShowRunChoice] = useState(false)
  const [scope, setScope] = useState('all')
  const run = {
    analyzing: false,
    showRunChoice,
    setShowRunChoice,
    scope,
    setScope,
    pendingDocuments: [],
    eligibleDocuments: [{ id: 1, original_filename: 'report.pdf', approved_article_count: 3 }],
    selectedDocumentIds: [],
    setSelectedDocumentIds: vi.fn(),
    runAnalysis,
  }
  return (
    <>
      <RunAnalysisButton run={run} />
      <RunAnalysisChoiceModal run={run} />
    </>
  )
}

const openFromTrigger = () => {
  const trigger = screen.getByRole('button', { name: 'Run analysis' })
  trigger.focus()
  fireEvent.click(trigger)
  return trigger
}

describe('RunAnalysisChoiceModal', () => {
  it('opens on the chosen scope and is labelled by its own title', () => {
    render(<Harness />)
    openFromTrigger()
    expect(screen.getByRole('dialog', { name: 'Run analysis' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /All documents/ })).toHaveFocus()
  })

  it('keeps Tab inside, closes on Escape, and returns focus to the trigger', () => {
    render(<Harness />)
    const trigger = openFromTrigger()
    const cancel = screen.getByRole('button', { name: 'Cancel' })

    cancel.focus()
    fireEvent.keyDown(document.activeElement, { key: 'Tab' })
    expect(screen.getByRole('button', { name: 'Close dialog' })).toHaveFocus()
    fireEvent.keyDown(document.activeElement, { key: 'Tab', shiftKey: true })
    expect(cancel).toHaveFocus()

    fireEvent.keyDown(document.activeElement, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('returns focus to the trigger after Cancel', () => {
    const runAnalysis = vi.fn()
    render(<Harness runAnalysis={runAnalysis} />)
    const trigger = openFromTrigger()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    expect(runAnalysis).not.toHaveBeenCalled()
  })
})

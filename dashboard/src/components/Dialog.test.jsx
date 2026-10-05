import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Dialog from './Dialog.jsx'

function renderDialog(props = {}) {
  const onClose = vi.fn()
  render(
    <Dialog titleId="t" onClose={onClose} {...props}>
      <h2 id="t">Override reason</h2>
      <textarea aria-label="Reason" />
    </Dialog>,
  )
  return { onClose, backdrop: screen.getByRole('dialog').parentElement }
}

describe('Dialog', () => {
  it('closes on a press that starts and ends on the backdrop', () => {
    const { onClose, backdrop } = renderDialog()
    fireEvent.mouseDown(backdrop)
    fireEvent.click(backdrop)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('stays open when a press inside the panel is released over the backdrop', () => {
    const { onClose, backdrop } = renderDialog()
    // A text selection dragged out of the field: the click lands on the
    // backdrop (the common ancestor), but the press began inside.
    fireEvent.mouseDown(screen.getByRole('textbox', { name: 'Reason' }))
    fireEvent.click(backdrop)
    fireEvent.click(screen.getByRole('dialog'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('ignores the backdrop and Escape while busy', () => {
    const { onClose, backdrop } = renderDialog({ busy: true })
    fireEvent.mouseDown(backdrop)
    fireEvent.click(backdrop)
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('falls back to the first focusable control when the preferred one is disabled', () => {
    const preferred = { current: { disabled: true, focus: vi.fn() } }
    renderDialog({ initialFocusRef: preferred })
    expect(screen.getByRole('textbox', { name: 'Reason' })).toHaveFocus()
    expect(preferred.current.focus).not.toHaveBeenCalled()
  })
})

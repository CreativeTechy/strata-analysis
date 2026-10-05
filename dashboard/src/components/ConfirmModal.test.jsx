import { useState } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import ConfirmModal from './ConfirmModal.jsx'

// Opens the modal from a real trigger button so focus restoration can be
// checked the way a keyboard user would hit it.
function Harness({ onConfirm = vi.fn(), ...props }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Delete study</button>
      <ConfirmModal
        open={open}
        title="Delete this study?"
        message="This cannot be undone."
        confirmLabel="Delete"
        onClose={() => setOpen(false)}
        onConfirm={() => {
          onConfirm()
          setOpen(false)
        }}
        {...props}
      />
    </>
  )
}

const openFromTrigger = () => {
  const trigger = screen.getByRole('button', { name: 'Delete study' })
  trigger.focus()
  fireEvent.click(trigger)
  return trigger
}

const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

describe('ConfirmModal', () => {
  it('opens on Cancel and is labelled by its own title and message', () => {
    render(<Harness />)
    openFromTrigger()
    const dialog = screen.getByRole('dialog', { name: 'Delete this study?' })
    expect(dialog).toHaveAccessibleDescription('This cannot be undone.')
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })

  it('focuses the confirm button when there is no Cancel', () => {
    render(<Harness hideCancel confirmLabel="Done" />)
    openFromTrigger()
    expect(screen.getByRole('button', { name: 'Done' })).toHaveFocus()
  })

  it('gives each open dialog unique label ids', () => {
    render(
      <>
        <ConfirmModal open title="First" message="One" />
        <ConfirmModal open title="Second" message="Two" />
      </>,
    )
    const [first, second] = screen.getAllByRole('dialog')
    expect(first.getAttribute('aria-labelledby')).not.toBe(second.getAttribute('aria-labelledby'))
    expect(first.getAttribute('aria-describedby')).not.toBe(second.getAttribute('aria-describedby'))
    expect(first).toHaveAccessibleName('First')
    expect(second).toHaveAccessibleName('Second')
  })

  it('keeps Tab and Shift+Tab inside the dialog', () => {
    render(<Harness />)
    openFromTrigger()
    const close = screen.getByRole('button', { name: 'Close dialog' })
    const confirm = screen.getByRole('button', { name: 'Delete' })

    confirm.focus()
    fireEvent.keyDown(document.activeElement, { key: 'Tab' })
    expect(close).toHaveFocus()
    fireEvent.keyDown(document.activeElement, { key: 'Tab', shiftKey: true })
    expect(confirm).toHaveFocus()
  })

  it('pulls focus back into the dialog if it has escaped to the page', () => {
    render(<Harness />)
    const trigger = openFromTrigger()
    trigger.focus()
    fireEvent.keyDown(document.activeElement, { key: 'Tab' })
    expect(screen.getByRole('button', { name: 'Close dialog' })).toHaveFocus()
  })

  it('closes on Escape and returns focus to the trigger', () => {
    render(<Harness />)
    const trigger = openFromTrigger()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('returns focus to the trigger after Cancel and after a confirmation', () => {
    const onConfirm = vi.fn()
    render(<Harness onConfirm={onConfirm} />)
    const trigger = openFromTrigger()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(trigger).toHaveFocus()
    expect(onConfirm).not.toHaveBeenCalled()

    openFromTrigger()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(trigger).toHaveFocus()
  })

  it('submits once while a confirmation is pending and ignores Escape until it settles', async () => {
    const pending = deferred()
    const onConfirm = vi.fn(() => pending.promise)
    const onClose = vi.fn()
    render(<ConfirmModal open title="Delete this user?" confirmLabel="Delete" onClose={onClose} onConfirm={onConfirm} />)

    const confirm = screen.getByRole('button', { name: 'Delete' })
    fireEvent.click(confirm)
    fireEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledTimes(1)

    await waitFor(() => expect(confirm).toBeDisabled())
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Close dialog' })).toBeDisabled()
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-busy', 'true')

    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(onClose).not.toHaveBeenCalled()

    await act(async () => { pending.resolve() })
    expect(confirm).toBeEnabled()
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('unlocks once a failed confirmation settles so it can be retried', async () => {
    const pending = deferred()
    const onConfirm = vi.fn(() => pending.promise.catch(() => {}))
    render(<ConfirmModal open title="Delete this role?" confirmLabel="Delete" onClose={vi.fn()} onConfirm={onConfirm} />)

    const confirm = screen.getByRole('button', { name: 'Delete' })
    fireEvent.click(confirm)
    await waitFor(() => expect(confirm).toBeDisabled())

    await act(async () => { pending.reject(new Error('in use')) })
    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledTimes(2)
  })

  it('stays locked while the caller reports itself busy', () => {
    const onClose = vi.fn()
    const onConfirm = vi.fn()
    render(<ConfirmModal open busy title="Delete this study?" confirmLabel="Delete" onClose={onClose} onConfirm={onConfirm} />)
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onConfirm).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })
})

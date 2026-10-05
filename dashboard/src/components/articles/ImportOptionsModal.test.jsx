import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ImportOptionsModal from './ImportOptionsModal.jsx'

describe('ImportOptionsModal', () => {
  it('opens on the first option, traps Tab, and closes on Escape', () => {
    const onClose = vi.fn()
    render(<ImportOptionsModal open hasProject onClose={onClose} />)
    const dialog = screen.getByRole('dialog', { name: 'Import articles' })
    expect(dialog.getAttribute('aria-describedby')).toBeTruthy()

    const [files, folder] = screen.getAllByRole('button').filter((button) => button.className === 'import-option-card')
    expect(files).toHaveFocus()

    folder.focus()
    fireEvent.keyDown(document.activeElement, { key: 'Tab' })
    expect(screen.getByRole('button', { name: 'Close dialog' })).toHaveFocus()

    fireEvent.keyDown(document.activeElement, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('falls back to the close button when no project is chosen', () => {
    render(<ImportOptionsModal open hasProject={false} onClose={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Close dialog' })).toHaveFocus()
  })
})

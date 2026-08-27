import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import UserAssignField from './UserAssignField.jsx'

const USERS = [
  { id: 1, username: 'alice', email: 'alice@example.com', role: 'admin' },
  { id: 2, username: 'bob', email: 'bob@example.com', role: 'viewer' },
]

describe('UserAssignField', () => {
  it('lists every user with a checkbox', () => {
    render(<UserAssignField users={USERS} selectedIds={[]} onToggle={vi.fn()} query="" onQueryChange={vi.fn()} />)
    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.getByText('bob')).toBeInTheDocument()
  })

  it('checks the checkbox for selected user ids', () => {
    render(<UserAssignField users={USERS} selectedIds={[2]} onToggle={vi.fn()} query="" onQueryChange={vi.fn()} />)
    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes[0]).not.toBeChecked()
    expect(checkboxes[1]).toBeChecked()
  })

  it('calls onToggle with the numeric user id when a row is clicked', () => {
    const onToggle = vi.fn()
    render(<UserAssignField users={USERS} selectedIds={[]} onToggle={onToggle} query="" onQueryChange={vi.fn()} />)
    fireEvent.click(screen.getAllByRole('checkbox')[0])
    expect(onToggle).toHaveBeenCalledWith(1)
  })

  it('filters the visible users by the search query', () => {
    render(<UserAssignField users={USERS} selectedIds={[]} onToggle={vi.fn()} query="bob" onQueryChange={vi.fn()} />)
    expect(screen.queryByText('alice')).not.toBeInTheDocument()
    expect(screen.getByText('bob')).toBeInTheDocument()
  })

  it('shows an empty state when there are no dashboard users at all', () => {
    render(<UserAssignField users={[]} selectedIds={[]} onToggle={vi.fn()} query="" onQueryChange={vi.fn()} />)
    expect(screen.getByText('No dashboard users yet.')).toBeInTheDocument()
  })
})

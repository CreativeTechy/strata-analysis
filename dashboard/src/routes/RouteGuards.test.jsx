import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { RequireAuth, RequirePermission } from './RouteGuards.jsx'
import { useAuth } from '../auth/useAuth.js'

vi.mock('../auth/useAuth.js', () => ({ useAuth: vi.fn() }))

function renderGuardedRoute(initialEntry = '/protected') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<div>Login page</div>} />
        <Route element={<RequireAuth />}>
          <Route path="/protected" element={<div>Protected content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  )
}

describe('RequireAuth', () => {
  it('shows a loading state while auth is resolving', () => {
    useAuth.mockReturnValue({ user: null, loading: true })
    renderGuardedRoute()
    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })

  it('redirects to /login when there is no user', () => {
    useAuth.mockReturnValue({ user: null, loading: false })
    renderGuardedRoute()
    expect(screen.getByText('Login page')).toBeInTheDocument()
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument()
  })

  it('renders the protected route once a user is present', () => {
    useAuth.mockReturnValue({ user: { id: 1 }, loading: false })
    renderGuardedRoute()
    expect(screen.getByText('Protected content')).toBeInTheDocument()
  })
})

describe('RequirePermission', () => {
  it('shows "Access denied" when the permission check fails', () => {
    useAuth.mockReturnValue({ hasPermission: () => false })
    render(<RequirePermission permissions={['projects.create']}><div>Gated content</div></RequirePermission>)
    expect(screen.getByText('Access denied')).toBeInTheDocument()
    expect(screen.queryByText('Gated content')).not.toBeInTheDocument()
  })

  it('renders the children when the permission check passes', () => {
    useAuth.mockReturnValue({ hasPermission: () => true })
    render(<RequirePermission permissions={['projects.create']}><div>Gated content</div></RequirePermission>)
    expect(screen.getByText('Gated content')).toBeInTheDocument()
  })

  it('passes every required permission key through to hasPermission', () => {
    const hasPermission = vi.fn(() => true)
    useAuth.mockReturnValue({ hasPermission })
    render(<RequirePermission permissions={['a', 'b']}><div>ok</div></RequirePermission>)
    expect(hasPermission).toHaveBeenCalledWith('a', 'b')
  })
})

import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { LogIn } from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const redirectTo = location.state?.from?.pathname || '/dashboard';

  const onSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      navigate(redirectTo, { replace: true });
    } catch (err) {
      setError(err.message || 'Login failed.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg, #f4f5f7)',
      }}
    >
      <form
        onSubmit={onSubmit}
        className="glass-card"
        style={{ width: 360, padding: 32, display: 'flex', flexDirection: 'column', gap: 16 }}
      >
        <div>
          <h1 className="title" style={{ fontSize: '1.4rem', marginBottom: 4 }}>Strata</h1>
          <p className="subtitle">Sign in to continue</p>
        </div>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: '0.85rem' }}>Username or email</span>
          <input
            className="filter-select"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>

        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: '0.85rem' }}>Password</span>
          <input
            className="filter-select"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {error && (
          <div className="panel-chip" style={{ background: '#fde2e2', color: '#9c1c1c' }}>
            {error}
          </div>
        )}

        <button type="submit" className="btn-primary" disabled={submitting} style={{ justifyContent: 'center' }}>
          <LogIn size={16} />
          {submitting ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}

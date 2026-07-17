import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { LogIn, AlertCircle, RefreshCw, Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

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
    <div className="login-page">
      <div className="bg-pattern"></div>

      <div className="login-shell">
        <div className="login-brand">
          <div className="login-logo">
            <img src="/favicon.png" alt="Strata" />
          </div>
          <div>
            <h1 className="title login-title">Strata</h1>
            <p className="subtitle">Media Intelligence Platform</p>
          </div>
        </div>

        <form onSubmit={onSubmit} className="glass-card login-card">
          <div className="login-card-heading">
            <h2>Welcome back</h2>
            <p className="subtitle">Sign in to access your intelligence workspace</p>
          </div>

          <label className="login-field">
            <span>Username or email</span>
            <input
              className="filter-select login-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
              placeholder="you@company.com"
            />
          </label>

          <label className="login-field">
            <span>Password</span>
            <div className="login-password-wrap">
              <input
                className="filter-select login-input"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                placeholder="••••••••"
              />
              <button
                type="button"
                className="login-password-toggle"
                onClick={() => setShowPassword((value) => !value)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                tabIndex={-1}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </label>

          {error && (
            <div className="login-error" role="alert">
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          <button type="submit" className="btn-primary login-submit" disabled={submitting}>
            {submitting ? <RefreshCw size={16} className="icon-spin" /> : <LogIn size={16} />}
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="login-footnote">Protected workspace &middot; Contact an admin for access</p>
      </div>
    </div>
  );
}

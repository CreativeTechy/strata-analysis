import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';
import { LogIn, AlertCircle, RefreshCw, Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../auth/useAuth.js';
import { translateApiError } from '../lib/apiError.js';
import LanguageSwitcher from './LanguageSwitcher.jsx';

export default function LoginPage() {
  const { t } = useTranslation(['auth', 'common']);
  const { t: tErrors } = useTranslation('errors');
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
      setError((err.code ? translateApiError(tErrors, err) : err.message) || t('login.genericError'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      <div className="bg-pattern"></div>

      <div className="login-shell">
        <LanguageSwitcher className="login-language-switcher" />

        <div className="login-brand">
          <div className="login-logo">
            <img src="/favicon.png" alt={t('common:app.name')} />
          </div>
          <div>
            <h1 className="title login-title">{t('common:app.name')}</h1>
            <p className="subtitle">{t('login.brandTagline')}</p>
          </div>
        </div>

        <form onSubmit={onSubmit} className="glass-card login-card">
          <div className="login-card-heading">
            <h2>{t('login.heading')}</h2>
            <p className="subtitle">{t('login.subheading')}</p>
          </div>

          <label className="login-field">
            <span>{t('login.usernameLabel')}</span>
            <input
              className="filter-select login-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
              placeholder={t('login.usernamePlaceholder')}
              dir="ltr"
            />
          </label>

          <label className="login-field">
            <span>{t('login.passwordLabel')}</span>
            <div className="login-password-wrap">
              <input
                className="filter-select login-input"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                placeholder="••••••••"
                dir="ltr"
              />
              <button
                type="button"
                className="login-password-toggle"
                onClick={() => setShowPassword((value) => !value)}
                aria-label={showPassword ? t('login.hidePassword') : t('login.showPassword')}
                tabIndex={-1}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </label>

          {error && (
            <div className="login-error" role="alert">
              <AlertCircle size={16} />
              <span dir="auto">{error}</span>
            </div>
          )}

          <button type="submit" className="btn-primary login-submit" disabled={submitting}>
            {submitting ? <RefreshCw size={16} className="icon-spin" /> : <LogIn size={16} />}
            {submitting ? t('login.submitting') : t('login.submit')}
          </button>
        </form>

        <p className="login-footnote">{t('login.footnote')}</p>
      </div>
    </div>
  );
}

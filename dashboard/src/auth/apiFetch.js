const CSRF_COOKIE_NAME = 'strata_csrf';
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function readCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : '';
}

function isSameOriginApiRequest(input) {
  const url = typeof input === 'string' ? input : input?.url || '';
  if (url.startsWith('/api') || url.startsWith('/scrape')) return true;
  try {
    return new URL(url, window.location.href).origin === window.location.origin;
  } catch {
    return false;
  }
}

// Installs a one-time wrapper around window.fetch so every existing fetch()
// call site in the dashboard gets CSRF-protected mutations and a global
// 401 -> "you were logged out" signal, without editing each call site.
export function installApiInterceptor() {
  if (window.__strataFetchPatched) return;
  window.__strataFetchPatched = true;

  const nativeFetch = window.fetch.bind(window);

  window.fetch = async (input, init = {}) => {
    const method = (init.method || (typeof input !== 'string' && input?.method) || 'GET').toUpperCase();

    let nextInit = init;
    if (UNSAFE_METHODS.has(method) && isSameOriginApiRequest(input)) {
      const csrfToken = readCookie(CSRF_COOKIE_NAME);
      if (csrfToken) {
        nextInit = {
          ...init,
          headers: {
            ...(init.headers || {}),
            'X-CSRF-Token': csrfToken,
          },
        };
      }
    }

    const response = await nativeFetch(input, nextInit);
    if (response.status === 401 && isSameOriginApiRequest(input)) {
      window.dispatchEvent(new CustomEvent('strata:unauthorized'));
    }
    return response;
  };
}

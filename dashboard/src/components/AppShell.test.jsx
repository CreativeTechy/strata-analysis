import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import i18n from '../i18n/index.js';
import { useAuth } from '../auth/useAuth.js';
import AppShell from './AppShell.jsx';

vi.mock('../auth/useAuth.js', () => ({ useAuth: vi.fn() }));

function LocationView({ page }) {
  const location = useLocation();
  return <div>{page} content <output aria-label="Current search">{location.search}</output></div>;
}

function renderShell(initialEntry = '/dashboard') {
  useAuth.mockReturnValue({
    user: { username: 'jsmith', role: 'admin' },
    hasPermission: () => true,
    logout: vi.fn(),
  });
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/dashboard" element={<LocationView page="Dashboard" />} />
          <Route path="/reports" element={<LocationView page="Reports" />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('AppShell / Sidebar - RTL navigation and mobile drawer', () => {
  afterEach(async () => {
    await act(async () => {
      await i18n.changeLanguage('en');
    });
    document.documentElement.dir = 'ltr';
  });

  it('opens and closes the mobile navigation drawer in LTR', async () => {
    const user = userEvent.setup();
    renderShell();

    const openButton = screen.getByRole('button', { name: 'Open navigation' });
    await user.click(openButton);

    const closeButton = screen.getByRole('button', { name: 'Close navigation' });
    await user.click(closeButton);

    expect(screen.getByRole('button', { name: 'Open navigation' })).toBeInTheDocument();
  });

  it('renders translated Arabic navigation labels and mirrors the mobile drawer under RTL', async () => {
    await act(async () => {
      await i18n.changeLanguage('ar');
    });
    document.documentElement.dir = 'rtl';

    const user = userEvent.setup();
    renderShell();

    // Sidebar section/nav labels come from the `nav` namespace and must be
    // in Arabic once the interface locale is Arabic.
    expect(screen.getByText('لوحة المعلومات')).toBeInTheDocument();
    expect(screen.getByText('الرؤى')).toBeInTheDocument();

    // The desktop collapse toggle is direction-dependent chrome (collapse-
    // toward-an-edge) and must carry the mirroring hook so the global RTL
    // CSS rule can flip it.
    const collapseToggle = screen.getByRole('button', { name: 'طي شريط التنقل' });
    expect(collapseToggle.querySelector('.rtl-mirror')).toBeInTheDocument();

    const openButton = screen.getByRole('button', { name: 'فتح التنقل' });
    await user.click(openButton);
    expect(screen.getByRole('button', { name: 'إغلاق التنقل' })).toBeInTheDocument();
  });

  it('renders the logout label translated and keeps the raw role value as user content (dir=auto)', async () => {
    await act(async () => {
      await i18n.changeLanguage('ar');
    });
    renderShell();

    expect(screen.getByText('تسجيل الخروج')).toBeInTheDocument();
    const roleChip = screen.getByText('admin');
    expect(roleChip).toHaveAttribute('dir', 'auto');
  });

  it.each([
    ['period selection', '/dashboard?period=7d', '?period=7d'],
    ['analysis run selection', '/dashboard?run_id=run-42', '?run_id=run-42'],
  ])('preserves the %s when navigating from dashboard to reports', async (_label, initialEntry, expectedSearch) => {
    const user = userEvent.setup();
    renderShell(initialEntry);

    await user.click(screen.getByRole('link', { name: 'Reports' }));

    expect(screen.getByText('Reports content')).toBeInTheDocument();
    expect(screen.getByLabelText('Current search')).toHaveTextContent(expectedSearch);
  });
});

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import i18n, { LOCALE_STORAGE_KEY } from '../i18n/index.js';
import LanguageSwitcher from './LanguageSwitcher.jsx';

describe('LanguageSwitcher', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
    window.localStorage.clear();
  });

  it('shows both supported languages with English selected by default', () => {
    render(<LanguageSwitcher />);
    const english = screen.getByRole('button', { name: 'English' });
    const arabic = screen.getByRole('button', { name: 'العربية' });
    expect(english).toHaveAttribute('aria-pressed', 'true');
    expect(arabic).toHaveAttribute('aria-pressed', 'false');
  });

  it('switches the active i18next language and persists the choice on selection', async () => {
    const user = userEvent.setup();
    render(<LanguageSwitcher />);
    await user.click(screen.getByRole('button', { name: 'العربية' }));

    await waitFor(() => expect(i18n.language).toBe('ar'));
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('ar');
  });
});

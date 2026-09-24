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
    const select = screen.getByRole('combobox');
    expect(select.value).toBe('en');
    expect(screen.getByRole('option', { name: 'English' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'العربية' })).toBeInTheDocument();
  });

  it('switches the active i18next language and persists the choice on selection', async () => {
    const user = userEvent.setup();
    render(<LanguageSwitcher />);
    await user.selectOptions(screen.getByRole('combobox'), 'ar');

    await waitFor(() => expect(i18n.language).toBe('ar'));
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('ar');
  });
});

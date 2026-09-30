import { afterEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DiscoveryLog } from './CompetitorOnboarding.jsx';
import i18n from '../i18n/index.js';

describe('DiscoveryLog', () => {
  afterEach(() => i18n.changeLanguage('en'));

  it('shows coded progress lines in the UI language, uncoded ones as sent', async () => {
    await i18n.changeLanguage('ar');
    render(
      <DiscoveryLog
        active={false}
        logs={[
          { ts: '2026-09-30T07:00:00Z', message: 'Scope: 1 document.', code: 'scope_documents', params: { count: 1 } },
          { ts: '2026-09-30T07:00:01Z', message: 'Kept 13 article(s) as evidence.', code: 'kept_evidence', params: { count: 13 } },
          { ts: '2026-09-30T07:00:02Z', message: 'A line from an older run.' },
        ]}
      />,
    );
    expect(screen.getByText('النطاق: مستند واحد.')).toBeInTheDocument();
    expect(screen.getByText('تم الاحتفاظ بـ 13 مقالًا كدليل.')).toBeInTheDocument();
    expect(screen.getByText('A line from an older run.')).toBeInTheDocument();
    expect(screen.queryByText('Scope: 1 document.')).not.toBeInTheDocument();
  });
});

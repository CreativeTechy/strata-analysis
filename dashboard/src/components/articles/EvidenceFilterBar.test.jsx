import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import EvidenceFilterBar from './EvidenceFilterBar.jsx';
import i18n from '../../i18n/index.js';
import { LabelProjectProvider } from '../../i18n/LabelProjectContext.jsx';
import { resetTranslatedLabelsCache } from '../../i18n/useTranslatedLabels.js';
import { translateLabels } from '../../api/i18nApi.js';

vi.mock('../../api/i18nApi.js', () => ({ translateLabels: vi.fn() }));

function renderBar(evidence, handlers = {}) {
  return render(
    <LabelProjectProvider value={8}>
      <EvidenceFilterBar evidence={evidence} sentiment="all" run={null} onRemove={handlers.onRemove || vi.fn()} onRemoveSentiment={vi.fn()} onClear={vi.fn()} />
    </LabelProjectProvider>,
  );
}

describe('EvidenceFilterBar', () => {
  beforeEach(() => {
    resetTranslatedLabelsCache();
    translateLabels.mockReset();
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('labels demographic and platform chips in Arabic, like the slice they came from', async () => {
    await i18n.changeLanguage('ar');
    translateLabels.mockResolvedValue({ Retired: 'متقاعد' });
    renderBar({ period: '30d', region: 'Lebanon\u200f', gender: 'female', age_range: '65_plus', segment: 'Retired', platform: 'Documents' });
    expect(screen.getByText('لبنان')).toBeInTheDocument();
    expect(screen.getByText('أنثى')).toBeInTheDocument();
    expect(screen.getByText('65 فأكثر')).toBeInTheDocument();
    expect(screen.getByText('المستندات')).toBeInTheDocument();
    expect(await screen.findByText('متقاعد')).toBeInTheDocument();
    expect(translateLabels).toHaveBeenCalledWith(8, 'ar', ['Retired']);
  });

  it('removes one dimension at a time', async () => {
    await i18n.changeLanguage('en');
    const onRemove = vi.fn();
    renderBar({ region: 'Lebanon' }, { onRemove });
    expect(screen.getByText('Lebanon')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: i18n.t('articles:evidence.remove', { label: 'Lebanon' }) }));
    expect(onRemove).toHaveBeenCalledWith('region');
  });

  it('renders nothing without an evidence scope or bucket', () => {
    const { container } = renderBar({});
    expect(container).toBeEmptyDOMElement();
  });
});

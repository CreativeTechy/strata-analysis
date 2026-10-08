import { cloneElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import DemographicSentimentChart from './DemographicSentimentChart.jsx';
import i18n from '../i18n/index.js';
import { LabelProjectProvider } from '../i18n/LabelProjectContext.jsx';
import { resetTranslatedLabelsCache } from '../i18n/useTranslatedLabels.js';
import { translateLabels } from '../api/i18nApi.js';

// A fixed size instead of the measured one, so recharts draws its axis
// labels in jsdom - those labels are what this suite checks.
vi.mock('./ResponsiveChartContainer.jsx', () => ({
  default: ({ children }) => cloneElement(children, { width: 600, height: 300 }),
}));
vi.mock('../api/i18nApi.js', () => ({ translateLabels: vi.fn() }));

const row = (value, total) => ({ value, total, positive: total, negative: 0, neutral: 0, mixed: 0 });

function renderChart(data) {
  return render(
    <LabelProjectProvider value={3}>
      <DemographicSentimentChart title="Region" data={data} />
    </LabelProjectProvider>,
  );
}

describe('DemographicSentimentChart', () => {
  beforeEach(() => {
    resetTranslatedLabelsCache();
    translateLabels.mockReset();
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('labels every bucket in Arabic: countries however stored, enums, and free text', async () => {
    await i18n.changeLanguage('ar');
    translateLabels.mockResolvedValue({ 'North Sea': 'بحر الشمال' });
    const { container } = renderChart([row('Lebanon\u200f', 5), row('لبنان', 2), row('North Sea', 2), row('unknown', 1)]);
    expect(screen.getAllByText('لبنان').length).toBeGreaterThan(0);
    expect(screen.getAllByText('غير معروف').length).toBeGreaterThan(0);
    expect((await screen.findAllByText('بحر الشمال')).length).toBeGreaterThan(0);
    expect(translateLabels).toHaveBeenCalledWith(3, 'ar', ['North Sea']);
    expect(container).not.toHaveTextContent(/Lebanon|North Sea|Unknown/);
  });

  it('labels gender and age buckets in English without asking the server', async () => {
    await i18n.changeLanguage('en');
    renderChart([row('female', 3), row('male', 2), row('65_plus', 1)]);
    for (const label of ['Female', 'Male', '65+']) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    expect(translateLabels).not.toHaveBeenCalled();
  });

  it('shows the not-enough-signal state for fewer than two buckets', async () => {
    await i18n.changeLanguage('en');
    const { container } = renderChart([row('female', 3)]);
    expect(screen.getByText(i18n.t('dashboard:demographicChart.notEnoughSignalTitle'))).toBeInTheDocument();
    // Scoped to the chart: recharts leaves its text-measuring span in <body>.
    expect(container).not.toHaveTextContent('Female');
  });
});

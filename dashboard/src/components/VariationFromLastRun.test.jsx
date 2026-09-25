import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import VariationFromLastRun from './VariationFromLastRun.jsx';
import { getReportVariation } from '../api/projectsApi.js';
import i18n from '../i18n/index.js';

vi.mock('../api/projectsApi.js', () => ({ getReportVariation: vi.fn() }));

const COMPARISON = {
  status: 'ok',
  current_scope_label: 'Analysis #3 - Mar 03, 2026',
  previous_scope_label: 'Analysis #2 - Jan 10, 2026',
  current_sequence_number: 3,
  previous_sequence_number: 2,
  current_date: '2026-03-03',
  previous_date: '2026-01-10',
  narrative: 'Ideas & Themes:\nDelivery improved between the two runs.',
  metrics: {
    current: { total: 10, net_sentiment: 40 },
    previous: { total: 8, net_sentiment: 0 },
    deltas: { net_sentiment: 40 },
    coverage: { common: 6, added: 4, removed: 2 },
  },
};

describe('VariationFromLastRun', () => {
  beforeEach(() => getReportVariation.mockReset());

  it('loads and renders the selected run comparison', async () => {
    getReportVariation.mockResolvedValue(COMPARISON);
    render(<VariationFromLastRun projectId={1} runId="run-3" />);

    expect(await screen.findByText(/Delivery improved/)).toBeInTheDocument();
    expect(screen.getByText('Analysis #3 - Mar 3, 2026 compared with Analysis #2 - Jan 10, 2026')).toBeInTheDocument();
    expect(screen.getByText('6 articles in both runs · 4 added · 2 removed')).toBeInTheDocument();
    expect(screen.getByText('+40')).toBeInTheDocument();
    expect(screen.getByText('Selected run articles')).toBeInTheDocument();
    expect(getReportVariation).toHaveBeenCalledWith(1, { run_id: 'run-3' }, expect.any(AbortSignal));
  });

  it('regenerates on demand', async () => {
    getReportVariation.mockResolvedValue(COMPARISON);
    render(<VariationFromLastRun projectId={1} runId="run-3" />);
    await screen.findByText(/Delivery improved/);

    fireEvent.click(screen.getByRole('button', { name: 'Regenerate variation from last run' }));
    await waitFor(() => expect(getReportVariation).toHaveBeenLastCalledWith(
      1, { run_id: 'run-3', regenerate: 'true' },
    ));
  });

  it('asks for a run without making a request in date-range mode', () => {
    render(<VariationFromLastRun projectId={1} runId={null} />);
    expect(screen.getByText(/Select an analysis run/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Regenerate variation from last run' })).toBeDisabled();
    expect(getReportVariation).not.toHaveBeenCalled();
  });

  it('shows a translated reason for an unavailable comparison', async () => {
    getReportVariation.mockResolvedValue({
      status: 'unavailable',
      reason_code: 'no_previous_run',
      reason: 'No previous analysis run with saved results exists for this project.',
      metrics: { current: { total: 4 }, previous: null, deltas: null, coverage: null },
    });
    render(<VariationFromLastRun projectId={1} runId="run-1" />);
    expect(await screen.findByText('No previous analysis run with saved results exists for this project.')).toBeInTheDocument();
  });

  it('shows the generic narrative-failure notice instead of the raw reason', async () => {
    getReportVariation.mockResolvedValue({ ...COMPARISON, status: 'llm_failed', narrative: null, reason: 'Model host unreachable' });
    render(<VariationFromLastRun projectId={1} runId="run-3" />);
    const notice = await screen.findByText('The narrative could not be generated; verified metrics are still shown.');
    expect(notice).toHaveAttribute('title', 'Model host unreachable');
    expect(screen.getByText('Selected run articles')).toBeInTheDocument();
  });

  it('renders every label in Arabic', async () => {
    await i18n.changeLanguage('ar');
    getReportVariation.mockResolvedValue(COMPARISON);
    render(<VariationFromLastRun projectId={1} runId="run-3" />);

    expect(await screen.findByRole('heading', { name: 'التغيّر منذ آخر عملية تحليل' })).toBeInTheDocument();
    expect(screen.getByText(/^التحليل رقم 3 - .* مقارنةً مع التحليل رقم 2 - /)).toBeInTheDocument();
    expect(screen.getByText('مقالات عملية التحليل المحددة')).toBeInTheDocument();
    expect(screen.getByText('6 مقالات مشتركة بين العمليتين · المُضافة: 4 · المحذوفة: 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'إعادة إنشاء التغيّر منذ آخر عملية تحليل' })).toBeInTheDocument();
    expect(screen.queryByText(/Selected run articles|compared with/)).not.toBeInTheDocument();
  });

  it('shows the Arabic reason for an unavailable comparison', async () => {
    await i18n.changeLanguage('ar');
    getReportVariation.mockResolvedValue({ status: 'unavailable', reason_code: 'no_current_articles', metrics: {} });
    render(<VariationFromLastRun projectId={1} runId="run-1" />);
    expect(await screen.findByText('لا توجد مقالات محلَّلة في عملية التحليل المحددة.')).toBeInTheDocument();
  });
});

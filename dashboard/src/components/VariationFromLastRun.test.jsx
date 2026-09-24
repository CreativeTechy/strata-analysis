import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import VariationFromLastRun from './VariationFromLastRun.jsx';
import { getReportVariation } from '../api/projectsApi.js';

vi.mock('../api/projectsApi.js', () => ({ getReportVariation: vi.fn() }));

const COMPARISON = {
  status: 'ok',
  current_scope_label: 'Analysis #3 - Mar 03, 2026',
  previous_scope_label: 'Analysis #2 - Jan 10, 2026',
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
    expect(screen.getByText(/Analysis #3.*compared with Analysis #2/)).toBeInTheDocument();
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
});

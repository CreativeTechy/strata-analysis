import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import i18n from '../i18n/index.js';
import { XAxis, YAxis } from './ChartAxes.jsx';

// Recharts' own axes need a chart around them to render anything, so they're
// replaced with props recorders - what matters here is what the wrappers
// hand Recharts, not how Recharts then draws it.
const received = vi.hoisted(() => ({ x: null, y: null }));
vi.mock('recharts', () => ({
  XAxis: (props) => { received.x = props; return null; },
  YAxis: (props) => { received.y = props; return null; },
}));

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('ChartAxes', () => {
  it('passes LTR axes through with only the category padding added', async () => {
    await i18n.changeLanguage('en');
    render(<><XAxis dataKey="date" /><YAxis allowDecimals={false} /></>);

    expect(received.x).toEqual({ dataKey: 'date', padding: { left: 16, right: 16 } });
    expect(received.y).toEqual({ allowDecimals: false });
  });

  it('mirrors both axes for an RTL locale', async () => {
    await i18n.changeLanguage('ar');
    render(<><XAxis dataKey="date" /><YAxis /></>);

    expect(received.x).toMatchObject({ dataKey: 'date', reversed: true });
    expect(received.y).toMatchObject({ orientation: 'right' });
  });

  it('keeps a numeric axis flush with the plot edge', async () => {
    await i18n.changeLanguage('ar');
    render(<XAxis type="number" domain={[0, 100]} />);

    expect(received.x).not.toHaveProperty('padding');
    expect(received.x).toMatchObject({ type: 'number', reversed: true });
  });

  it('lets a chart set its own padding', async () => {
    render(<XAxis dataKey="date" padding={{ left: 0, right: 0 }} />);

    expect(received.x.padding).toEqual({ left: 0, right: 0 });
  });
});

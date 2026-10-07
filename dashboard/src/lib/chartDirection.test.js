import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { directionalMargin, directionalXAxisProps, directionalYAxisProps } from './chartDirection.js';

describe('directionalXAxisProps', () => {
  it('leaves an LTR axis alone', () => {
    expect(directionalXAxisProps({}, false)).toEqual({});
    expect(directionalXAxisProps({ reversed: true }, false)).toEqual({});
  });

  it('runs an RTL axis right-to-left', () => {
    expect(directionalXAxisProps({}, true)).toEqual({ reversed: true });
  });

  it('un-reverses an axis that was already reversed in LTR', () => {
    expect(directionalXAxisProps({ reversed: true }, true)).toEqual({ reversed: false });
  });
});

describe('directionalYAxisProps', () => {
  it('leaves an LTR axis alone', () => {
    expect(directionalYAxisProps({}, false)).toEqual({});
  });

  it('moves the value axis to the other side in RTL', () => {
    expect(directionalYAxisProps({}, true)).toEqual({ orientation: 'right' });
    expect(directionalYAxisProps({ orientation: 'right' }, true)).toEqual({ orientation: 'left' });
  });
});

describe('directionalMargin', () => {
  it('leaves an LTR margin alone', () => {
    const margin = { top: 4, right: 16, left: 0, bottom: 4 };
    expect(directionalMargin(margin, false)).toBe(margin);
  });

  it('swaps left and right in RTL', () => {
    expect(directionalMargin({ top: 4, right: 16, left: 0, bottom: 4 }, true))
      .toEqual({ top: 4, right: 0, left: 16, bottom: 4 });
  });

  it('does not invent a side the caller left to the Recharts default', () => {
    expect(directionalMargin({ top: 4, right: 16 }, true)).toEqual({ top: 4, left: 16 });
    expect(directionalMargin(undefined, true)).toBeUndefined();
  });
});

// The axis-label overlap under dir="rtl" is fixed in CSS, not props - this
// keeps that rule from being dropped in a stylesheet cleanup.
describe('chart text direction rule', () => {
  it('pins Recharts SVG text to ltr with per-label bidi', () => {
    const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../styles/index.css'), 'utf8');
    const rule = css.match(/\.recharts-surface text\s*\{([^}]*)\}/);
    expect(rule?.[1]).toMatch(/direction:\s*ltr/);
    expect(rule?.[1]).toMatch(/unicode-bidi:\s*plaintext/);
  });
});

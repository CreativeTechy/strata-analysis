import { useLocale } from '../i18n/useLocale.js';

/**
 * Recharts lays every chart out in physical SVG coordinates and knows nothing
 * about document direction: under <html dir="rtl"> its axes still start on
 * the left and time still runs left-to-right, the opposite of how the rest of
 * an Arabic page reads. These helpers mirror a cartesian chart's horizontal
 * direction for an RTL locale - the category/time axis runs right-to-left and
 * the value axis sits on the right - and are applied once, inside
 * ChartAxes.jsx's XAxis/YAxis, so no individual chart has to remember to.
 *
 * (The other half of RTL chart breakage - SVG labels drawn on top of the axis
 * they label - is CSS, not props: see the "Charts" block in index.css.)
 */

// XOR rather than a plain `true`, so a chart that deliberately reverses its
// axis in LTR still reads mirrored (i.e. un-reversed) in RTL.
export function directionalXAxisProps({ reversed = false } = {}, isRtl = false) {
  return isRtl ? { reversed: !reversed } : {};
}

const MIRRORED_Y_ORIENTATION = { left: 'right', right: 'left' };

export function directionalYAxisProps({ orientation = 'left' } = {}, isRtl = false) {
  return isRtl ? { orientation: MIRRORED_Y_ORIENTATION[orientation] || orientation } : {};
}

// Swaps left/right of a chart's `margin`, so the extra room a chart leaves
// for (say) its last tick label follows that label to the other side.
// Only the keys the caller set are swapped - an unset side stays unset so
// Recharts' own default still applies to it.
export function directionalMargin(margin, isRtl = false) {
  if (!isRtl || !margin) return margin;
  const { left, right, ...rest } = margin;
  const mirrored = { ...rest };
  if (right !== undefined) mirrored.left = right;
  if (left !== undefined) mirrored.right = left;
  return mirrored;
}

export function useDirectionalMargin(margin) {
  const { isRtl } = useLocale();
  return directionalMargin(margin, isRtl);
}

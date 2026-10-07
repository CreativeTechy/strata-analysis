import { XAxis as RechartsXAxis, YAxis as RechartsYAxis } from 'recharts';
import { useLocale } from '../i18n/useLocale.js';
import { directionalXAxisProps, directionalYAxisProps } from '../lib/chartDirection.js';

// Drop-in replacements for Recharts' XAxis/YAxis that mirror for an RTL
// locale (see lib/chartDirection.js). Every cartesian chart imports its axes
// from here - eslint.config.js rejects importing them from 'recharts'
// directly - so a new chart gets the right direction without having to know
// it needs to.

// With no padding a category axis puts its first tick exactly on the value
// axis, so that tick's centered label runs into the value axis's lowest
// label in the corner (and the last one into the card edge). A numeric axis
// keeps Recharts' default: there the edge *is* the 0%/minimum value.
const CATEGORY_AXIS_PADDING = { left: 16, right: 16 };

export function XAxis(props) {
  const { isRtl } = useLocale();
  const defaults = props.type === 'number' ? {} : { padding: CATEGORY_AXIS_PADDING };
  return <RechartsXAxis {...defaults} {...props} {...directionalXAxisProps(props, isRtl)} />;
}

export function YAxis(props) {
  const { isRtl } = useLocale();
  return <RechartsYAxis {...props} {...directionalYAxisProps(props, isRtl)} />;
}

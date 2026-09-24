import { ResponsiveContainer } from 'recharts';

const INITIAL_CHART_DIMENSION = { width: 1, height: 1 };

export default function ResponsiveChartContainer(props) {
  return <ResponsiveContainer initialDimension={INITIAL_CHART_DIMENSION} {...props} />;
}

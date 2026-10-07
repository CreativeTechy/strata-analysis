import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // Charts must mirror for RTL locales; the wrappers do that once so no
      // chart can forget to (see src/lib/chartDirection.js).
      'no-restricted-imports': ['error', {
        paths: [{
          name: 'recharts',
          importNames: ['XAxis', 'YAxis', 'ResponsiveContainer'],
          message: "Import XAxis/YAxis from './ChartAxes.jsx' and ResponsiveContainer from './ResponsiveChartContainer.jsx' so the chart follows the page direction.",
        }],
      }],
    },
  },
  {
    files: ['src/components/ChartAxes.jsx', 'src/components/ResponsiveChartContainer.jsx'],
    rules: { 'no-restricted-imports': 'off' },
  },
])

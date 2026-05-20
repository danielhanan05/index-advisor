/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
        sans: ['"DM Sans"', 'sans-serif'],
        display: ['"Space Grotesk"', 'sans-serif'],
      },
      colors: {
        bg: {
          base: '#0c0e0f',
          surface: '#111416',
          elevated: '#171b1e',
          border: '#1e2327',
          hover: '#1c2024',
        },
        green: {
          400: '#4ade80',
          500: '#22c55e',
          600: '#16a34a',
          dim: '#1a3326',
          glow: 'rgba(74, 222, 128, 0.15)',
        },
        amber: {
          400: '#fbbf24',
          dim: '#2d2310',
        },
        red: {
          400: '#f87171',
          dim: '#2d1515',
        },
        blue: {
          400: '#60a5fa',
          dim: '#0f1d35',
        },
        text: {
          primary: '#e8eaec',
          secondary: '#8b9299',
          muted: '#4a5260',
          accent: '#4ade80',
        },
      },
    },
  },
  plugins: [],
}

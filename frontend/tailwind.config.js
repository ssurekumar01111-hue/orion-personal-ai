/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        orion: {
          950: '#090b0e',
          900: '#0d1017',
          850: '#121620',
          800: '#181e2b',
          750: '#1f2737',
          700: '#273145',
          600: '#384661',
          500: '#526487',
          400: '#7e90b2',
          300: '#adc0de',
          200: '#d7e2f1',
          100: '#f0f5fb',
          accent: '#06b6d4',      // cyan-500
          accentHover: '#0891b2', // cyan-600
          emerald: '#10b981',
          amber: '#f59e0b',
          rose: '#f43f5e',
        }
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Menlo', 'Monaco', 'Courier New', 'monospace'],
      }
    },
  },
  plugins: [],
}

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx}',
    './components/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        'brut-bg': '#f5f2eb',
        'brut-bg2': '#ede9e0',
        'brut-hero': '#11110f',
        'brut-ink': '#1a1814',
        'brut-ink2': '#3d3a34',
        'brut-muted': '#8a8680',
        'brut-accent': '#e8410a',
        'brut-yellow': '#f5c842',
        'brut-border': '#d4cfc5',
        'brut-border2': '#c5bfb4',
        brand: {
          50: '#f5f3ff',
          100: '#ede9fe',
          200: '#ddd6fe',
          500: '#8b5cf6',
          600: '#7c3aed',
          700: '#6d28d9',
          800: '#5b21b6',
        },
      },
      fontFamily: {
        syne: ['Syne', 'sans-serif'],
        mono: ['DM Mono', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
        code: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      borderWidth: {
        DEFAULT: '1px',
        2: '2px',
      },
    },
  },
  plugins: [],
}

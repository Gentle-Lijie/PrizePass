/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: 'rgb(var(--color-ink) / <alpha-value>)',
        accent: 'rgb(var(--color-accent) / <alpha-value>)',
        canvas: 'rgb(var(--color-canvas) / <alpha-value>)',
      },
    },
  },
  plugins: [],
}

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#172033',
        accent: '#2563eb',
        canvas: '#f5f7fb',
      },
    },
  },
  plugins: [],
}

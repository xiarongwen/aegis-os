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
        bg: 'var(--color-bg)',
        surface: 'var(--color-surface)',
        border: 'var(--color-border)',
        text: 'var(--color-text)',
        muted: 'var(--color-muted)',
        primary: 'var(--color-primary)',
        'primary-text': 'var(--color-primary-text)',
        bubble: 'var(--color-bubble)',
        'bubble-self': 'var(--color-bubble-self)',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
  ],
}

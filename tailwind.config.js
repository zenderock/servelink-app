/** @type {import('tailwindcss').Config} */
const defaultTheme = require('tailwindcss/defaultTheme')

module.exports = {
  darkMode: 'class',
  content: [
    './app/templates/**/*.html',
    './app/static/**/*.js',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter var', ...defaultTheme.fontFamily.sans],
        mono: ['JetBrains Mono', ...defaultTheme.fontFamily.mono],
      },
      colors: {
        border: "hsl(var(--border))",
        input: {
          DEFAULT: "hsl(var(--input))",
          placeholder: "hsl(var(--input-placeholder))",
        },
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        danger: {
          DEFAULT: "hsl(var(--danger))",
          foreground: "hsl(var(--danger-foreground))",
        },
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
      },
    },
  },
  safelist: [
    ...['red', 'orange', 'amber', 'yellow', 'lime', 'green', 'emerald', 
       'teal', 'cyan', 'sky', 'blue', 'indigo', 'violet', 'purple', 
       'fuchsia', 'pink', 'rose'].flatMap(color => [
      `from-${color}-100`,
      `to-${color}-100/50`,
      `border-${color}-200`,
      `dark:from-${color}-950/50`,
      `dark:to-${color}-950`,
      `dark:border-${color}-900`,
      `text-${color}-500`
    ])
  ],
  plugins: [
    require('@tailwindcss/forms'),
  ],
}
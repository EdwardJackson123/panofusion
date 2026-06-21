/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        serif: ['Georgia', 'Cambria', '"Times New Roman"', 'serif'],
        sans: ['"Inter"', 'system-ui', '-apple-system', 'Arial', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', '"Consolas"', 'monospace'],
      },
      colors: {
        // Anthropic-inspired warm palette
        parchment: '#f5f4ed',
        ivory: '#faf9f5',
        'near-black': '#141413',
        terracotta: {
          DEFAULT: '#c96442',
          light: '#d97757',
          dark: '#b35438',
        },
        charcoal: {
          warm: '#4d4c48',
          dark: '#3d3d3a',
        },
        olive: {
          gray: '#5e5d59',
        },
        stone: {
          gray: '#87867f',
        },
        'warm-silver': '#b0aea5',
        'warm-sand': '#e8e6dc',
        'dark-surface': '#30302e',
        // Semantic
        border: {
          cream: '#f0eee6',
          warm: '#e8e6dc',
          dark: '#30302e',
        },
        ring: {
          warm: '#d1cfc5',
          subtle: '#dedc01',
          deep: '#c2c0b6',
        },
        focus: {
          blue: '#3898ec',
        },
        error: {
          crimson: '#b53333',
        },
      },
      fontSize: {
        'display': ['4rem', { lineHeight: '1.10', fontWeight: '500' }],
        'section': ['3.25rem', { lineHeight: '1.20', fontWeight: '500' }],
        'subhead-lg': ['2.3rem', { lineHeight: '1.30', fontWeight: '500' }],
        'subhead': ['2rem', { lineHeight: '1.10', fontWeight: '500' }],
        'subhead-sm': ['1.6rem', { lineHeight: '1.20', fontWeight: '500' }],
        'feature': ['1.3rem', { lineHeight: '1.20', fontWeight: '500' }],
        'body-serif': ['1.06rem', { lineHeight: '1.60', fontWeight: '400' }],
        'body-lg': ['1.25rem', { lineHeight: '1.60', fontWeight: '400' }],
        'body': ['1rem', { lineHeight: '1.60', fontWeight: '400' }],
        'body-sm': ['0.94rem', { lineHeight: '1.60', fontWeight: '400' }],
        'caption': ['0.88rem', { lineHeight: '1.43', fontWeight: '400' }],
        'label': ['0.75rem', { lineHeight: '1.60', fontWeight: '500', letterSpacing: '0.12px' }],
        'overline': ['0.63rem', { lineHeight: '1.60', fontWeight: '400', letterSpacing: '0.5px' }],
        'micro': ['0.6rem', { lineHeight: '1.60', fontWeight: '400', letterSpacing: '0.096px' }],
        'code': ['0.94rem', { lineHeight: '1.60', fontWeight: '400', letterSpacing: '-0.32px' }],
      },
      borderRadius: {
        'sharp': '4px',
        'subtle': '6px',
        'comfortable': '8px',
        'generous': '12px',
        'very': '16px',
        'highly': '24px',
        'max': '32px',
      },
      boxShadow: {
        'ring-warm': '0px 0px 0px 1px #d1cfc5',
        'ring-subtle': '0px 0px 0px 1px #dedc01',
        'ring-deep': '0px 0px 0px 1px #c2c0b6',
        'ring-terracotta': '0px 0px 0px 1px #c96442',
        'whisper': 'rgba(0,0,0,0.05) 0px 4px 24px',
        'inset-warm': 'inset 0px 0px 0px 1px rgba(0,0,0,0.15)',
      },
      spacing: {
        'section': '80px',
      },
    },
  },
  plugins: [],
}

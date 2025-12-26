/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                'background': '#0a0a0c',
                'panel': '#161925',
                'oled': '#000000',
                'tv-bg': '#131722',
                'tv-grid': '#2a2e39',
                'tv-green': '#22ab94',
                'tv-red': '#f23645',
                'accent-cyan': '#00FFFF',
                'accent-purple': '#BF00FF',
                'accent-green': '#39FF14',
                'accent-red': '#FF3131',
            },
            fontFamily: {
                sans: ['Outfit', 'sans-serif'],
                mono: ['JetBrains Mono', 'monospace'],
            },
            boxShadow: {
                'neon-cyan': '0 0 20px rgba(0, 255, 255, 0.15)',
                'neon-green': '0 0 20px rgba(57, 255, 20, 0.15)',
            },
            backgroundImage: {
                'glow-conic': 'conic-gradient(from 180deg at 50% 50%, #00f5ff 0deg, #9d00ff 120deg, #00ff9d 240deg, #00f5ff 360deg)',
            }
        },
    },
    plugins: [],
}

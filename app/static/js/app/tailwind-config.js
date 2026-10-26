
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: { sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'] },
                    colors: {
                        brand: {
                            /* Fallback chain: tenant branding → violet. Without the
                               fallback, an unbranded tenant renders bg-brand-600 as
                               transparent and white labels become invisible. */
                            50: 'color-mix(in srgb, var(--brand-color, #7c3aed) 5%, white)',
                            100: 'color-mix(in srgb, var(--brand-color, #7c3aed) 10%, white)',
                            200: 'color-mix(in srgb, var(--brand-color, #7c3aed) 20%, white)',
                            300: 'color-mix(in srgb, var(--brand-color, #7c3aed) 35%, white)',
                            400: 'color-mix(in srgb, var(--brand-color, #7c3aed) 55%, white)',
                            500: 'color-mix(in srgb, var(--brand-color, #7c3aed) 70%, white)',
                            600: 'var(--brand-color, #7c3aed)',
                            700: 'color-mix(in srgb, var(--brand-color, #7c3aed) 85%, black)',
                            800: 'color-mix(in srgb, var(--brand-color, #7c3aed) 65%, black)',
                            900: 'color-mix(in srgb, var(--brand-color, #7c3aed) 45%, black)',
                            950: 'color-mix(in srgb, var(--brand-color, #7c3aed) 25%, black)',
                        },
                        ink: {
                            50: '#fbfbfd', 100: '#f5f5f7', 200: '#e8e8ed',
                            300: '#d2d2d7', 400: '#aeaeb2', 500: '#86868b',
                            600: '#6e6e73', 700: '#3a3a3c', 800: '#1d1d1f',
                            900: '#1d1d1f', 950: '#0d0d0f',
                        }
                    },
                    boxShadow: {
                        'xs': '0 1px 2px 0 rgba(0,0,0,0.04)',
                        'soft': '0 1px 3px 0 rgba(0,0,0,0.04), 0 1px 2px -1px rgba(0,0,0,0.02)',
                        'card': '0 1px 3px 0 rgba(0,0,0,0.05), 0 0 0 1px rgba(0,0,0,0.03)',
                        'card-hover': '0 8px 30px -6px rgba(0,0,0,0.08), 0 0 0 1px rgba(0,0,0,0.04)',
                        'lift': '0 20px 60px -12px rgba(0,0,0,0.10), 0 2px 8px -2px rgba(0,0,0,0.04)',
                        'modal': '0 24px 80px -8px rgba(0,0,0,0.12), 0 2px 8px -2px rgba(0,0,0,0.06), 0 0 0 1px rgba(0,0,0,0.04)',
                        'glow': '0 4px 20px -4px rgba(139,92,246,0.15)',
                    },
                    borderRadius: {
                        '2xl': '1rem', '3xl': '1.25rem', '4xl': '1.75rem',
                    },
                    transitionTimingFunction: {
                        'spring': 'cubic-bezier(0.25, 0.46, 0.45, 0.94)',
                        'out-expo': 'cubic-bezier(0.16, 1, 0.3, 1)',
                    }
                }
            }
        }

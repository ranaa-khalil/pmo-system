/** Tailwind build config — ADR-07: compiled Tailwind replaces the Play CDN.
 *
 *  theme.extend is copied VERBATIM from app/static/js/app/tailwind-config.js
 *  (the Play CDN's runtime config). The CDN was Tailwind v3.4.17; the build
 *  pins the same version, so the compiled artifact generates the exact same
 *  utilities the JIT did — zero visual change is the acceptance gate
 *  (tests/test_css_coverage.py).
 *
 *  The token keys below consume app/static/css/tokens.css (§6) via var()
 *  where Tailwind supports it. Every addition is a NEW name — nothing the
 *  CDN generated today is renamed, overridden or removed.
 *
 *  NOTE on `colors.brand`: it stays the TENANT-DYNAMIC palette
 *  (color-mix over --brand-color, violet default) — that is what
 *  text-brand-600 etc. rendered under the CDN. The §6 static indigo scale
 *  lives in tokens.css as --brand-50…700 and is a separate system.
 */
module.exports = {
    content: [
        './app/templates/**/*.html',
        './app/static/js/**/*.js',
    ],
    theme: {
        extend: {
            /* verbatim from tailwind-config.js */
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
                },
                /* tokens.css §6 — state colors (additive, new names) */
                state: {
                    success: 'var(--state-success, #10b981)',
                    warning: 'var(--state-warning, #f59e0b)',
                    danger: 'var(--state-danger, #ef4444)',
                    neutral: 'var(--state-neutral, #64748b)',
                },
                /* tokens.css §6 — accent (additive, new name) */
                accent: {
                    600: 'var(--accent-600, #7c3aed)',
                },
            },
            /* verbatim from tailwind-config.js */
            boxShadow: {
                'xs': '0 1px 2px 0 rgba(0,0,0,0.04)',
                'soft': '0 1px 3px 0 rgba(0,0,0,0.04), 0 1px 2px -1px rgba(0,0,0,0.02)',
                'card': '0 1px 3px 0 rgba(0,0,0,0.05), 0 0 0 1px rgba(0,0,0,0.03)',
                'card-hover': '0 8px 30px -6px rgba(0,0,0,0.08), 0 0 0 1px rgba(0,0,0,0.04)',
                'lift': '0 20px 60px -12px rgba(0,0,0,0.10), 0 2px 8px -2px rgba(0,0,0,0.04)',
                'modal': '0 24px 80px -8px rgba(0,0,0,0.12), 0 2px 8px -2px rgba(0,0,0,0.06), 0 0 0 1px rgba(0,0,0,0.04)',
                'glow': '0 4px 20px -4px rgba(139,92,246,0.15)',
                /* tokens.css §6 — elevation ladder (additive, new names).
                   e0 is "border only": a zero shadow, never `none` (the ring
                   var chain would emit invalid CSS). */
                'e0': '0 0 #0000',
                'e1': 'var(--elevation-1, 0 1px 2px 0 rgb(0 0 0 / 0.05))',
                'e2': 'var(--elevation-2, 0 4px 12px -2px rgb(0 0 0 / 0.10))',
                'e3': 'var(--elevation-3, 0 24px 60px -12px rgb(0 0 0 / 0.18))',
            },
            /* verbatim from tailwind-config.js */
            borderRadius: {
                '2xl': '1rem', '3xl': '1.25rem', '4xl': '1.75rem',
                /* tokens.css §6 — radii 6/8/10/999 only (additive, new names) */
                'token-sm': 'var(--radius-sm, 6px)',
                'token-md': 'var(--radius-md, 8px)',
                'token-lg': 'var(--radius-lg, 10px)',
                'token-pill': 'var(--radius-pill, 999px)',
            },
            /* verbatim from tailwind-config.js */
            transitionTimingFunction: {
                'spring': 'cubic-bezier(0.25, 0.46, 0.45, 0.94)',
                'out-expo': 'cubic-bezier(0.16, 1, 0.3, 1)',
            },
            /* tokens.css §6 — motion 150–200ms (additive, new names) */
            transitionDuration: {
                'fast': 'var(--motion-fast, 150ms)',
                'base': 'var(--motion-base, 200ms)',
            },
        },
    },
    plugins: [],
};

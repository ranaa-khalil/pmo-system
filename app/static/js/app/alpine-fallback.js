// Alpine.js fallback: if Alpine doesn't load within 5s, show a retry
// screen instead of stripping x-cloak.
//
// (Old behavior — removeAttribute('x-cloak') on every element — was the
// "many popups + no actions" bug: all 69 cloaked modals/drawers/panels
// became visible at once with no interactivity, because Alpine was the
// thing that makes them interactive. A versioned alpine.min.js?v=N import
// in pmo-app.js with retry/backoff now prevents the underlying failure;
// this screen is the last line of defense for anything that slips past
// the retries (offline, 502, corrupted download that survives revalidation).
setTimeout(function () {
    if (typeof Alpine === 'undefined') {
        console.error('[PMO] Alpine.js failed to load — showing retry screen');
        try {
            document.body.style.display = '';
            var host = document.querySelector('[x-data="pmoRoot"]') || document.body;
            host.innerHTML =
                '<div style="min-height:100vh;display:flex;align-items:center;justify-content:center;' +
                'background:#f8fafc;font-family:Inter,system-ui,sans-serif;color:#1e293b;padding:24px;box-sizing:border-box">' +
                '<div style="max-width:420px;text-align:center;background:#fff;border:1px solid #e2e8f0;' +
                'border-radius:16px;padding:32px;box-shadow:0 10px 30px rgba(15,23,42,.06)">' +
                '<div style="width:44px;height:44px;margin:0 auto 16px;border-radius:12px;background:#7c3aed;color:#fff;' +
                'display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:700">P</div>' +
                '<div style="font-size:16px;font-weight:600;margin-bottom:8px">The app didn&rsquo;t finish loading</div>' +
                '<div style="font-size:13px;color:#64748b;margin-bottom:20px;line-height:1.5">' +
                'This usually means the interface script was cut off partway (a dropped ' +
                'connection or a stale cached copy). Reloading fixes it.</div>' +
                '<button onclick="location.reload(true)" ' +
                'style="background:#7c3aed;color:#fff;border:0;border-radius:10px;padding:10px 22px;' +
                'font-size:14px;font-weight:600;cursor:pointer">Reload the app</button>' +
                '</div></div>';
        } catch (e) {
            // Last resort: leave the page as-is.
        }
    }
}, 5000);

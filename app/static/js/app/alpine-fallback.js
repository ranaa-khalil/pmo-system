// Alpine.js fallback: if Alpine doesn't load within 3s, show the page anyway.
// (Previously this file was an HTML <script> block served as .js — the browser
// parsed it as markup and the fallback never ran. Fixed in QA pass 2026-10-28.)
setTimeout(function () {
    if (typeof Alpine === 'undefined') {
        console.error('[PMO] Alpine.js failed to load from CDN — removing x-cloak');
        document.querySelectorAll('[x-cloak]').forEach(function (el) {
            el.removeAttribute('x-cloak');
        });
        document.body.style.display = '';
    }
}, 3000);

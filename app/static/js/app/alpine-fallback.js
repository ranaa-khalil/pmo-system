<!-- Fallback: if Alpine.js doesn't load within 3s, show the page anyway -->
<script>
    setTimeout(function() {
        if (typeof Alpine === 'undefined') {
            console.error('[PMO] Alpine.js failed to load from CDN — removing x-cloak');
            document.body.removeAttribute('x-cloak');
            document.body.style.display = '';
        }
    }, 3000);
</script>
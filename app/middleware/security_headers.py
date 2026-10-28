"""Security headers middleware — adds compliance/security headers to responses.

Adds: Content-Security-Policy, X-Frame-Options, X-Content-Type-Options,
Strict-Transport-Security (HSTS), Referrer-Policy.
"""
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "SAMEORIGIN"

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # HSTS (only in production with HTTPS)
        # response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Strict CSP with per-response nonce (set by app/frontend.py for the
        # SPA shell): script-src allows only nonced scripts + self-hosted
        # files — no unsafe-inline for scripts. 'unsafe-eval' is REQUIRED:
        # Alpine 3.x compiles every directive (x-show, @click, x-data) via
        # new Function(); without it every binding silently fails (all
        # x-show elements visible, all actions dead — the "popups on load"
        # incident). Scripts stay fully nonced; the eval surface is our own
        # self-hosted, nonced Alpine + app code only.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'nonce-{nonce}' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https:; "
            "frame-ancestors 'self'"
        ).format(nonce=getattr(request.state, "csp_nonce", ""))

        # Permissions policy
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        return response

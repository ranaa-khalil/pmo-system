"""Rate limiting middleware — per-tenant request rate limits.

Uses slowapi with an in-memory backend (upgradeable to Redis).
Free plan: 100 req/min, Paid plans: 1000 req/min.

Returns 429 with Retry-After header when limit is exceeded.
"""
import time
from collections import defaultdict

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.models.tenant import PLAN_FREE


# Rate limits per plan (requests per minute)
RATE_LIMITS = {
    PLAN_FREE: 500,       # 500 req/min
    "team": 2000,         # 2000 req/min
    "business": 5000,     # 5000 req/min
    "enterprise": 10000,  # 10000 req/min
}

DEFAULT_LIMIT = 500  # Default for unknown plans


class InMemoryRateLimiter:
    """Simple in-memory rate limiter using sliding window.

    Can be replaced with Redis backend for production.
    Stores: {tenant_id: [timestamp, timestamp, ...]}
    """

    def __init__(self):
        self._requests = defaultdict(list)
        self._window_seconds = 60  # 1 minute window

    def check(self, key: str, limit: int) -> tuple[bool, int]:
        """Check if a request is allowed.

        Returns (allowed, retry_after_seconds).
        """
        now = time.time()
        window_start = now - self._window_seconds

        # Remove old entries outside the window
        self._requests[key] = [ts for ts in self._requests[key] if ts > window_start]

        if len(self._requests[key]) >= limit:
            # Calculate retry-after (oldest entry in window + window - now)
            oldest = min(self._requests[key])
            retry_after = int(oldest + self._window_seconds - now) + 1
            return False, max(1, retry_after)

        self._requests[key].append(now)
        return True, 0

    def cleanup(self):
        """Remove expired entries to prevent memory growth."""
        now = time.time()
        window_start = now - self._window_seconds
        for key in list(self._requests.keys()):
            self._requests[key] = [ts for ts in self._requests[key] if ts > window_start]
            if not self._requests[key]:
                del self._requests[key]


# Singleton instance
rate_limiter = InMemoryRateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-tenant rate limiting middleware.

    Limits requests based on the tenant's plan.
    """

    SKIP_PATHS = {"/health", "/api/auth/login", "/api/auth/register", "/api/auth/accept-invite"}

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks and auth endpoints
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        # Skip non-API requests (static files, etc.)
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        # Try to get tenant_id from request state
        tenant_id = getattr(request.state, "tenant_id", None)
        plan = getattr(request.state, "tenant_plan", PLAN_FREE)

        # Use IP address as fallback for unauthenticated requests
        if not tenant_id:
            client_ip = request.client.host if request.client else "unknown"
            key = f"ip:{client_ip}"
            limit = DEFAULT_LIMIT
        else:
            key = f"tenant:{tenant_id}"
            limit = RATE_LIMITS.get(plan, DEFAULT_LIMIT)

        allowed, retry_after = rate_limiter.check(key, limit)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)

        # Add rate limit info to response headers
        remaining = max(0, limit - len(rate_limiter._requests.get(key, [])))
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response

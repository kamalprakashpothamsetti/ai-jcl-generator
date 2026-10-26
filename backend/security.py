"""Production Security, Access Control, Rate Limiting & Spend Guardrails.

Provides:
- Studio Access Key authentication for paid AI generation endpoints
- In-memory sliding-window IP rate limiting
- Daily spend quota enforcement to prevent runaway API billing
- Reverse proxy IP extraction (X-Forwarded-For)
- Safe constant-time token comparison
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import Header, HTTPException, Request


# =====================================================================
# 1. ACCESS KEY AUTHENTICATION
# =====================================================================

def get_configured_access_key() -> Optional[str]:
    """Retrieve studio access key from environment if configured."""
    key = os.getenv("STUDIO_API_KEY") or os.getenv("API_ACCESS_KEY")
    if key and key.strip():
        return key.strip()
    return None


def verify_ai_access_key(request: Request) -> None:
    """FastAPI helper to protect paid AI endpoints.

    If STUDIO_API_KEY is configured in backend environment:
      - Validates X-Studio-Access-Key or Authorization: Bearer <key>
      - Rejects missing or invalid keys with HTTP 401 Unauthorized
    If STUDIO_API_KEY is not set:
      - Allows access (unrestricted mode for local development/self-hosting)
    """
    expected_key = get_configured_access_key()
    if not expected_key:
        return  # No authentication required if key is not configured in backend

    provided_key: Optional[str] = None
    x_key = request.headers.get("x-studio-access-key")
    auth_hdr = request.headers.get("authorization")

    if x_key and x_key.strip():
        provided_key = x_key.strip()
    elif auth_hdr and auth_hdr.strip():
        parts = auth_hdr.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided_key = parts[1]
        elif len(parts) == 1:
            provided_key = parts[0]

    if not provided_key or not secrets.compare_digest(provided_key, expected_key):
        raise HTTPException(
            status_code=401,
            detail="Access key required for AI endpoints. Please configure your Access Key in Settings.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# =====================================================================
# 2. IN-MEMORY SLIDING-WINDOW RATE LIMITER
# =====================================================================

class SlidingWindowRateLimiter:
    """In-memory rate limiter per client IP address."""

    def __init__(self, default_limit_per_minute: int = 30):
        self._default_limit = default_limit_per_minute
        self._requests: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def get_limit(self) -> int:
        val = os.getenv("RATE_LIMIT_PER_MINUTE")
        if val:
            try:
                return max(1, int(val))
            except ValueError:
                pass
        return self._default_limit

    def check_rate_limit(self, request: Request, custom_limit: Optional[int] = None) -> None:
        """Enforces rate limit for client IP. Raises HTTP 429 if exceeded."""
        limit = custom_limit or self.get_limit()
        client_ip = self._extract_client_ip(request)
        now = time.time()
        window_start = now - 60.0

        with self._lock:
            history = self._requests.get(client_ip, [])
            # Prune timestamps older than 60 seconds
            history = [ts for ts in history if ts > window_start]

            if len(history) >= limit:
                retry_after = max(1, int(60 - (now - history[0])))
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded ({limit} requests/min). Please try again in {retry_after} seconds.",
                    headers={"Retry-After": str(retry_after)},
                )

            history.append(now)
            self._requests[client_ip] = history

    def _extract_client_ip(self, request: Request) -> str:
        """Extracts client IP, respecting X-Forwarded-For when behind proxy."""
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            # First IP in the list is the original client IP
            first_ip = x_forwarded_for.split(",")[0].strip()
            if first_ip:
                return first_ip
        if request.client and request.client.host:
            return request.client.host
        return "127.0.0.1"

    def reset_for_tests(self) -> None:
        """Reset internal history for unit tests."""
        with self._lock:
            self._requests.clear()


rate_limiter = SlidingWindowRateLimiter()


# =====================================================================
# 3. DAILY SPEND QUOTA GUARDRAIL
# =====================================================================

class DailySpendTracker:
    """Tracks estimated LLM spending across requests in current UTC day."""

    def __init__(self, default_daily_limit_usd: float = 5.0):
        self._default_limit = default_daily_limit_usd
        self._current_day: Optional[str] = None
        self._daily_spend: float = 0.0
        self._lock = threading.Lock()

    def get_limit(self) -> float:
        val = os.getenv("DAILY_SPEND_LIMIT_USD")
        if val:
            try:
                return max(0.01, float(val))
            except ValueError:
                pass
        return self._default_limit

    def check_limit_before_call(self) -> None:
        """Checks if daily spending ceiling has been reached."""
        limit = self.get_limit()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self._lock:
            if self._current_day != today:
                self._current_day = today
                self._daily_spend = 0.0

            if self._daily_spend >= limit:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Daily AI spending limit of ${limit:.2f} reached "
                        f"(Spent: ${self._daily_spend:.4f}). "
                        "Quota resets at 00:00 UTC."
                    ),
                    headers={"Retry-After": "3600"},
                )

    def record_cost(self, cost_usd: Optional[float]) -> None:
        """Records the estimated cost of an LLM generation."""
        if not cost_usd or cost_usd <= 0:
            return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._lock:
            if self._current_day != today:
                self._current_day = today
                self._daily_spend = 0.0
            self._daily_spend += cost_usd

    def get_status(self) -> Dict[str, float]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._lock:
            if self._current_day != today:
                self._current_day = today
                self._daily_spend = 0.0
            return {
                "spent_usd": round(self._daily_spend, 5),
                "limit_usd": self.get_limit(),
                "remaining_usd": max(0.0, round(self.get_limit() - self._daily_spend, 5)),
            }

    def reset_for_tests(self) -> None:
        with self._lock:
            self._current_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self._daily_spend = 0.0


spend_tracker = DailySpendTracker()

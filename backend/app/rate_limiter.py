import ipaddress
import os
import time
from collections import defaultdict
from fastapi import HTTPException, Request, status


class InMemoryRateLimiter:
    """
    In-memory sliding window rate limiter.

    Compatible with single-instance deployments (such as Render free tier)
    without requiring external infrastructure like Redis or paid dependencies.

    Limitations:
    - State is held in-memory and resets upon process restart / redeploy.
    - Rate limits apply per instance/process; does not share state across
      horizontal replicas if scaled out.
    - Memory usage is bounded by automatic periodic eviction of expired buckets.
    """

    def __init__(self) -> None:
        # (scope, client_key) -> list of request timestamps
        self._buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._last_cleanup = time.monotonic()

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup > 120.0:
            self._last_cleanup = now
            stale_keys = []
            for key, timestamps in self._buckets.items():
                self._buckets[key] = [t for t in timestamps if now - t < 600.0]
                if not self._buckets[key]:
                    stale_keys.append(key)
            for key in stale_keys:
                self._buckets.pop(key, None)

    def check(
        self,
        scope: str,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """
        Check and record a request.
        Returns: (is_allowed: bool, retry_after_seconds: int)
        """
        now = time.monotonic()
        self._cleanup(now)

        cutoff = now - window_seconds
        current_history = [t for t in self._buckets[(scope, key)] if t > cutoff]
        self._buckets[(scope, key)] = current_history

        if len(current_history) >= max_requests:
            oldest = current_history[0]
            retry_after = max(1, int(oldest + window_seconds - now))
            return False, retry_after

        current_history.append(now)
        return True, 0

    def clear(self) -> None:
        """Clear all rate limit state (primarily for tests)."""
        self._buckets.clear()


# Global rate limiter instance
limiter = InMemoryRateLimiter()

DEFAULT_TRUSTED_PROXY_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),      # IPv4 Loopback
    ipaddress.ip_network("::1/128"),          # IPv6 Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # RFC 1918 (Render internal network)
    ipaddress.ip_network("172.16.0.0/12"),    # RFC 1918 (Docker / container bridge)
    ipaddress.ip_network("192.168.0.0/16"),   # RFC 1918 (Private network)
    ipaddress.ip_network("fc00::/7"),         # IPv6 Unique Local Address
)


def get_trusted_proxy_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """
    Get the list of trusted proxy networks, combining defaults with ORION_TRUSTED_PROXIES.
    """
    networks = list(DEFAULT_TRUSTED_PROXY_NETWORKS)
    env_proxies = os.environ.get("ORION_TRUSTED_PROXIES", "").strip()
    if env_proxies:
        for item in env_proxies.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                if "/" in item:
                    networks.append(ipaddress.ip_network(item, strict=False))
                else:
                    networks.append(
                        ipaddress.ip_network(f"{item}/32" if ":" not in item else f"{item}/128")
                    )
            except ValueError:
                pass
    return networks


def is_trusted_peer(host: str | None) -> bool:
    """
    Determine if the direct socket peer is a trusted proxy.
    Only connections from trusted proxies may supply forwarded IP headers.
    """
    if not host:
        return False
    if host in ("testclient", "localhost"):
        return True
    try:
        addr = ipaddress.ip_address(host)
        return any(addr in net for net in get_trusted_proxy_networks())
    except ValueError:
        return False


def get_client_ip(request: Request) -> str:
    """
    Extract client IP address safely, enforcing a justified trust boundary.

    Trust boundary rules:
    1. Direct Public Connection:
       If the direct socket peer (request.client.host) is NOT a trusted proxy,
       all forwarded headers (X-Forwarded-For, CF-Connecting-IP, True-Client-IP)
       are untrusted user input and are strictly ignored. The socket peer IP is returned.
    2. Trusted Proxy Connection (e.g. Render edge / Cloudflare or local reverse proxy):
       a. Check CF-Connecting-IP / True-Client-IP:
          Render uses Cloudflare at the edge, which unconditionally overwrites
          CF-Connecting-IP with the true connecting client IP.
       b. Fall back to X-Forwarded-For:
          Traverse from right to left (since proxies append to the chain) and pick
          the first valid IP that is NOT an internal proxy hop, preventing attackers
          from prepending spoofed IPs to get fresh rate-limit buckets.
    3. Fall back to socket peer host or '127.0.0.1'.
    """
    direct_host = request.client.host if request.client else None

    # Enforce trust boundary: if peer is not trusted, never trust forwarded headers
    if not is_trusted_peer(direct_host):
        return direct_host or "127.0.0.1"

    # Peer is a trusted proxy. First inspect Cloudflare edge headers (used on Render)
    for header_name in ("CF-Connecting-IP", "True-Client-IP"):
        val = request.headers.get(header_name)
        if val:
            candidate = val.strip()
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                pass

    # Next inspect X-Forwarded-For chain from right to left
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        trusted_nets = get_trusted_proxy_networks()
        valid_candidates = []
        for p in reversed(parts):
            try:
                addr = ipaddress.ip_address(p)
                valid_candidates.append(p)
                # First IP from right that is not an internal proxy is the client
                if not any(addr in net for net in trusted_nets):
                    return p
            except ValueError:
                continue
        if valid_candidates:
            return valid_candidates[0]

    return direct_host or "127.0.0.1"


def record_auth_failure(request: Request, max_failures: int = 10, window_seconds: int = 60) -> None:
    """
    Record an authentication failure and rate-limit if brute-force threshold is reached.
    Default: 10 failed authentication attempts per minute per IP.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = limiter.check("auth_failures", client_ip, max_failures, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed authentication attempts. Please wait before retrying.",
            headers={"Retry-After": str(retry_after)},
        )


def check_auth_attempts(request: Request, max_attempts: int = 60, window_seconds: int = 60) -> None:
    """
    Rate-limit overall authentication checks per client IP to prevent flood attacks.
    Default: 60 attempts per minute per IP.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = limiter.check("auth_attempts", client_ip, max_attempts, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication requests. Please wait before retrying.",
            headers={"Retry-After": str(retry_after)},
        )


def check_expensive_rate_limit(request: Request, max_requests: int = 20, window_seconds: int = 60) -> None:
    """
    Rate limit expensive endpoints (chat, agent run, planner) per client IP.
    Default: 20 requests per minute per IP.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = limiter.check("expensive_ai", client_ip, max_requests, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for AI operations. Please wait before sending another request.",
            headers={"Retry-After": str(retry_after)},
        )

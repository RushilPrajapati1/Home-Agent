"""The only way housing-mcp talks to the internet: HTTPS GETs to allowlisted hosts.

Errors raised from here never carry a query string or headers, so an API key passed as a
parameter (FRED) or header (RentCast) can't leak into a log line or a tool error.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

ALLOWED_HOSTS: frozenset[str] = frozenset({"api.stlouisfed.org", "api.rentcast.io"})
RETRY_STATUSES: frozenset[int] = frozenset({500, 502, 503, 504})

# httpx logs every request URL at INFO, query string (and so FRED's api_key) included.
logging.getLogger("httpx").setLevel(logging.WARNING)


class EgressDenied(RuntimeError):
    """A request to a host or scheme outside the allowlist."""


class UpstreamError(RuntimeError):
    """An outside API failed. ``status`` is None for transport errors."""

    def __init__(self, where: str, status: int | None, reason: str) -> None:
        super().__init__(f"{where}: {reason}")
        self.status = status


def check_allowed(url: httpx.URL) -> None:
    if url.scheme != "https" or url.host not in ALLOWED_HOSTS:
        raise EgressDenied(f"egress to {url.scheme}://{url.host} is not allowlisted")


async def _check_request(request: httpx.Request) -> None:
    check_allowed(request.url)


class SafeClient:
    def __init__(
        self,
        *,
        timeout_s: float = 10.0,
        retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._retries = retries
        self._sleep = sleep
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=False,
            transport=transport,
            # Belt and braces: re-checked on the request object httpx actually sends.
            event_hooks={"request": [_check_request]},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        before_attempt: Callable[[], Awaitable[None]] | None = None,
    ) -> Any:
        """GET and decode JSON, retrying transport errors and 5xx with backoff.

        ``before_attempt`` runs before every attempt, retries included (quota accounting).
        """
        target = httpx.URL(url)
        check_allowed(target)
        where = f"{target.host}{target.path}"
        for attempt in range(self._retries + 1):
            last = attempt == self._retries
            if before_attempt is not None:
                await before_attempt()
            try:
                resp = await self._http.get(target, params=params, headers=headers)
            except httpx.TransportError as exc:
                if last:
                    raise UpstreamError(where, None, type(exc).__name__) from None
            else:
                if resp.status_code in RETRY_STATUSES and not last:
                    pass
                elif resp.is_success:
                    try:
                        return resp.json()
                    except ValueError:
                        raise UpstreamError(where, resp.status_code, "invalid JSON") from None
                else:
                    raise UpstreamError(where, resp.status_code, f"HTTP {resp.status_code}")
            await self._sleep(0.5 * 2**attempt)
        raise AssertionError("unreachable")  # pragma: no cover

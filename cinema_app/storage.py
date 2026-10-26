from __future__ import annotations

"""Cinema-owned database boundary, never connected to Shield globals.

The local migration preview never instantiates this adapter. A future
authorized Cinema service can supply an independently configured client factory.
No real databases, tables, credentials or data are modified by this module.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import time
from typing import Any, Callable, Mapping, TypeVar
from urllib.parse import urlsplit

T = TypeVar("T")
_URL_ENV = "CINEMA_SUPABASE_URL"
_KEY_ENV = "CINEMA_SUPABASE_SERVICE_ROLE_KEY"
_MAX_READ_ATTEMPTS = 2
_MAX_CONCURRENT_REQUESTS = 4


class CinemaStorageUnavailable(RuntimeError):
    """Fail-closed error without leaking the underlying DB exception or secret."""


@dataclass(frozen=True, slots=True)
class CinemaStorageConfig:
    url: str
    service_role_key: str = field(repr=False)

    @classmethod
    def from_environment(
        cls, env: Mapping[str, str] | None = None
    ) -> "CinemaStorageConfig":
        values = os.environ if env is None else env
        url = str(values.get(_URL_ENV, "") or "").strip().rstrip("/")
        key = str(values.get(_KEY_ENV, "") or "").strip()
        if not url or len(key.encode("utf-8")) < 32:
            raise CinemaStorageUnavailable(
                "Cinema's independent database URL/service credentials are not configured"
            )
        try:
            parsed = urlsplit(url)
            parsed_port = parsed.port
            host = parsed.hostname
        except ValueError:
            raise CinemaStorageUnavailable(
                "Cinema database endpoint must be an HTTPS origin without credentials or path"
            ) from None
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
            or not 1 <= (parsed_port or 443) <= 65535
        ):
            raise CinemaStorageUnavailable(
                "Cinema database endpoint must be an HTTPS origin without credentials or path"
            )
        # Deliberately NEVER fall back to SUPABASE_URL, SUPABASE_KEY,
        # DANK_SUPABASE_* or any Dank Shield service-role credentials.
        return cls(url=url, service_role_key=key)


class CinemaStorage:
    def __init__(
        self,
        config: CinemaStorageConfig,
        *,
        client_factory: Callable[[str, str], Any],
    ) -> None:
        if not callable(client_factory):
            raise TypeError("Cinema client factory must be callable")
        self._config = config
        self._client_factory = client_factory
        self._gate = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)

    async def read(self, operation: Callable[[Any], T]) -> T:
        """Retry a transport failure once for idempotent reads only."""
        return await self._execute(operation, retry_read=True)

    async def write(self, operation: Callable[[Any], T]) -> T:
        """Never retry a write automatically: it may have already committed."""
        return await self._execute(operation, retry_read=False)

    async def _execute(self, operation: Callable[[Any], T], *, retry_read: bool) -> T:
        if not callable(operation):
            raise TypeError("Database operation must be callable")
        async with self._gate:
            return await asyncio.to_thread(self._execute_sync, operation, retry_read)

    def _execute_sync(
        self, operation: Callable[[Any], T], retry_read: bool
    ) -> T:
        attempts = _MAX_READ_ATTEMPTS if retry_read else 1
        for attempt in range(attempts):
            try:
                client = self._client_factory(
                    self._config.url, self._config.service_role_key
                )
                if client is None:
                    raise CinemaStorageUnavailable("Independent Cinema storage is not available")
                return operation(client)
            except CinemaStorageUnavailable:
                raise
            except Exception as exc:
                # No arbitrary-error retries and no retries for potentially
                # committed writes. Never place the exception body in a log
                # or public error (it may contain credentials or query data).
                retryable = isinstance(exc, (TimeoutError, ConnectionError, BrokenPipeError))
                if retry_read and retryable and attempt + 1 < attempts:
                    time.sleep(0.12 * (attempt + 1))
                    continue
                raise CinemaStorageUnavailable(
                    f"Cinema database request failed safely ({type(exc).__name__})"
                ) from None
        raise CinemaStorageUnavailable("Cinema database read attempts exhausted")


def rows(response: Any) -> list[dict[str, Any]]:
    value = getattr(response, "data", None)
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "CinemaStorage", "CinemaStorageConfig", "CinemaStorageUnavailable",
    "rows", "utc_now",
]

from __future__ import annotations

"""Stateless signing primitive for a future standalone Cinema auth service.

Tokens are not authorization to join a Discord guild, enter a Cinema room,
or stream any media. Callers MUST verify current membership, permissions and
session revocation independently before granting access.
"""

import base64
from dataclasses import dataclass
import hashlib
import hmac
import os
import re
import secrets
import time
from typing import Mapping

VERSION = "c2"
MAX_AGE_SECONDS = 6 * 60 * 60
_CLOCK_SKEW_SECONDS = 60
PURPOSES = frozenset({"login-link", "browser-session"})
SIGNING_KEY_ENV = "CINEMA_SESSION_SIGNING_KEY"
_B64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class SignedIdentity:
    guild_id: int
    user_id: int
    issued_at: int
    expires_at: int
    purpose: str


class CinemaSigner:
    def __init__(self, key: bytes) -> None:
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("Cinema signing key must contain at least 32 bytes")
        self._key = key

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> "CinemaSigner":
        values = os.environ if env is None else env
        raw = str(values.get(SIGNING_KEY_ENV, "") or "")
        if len(raw.encode("utf-8")) < 32:
            raise ValueError(f"{SIGNING_KEY_ENV} is not configured with 32+ bytes")
        # No fallback to DANK_TORRENT_STREAM_SECRET or any Dank Shield secret.
        return cls(raw.encode("utf-8"))

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _decode(encoded: str) -> bytes | None:
        if not encoded or not _B64URL_PATTERN.fullmatch(encoded):
            return None
        try:
            decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        except (ValueError, base64.binascii.Error):
            return None
        return decoded if CinemaSigner._encode(decoded) == encoded else None

    def issue(
        self,
        *,
        guild_id: int,
        user_id: int,
        purpose: str,
        ttl_seconds: int,
        now: int | None = None,
    ) -> str:
        if purpose not in PURPOSES:
            raise ValueError("Unknown Cinema signing purpose")
        if int(guild_id) <= 0 or int(user_id) <= 0:
            raise ValueError("Guild and user IDs must be positive")
        if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= MAX_AGE_SECONDS:
            raise ValueError("Cinema token duration exceeds the maximum")
        issued_at = int(time.time()) if now is None else int(now)
        expires_at = issued_at + ttl_seconds
        nonce = secrets.token_hex(16)
        data = (
            f"{VERSION}|{purpose}|{int(guild_id)}|{int(user_id)}|"
            f"{issued_at}|{expires_at}|{nonce}"
        ).encode("ascii")
        payload = self._encode(data)
        signature = hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def verify(
        self,
        token: str,
        *,
        guild_id: int,
        purpose: str,
        now: int | None = None,
    ) -> SignedIdentity | None:
        if purpose not in PURPOSES:
            return None
        value = str(token or "")
        if not value or len(value) > 1024 or value.count(".") != 1:
            return None
        payload, signature = value.split(".", 1)
        if not _HEX_PATTERN.fullmatch(signature):
            return None
        expected = hmac.new(
            self._key, payload.encode("ascii", errors="ignore"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        data = self._decode(payload)
        if data is None:
            return None
        try:
            version, embedded_purpose, gid, uid, iat, exp, nonce = data.decode("ascii").split("|")
            user_id = int(uid)
            embedded_gid = int(gid)
            issued_at = int(iat)
            expires_at = int(exp)
            expected_gid = int(guild_id)
        except (ValueError, UnicodeDecodeError):
            return None
        if (
            version != VERSION
            or embedded_purpose != purpose
            or expected_gid <= 0
            or embedded_gid != expected_gid
            or user_id <= 0
            or len(nonce) != 32
            or not all(c in "0123456789abcdef" for c in nonce)
        ):
            return None
        current_time = int(time.time()) if now is None else int(now)
        duration = expires_at - issued_at
        if (
            duration < 1
            or duration > MAX_AGE_SECONDS
            or issued_at > current_time + _CLOCK_SKEW_SECONDS
            or expires_at < current_time
        ):
            return None
        return SignedIdentity(
            guild_id=embedded_gid,
            user_id=user_id,
            issued_at=issued_at,
            expires_at=expires_at,
            purpose=embedded_purpose,
        )

from __future__ import annotations

"""Discord OAuth authorization-code handshake for independent Cinema identity.

The module provides a server-side, single-use state and PKCE boundary. It
does not mount public routes, persist user tokens, create cookies, connect to
Dank Shield, or authorize any media playback. HTTP handlers and session
revocation must be implemented before exposing a public login.
"""

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from typing import Any, Callable, Collection, Mapping
from urllib.parse import urlencode, urlsplit

import aiohttp

from .discord_identity import DiscordGuildProof, GUILDS_ENDPOINT, USER_ENDPOINT, verify_discord_guild_proof

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
API_ORIGIN = "https://discord.com/api/v10"
SCOPES = frozenset(("identify", "guilds"))
STATE_TTL = 300
MAX_PENDING_STATES = 512


class CinemaOAuthError(ValueError):
    """Safe, nonsecret authentication failure."""


@dataclass(frozen=True, slots=True)
class CinemaOAuthConfig:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str

    @classmethod
    def from_environment(cls, values: Mapping[str, str] | None = None) -> "CinemaOAuthConfig":
        env = os.environ if values is None else values
        return cls(
            client_id=str(env.get("CINEMA_DISCORD_CLIENT_ID", "") or ""),
            client_secret=str(env.get("CINEMA_DISCORD_CLIENT_SECRET", "") or ""),
            redirect_uri=str(env.get("CINEMA_DISCORD_REDIRECT_URI", "") or ""),
        )

    def __post_init__(self) -> None:
        ident = self.client_id
        if not ident or not ident.isascii() or not ident.isdigit() or len(ident) > 20 or int(ident) <= 0:
            raise CinemaOAuthError("Invalid independent Cinema Discord application ID")
        if len(self.client_secret.encode("utf-8")) < 16:
            raise CinemaOAuthError("Independent Cinema OAuth client secret is missing")
        parsed = urlsplit(self.redirect_uri)
        try:
            port_ok = parsed.port is None or 1 <= parsed.port <= 65535
        except ValueError:
            port_ok = False
        if not (
            parsed.hostname
            and port_ok
            and parsed.path not in ("", "/")
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and (
                parsed.scheme == "https"
                or (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost"))
            )
        ):
            raise CinemaOAuthError("Cinema OAuth redirect must be a registered HTTPS callback (or local loopback)")


@dataclass(frozen=True, slots=True)
class CinemaOAuthStart:
    authorize_url: str
    state: str
    browser_nonce: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class OAuthGrant:
    access_token: str = field(repr=False)
    expires_in: int
    scopes: frozenset[str]


@dataclass(frozen=True, slots=True)
class VerifiedCinemaLogin:
    guild: DiscordGuildProof
    grant: OAuthGrant = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Pending:
    guild_id: int
    nonce_digest: bytes
    verifier: str
    expires_at: float


class CinemaOAuthStates:
    """Single-use short-lived CSRF state, bound to a browser-only nonce.

    Process-local pending state is valid for a single development instance.
    Production needs a shared TTL store with atomic consume and rate limiting.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._pending: dict[str, _Pending] = {}

    @staticmethod
    def _digest(value: str) -> bytes:
        return hashlib.sha256(value.encode("utf-8")).digest()

    @staticmethod
    def _challenge(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def begin(self, config: CinemaOAuthConfig, *, guild_id: int) -> CinemaOAuthStart:
        if type(guild_id) is not int or guild_id <= 0 or guild_id >= 2**64:
            raise CinemaOAuthError("Invalid Cinema guild ID")
        with self._lock:
            now = self._clock()
            self._pending = {key: pending for key, pending in self._pending.items() if pending.expires_at > now}
            if len(self._pending) >= MAX_PENDING_STATES:
                raise CinemaOAuthError("Too many unfinished Cinema logins")
            state = secrets.token_urlsafe(32)
            nonce = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(48)
            while state in self._pending:
                state = secrets.token_urlsafe(32)
            self._pending[state] = _Pending(guild_id, self._digest(nonce), verifier, now + STATE_TTL)
        url = AUTHORIZE_URL + "?" + urlencode({
            "response_type": "code",
            "client_id": config.client_id,
            "scope": "identify guilds",
            "redirect_uri": config.redirect_uri,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": self._challenge(verifier),
        })
        return CinemaOAuthStart(authorize_url=url, state=state, browser_nonce=nonce)

    def consume(self, *, state: str, browser_nonce: str, issuer: str) -> tuple[int, str]:
        if not isinstance(state, str) or len(state) > 128 or not state:
            raise CinemaOAuthError("Invalid or expired Cinema login state")
        with self._lock:
            pending = self._pending.pop(state, None)
        if pending is None or self._clock() >= pending.expires_at:
            raise CinemaOAuthError("Invalid or expired Cinema login state")
        if issuer != "https://discord.com":
            raise CinemaOAuthError("Unexpected OAuth authorization issuer")
        if (
            not isinstance(browser_nonce, str)
            or len(browser_nonce) > 256
            or not hmac.compare_digest(pending.nonce_digest, self._digest(browser_nonce))
        ):
            raise CinemaOAuthError("Cinema login browser session mismatch")
        return pending.guild_id, pending.verifier


class DiscordOAuthTransport:
    """Fixed Discord endpoints only. No caller-supplied URL or redirects."""

    def __init__(self, session: aiohttp.ClientSession, config: CinemaOAuthConfig) -> None:
        self._session = session
        self._config = config

    @staticmethod
    async def _read_json(response: aiohttp.ClientResponse, *, max_bytes: int) -> Any:
        if response.status != 200:
            raise CinemaOAuthError("Discord OAuth service rejected the request")
        content = await response.content.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise CinemaOAuthError("Discord OAuth response exceeded its size limit")
        try:
            return json.loads(content)
        except (ValueError, UnicodeDecodeError):
            raise CinemaOAuthError("Discord OAuth response was invalid") from None

    async def exchange(self, code: str, verifier: str) -> OAuthGrant:
        if (
            not isinstance(code, str) or not code or len(code) > 2048
            or any(ch.isspace() for ch in code)
        ):
            raise CinemaOAuthError("Invalid Discord authorization code")
        try:
            async with self._session.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code", "code": code,
                    "redirect_uri": self._config.redirect_uri,
                    "code_verifier": verifier,
                },
                auth=aiohttp.BasicAuth(self._config.client_id, self._config.client_secret),
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                value = await self._read_json(response, max_bytes=8192)
        except CinemaOAuthError:
            raise
        except Exception:
            raise CinemaOAuthError("Discord OAuth token exchange unavailable") from None
        if not isinstance(value, Mapping):
            raise CinemaOAuthError("Discord OAuth response was invalid")
        token = value.get("access_token")
        scopes = value.get("scope")
        expires = value.get("expires_in")
        if (
            value.get("token_type", "").lower() != "bearer"
            or not isinstance(token, str) or not token or len(token) > 4096
            or any(ch.isspace() for ch in token)
            or not isinstance(scopes, str)
            or not isinstance(expires, int) or isinstance(expires, bool)
            or not 1 <= expires <= 60 * 60 * 24 * 30
        ):
            raise CinemaOAuthError("Discord OAuth token contract was invalid")
        allowed = frozenset(scopes.split())
        if not SCOPES.issubset(allowed):
            raise CinemaOAuthError("Discord OAuth scopes are insufficient")
        return OAuthGrant(access_token=token, expires_in=expires, scopes=allowed)

    async def fetch(self, path: str, token: str) -> Any:
        if path not in (USER_ENDPOINT, GUILDS_ENDPOINT):
            raise CinemaOAuthError("Unsupported Discord OAuth resource")
        if not isinstance(token, str) or not token or len(token) > 4096 or any(ch.isspace() for ch in token):
            raise CinemaOAuthError("Invalid Discord bearer token")
        try:
            async with self._session.get(
                API_ORIGIN + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                return await self._read_json(response, max_bytes=1024 * 1024)
        except CinemaOAuthError:
            raise
        except Exception:
            raise CinemaOAuthError("Discord user verification unavailable") from None


class CinemaOAuthFlow:
    def __init__(self, config: CinemaOAuthConfig, *, states: CinemaOAuthStates | None = None) -> None:
        self.config = config
        self.states = states if states is not None else CinemaOAuthStates()

    def begin(self, *, guild_id: int) -> CinemaOAuthStart:
        return self.states.begin(self.config, guild_id=guild_id)

    async def complete(
        self, *, state: str, browser_nonce: str, issuer: str,
        code: str, transport: DiscordOAuthTransport,
        installed_cinema_guilds: Collection[int],
    ) -> VerifiedCinemaLogin:
        guild_id, verifier = self.states.consume(
            state=state, browser_nonce=browser_nonce, issuer=issuer,
        )
        grant = await transport.exchange(code, verifier)
        proof = await verify_discord_guild_proof(
            bearer_token=grant.access_token,
            target_guild_id=guild_id,
            fetcher=transport.fetch,
            installed_cinema_guilds=installed_cinema_guilds,
        )
        if proof is None:
            raise CinemaOAuthError("Discord identity or Cinema guild membership was not verified")
        return VerifiedCinemaLogin(guild=proof, grant=grant)


__all__ = [
    "CinemaOAuthConfig", "CinemaOAuthError", "CinemaOAuthFlow",
    "CinemaOAuthStart", "CinemaOAuthStates", "DiscordOAuthTransport",
    "OAuthGrant", "VerifiedCinemaLogin",
]

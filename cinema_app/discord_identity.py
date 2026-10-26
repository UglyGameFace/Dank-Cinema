from __future__ import annotations
"""Independent Discord user/guild proof, not an OAuth exchange or room grant.

Transport must call Discord's official HTTPS /users/@me and /users/@me/guilds
with a Cinema-owned OAuth user bearer token. App installation must be verified
by a separate authoritative Cinema source. No HTTP routes are exposed here.
"""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Collection, Mapping

Fetcher = Callable[[str, str], Awaitable[Any]]
USER_ENDPOINT = "/users/@me"
GUILDS_ENDPOINT = "/users/@me/guilds"

@dataclass(frozen=True, slots=True)
class DiscordGuildProof:
    user_id: int
    guild_id: int

def _snowflake(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    raw = str(value or "").strip()
    if not raw.isascii() or not raw.isdigit() or len(raw) > 20:
        return 0
    parsed = int(raw)
    return parsed if parsed > 0 else 0

async def verify_discord_guild_proof(
    *,
    bearer_token: str,
    target_guild_id: int,
    fetcher: Fetcher,
    installed_cinema_guilds: Collection[int],
    expected_user_id: int | None = None,
) -> DiscordGuildProof | None:
    """Fail closed unless Discord user membership and Cinema installation agree."""
    token = str(bearer_token or "")
    gid = _snowflake(target_guild_id)
    if not token or len(token) > 4096 or any(ch.isspace() for ch in token) or not gid or not callable(fetcher):
        return None
    try:
        installs = {_snowflake(x) for x in installed_cinema_guilds}
    except (ValueError, TypeError):
        return None
    if gid not in installs:
        return None
    try:
        user = await fetcher(USER_ENDPOINT, token)
        guilds = await fetcher(GUILDS_ENDPOINT, token)
    except Exception:
        return None
    if not isinstance(user, Mapping) or user.get("bot") is True:
        return None
    uid = _snowflake(user.get("id"))
    if not uid or (expected_user_id is not None and uid != _snowflake(expected_user_id)):
        return None
    if not isinstance(guilds, list) or len(guilds) > 2000:
        return None
    if not any(isinstance(row, Mapping) and _snowflake(row.get("id")) == gid for row in guilds):
        return None
    return DiscordGuildProof(user_id=uid, guild_id=gid)

__all__ = ("DiscordGuildProof", "USER_ENDPOINT", "GUILDS_ENDPOINT", "verify_discord_guild_proof")

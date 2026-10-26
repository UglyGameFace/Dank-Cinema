from __future__ import annotations

"""Cinema-owned, source-agnostic room lifecycle for future authenticated watch parties.

This is an in-memory domain layer, not a public room API or an authorization
service. HTTP/Discord handlers must independently verify the current user,
guild install, permissions and session revocation before passing a guild proof.
No Shield imports, media resolvers, downloads, background tasks, or network IO.
"""

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .discord_identity import DiscordGuildProof

MAX_ROOM_VIEWERS = 20  # Includes the host; never quietly oversubscribe.
MAX_PRIVATE_INVITES = 50
MAX_ROOMS_PER_GUILD = 16
VIEWER_STALE_SECONDS = 120
EMPTY_ROOM_TTL_SECONDS = 1800


class RoomAccessError(ValueError):
    """Room operation denied without exposing member identities or secrets."""


@dataclass(frozen=True, slots=True)
class RoomSnapshot:
    room_id: str
    guild_id: int
    channel_id: int
    host_id: int
    private: bool
    viewer_ids: tuple[int, ...]
    viewer_count: int
    host_present: bool
    end_votes: int
    end_votes_needed: int
    created_at: float


@dataclass(slots=True)
class _Room:
    room_id: str
    guild_id: int
    channel_id: int
    host_id: int
    private: bool
    created_at: float
    viewers: dict[int, float] = field(default_factory=dict)
    invitations: set[int] = field(default_factory=set)
    end_votes: set[int] = field(default_factory=set)
    empty_since: float | None = None


class CinemaRooms:
    """Thread-safe, bounded *ephemeral* rooms with explicit expiry calls.

    A restart loses room state. Persistence and cross-process coordination are
    separate prerequisites before production. Guild proofs do not establish
    room-specific moderator privileges.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._rooms: dict[str, _Room] = {}

    @staticmethod
    def _valid_id(value: object) -> bool:
        return type(value) is int and 0 < value < 2**64

    @classmethod
    def _require_proof(cls, proof: DiscordGuildProof, guild_id: int) -> int:
        if (
            not isinstance(proof, DiscordGuildProof)
            or not cls._valid_id(proof.user_id)
            or not cls._valid_id(proof.guild_id)
            or proof.guild_id != guild_id
        ):
            raise RoomAccessError("A current matching Cinema guild proof is required")
        return proof.user_id

    def _get(self, room_id: str) -> _Room:
        if not isinstance(room_id, str) or len(room_id) > 128:
            raise RoomAccessError("Cinema room not found")
        room = self._rooms.get(room_id)
        if room is None:
            raise RoomAccessError("Cinema room not found")
        return room

    @staticmethod
    def _expire_viewers(room: _Room, now: float) -> None:
        for uid, seen in tuple(room.viewers.items()):
            if now - seen > VIEWER_STALE_SECONDS:
                del room.viewers[uid]
        room.end_votes.intersection_update(room.viewers)
        if not room.viewers and room.empty_since is None:
            room.empty_since = now
        elif room.viewers:
            room.empty_since = None

    @staticmethod
    def _snapshot(room: _Room) -> RoomSnapshot:
        count = len(room.viewers)
        return RoomSnapshot(
            room_id=room.room_id, guild_id=room.guild_id,
            channel_id=room.channel_id, host_id=room.host_id,
            private=room.private, viewer_ids=tuple(sorted(room.viewers)),
            viewer_count=count, host_present=room.host_id in room.viewers,
            end_votes=len(room.end_votes), end_votes_needed=count // 2 + 1,
            created_at=room.created_at,
        )

    def create(
        self, *, guild_id: int, channel_id: int,
        host: DiscordGuildProof, private: bool = False,
    ) -> RoomSnapshot:
        uid = self._require_proof(host, guild_id)
        if not self._valid_id(channel_id) or type(private) is not bool:
            raise RoomAccessError("Invalid Cinema channel or room mode")
        with self._lock:
            now = self._clock()
            self._cleanup_locked(now)
            if sum(1 for x in self._rooms.values() if x.guild_id == guild_id) >= MAX_ROOMS_PER_GUILD:
                raise RoomAccessError("Cinema room limit reached for this server")
            if any(x.guild_id == guild_id and x.channel_id == channel_id for x in self._rooms.values()):
                raise RoomAccessError("This channel already has a Cinema room")
            room_id = secrets.token_urlsafe(18)
            while room_id in self._rooms:
                room_id = secrets.token_urlsafe(18)
            room = _Room(room_id=room_id, guild_id=guild_id, channel_id=channel_id,
                         host_id=uid, private=private, created_at=now, viewers={uid: now})
            self._rooms[room_id] = room
            return self._snapshot(room)

    def invite(self, room_id: str, *, host: DiscordGuildProof, user_id: int) -> RoomSnapshot:
        with self._lock:
            room = self._get(room_id)
            uid = self._require_proof(host, room.guild_id)
            if uid != room.host_id:
                raise RoomAccessError("Only the room host can manage invitations")
            if not room.private or not self._valid_id(user_id):
                raise RoomAccessError("Invitation requires a private room and a valid user")
            if user_id not in room.invitations and len(room.invitations) >= MAX_PRIVATE_INVITES:
                raise RoomAccessError("Private invitation limit reached")
            room.invitations.add(user_id)
            return self._snapshot(room)

    def revoke(self, room_id: str, *, host: DiscordGuildProof, user_id: int) -> RoomSnapshot:
        with self._lock:
            room = self._get(room_id)
            if self._require_proof(host, room.guild_id) != room.host_id:
                raise RoomAccessError("Only the room host can manage invitations")
            if user_id == room.host_id:
                raise RoomAccessError("Cannot revoke the host")
            room.invitations.discard(user_id)
            room.viewers.pop(user_id, None)
            room.end_votes.discard(user_id)
            self._expire_viewers(room, self._clock())
            return self._snapshot(room)

    def join(self, room_id: str, *, viewer: DiscordGuildProof) -> RoomSnapshot:
        with self._lock:
            room = self._get(room_id)
            uid = self._require_proof(viewer, room.guild_id)
            now = self._clock()
            self._expire_viewers(room, now)
            if room.private and uid not in room.invitations and uid != room.host_id:
                raise RoomAccessError("Private Cinema room invitation required")
            if uid not in room.viewers and len(room.viewers) >= MAX_ROOM_VIEWERS:
                raise RoomAccessError("Cinema viewer capacity reached")
            room.viewers[uid] = now
            room.empty_since = None
            return self._snapshot(room)

    def heartbeat(self, room_id: str, *, viewer: DiscordGuildProof) -> RoomSnapshot:
        with self._lock:
            room = self._get(room_id)
            uid = self._require_proof(viewer, room.guild_id)
            now = self._clock()
            self._expire_viewers(room, now)
            if uid not in room.viewers:
                raise RoomAccessError("Join the Cinema room before sending presence")
            room.viewers[uid] = now
            return self._snapshot(room)

    def leave(self, room_id: str, *, viewer: DiscordGuildProof) -> RoomSnapshot:
        with self._lock:
            room = self._get(room_id)
            uid = self._require_proof(viewer, room.guild_id)
            room.viewers.pop(uid, None)
            room.end_votes.discard(uid)
            self._expire_viewers(room, self._clock())
            return self._snapshot(room)

    def vote_to_end(self, room_id: str, *, viewer: DiscordGuildProof) -> bool:
        """When the host leaves, active viewers may vote to end the room."""
        with self._lock:
            room = self._get(room_id)
            uid = self._require_proof(viewer, room.guild_id)
            now = self._clock()
            self._expire_viewers(room, now)
            if uid not in room.viewers:
                raise RoomAccessError("Only active Cinema viewers can vote")
            if room.host_id in room.viewers:
                raise RoomAccessError("Host is present; no host-absence vote is needed")
            room.end_votes.add(uid)
            if len(room.end_votes) >= len(room.viewers) // 2 + 1:
                del self._rooms[room_id]
                return True
            return False

    def end(self, room_id: str, *, host: DiscordGuildProof) -> None:
        with self._lock:
            room = self._get(room_id)
            uid = self._require_proof(host, room.guild_id)
            self._expire_viewers(room, self._clock())
            if uid != room.host_id or uid not in room.viewers:
                raise RoomAccessError("Only the active room host can end this room")
            del self._rooms[room_id]

    def get(self, room_id: str, *, viewer: DiscordGuildProof) -> RoomSnapshot:
        with self._lock:
            room = self._get(room_id)
            uid = self._require_proof(viewer, room.guild_id)
            self._expire_viewers(room, self._clock())
            if uid != room.host_id and room.private and uid not in room.invitations:
                raise RoomAccessError("Private Cinema room invitation required")
            return self._snapshot(room)

    def _cleanup_locked(self, now: float) -> int:
        expired: list[str] = []
        for room_id, room in self._rooms.items():
            self._expire_viewers(room, now)
            if room.empty_since is not None and now - room.empty_since >= EMPTY_ROOM_TTL_SECONDS:
                expired.append(room_id)
        for room_id in expired:
            del self._rooms[room_id]
        return len(expired)

    def cleanup_expired(self) -> int:
        """Explicit maintenance call; there is no implicit background worker."""
        with self._lock:
            return self._cleanup_locked(self._clock())


__all__ = [
    "CinemaRooms", "RoomAccessError", "RoomSnapshot",
    "MAX_ROOM_VIEWERS", "MAX_PRIVATE_INVITES", "MAX_ROOMS_PER_GUILD",
    "VIEWER_STALE_SECONDS", "EMPTY_ROOM_TTL_SECONDS",
]

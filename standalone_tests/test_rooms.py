from __future__ import annotations

import unittest

from cinema_app.discord_identity import DiscordGuildProof
from cinema_app.rooms import (
    CinemaRooms, EMPTY_ROOM_TTL_SECONDS, MAX_PRIVATE_INVITES,
    MAX_ROOMS_PER_GUILD, MAX_ROOM_VIEWERS, RoomAccessError, VIEWER_STALE_SECONDS,
)


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def proof(user: int, guild: int = 99) -> DiscordGuildProof:
    return DiscordGuildProof(user_id=user, guild_id=guild)


class IndependentCinemaRoomTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.rooms = CinemaRooms(clock=self.clock)
        self.host = proof(1)

    def make_room(self, private: bool = False):
        return self.rooms.create(guild_id=99, channel_id=500, host=self.host, private=private)

    def test_create_channel_unique_and_guild_bounded(self) -> None:
        room = self.make_room()
        self.assertEqual(room.viewer_ids, (1,))
        self.assertTrue(room.host_present)
        with self.assertRaises(RoomAccessError):
            self.make_room()
        for i in range(1, MAX_ROOMS_PER_GUILD):
            self.rooms.create(guild_id=99, channel_id=500 + i, host=self.host)
        with self.assertRaises(RoomAccessError):
            self.rooms.create(guild_id=99, channel_id=1000, host=self.host)
        # Other servers have separate limits.
        other = self.rooms.create(guild_id=100, channel_id=500, host=proof(2, 100))
        self.assertEqual(other.guild_id, 100)

    def test_cross_guild_and_invalid_proof_rejected(self) -> None:
        room = self.make_room()
        for user in (proof(3, 100), proof(0), "not-proof", None):
            with self.assertRaises(RoomAccessError):
                self.rooms.join(room.room_id, viewer=user)
        with self.assertRaises(RoomAccessError):
            self.rooms.create(guild_id=100, channel_id=30, host=self.host)
        with self.assertRaises(RoomAccessError):
            self.rooms.create(guild_id=99, channel_id=bool(True), host=self.host)
        self.assertEqual(self.rooms.get(room.room_id, viewer=self.host).viewer_count, 1)

    def test_private_requires_invite_and_revocation_ejects(self) -> None:
        room = self.make_room(private=True)
        with self.assertRaises(RoomAccessError):
            self.rooms.join(room.room_id, viewer=proof(2))
        with self.assertRaises(RoomAccessError):
            self.rooms.invite(room.room_id, host=proof(2), user_id=3)
        self.rooms.invite(room.room_id, host=self.host, user_id=2)
        self.rooms.join(room.room_id, viewer=proof(2))
        self.assertEqual(self.rooms.get(room.room_id, viewer=proof(2)).viewer_count, 2)
        after = self.rooms.revoke(room.room_id, host=self.host, user_id=2)
        self.assertEqual(after.viewer_ids, (1,))
        with self.assertRaises(RoomAccessError):
            self.rooms.get(room.room_id, viewer=proof(2))
        with self.assertRaises(RoomAccessError):
            self.rooms.revoke(room.room_id, host=self.host, user_id=1)

    def test_private_invites_have_independent_cap(self) -> None:
        room = self.make_room(private=True)
        for uid in range(2, MAX_PRIVATE_INVITES + 2):
            self.rooms.invite(room.room_id, host=self.host, user_id=uid)
        with self.assertRaises(RoomAccessError):
            self.rooms.invite(room.room_id, host=self.host, user_id=1000)
        # Re-adding an invite doesn't consume another slot.
        self.rooms.invite(room.room_id, host=self.host, user_id=2)

    def test_twenty_viewer_capacity_and_rejoining_is_idempotent(self) -> None:
        room = self.make_room()
        for uid in range(2, MAX_ROOM_VIEWERS + 1):
            self.rooms.join(room.room_id, viewer=proof(uid))
        self.assertEqual(self.rooms.join(room.room_id, viewer=self.host).viewer_count, 20)
        with self.assertRaises(RoomAccessError):
            self.rooms.join(room.room_id, viewer=proof(MAX_ROOM_VIEWERS + 1))
        self.rooms.leave(room.room_id, viewer=proof(2))
        self.assertEqual(self.rooms.join(room.room_id, viewer=proof(21)).viewer_count, 20)

    def test_host_leave_allows_majority_end_vote(self) -> None:
        room = self.make_room()
        self.rooms.join(room.room_id, viewer=proof(2))
        self.rooms.join(room.room_id, viewer=proof(3))
        with self.assertRaises(RoomAccessError):
            self.rooms.vote_to_end(room.room_id, viewer=proof(2))
        self.rooms.leave(room.room_id, viewer=self.host)
        self.assertFalse(self.rooms.vote_to_end(room.room_id, viewer=proof(2)))
        self.assertTrue(self.rooms.vote_to_end(room.room_id, viewer=proof(3)))
        with self.assertRaises(RoomAccessError):
            self.rooms.get(room.room_id, viewer=proof(2))

    def test_departed_voters_do_not_count_and_host_can_return(self) -> None:
        room = self.make_room()
        for uid in (2, 3, 4):
            self.rooms.join(room.room_id, viewer=proof(uid))
        self.rooms.leave(room.room_id, viewer=self.host)
        self.assertFalse(self.rooms.vote_to_end(room.room_id, viewer=proof(2)))
        self.rooms.leave(room.room_id, viewer=proof(2))
        snapshot = self.rooms.join(room.room_id, viewer=self.host)
        self.assertTrue(snapshot.host_present)
        self.assertEqual(snapshot.end_votes, 0)
        with self.assertRaises(RoomAccessError):
            self.rooms.vote_to_end(room.room_id, viewer=proof(3))
        self.rooms.end(room.room_id, host=self.host)
        with self.assertRaises(RoomAccessError):
            self.rooms.get(room.room_id, viewer=self.host)

    def test_unauthorized_end_and_heartbeat_rejected(self) -> None:
        room = self.make_room()
        with self.assertRaises(RoomAccessError):
            self.rooms.end(room.room_id, host=proof(2))
        with self.assertRaises(RoomAccessError):
            self.rooms.heartbeat(room.room_id, viewer=proof(2))
        self.rooms.heartbeat(room.room_id, viewer=self.host)
        self.assertEqual(self.rooms.get(room.room_id, viewer=self.host).viewer_count, 1)

    def test_stale_slots_expire_and_empty_rooms_expire(self) -> None:
        room = self.make_room()
        self.rooms.join(room.room_id, viewer=proof(2))
        self.clock.advance(VIEWER_STALE_SECONDS + 1)
        self.assertEqual(self.rooms.cleanup_expired(), 0)
        self.assertEqual(self.rooms.get(room.room_id, viewer=self.host).viewer_count, 0)
        self.clock.advance(EMPTY_ROOM_TTL_SECONDS)
        self.assertEqual(self.rooms.cleanup_expired(), 1)
        with self.assertRaises(RoomAccessError):
            self.rooms.get(room.room_id, viewer=self.host)

    def test_no_reflection_of_mutable_internal_state_in_snapshots(self) -> None:
        room = self.make_room()
        self.rooms.join(room.room_id, viewer=proof(2))
        self.assertEqual(room.viewer_ids, (1,))
        self.assertEqual(self.rooms.get(room.room_id, viewer=self.host).viewer_ids, (1, 2))
        with self.assertRaises(Exception):
            room.viewer_count = 200

    def test_no_network_downloads_or_implicit_services(self) -> None:
        import inspect
        from cinema_app import rooms
        source = inspect.getsource(rooms)
        for forbidden in ("import libtorrent", "import stoney_verify",
                          "import aiohttp", "import requests",
                          "get_torrent_manager", "register_cinema_site_routes"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

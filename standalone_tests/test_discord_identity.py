from __future__ import annotations
import unittest
from cinema_app.discord_identity import verify_discord_guild_proof, USER_ENDPOINT, GUILDS_ENDPOINT

TOKEN = "test-user-oauth-token"

class IndependentDiscordGuildTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_user_membership_and_app_installation(self) -> None:
        calls = []
        async def fetch(path, token):
            calls.append((path, token))
            return {"id": "123"} if path == USER_ENDPOINT else [{"id": "789"}]
        proof = await verify_discord_guild_proof(
            bearer_token=TOKEN, target_guild_id=789, expected_user_id=123,
            fetcher=fetch, installed_cinema_guilds={789},
        )
        self.assertIsNotNone(proof)
        self.assertEqual((proof.user_id, proof.guild_id), (123, 789))
        self.assertEqual(calls, [(USER_ENDPOINT,TOKEN),(GUILDS_ENDPOINT,TOKEN)])

    async def test_refuse_user_guild_when_cinema_app_not_installed(self) -> None:
        async def no_fetch(*_args):
            raise AssertionError("should not call Discord without app install")
        self.assertIsNone(await verify_discord_guild_proof(
            bearer_token=TOKEN, target_guild_id=789,
            fetcher=no_fetch, installed_cinema_guilds=set(),
        ))

    async def test_exact_guild_and_user_proof(self) -> None:
        async def fetch(path, _token):
            return {"id": "123"} if path == USER_ENDPOINT else [{"id": "788"}]
        self.assertIsNone(await verify_discord_guild_proof(
            bearer_token=TOKEN, target_guild_id=789, fetcher=fetch,
            installed_cinema_guilds={789},
        ))
        self.assertIsNone(await verify_discord_guild_proof(
            bearer_token=TOKEN, target_guild_id=788, fetcher=fetch,
            installed_cinema_guilds={788}, expected_user_id=456,
        ))

    async def test_malformed_token_data_and_api_outage_fail_closed(self) -> None:
        async def fail(*_args):
            raise PermissionError("Discord response contains credentials")
        async def malformed(path, _token):
            return {"id":"123"} if path == USER_ENDPOINT else {"id":"789"}
        for fetcher, token in ((fail,TOKEN),(malformed,TOKEN),(fail,"a\nb"),(fail,"")):
            self.assertIsNone(await verify_discord_guild_proof(
                bearer_token=token,target_guild_id=789,
                fetcher=fetcher,installed_cinema_guilds={789},
            ))

    async def test_reject_bot_and_wrong_type_snowflake(self) -> None:
        async def fetch(path, _token):
            return {"id":"123","bot":True} if path == USER_ENDPOINT else [{"id":"789"}]
        self.assertIsNone(await verify_discord_guild_proof(
            bearer_token=TOKEN,target_guild_id=789,fetcher=fetch,
            installed_cinema_guilds={789},
        ))
        self.assertIsNone(await verify_discord_guild_proof(
            bearer_token=TOKEN,target_guild_id=-1,fetcher=fetch,
            installed_cinema_guilds={789},
        ))

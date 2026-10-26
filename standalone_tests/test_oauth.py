from __future__ import annotations

import asyncio
import hashlib
import base64
import unittest
from urllib.parse import parse_qs, urlsplit

from cinema_app.oauth import (
    AUTHORIZE_URL, TOKEN_URL, CinemaOAuthConfig, CinemaOAuthError,
    CinemaOAuthFlow, CinemaOAuthStates, OAuthGrant, DiscordOAuthTransport,
)
from cinema_app.discord_identity import USER_ENDPOINT, GUILDS_ENDPOINT

CONFIG = CinemaOAuthConfig(
    client_id="123456789123456789",
    client_secret="fake-only-for-test-oauth-secret-12345",
    redirect_uri="https://cinema.example.org/auth/discord/callback",
)


class Timer:
    def __init__(self): self.value = 1000.0
    def __call__(self): return self.value


class OAuthStatesTests(unittest.TestCase):
    def setUp(self):
        self.timer = Timer()
        self.states = CinemaOAuthStates(clock=self.timer)

    def test_only_independent_config_and_exact_redirect(self):
        with self.assertRaises(CinemaOAuthError):
            CinemaOAuthConfig.from_environment({
                "DANK_TORRENT_STREAM_SECRET": "secret-legacy",
                "DISCORD_CLIENT_ID": CONFIG.client_id,
                "DISCORD_CLIENT_SECRET": CONFIG.client_secret,
            })
        for uri in ("http://cinema.example.org/callback", "https://user@cinema.example.org/callback",
                    "https://cinema.example.org/callback?redirect=evil", "https://cinema.example.org",
                    "https://cinema.example.org:bad/callback"):
            with self.subTest(uri=uri):
                with self.assertRaises(CinemaOAuthError):
                    CinemaOAuthConfig(CONFIG.client_id, CONFIG.client_secret, uri)
        self.assertNotIn(CONFIG.client_secret, repr(CONFIG))

    def test_pkce_state_is_bound_to_one_browser_one_callback(self):
        start = self.states.begin(CONFIG, guild_id=42)
        url = urlsplit(start.authorize_url)
        self.assertEqual(url.scheme + "://" + url.netloc + url.path, AUTHORIZE_URL)
        args = parse_qs(url.query)
        self.assertEqual(args["scope"], ["identify guilds"])
        self.assertEqual(args["state"], [start.state])
        self.assertEqual(args["redirect_uri"], [CONFIG.redirect_uri])
        self.assertEqual(args["code_challenge_method"], ["S256"])
        guild, verifier = self.states.consume(
            state=start.state, browser_nonce=start.browser_nonce,
            issuer="https://discord.com",
        )
        self.assertEqual(guild, 42)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, args["code_challenge"][0])
        with self.assertRaises(CinemaOAuthError):
            self.states.consume(state=start.state,browser_nonce=start.browser_nonce,issuer="https://discord.com")

    def test_wrong_browser_and_wrong_issuer_fail_closed_and_consume(self):
        for bad in ("nonce", "issuer"):
            start = self.states.begin(CONFIG, guild_id=42)
            with self.assertRaises(CinemaOAuthError):
                self.states.consume(state=start.state,
                    browser_nonce="wrong" if bad == "nonce" else start.browser_nonce,
                    issuer="https://attacker.org" if bad == "issuer" else "https://discord.com")
            with self.assertRaises(CinemaOAuthError):
                self.states.consume(state=start.state,browser_nonce=start.browser_nonce,issuer="https://discord.com")

    def test_state_expires_and_rejects_invalid_ids(self):
        start = self.states.begin(CONFIG, guild_id=42)
        self.timer.value += 301
        with self.assertRaises(CinemaOAuthError):
            self.states.consume(state=start.state,browser_nonce=start.browser_nonce,issuer="https://discord.com")
        for value in (0, -1, True, "5", 2**64):
            with self.assertRaises(CinemaOAuthError):
                self.states.begin(CONFIG,guild_id=value)


class FakeTransport:
    def __init__(self, user="123", guild="42", scope=frozenset(("identify", "guilds"))):
        self.user=user; self.guild=guild; self.scope=scope; self.calls=[]
    async def exchange(self, code, verifier):
        self.calls.append(("exchange", code))
        return OAuthGrant(access_token="test-oauth-token",expires_in=300,scopes=self.scope)
    async def fetch(self,path,token):
        self.calls.append((path, token))
        return {"id": self.user} if path == USER_ENDPOINT else [{"id": self.guild}]


class OAuthFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_independent_identity_and_guild(self):
        flow=CinemaOAuthFlow(CONFIG)
        start=flow.begin(guild_id=42)
        transport=FakeTransport()
        login=await flow.complete(state=start.state,browser_nonce=start.browser_nonce,
            issuer="https://discord.com",code="one-time-code",
            transport=transport,installed_cinema_guilds={42})
        self.assertEqual((login.guild.user_id,login.guild.guild_id),(123,42))
        self.assertEqual([x[0] for x in transport.calls],["exchange",USER_ENDPOINT,GUILDS_ENDPOINT])
        self.assertNotIn("test-oauth-token",repr(login))
        with self.assertRaises(CinemaOAuthError):
            await flow.complete(state=start.state,browser_nonce=start.browser_nonce,
                issuer="https://discord.com",code="replayed-code",transport=transport,
                installed_cinema_guilds={42})

    async def test_uninstalled_or_other_guild_is_denied(self):
        for installed,guild in ((set(),"42"),({42},"43")):
            flow=CinemaOAuthFlow(CONFIG)
            start=flow.begin(guild_id=42)
            with self.assertRaises(CinemaOAuthError):
                await flow.complete(state=start.state,browser_nonce=start.browser_nonce,
                    issuer="https://discord.com",code="one-time-code",
                    transport=FakeTransport(guild=guild),installed_cinema_guilds=installed)

    async def test_no_external_call_for_wrong_nonce(self):
        flow=CinemaOAuthFlow(CONFIG)
        start=flow.begin(guild_id=42)
        transport=FakeTransport()
        with self.assertRaises(CinemaOAuthError):
            await flow.complete(state=start.state,browser_nonce="attacker",issuer="https://discord.com",
                code="one-time-code",transport=transport,installed_cinema_guilds={42})
        self.assertEqual(transport.calls, [])


class TransportBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_redirects_and_only_official_discord_urls(self):
        class Response:
            status=200
            def __init__(self, payload): self.content=self;self.payload=payload
            async def read(self,max_size): return self.payload
            async def __aenter__(self): return self
            async def __aexit__(self,*args): return False
        class Session:
            def __init__(self):self.requests=[]
            def post(self,url,**kwargs):
                self.requests.append(("post",url,kwargs))
                return Response(b'{"access_token":"opaque-test-token","token_type":"Bearer","expires_in":3600,"scope":"identify guilds"}')
            def get(self,url,**kwargs):
                self.requests.append(("get",url,kwargs))
                return Response(b'{"id":"123"}')
        session=Session()
        transport=DiscordOAuthTransport(session,CONFIG)
        grant=await transport.exchange("safe-code","safe-verifier")
        self.assertEqual(grant.scopes,frozenset(("identify","guilds")))
        self.assertEqual(await transport.fetch(USER_ENDPOINT,grant.access_token),{"id":"123"})
        self.assertEqual(session.requests[0][1],TOKEN_URL)
        self.assertEqual(session.requests[0][2]["allow_redirects"],False)
        self.assertEqual(session.requests[0][2]["data"]["redirect_uri"],CONFIG.redirect_uri)
        self.assertEqual(session.requests[1][1],"https://discord.com/api/v10"+USER_ENDPOINT)
        self.assertEqual(session.requests[1][2]["allow_redirects"],False)
        with self.assertRaises(CinemaOAuthError):
            await transport.fetch("https://attacker.example.org/steal",grant.access_token)
        self.assertEqual(len(session.requests),2)

    async def test_unexpected_scopes_and_errors_fail_closed(self):
        class Response:
            status=200; content=None
            def __init__(self,data): self.content=self;self.data=data
            async def read(self,max_bytes): return self.data
            async def __aenter__(self):return self
            async def __aexit__(self,*args):return False
        class Session:
            def post(self,*args,**kwargs):return Response(b'{"access_token":"secret","token_type":"Bearer","scope":"identify","expires_in":300}')
        with self.assertRaises(CinemaOAuthError):
            await DiscordOAuthTransport(Session(),CONFIG).exchange("valid-code","verifier")

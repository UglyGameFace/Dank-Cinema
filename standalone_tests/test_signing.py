from __future__ import annotations

import unittest

from cinema_app.signing import CinemaSigner, MAX_AGE_SECONDS

KEY = b"standalone-cinema-example-signing-key-with-high-entropy-placeholder"


class IndependentSigningTests(unittest.TestCase):
    def test_missing_or_short_key_never_falls_back_to_torrent_secret(self) -> None:
        with self.assertRaises(ValueError):
            CinemaSigner.from_environment({
                "DANK_TORRENT_STREAM_SECRET": "legacy-" + "x" * 64,
            })
        with self.assertRaises(ValueError):
            CinemaSigner.from_environment({"CINEMA_SESSION_SIGNING_KEY": "weak"})
        assert isinstance(
            CinemaSigner.from_environment({"CINEMA_SESSION_SIGNING_KEY": KEY.decode()}),
            CinemaSigner,
        )

    def test_token_round_trip_with_specific_guild_and_purpose(self) -> None:
        signer = CinemaSigner(KEY)
        token = signer.issue(
            guild_id=123, user_id=456, purpose="login-link",
            ttl_seconds=300, now=10000,
        )
        result = signer.verify(token, guild_id=123, purpose="login-link", now=10200)
        assert result is not None
        self.assertEqual(result.user_id, 456)
        self.assertEqual(result.guild_id, 123)
        self.assertEqual(result.purpose, "login-link")
        self.assertEqual(result.expires_at, 10300)

    def test_cross_purpose_and_cross_guild_rejected(self) -> None:
        signer = CinemaSigner(KEY)
        token = signer.issue(guild_id=123, user_id=456, purpose="login-link", ttl_seconds=60, now=100)
        self.assertIsNone(signer.verify(token, guild_id=124, purpose="login-link", now=110))
        self.assertIsNone(signer.verify(token, guild_id=123, purpose="browser-session", now=110))

    def test_tamper_wrong_secret_and_expiry_rejected(self) -> None:
        signer = CinemaSigner(KEY)
        token = signer.issue(
            guild_id=123, user_id=456, purpose="browser-session",
            ttl_seconds=3600, now=1000,
        )
        self.assertIsNone(signer.verify(token, guild_id=123, purpose="browser-session", now=4601))
        self.assertIsNone(
            CinemaSigner(b"other-secure-signing-key-different-from-the-first").verify(
                token, guild_id=123, purpose="browser-session", now=1001
            )
        )
        self.assertIsNone(signer.verify(token[:-1] + "0", guild_id=123, purpose="browser-session", now=1100))
        self.assertIsNone(signer.verify(token + ".", guild_id=123, purpose="browser-session", now=1100))

    def test_future_dated_or_overlong_tokens_rejected(self) -> None:
        signer = CinemaSigner(KEY)
        token = signer.issue(guild_id=2, user_id=3, purpose="login-link", ttl_seconds=200, now=10000)
        self.assertIsNone(signer.verify(token, guild_id=2, purpose="login-link", now=9900))
        with self.assertRaises(ValueError):
            signer.issue(guild_id=2, user_id=3, purpose="login-link", ttl_seconds=MAX_AGE_SECONDS + 1)
        with self.assertRaises(ValueError):
            signer.issue(guild_id=0, user_id=3, purpose="login-link", ttl_seconds=1)
        with self.assertRaises(ValueError):
            signer.issue(guild_id=2, user_id=3, purpose="invalid", ttl_seconds=100)

    def test_archived_legacy_site_signatures_not_implicitly_compatible(self) -> None:
        signer = CinemaSigner(KEY)
        self.assertIsNone(signer.verify("1.2.123.deadbeef", guild_id=1, purpose="login-link", now=100))
        self.assertIsNone(signer.verify("", guild_id=1, purpose="login-link", now=100))

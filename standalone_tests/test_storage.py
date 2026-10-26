from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest

from cinema_app.storage import (
    CinemaStorage, CinemaStorageConfig, CinemaStorageUnavailable, rows, utc_now,
)

URL = "https://cinema-independent-example.supabase.co"
KEY = "cinema-independent-placeholder-" + "A" * 40


class StorageConfigurationTests(unittest.TestCase):
    def test_does_not_accept_legacy_shield_credentials(self) -> None:
        with self.assertRaises(CinemaStorageUnavailable):
            CinemaStorageConfig.from_environment({
                "SUPABASE_URL": URL,
                "SUPABASE_SERVICE_ROLE_KEY": KEY,
                "DANK_SUPABASE_URL": URL,
                "DANK_SUPABASE_SERVICE_ROLE_KEY": KEY,
            })

    def test_configured_storage_keeps_credentials_out_of_repr(self) -> None:
        result = CinemaStorageConfig.from_environment({
            "CINEMA_SUPABASE_URL": URL + "/",
            "CINEMA_SUPABASE_SERVICE_ROLE_KEY": KEY,
        })
        self.assertEqual(result.url, URL)
        self.assertEqual(result.service_role_key, KEY)
        self.assertNotIn(KEY, repr(result))

    def test_rejects_insecure_or_ambiguous_endpoint(self) -> None:
        for endpoint in (
            "http://cinema.example.net",
            "https://user:password@cinema.example.net",
            "https://cinema.example.net/rest/v1",
            "https://cinema.example.net?key=secret",
            "https://cinema.example.net/#fragment",
            "not-a-url",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(CinemaStorageUnavailable):
                    CinemaStorageConfig.from_environment({
                        "CINEMA_SUPABASE_URL": endpoint,
                        "CINEMA_SUPABASE_SERVICE_ROLE_KEY": KEY,
                    })

    def test_requires_nontrivial_dedicated_key(self) -> None:
        with self.assertRaises(CinemaStorageUnavailable):
            CinemaStorageConfig.from_environment({
                "CINEMA_SUPABASE_URL": URL,
                "CINEMA_SUPABASE_SERVICE_ROLE_KEY": "1234",
            })

    def test_data_helpers_filter_invalid_rows(self) -> None:
        self.assertEqual(rows(SimpleNamespace(data=[{"x": 1}, {}, None, "bad"])), [{"x": 1}, {}])
        self.assertEqual(rows(SimpleNamespace(data="not-list")), [])
        self.assertIn("+00:00", utc_now())


class StorageOperationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = CinemaStorageConfig.from_environment({
            "CINEMA_SUPABASE_URL": URL,
            "CINEMA_SUPABASE_SERVICE_ROLE_KEY": KEY,
        })

    async def test_read_retries_one_connection_failure_only(self) -> None:
        seen = []
        def factory(url, key):
            seen.append((url, key))
            if len(seen) == 1:
                raise ConnectionError("private host not available")
            return {"value": 42}
        client = CinemaStorage(self.config, client_factory=factory)
        self.assertEqual(await client.read(lambda db: db["value"]), 42)
        self.assertEqual(len(seen), 2)

    async def test_write_is_never_retried_even_on_timeout(self) -> None:
        calls = 0
        def factory(_url, _key):
            nonlocal calls
            calls += 1
            raise TimeoutError("perhaps the insert committed with secret: " + KEY)
        client = CinemaStorage(self.config, client_factory=factory)
        with self.assertRaises(CinemaStorageUnavailable) as ctx:
            await client.write(lambda db: db)
        self.assertEqual(calls, 1)
        self.assertNotIn(KEY, str(ctx.exception))
        self.assertNotIn("perhaps", str(ctx.exception))

    async def test_programming_errors_are_not_retried(self) -> None:
        calls = 0
        def factory(_url, _key):
            nonlocal calls
            calls += 1
            return object()
        client = CinemaStorage(self.config, client_factory=factory)
        with self.assertRaises(CinemaStorageUnavailable):
            await client.read(lambda _: 1 / 0)
        self.assertEqual(calls, 1)

    async def test_client_creation_is_lazy_and_does_not_network_during_preview(self) -> None:
        calls = 0
        def factory(_url, _key):
            nonlocal calls
            calls += 1
            return "ok"
        storage = CinemaStorage(self.config, client_factory=factory)
        self.assertEqual(calls, 0)
        self.assertEqual(await storage.read(lambda x: x), "ok")
        self.assertEqual(calls, 1)

    async def test_missing_client_fails_closed(self) -> None:
        storage = CinemaStorage(self.config, client_factory=lambda _u, _k: None)
        with self.assertRaisesRegex(CinemaStorageUnavailable, "not available"):
            await storage.read(lambda c: c)

from __future__ import annotations

import ast
from pathlib import Path
import unittest

from aiohttp.test_utils import TestClient, TestServer

from cinema_app.preview import (
    create_preview_app,
    is_preview_enabled,
    preview_bind_address,
    preview_port,
)

ROOT = Path(__file__).resolve().parents[1]


class PreviewConfigurationTests(unittest.TestCase):
    def test_preview_is_opt_in_and_disabled_by_default(self) -> None:
        self.assertFalse(is_preview_enabled({}))
        self.assertFalse(is_preview_enabled({"CINEMA_PREVIEW_ENABLED": "false"}))
        self.assertTrue(is_preview_enabled({"CINEMA_PREVIEW_ENABLED": "true"}))

    def test_preview_cannot_bind_publicly(self) -> None:
        self.assertEqual(preview_bind_address({}), "127.0.0.1")
        for address in ("0.0.0.0", "::", "localhost", "example.net"):
            with self.subTest(address=address):
                with self.assertRaisesRegex(ValueError, "loopback-only"):
                    preview_bind_address({"CINEMA_PREVIEW_BIND_HOST": address})

    def test_port_requires_nonprivileged_integer(self) -> None:
        self.assertEqual(preview_port({}), 18080)
        for value in ("0", "80", "65536", "wat"):
            with self.subTest(port=value):
                with self.assertRaises(ValueError):
                    preview_port({"CINEMA_PREVIEW_PORT": value})

    def test_new_app_imports_no_archived_shield_or_media_runtime(self) -> None:
        for path in (ROOT / "cinema_app").glob("*.py"):
            with self.subTest(module=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                imports = [
                    node.module or ""
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                ]
                imports.extend(
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Import)
                    for alias in node.names
                )
                self.assertFalse(
                    any(
                        name.startswith((
                            "stoney_verify", "libtorrent", "torrent",
                            "cinema_app.media", "cinema_app.discord",
                        ))
                        for name in imports
                    ),
                    imports,
                )


class PreviewRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.client = TestClient(TestServer(create_preview_app()))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_health_is_explicitly_offline(self) -> None:
        async with self.client.get("/health") as result:
            self.assertEqual(result.status, 200)
            value = await result.json()
            self.assertEqual(value["status"], "offline")
            for field in (
                "watch_parties_enabled", "downloads_enabled",
                "torrent_engine_enabled", "discord_bridge_enabled",
            ):
                self.assertIs(value[field], False)

    async def test_home_does_not_misrepresent_active_player(self) -> None:
        async with self.client.get("/") as result:
            self.assertEqual(result.status, 200)
            page = await result.text()
            self.assertIn("migration preview", page.lower())
            self.assertIn("inactive", page.lower())
            self.assertEqual(result.headers["Cache-Control"], "no-store")

    async def test_archived_cinema_and_media_routes_not_mounted(self) -> None:
        for route in (
            "/cinema", "/cinema/123", "/movie/abc/watch",
            "/media/torrent/stream/abc", "/api/cinema/feed",
            "/cinema/auth/callback", "/oauth/callback",
        ):
            with self.subTest(route=route):
                async with self.client.get(route) as response:
                    self.assertEqual(response.status, 404)

    async def test_player_routes_cannot_be_activated_with_post(self) -> None:
        for route in ("/cinema/start", "/api/sessions", "/media/torrent/stream"):
            with self.subTest(route=route):
                async with self.client.post(route, json={}) as response:
                    self.assertEqual(response.status, 404)

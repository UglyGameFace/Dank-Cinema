from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SafeLocalMediaComposeTests(unittest.TestCase):
    def test_jellyfin_is_opt_in_and_bound_to_localhost(self) -> None:
        compose = (ROOT / "ops" / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn('profiles: ["local-media"]', compose)
        self.assertIn('127.0.0.1:', compose)
        self.assertIn(':8096', compose)
        self.assertIn(':/media:ro', compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertIn("./jellyfin/config:/config", compose)
        self.assertIn("./jellyfin/cache:/cache", compose)

    def test_no_unreviewed_downloader_or_public_cinema_server(self) -> None:
        compose = (ROOT / "ops" / "compose.yaml").read_text(encoding="utf-8")
        for unexpected in (
            "qbittorrent:", "gluetun:", "transmission:",
            "torrent:", "privileged:", "/dev/net/tun", "NET_ADMIN",
            "cinema_app.preview", '0.0.0.0:',
        ):
            with self.subTest(unexpected=unexpected):
                self.assertNotIn(unexpected, compose)

    def test_sensitive_runtime_data_is_gitignored(self) -> None:
        patterns = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for required in ("ops/.env", "providers/*.env", "client.key",
                         "client.crt", "wireguard/*.conf",
                         "ops/media/", "ops/jellyfin/"):
            self.assertIn(required, patterns)
        example = (ROOT / "ops" / ".env.example").read_text(encoding="utf-8")
        self.assertNotIn("DISCORD_TOKEN=", example)
        self.assertNotIn("OPENVPN_PASSWORD=", example)


if __name__ == "__main__":
    unittest.main()

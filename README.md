# Dank Cinema

Dank Cinema is being separated from the [Dank Shield](https://github.com/UglyGameFace/Dank-Shield) bot.

## Extraction status: source-preservation checkpoint (October 25, 2026)

This branch preserves the original Cinema-specific implementation, browser assets, schema migrations, docs and tests at their historical `stoney_verify/` paths, copied byte-for-byte from Dank Shield source commit `930f1796c3c1dd5d81d505f9ee4b4946de0952e7`. Unrelated Dank Shield runtime components have **not** been copied here.

**Not a standalone running application.** Many modules still import Dank Shield shared services such as globals, permissions, guild configuration, session/role logic, database adapters and Discord command infrastructure. Tests have not been ported to a fully independent runtime; nothing on this branch starts a server, transfers data, or deploys media services. Do not configure this repository for automatic hosting until those dependencies are isolated and tested.

No private keys, tokens, PostgreSQL rows, runtime caches, media, torrent payloads, user data, or live process state were migrated. No production Discloud runtime has been changed by this source-copy step.

## Next migration gates

1. Make Cinema's Discord command bot, membership lookups and storage independent of Dank Shield; define standalone environment and deployment policy.
2. Rewrite shared imports, configuration, and data ownership; transfer only consented required database state after backup and verified schema support.
3. Preserve Cinema site, authenticated sessions, subtitles, catalog, legitimate watch-party functionality and user-facing playback controls with regression tests.
4. Keep torrent acquisition/download/seeding disabled pending provider and authorization review. Moving code to this repository is not a mechanism to conceal copyright-infringing traffic from Discloud.
5. Independently validate builds, CI, startup/shutdown, auth, networking and operation on target hosting before activation.

The two previously missing files, `docs/DANK_CINEMA_MEDIA_COMPATIBILITY.md` and `tests/test_movie_night_preferences.py`, are now included in this archival snapshot. They were transferred from the source commit with matching Git blob SHA hashes.

See [extraction issue #1](https://github.com/UglyGameFace/Dank-Cinema/issues/1) for the paired Shield cutover and release gates.

## Independent bootstrap (non-production)

A separate `cinema_app/` entrypoint now supports an opt-in, loopback-only, **offline**
migration preview and read-only health endpoint. It deliberately does not import
the historical Cinema/Shield code or enable media. See
[`docs/STANDALONE_BOOTSTRAP.md`](docs/STANDALONE_BOOTSTRAP.md) for exact
boundaries and remaining migration work. There is still **no production deploy**.

## Planned Docker host runtime

The intended standalone deployment separates the Cinema Discord bot, authenticated
web/API service, independent state store, and a private Jellyfin media backend.
The verified design and required security fixes for the proposed multi-container
VPN / media layout are in
[Docker runtime architecture](docs/DOCKER_RUNTIME_ARCHITECTURE.md).

An **opt-in local Jellyfin-only** Compose profile is available at
[`ops/compose.yaml`](ops/compose.yaml), using
[`ops/.env.example`](ops/.env.example). It binds Jellyfin to loopback and
uses a read-only media volume. It is **not** the operational watch-party stack.
The independent Cinema app/bot and any authorized media acquisition have not
been deployed; existing Discloud incident restrictions remain in effect.

## Work in progress: Cinema-owned room state

The independent `cinema_app.rooms` lifecycle now models public/private watch-party membership, a 20-person cap, host absence voting and idle expiry, with standalone tests. It is not wired to a public server or media backend. See [standalone bootstrap notes](docs/STANDALONE_BOOTSTRAP.md).

## Independent Discord login groundwork

The Cinema-owned [OAuth authorization-code and guild proof handshake](docs/DISCORD_OAUTH_HANDSHAKE.md)
uses one-time browser-bound state and PKCE, with no Dank Shield token reuse.
It is an offline-tested security component only; no public login endpoint,
Discord installation automation or playback deployment has been activated.

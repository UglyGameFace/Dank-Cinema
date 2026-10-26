# Standalone bootstrap, isolated migration preview

The historic Cinema modules under `stoney_verify/` are preserved source, not
importable production dependencies. The separate `cinema_app` package is the
only supported new entrypoint and is deliberately **offline**.

## Local opt-in verification

```bash
python -m pip install -r requirements-preview.txt
python -m unittest discover -s standalone_tests -v
CINEMA_PREVIEW_ENABLED=true python -m cinema_app
```

Without the explicit opt-in, `python -m cinema_app` exits immediately.
When enabled, it listens on **127.0.0.1:18080** and refuses nonloopback
addresses, public binding and privileged ports. It returns a plain migration
status page, a truthful `/health` status, and 404 for old player, OAuth,
torrent and Cinema routes.

**This does not rebuild watch parties, provide identity, reconnect the bot,
migrate Supabase data, or support media playback.** No service deployment,
background job, torrent source fetch or media transfer is implemented.

## Components that still need migration

| Component | Archived location | Independent dependency required |
| --- | --- | --- |
| Cinema browser and discovery APIs | `stoney_verify/cinema_site.py` | Standalone auth, guild membership, catalog/DB adapter |
| Browser session auth | `stoney_verify/cinema_site_auth.py` | Own Discord OAuth app, secret rotation and cookie controls |
| Watch-party state | `stoney_verify/movie_night.py`, `movie_night_session.py` | Independent session model and ownership |
| Media player and subtitles | `stoney_verify/movie_night_web.py`, `cinema_subtitles.py` | Authorized media inputs, playback state and source rights |
| Storage | `stoney_verify/cinema_storage.py` | Dedicated DB client/migrations, no import from Shield globals |
| Slash commands | `stoney_verify/commands_ext/public_movie_night.py` | Own Discord application, no Dank Shield command tree |
| Media acquisition code | `stoney_verify/torrent_streaming.py`, `torrent_media_server.py` | **Not enabled**; needs authorized use and hosting compliance review |

The code archive is immutable in purpose until these dependencies are replaced
with tested standalone implementations. Only then can a separate production
service be designed, with an independent deployment and verified data migration.

To verify Dank Shield production is genuinely detached, separately follow
`UglyGameFace/Dank-Shield/docs/CINEMA_SEPARATION_CUTOVER.md`; merging either
repository does not stop a running host process.

## Independent signing primitives (not yet exposed via HTTP)

The preview-only project now includes `cinema_app.signing.CinemaSigner` to
replace the old Cinema site's dependency on `DANK_TORRENT_STREAM_SECRET`.
It requires a **separate** `CINEMA_SESSION_SIGNING_KEY` of at least 32 bytes;
no legacy Shield or torrent secret fallback exists. The signer binds a short
expiration, purpose, guild ID and user ID using HMAC-SHA256. Legacy links/cookies
are deliberately incompatible, so a future migration needs explicit re-login.

**A cryptographically signed token is not a permission check.** Before using
a token to open a real session, the independent Cinema service must verify the
Discord login, current guild membership and user permissions, use HttpOnly,
Secure, SameSite cookies, and implement server-side revocation. No new login or
stream route has been mounted in this PR. Never put signing keys in Git.

## Cinema-owned database adapter (not connected to production)

The independent `cinema_app.storage` module replaces the old module's direct
dependency on `stoney_verify.globals.get_supabase`. It has **no** implicit
Shield/database fallback. It requires a Cinema-specific HTTPS origin and
service credential (`CINEMA_SUPABASE_URL` and
`CINEMA_SUPABASE_SERVICE_ROLE_KEY`), and a separately supplied client factory.

The application preview never constructs a database client or uses the key.
The adapter intentionally distinguishes read and write operations: idempotent
reads may retry one transport failure, while writes are never blindly retried
because the server might already have committed the first attempt. Error
messages suppress underlying response bodies and credentials. Four concurrent
requests is the configured internal limit for the adapter.

**This is an interface, not a completed data migration.** There is no live
database connection, data export, schema mutation, or use of Shield's
production Supabase credentials. Archived tables are only reference contracts.
Before production operation, provision a genuinely independent database,
validate schema and row ownership, inspect data retention, explicitly approve
and back up any migration, and implement revoked-session and current Discord
guild authorization checks before serving member data.

## Standalone Discord user / guild proof (not wired to public routes)

`cinema_app.discord_identity` compares Discord OAuth user identity from
`/users/@me` (scope `identify`) and a user's exact guild membership from
`/users/@me/guilds` (scope `guilds`) against a separately established
Cinema app-installation list. Missing scope/transport data, identity mismatch,
or incomplete membership lists fail closed. Fetch transport must target the
official Discord API using HTTPS, enforce timeouts and rate limits, and must
never forward bearer tokens to third-party domains.

A proof is **not** role permission, current member revocation, private room
authorization or media access. This does not add a live OAuth exchange or
session route; those dependencies still require independent implementation.

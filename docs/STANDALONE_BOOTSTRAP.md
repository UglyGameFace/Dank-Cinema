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

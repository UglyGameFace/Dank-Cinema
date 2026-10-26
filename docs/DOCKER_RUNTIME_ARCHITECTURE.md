# Dank Cinema: standalone Docker runtime target (architecture decision)

**Status 2026-10-25:** Design and safe local media foundation only.
No public Cinema deployment, torrent session, VPN switcher, watchdog, or live
database migration is authorized or implemented by this document.

## Owner's requested service split

The goal is a separate Docker-capable host and repository, never a child of
Dank Shield's Discloud `stoneyverify` process.

```text
Discord users ──> independent Dank Cinema bot ─┐
                                                │ authenticated room events
Web / Android / desktop ─> TLS reverse proxy ──┤
                                                v
                                 Cinema web/API + authorized watch parties
                                              │ │
                   independent Cinema DB <────┘ │
                                                v
                                     Jellyfin (private media library)
                                                │
                                    approved read-only media volume

[Future, separately approved]
Lawful acquisition workflow ─> isolated transfer boundary ─> reviewed import
```

- **Bot:** standalone Discord application/token, independent command tree,
  installation list, permissions and user verification. Ordinary Discord
  gateway and voice traffic does **not** traverse a downloader's VPN.
- **Web/API:** separate Cinema service, with OAuth callback, secure cookies,
  server-side membership/revocation, validated guild/room rights, rate limits,
  synchronized playback events and explicit health. The current
  `cinema_app.preview` must not be exposed publicly as if it were this.
- **Media library:** Jellyfin is a *private playback backend* for media the
  operator has rights to serve. Read-only library access where possible.
  Libraries, catalog entries and user playback permissions require explicit
  connection to Cinema's auth policy. Jellyfin alone does not provide
  synchronized Cinema watch-party behavior.
- **State/storage:** Cinema-specific database credentials and schema. Persist
  rooms/session state with atomic capacity checks, replayable events and
  revocation; the prototype `CinemaRooms` in PR #9 is currently process-local.
- **Public ingress:** only an explicitly approved HTTPS reverse proxy may
  expose authenticated Cinema application endpoints. Do not publish Jellyfin
  admin UI, database, torrent-client WebUI, or VPN administration ports.
- **Optional transfers:** provider-controlled, clearly isolated service,
  disabled by default and subject to the host's acceptable-use policy,
  source rights and separate approval. It must never reattach Cinema's old
  downloader/seeder to Dank Shield. A VPN does not resolve copyright complaints.

## Verified claims and corrections to the supplied example

1. **CyberGhost:** Gluetun's CyberGhost integration documents OpenVPN, unique
   OpenVPN credentials, a certificate and private key (optionally files named
   `client.crt` and `client.key`). A *custom* WireGuard configuration is a
   separate mode, not native CyberGhost support. Do not promise any universal
   '3-5x throughput' gain without measurement.
2. **Forwarding:** Gluetun natively supports VPN server-side port forwarding
   for PIA, ProtonVPN, Perfect Privacy and PrivateVPN. This is distinct from
   exposing a container port. CyberGhost and Mullvad must not be assumed to
   support this. Dynamic allocations require coordinated application state.
3. **Compose environment:** a project `.env` or explicit
   `docker compose --env-file` supplies *Compose interpolation*. A service
   `env_file:` supplies that container's environment. Putting VPN credentials
   and `DISCORD_TOKEN` into a single interchangeable file is unsafe and
   causes missing or cross-contaminated configuration. Use separate, non-git
   credential sources, and inspect redacted resolved configuration.
4. **Incorrect qBittorrent API:** `/api/v2/command/setPreferences` in the
   supplied example is not the documented current preferences endpoint.
   The proposed port-sync script also ignores failed authentication,
   transport failures and response codes. It must not be used unchanged.
5. **VPN verification:** external host IP differing from tunnel IP is a weak
   connectivity observation, not proof that the designated application's
   network namespace, DNS, IPv6 and all UDP traffic fail closed.
6. **Failover:** provider rotation as written can select missing providers,
   mismatch state after a manual switch, thrash on unhealthy startup, restart
   Discord unnecessarily and call a failed transfer 'recovered'. A failure
   must mean transfers STOP, never fallback to host networking or another
   unreviewed provider. Changes require per-provider testing, host permission
   and operational approval.
7. **Port publication:** `6881:6881` on the host and a separate dynamically
   forwarded VPN port are unrelated. Never publish an administrative WebUI
   or transfer ingress publicly by default. The supplied sample cannot be
   treated as a working production security boundary.
8. **Discloud deployment:** the existing app is managed through Discloud's
   ordinary `discloud.config`, not known to support privileged Compose,
   `NET_ADMIN`, `/dev/net/tun` or a nested container daemon. Use a separately
   approved Docker-capable host. Merely moving the stack or changing IP does
   not clear Discloud's earlier copyright complaint.

Reference: Docker Compose interpolation and service environment documentation,
Gluetun's CyberGhost/client-cert/port-forwarding/custom-WireGuard docs, and
qBittorrent WebUI API v5.0 docs (see end of document).

## Implemented now: optional Jellyfin-local Compose profile

- `ops/compose.yaml` introduces **only** `jellyfin` behind
  `127.0.0.1:8096`, with a persistent config/cache and a read-only
  `./media` directory. The service belongs to `local-media` profile,
  therefore **no service starts by default**.
- `ops/.env.example` has only safe, nonsecret local values. `.gitignore`
  excludes local credentials and media. No Dockerfile for the unfinished
  Cinema web/bot, and no VPN/downloader containers.
- An operator on a Docker-capable Linux host may inspect configuration with
  `docker compose -f ops/compose.yaml --profile local-media config`.
  The local Jellyfin service is **not** wired to Cinema and is not a finished
  deployment. Never publish it externally until authentication is tested.
- `jellyfin/jellyfin:latest` is only a local reference. Pin a reviewed image
  digest for production, and verify transcoding resources and backup strategy.

## Acceptance sequence

1. Complete and merge standalone room-state PR #9 with independent tests.
2. Implement the real Cinema web/API + Discord app, independent OAuth and
   role/guild proof, secure sessions, media authorization and revocation.
3. Connect an independently owned persistent store; safely migrate only
   approved room/configuration records after backup.
4. Integrate authorized media with Jellyfin, adaptive playback and per-user
   sync while preserving original Cinema UX; test mobile/desktop/20 viewers.
5. Add reproducible container builds with pinned revisions, non-root runtime,
   secrets management, no public admin endpoints, limits, logs and backups.
6. Validate on approved Docker-capable hosting with written acceptable-use
   clearance. Add optional lawful transfer service only after a separate
   compliance decision; it is **not** part of this release.
7. Separately verify live Dank Shield process and Discloud update after
   merged Shield #729-#732; repository cleanups do not stop running processes.

## Technical references

- Docker Compose interpolation:
  https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/
- Docker Compose service env file:
  https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/
- Gluetun CyberGhost:
  https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/cyberghost.md
- Gluetun port forwarding:
  https://github.com/qdm12/gluetun-wiki/blob/main/setup/advanced/vpn-port-forwarding.md
- Gluetun custom WireGuard:
  https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/custom.md
- qBittorrent WebUI API v5.0:
  https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-5.0)

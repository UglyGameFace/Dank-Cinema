# Standalone Cinema Discord OAuth handshake

This is a **non-deployed library**, not a working public login page. It contains
a Cinema-owned Discord authorization-code flow, isolated from Dank Shield.

- Configure `CINEMA_DISCORD_CLIENT_ID`, `CINEMA_DISCORD_CLIENT_SECRET` and
  an exact registered `CINEMA_DISCORD_REDIRECT_URI`. The secret is server-only.
- Request `identify guilds` via Discord's official OAuth authorize URL,
  use a random short-lived state and PKCE S256 challenge, and bind state to a
  secure browser-only nonce.
- The callback handler, when implemented, must check the issuer
  (`https://discord.com`), state, nonce and single-use expiry **before**
  exchanging the code using the configured server-side client credentials.
- The transport only contacts `discord.com` over HTTPS with redirects
  disabled. It validates token shape and scopes, then calls the official
  `/users/@me` and `/users/@me/guilds` APIs to construct the existing
  `DiscordGuildProof`, checking an independently supplied Cinema installation
  list for the exact guild.
- No Discord user token, refresh token or client secret is placed in URLs,
  browser storage, Git, debug logs or exception messages. Browser sessions are
  **not** issued by this module.

**Before production:** implement a real HTTPS callback and HttpOnly Secure
SameSite cookie, server-side session storage/revocation and audit trail,
CSRF nonce cookie, complete install/member/role checks per action, rotating
signing keys, rate limits, redirect allowlist, API outage handling and shared
state for multiple replicas. Development state is process-local and can be
lost at restart. It cannot be used to enter a watch party or access media.

Official specification:
https://discord.com/developers/docs/topics/oauth2

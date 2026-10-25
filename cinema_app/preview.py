from __future__ import annotations

"""Explicitly opt-in, loopback-only standalone Cinema migration preview.

This service intentionally does not mount archived movie, media, torrent,
Discord, OAuth or database routes. It is a verifiable independent boot path,
NOT the finished Cinema site or a production deployment.
"""

import os
from typing import Mapping

from aiohttp import web

_ENABLED_ENV = "CINEMA_PREVIEW_ENABLED"
_PORT_ENV = "CINEMA_PREVIEW_PORT"
_LOOPBACK = "127.0.0.1"
_DEFAULT_PORT = 18080


def is_preview_enabled(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    return str(values.get(_ENABLED_ENV, "")).strip().lower() == "true"


def preview_port(env: Mapping[str, str] | None = None) -> int:
    values = os.environ if env is None else env
    raw = str(values.get(_PORT_ENV, _DEFAULT_PORT)).strip()
    try:
        result = int(raw)
    except ValueError as exc:
        raise ValueError(f"{_PORT_ENV} must be an integer") from exc
    if result < 1024 or result > 65535:
        raise ValueError(f"{_PORT_ENV} must be between 1024 and 65535")
    return result


def preview_bind_address(env: Mapping[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    host = str(values.get("CINEMA_PREVIEW_BIND_HOST", _LOOPBACK)).strip()
    if host != _LOOPBACK:
        raise ValueError("The migration preview is loopback-only (127.0.0.1)")
    return host


async def _health(_request: web.Request) -> web.Response:
    return web.json_response(
        {
            "service": "dank-cinema",
            "mode": "migration-preview",
            "status": "offline",
            "watch_parties_enabled": False,
            "downloads_enabled": False,
            "torrent_engine_enabled": False,
            "discord_bridge_enabled": False,
        }
    )


async def _home(_request: web.Request) -> web.Response:
    return web.Response(
        text=(
            "<!doctype html><html lang=\"en\"><head>"
            "<meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Dank Cinema | Migration Preview</title>"
            "<style>"
            "body{background:#0b1512;color:#eef5ed;font-family:system-ui,sans-serif;"
            "min-height:100vh;display:grid;place-items:center;margin:0;padding:1rem}"
            "main{max-width:32rem}h1{color:#b7f0ca}p{line-height:1.6}"
            "</style></head><body><main><h1>Dank Cinema</h1>"
            "<p>This is an isolated migration preview, not the finished player.</p>"
            "<p>Watch parties, media transfers, Discord access and account features "
            "are inactive while the standalone services are separated and tested.</p>"
            "</main></body></html>"
        ),
        content_type="text/html",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def create_preview_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", _home)
    app.router.add_get("/health", _health)
    return app


def main() -> None:
    if not is_preview_enabled():
        raise SystemExit(
            "Dank Cinema archive is not an active application. "
            "For local-only migration preview set CINEMA_PREVIEW_ENABLED=true."
        )
    web.run_app(
        create_preview_app(),
        host=preview_bind_address(),
        port=preview_port(),
        access_log=None,
    )


__all__ = (
    "create_preview_app",
    "is_preview_enabled",
    "preview_bind_address",
    "preview_port",
    "main",
)

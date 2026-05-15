"""Telegram gateway management tools."""

import sys
import os

_gateway = None
_gateway_thread = None


def _get_token(args: dict) -> str:
    return args.get("token", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")


def telegram_start_handler(args: dict) -> dict:
    global _gateway, _gateway_thread
    token = _get_token(args)
    if not token:
        return {"error": "TELEGRAM_BOT_TOKEN not set. Set env var or pass token arg."}

    if _gateway and _gateway._running:
        return {"success": True, "message": "Gateway already running"}

    try:
        from redclaw.gateway.telegram import TelegramGateway
        _gateway = TelegramGateway(token)
        _gateway_thread = _gateway.start_background()
        return {"success": True, "message": "Telegram gateway started (long-polling)"}
    except Exception as e:
        return {"error": str(e)}


def telegram_stop_handler(args: dict) -> dict:
    global _gateway, _gateway_thread
    if not _gateway:
        return {"success": True, "message": "No gateway running"}
    _gateway.stop()
    _gateway = None
    _gateway_thread = None
    return {"success": True, "message": "Gateway stopped"}


def telegram_status_handler(args: dict) -> dict:
    global _gateway
    if _gateway and _gateway._running:
        return {
            "success": True, "running": True,
            "sessions": len(_gateway.sessions),
            "chats": list(_gateway.sessions.keys()),
        }
    return {"success": True, "running": False, "token_configured": bool(_get_token(args))}


def register_telegram_tools(registry):
    registry.register(
        name="telegram_start", toolset="gateway",
        schema={"type": "object", "properties": {
            "token": {"type": "string", "description": "Telegram Bot Token (defaults to TELEGRAM_BOT_TOKEN env var)"},
        }},
        handler=telegram_start_handler,
        description="Start Telegram gateway (long-polling)", emoji="🤖",
    )
    registry.register(
        name="telegram_stop", toolset="gateway",
        schema={"type": "object", "properties": {}},
        handler=telegram_stop_handler,
        description="Stop Telegram gateway", emoji="🛑",
    )
    registry.register(
        name="telegram_status", toolset="gateway",
        schema={"type": "object", "properties": {}},
        handler=telegram_status_handler,
        description="Check Telegram gateway status", emoji="📡",
    )

"""Telegram Gateway — long-polling bridge between Telegram Bot API and AIAgent."""

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx

TELEGRAM_LIMIT = 4000  # messages split at 4000 chars (safe under 4096)


class TelegramGateway:
    """Long-polls Telegram Bot API, routes messages to AIAgent, sends responses back."""

    def __init__(self, token: str):
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"
        self.sessions: dict = {}  # chat_id → {"agent": AIAgent, "user": str}
        self._running = False
        self._executor = ThreadPoolExecutor(max_workers=4)

    # ─── Public API ────────────────────────────────────────────

    def run_forever(self):
        """Blocking entry point — runs the asyncio polling loop."""
        asyncio.run(self._poll())

    def start_background(self):
        """Start in a daemon thread."""
        import threading
        self._running = True
        t = threading.Thread(target=self.run_forever, daemon=True)
        t.start()
        return t

    def stop(self):
        self._running = False

    # ─── Polling loop ──────────────────────────────────────────

    async def _poll(self):
        self._running = True
        offset = 0
        async with httpx.AsyncClient(timeout=30) as client:
            while self._running:
                try:
                    updates = await self._get_updates(client, offset)
                    for upd in updates:
                        offset = upd["update_id"] + 1
                        await self._handle_update(client, upd)
                except Exception as e:
                    print(f"[telegram] poll error: {e}", file=sys.stderr)
                await asyncio.sleep(2)

    async def _get_updates(self, client: httpx.AsyncClient, offset: int) -> list:
        r = await client.get(f"{self.base}/getUpdates",
                             params={"offset": offset, "timeout": 30})
        if r.status_code != 200:
            return []
        return r.json().get("result", [])

    # ─── Update dispatch ───────────────────────────────────────

    async def _handle_update(self, client: httpx.AsyncClient, upd: dict):
        msg = upd.get("message") or upd.get("channel_post")
        if not msg:
            return
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        text = (msg.get("text") or msg.get("caption") or "").strip()
        user = msg.get("from", {})

        if not chat_id or not text:
            return

        # Commands
        if text.startswith("/"):
            await self._handle_command(client, chat_id, text, user)
            return

        # Agent query
        await self._handle_message(client, chat_id, text, user)

    # ─── Commands ──────────────────────────────────────────────

    async def _handle_command(self, client: httpx.AsyncClient, chat_id: int, text: str, user: dict):
        cmd = text.split()[0].lower().lstrip("/").split("@")[0]

        if cmd == "reset":
            self.sessions.pop(chat_id, None)
            await self._send_message(client, chat_id, "Session reset.")

        elif cmd == "status":
            sess = self.sessions.get(chat_id)
            if sess:
                sid = sess["agent"].session_id
                await self._send_message(client, chat_id, f"Session active.\nID: `{sid}`")
            else:
                await self._send_message(client, chat_id, "No active session.")

        elif cmd == "start":
            username = user.get("first_name", "there")
            await self._send_message(client, chat_id,
                f"Hi {username}. I'm Reddy — a vertical intelligence agent.\n\n"
                "Send me a message and I'll research it.\n"
                "/reset — clear session\n"
                "/status — session info")

        else:
            # Unknown command → treat as agent query
            await self._handle_message(client, chat_id, text, user)

    # ─── Agent interaction ─────────────────────────────────────

    async def _handle_message(self, client: httpx.AsyncClient, chat_id: int, text: str, user: dict):
        # Get or create session
        if chat_id not in self.sessions:
            from redclaw.agent import create_agent
            agent = create_agent(session_id=f"tg_{chat_id}")
            self.sessions[chat_id] = {"agent": agent, "user": user.get("first_name", "")}

        agent = self.sessions[chat_id]["agent"]

        # Run agent in thread executor (agent.run_stream is synchronous)
        loop = asyncio.get_event_loop()

        def event_handler(event_type: str, data: dict):
            """Translate agent events → Telegram messages."""
            asyncio.run_coroutine_threadsafe(
                self._on_agent_event(client, chat_id, event_type, data), loop
            )

        try:
            await loop.run_in_executor(
                self._executor,
                lambda: agent.run_stream(text, on_event=event_handler),
            )
        except Exception as e:
            await self._send_message(client, chat_id, f"Error: {e}")

    async def _on_agent_event(self, client: httpx.AsyncClient, chat_id: int,
                               event_type: str, data: dict):
        """Handle one agent event — send appropriate Telegram response."""
        try:
            if event_type == "thinking":
                await self._send_chat_action(client, chat_id, "typing")

            elif event_type == "tool_call":
                name = data.get("name", "?")
                args = data.get("args", {})
                args_str = json.dumps(args, ensure_ascii=False)
                await self._send_message(client, chat_id,
                    f"▶ `{name}`\n`{args_str[:200]}`")

            elif event_type == "tool_result":
                name = data.get("name", "")
                result = data.get("result", "")
                preview = result[:300] + ("..." if len(result) > 300 else "")
                await self._send_message(client, chat_id, f"◀ *{name}*\n{preview}")

            elif event_type == "text_done":
                text = data.get("text", "")
                # Split long messages
                if len(text) <= TELEGRAM_LIMIT:
                    await self._send_message(client, chat_id, text)
                else:
                    parts = [text[i:i+TELEGRAM_LIMIT] for i in range(0, len(text), TELEGRAM_LIMIT)]
                    for p in parts:
                        await self._send_message(client, chat_id, p)

        except Exception as e:
            print(f"[telegram] event error: {e}", file=sys.stderr)

    # ─── Telegram API helpers ──────────────────────────────────

    async def _send_message(self, client: httpx.AsyncClient, chat_id: int, text: str):
        try:
            await client.post(f"{self.base}/sendMessage", json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            })
        except Exception:
            # Fallback: without Markdown parsing
            try:
                await client.post(f"{self.base}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": text,
                })
            except Exception as e:
                print(f"[telegram] send failed: {e}", file=sys.stderr)

    async def _send_chat_action(self, client: httpx.AsyncClient, chat_id: int, action: str):
        try:
            await client.post(f"{self.base}/sendChatAction", json={
                "chat_id": chat_id,
                "action": action,
            })
        except Exception:
            pass

# Reddy — Vertical Intelligence Agent

```
██████╗ ███████╗██████╗ ██████╗ ██╗   ██╗
██╔══██╗██╔════╝██╔══██╗██╔══██╗╚██╗ ██╔╝
██████╔╝█████╗  ██║  ██║██║  ██║ ╚████╔╝
██╔══██╗██╔══╝  ██║  ██║██║  ██║  ╚██╔╝
██║  ██║███████╗██████╔╝██████╔╝   ██║
╚═╝  ╚═╝╚══════╝╚═════╝ ╚═════╝    ╚═╝
```

XHS intelligence monitoring · Auto OCR · Hermes ReAct Agent

## Architecture

```
┌──────────────────────────────────────────────────┐
│              Reddy CLI (Node.js · zero deps)      │
│  animated logo · spinner · Hermes phase display   │
│  [Thinking]◆ → [Action]▶ → [Observe]◀ → [Answer]●│
└────────────────────┬─────────────────────────────┘
                     │ stdin/stdout JSON RPC
┌────────────────────┴─────────────────────────────┐
│            Python Backend (redclaw)               │
│  ┌─────────────────────────────────────────────┐ │
│  │        ToolRegistry (25 tools)              │ │
│  │  fetch_xhs  ocr_*  read_note  save_post   │ │
│  │  xhs_login  list_notes  search_posts  ...  │ │
│  └─────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────┐ │
│  │           SQLite (~/.reddy/reddy.db)        │ │
│  │       notes · radars · full-text search     │ │
│  └─────────────────────────────────────────────┘ │
└────────────────────┬─────────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
  MiniMax API   XHS Bridge    Umi-OCR
  (LLM)         (WebSocket)   (Paddle)
```

## Directory

```
reddy/
├── cli.js              # CLI entry (Node.js)
├── package.json
├── pyproject.toml
├── cli/src/
│   ├── agent-loop.js   # Python subprocess bridge + streaming
│   ├── config.js       # ~/.reddy/config.json
│   ├── logo.js         # ASCII art + Hermes phase labels + colors
│   ├── setup.js        # First-run config wizard
│   └── spinner.js      # Braille dot animated spinner
├── redclaw/
│   ├── agent.py        # AIAgent + ToolRegistry + SQLite + builtin tools
│   ├── stdio_cli.py    # JSON RPC server (stdin/stdout)
│   ├── memory.py
│   ├── gateway/
│   │   └── telegram.py       # Telegram long-polling gateway
│   ├── modules/
│   │   ├── xhs_tools.py            # fetch_xhs + xhs_login handlers
│   │   ├── xhs_search_and_save.py  # Legacy batch search
│   │   ├── ocr.py                  # Umi-OCR auto-start + API
│   │   ├── telegram_tools.py       # Gateway start/stop/status
│   │   ├── cron_tools.py           # Scheduled task scheduler
│   │   └── fetcher.py              # Platform fetcher factory
│   └── xhs/            # XHS browser bridge (CDP via Chrome extension)
│       ├── bridge.py           # BridgePage client (ws://localhost:9333)
│       ├── bridge_server.py   # WebSocket relay
│       ├── search.py          # Search feeds
│       ├── feed_detail.py     # Note detail + comments + anti-crawl
│       ├── login.py           # QR / phone / logout
│       ├── models.py          # Dataclasses
│       └── ...
└── 经验/               # Saved note JSON files (by session)
```

## Setup

```bash
cd reddy
pip install -e .          # Python deps
npm link                  # global "reddy" command
```

Then run anywhere:

```bash
reddy
```

First run launches the config wizard: provider → API key → model → OCR URL.

Config stored at `~/.reddy/config.json`.

## Usage

```
❯ help              Show commands
❯ show              Show current config
❯ config            Reconfigure
❯ exit              Quit

❯ /tools list       List all tools (25)
❯ /tools call       Call a tool directly <name> <json>
❯ /reset            Reset chat session
❯ /history          Show chat history
❯ /session          Show past sessions
❯ /export           Export chat to markdown
```

Natural language queries are routed to the LLM agent with automatic tool selection:

```
❯ Search XHS for "product manager" and summarize
❯ Login to XHS
❯ Read the note about AI PM career path
❯ Find all posts mentioning DeepSeek
❯ Generate a daily brief for my PM radar
```

## Tools

### XHS
| Tool | Description |
|------|-------------|
| `fetch_xhs` | Search XHS by keywords, auto OCR images, save to DB |
| `fetch_xhs_by_keyword` | Single keyword XHS search |
| `xhs_login` | Login/logout/status (QR scan or phone code) |
| `xhs_status` | Check bridge server + extension status |

### Data
| Tool | Description |
|------|-------------|
| `read_note` | Read full note by note_id |
| `list_notes` | Browse saved notes (by platform, paginated) |
| `search_posts` | Full-text search (SQLite LIKE — content + OCR text) |
| `save_post` | Save a post to DB |
| `read_file` | Read text file in reddy directories |
| `list_files` | List files in 经验 output directory |

### OCR
| Tool | Description |
|------|-------------|
| `ocr_image` | OCR local image file (Umi-OCR) |
| `ocr_url` | Download + OCR image URL |
| `ocr_batch` | Batch OCR from folder |
| `ocr_status` | Check Umi-OCR status |

### Gateway
| Tool | Description |
|------|-------------|
| `telegram_start` | Start Telegram bot gateway (long-polling) |
| `telegram_stop` | Stop Telegram gateway |
| `telegram_status` | Check gateway status + active chats |

### Cron
| Tool | Description |
|------|-------------|
| `schedule_task` | Schedule a recurring agent prompt |
| `list_tasks` | List all scheduled tasks |
| `delete_task` | Delete a scheduled task |
| `cron_status` | Check scheduler status |

### Radar
| Tool | Description |
|------|-------------|
| `create_radar` | Create monitoring radar |
| `get_radar` | Get radar config |
| `list_radars` | List all radars |
| `generate_brief` | Generate daily brief |

## XHS Login

Two login methods via the `xhs_login` tool:

**QR code scan:**
```
xhs_login action=qr        → get QR image
                         → scan with XHS app
xhs_login action=wait      → wait for completion
```

**Phone code:**
```
xhs_login action=send_code phone=138xxxx → receive SMS
xhs_login action=submit_code code=123456 → complete login
```

Other actions: `status` (check if logged in), `logout`.

## XHS Fetch Flow

```
1. Search → 2. Fetch every note detail → 3. Download images
      → 4. Auto OCR → 5. Save JSON + SQLite → 6. Return structured result
```

- OCR text merged into content for full-text search
- Anti-crawl: 2-4s delay between notes, QR verification backoff (15/30/60s)
- `max_notes: 0` = fetch all search results
- Bridge server + Chrome auto-started if needed

## Telegram Gateway

Long-polling bridge to Telegram Bot API. Supports multiple concurrent chats with per-chat agent sessions.

```bash
# Set bot token
set TELEGRAM_BOT_TOKEN=123456:ABC-DEF

# Then in reddy:
❯ Start the telegram gateway
```

**Features:**
- Each Telegram chat gets its own AIAgent session
- Agent events translated to Telegram messages (typing indicator, tool calls, results)
- Long responses auto-split at Telegram's 4096 char limit
- `/reset` — clear session, `/status` — session info, `/start` — welcome

## Scheduled Tasks (Cron)

Recurring agent prompts run on an interval. Tasks persist in SQLite and survive restarts.

```
❯ Schedule a task to search XHS for "AI PM" every 2 hours
❯ List my scheduled tasks
❯ Delete the daily summary task
```

- Interval-based scheduling (minutes)
- Results saved as cron posts in DB
- Background scheduler thread checks every 30s
- Auto-starts on first `schedule_task` call

## Dependencies

- **Node.js**: zero npm packages (built-in modules only)
- **Python**: `httpx`, `openai`, `websockets`, `requests`
- **External**: Umi-OCR (auto-discovered), XHS Bridge Chrome extension

## Acknowledgements

- [xiaohongshu-skills](https://github.com/autoclaw-cc/xiaohongshu-skills) — XHS browser automation core (`redclaw/xhs/`): CDP bridge, search, feed detail, login, anti-crawl
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — ReAct agent architecture: tool registry, tool use loop, structured thinking/action/observation cycle
- [Umi-OCR](https://github.com/hiroi-sora/Umi-OCR) — Offline OCR engine (PaddleOCR)

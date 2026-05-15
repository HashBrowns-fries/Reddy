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

Reddy 采用三层架构：**Node.js CLI（表现层）→ Python Agent（核心层）→ 外部服务（能力层）**。三层之间通过 stdin/stdout JSON RPC 实现松耦合通信。

### 整体数据流

```
用户输入（自然语言 / 斜杠命令）
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│              Reddy CLI (Node.js · 零依赖)                │
│                                                         │
│  cli.js ─► agent-loop.js                                │
│  ├─ 解析命令（/help /config /reset ...）                 │
│  ├─ spawn Python 子进程                                  │
│  ├─ 流式事件渲染:                                        │
│  │   [Thinking] ◆ → [Action] ▶ → [Observe] ◀ → [Answer] ●│
│  └─ Braille spinner + ANSI 颜色                         │
└────────────────────┬────────────────────────────────────┘
                     │ stdin/stdout JSON-RPC（每行一个 JSON）
                     │ cmd: init | run | list_tools | dispatch
                     │ stream: true → agent_event 推送
┌────────────────────┴────────────────────────────────────┐
│               Python Backend (redclaw)                   │
│                                                         │
│  stdio_cli.py  ←── JSON-RPC Server                      │
│       │                                                 │
│       ▼                                                 │
│  ┌─────────────────────────────────────────────────┐   │
│  │            AIAgent (Hermes ReAct)                │   │
│  │                                                 │   │
│  │  run() / run_stream()                           │   │
│  │    │                                            │   │
│  │    ├─ 1. 构建 System Prompt                      │   │
│  │    │     ├─ 工具列表（函数签名 + 描述）            │   │
│  │    │     └─ Memory 上下文（相关历史记忆）          │   │
│  │    │                                            │   │
│  │    ├─ 2. Prefetch Memory（向量检索相关记忆）      │   │
│  │    │                                            │   │
│  │    ├─ 3. ReAct Loop（最大 10 轮）                │   │
│  │    │     ┌──────────────────────────┐           │   │
│  │    │     │ Thinking  ── LLM 推理     │           │   │
│  │    │     │    ↓                     │           │   │
│  │    │     │ Action   ── 解析工具调用  │           │   │
│  │    │     │    ↓                     │           │   │
│  │    │     │ Observe  ── 执行工具     │           │   │
│  │    │     │    ↓                     │           │   │
│  │    │     │ 结果喂回 LLM → 下一轮     │           │   │
│  │    │     └──────────────────────────┘           │   │
│  │    │                                            │   │
│  │    ├─ 4. Memory Sync（写入新记忆）               │   │
│  │    │                                            │   │
│  │    └─ 5. 返回最终文本                             │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────┐  ┌────────────────────────┐  │
│  │   ToolRegistry (25)  │  │   MemoryManager         │  │
│  │                      │  │                         │  │
│  │  内置工具 (10):       │  │  MemoryProvider 接口:    │  │
│  │  ├─ Data: save_post  │  │  ├─ prefetch(query)     │  │
│  │  │  search_posts     │  │  ├─ sync(input,output)  │  │
│  │  │  read_note        │  │  ├─ build_prompt()      │  │
│  │  │  list_notes       │  │  └─ on_session_end()    │  │
│  │  ├─ Radar: create    │  │                         │  │
│  │  │  get/list/generate│  │  内置实现:               │  │
│  │  └─ IO: read_file    │  │  └─ BuiltinMemory       │  │
│  │     list_files       │  │    (~/.reddy/memory/)   │  │
│  │                      │  │                         │  │
│  │  模块工具 (15):       │  └────────────────────────┘  │
│  │  ├─ XHS: fetch/search│                              │
│  │  │  login/status     │  ┌────────────────────────┐  │
│  │  ├─ OCR: image/url   │  │  SQLite                 │  │
│  │  │  batch/status     │  │  (~/.reddy/reddy.db)    │  │
│  │  ├─ Telegram: start  │  │  ├─ posts              │  │
│  │  │  stop/status      │  │  ├─ radars             │  │
│  │  └─ Cron: schedule   │  │  └─ scheduled_tasks    │  │
│  │     list/delete/stat │  └────────────────────────┘  │
│  └──────────────────────┘                              │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┼──────────────┐
        ▼            ▼              ▼
   ┌─────────┐ ┌──────────┐ ┌──────────┐
   │ MiniMax │ │XHS Client│ │ Umi-OCR  │
   │   API   │ │API优先    │ │ (Paddle) │
   │         │ │ + httpx  │ │          │
   │Anthropic│ │xhshow签名│ │ 本地 OCR │
   │Messages │ │Playwright│ │ 引擎     │
   │兼容端点  │ │(登录)    │ │          │
   │         │ │CDP(回退) │ │          │
   │• Claude │ │          │ │          │
   │• M2.7   │ │          │ │          │
   └─────────┘ └──────────┘ └──────────┘
```

### Agent 核心：Hermes ReAct 循环

Reddy 的智能核心是 `AIAgent` 类（`redclaw/agent.py:509`），实现了标准的 **ReAct (Reasoning + Acting)** 范式：

#### 两种运行模式

| 模式 | 方法 | 工具调用方式 | 适用场景 |
|------|------|-------------|---------|
| **非流式** | `run()` | 正则解析文本中的 `action:` / `参数:` | DeepSeek 等不支持原生 tool_use 的模型 |
| **流式** | `run_stream()` | Anthropic 原生 `tools` 参数 + `tool_use` content block | MiniMax API（兼容 Claude tool_use） |

#### 流式事件系统

`run_stream()` 通过回调 `on_event(type, data)` 实时推送阶段事件：

```
session_start → thinking → tool_call → tool_result → ... → text_done
```

Node.js 前端接收 `agent_event` JSON 消息后渲染为：

```
[Thinking] ◆ 正在思考...
[Action]   ▶ fetch_xhs("AI产品经理")
[Observe]  ◀ 返回 20 条结果
[Answer]   ● 已为您找到以下内容...
```

#### 工具调用解析（非流式）

对于不支持原生 tool_use 的模型，使用正则从 LLM 文本输出中提取：

```
action: fetch_xhs
参数: {"keyword": "AI产品经理", "max_notes": 10}
```

工具执行结果以观察形式注入对话：

```
观察: {"success": true, "count": 10, "notes": [...]}

根据以上结果继续完成任务。
```

### 通信协议：JSON-RPC

Node.js CLI 和 Python Backend 之间通过 stdin/stdout 行分隔 JSON 通信：

```
→ {"cmd": "init", "id": 1}
← {"type": "rpc_result", "id": 1, "success": true, "tools": [...]}

→ {"cmd": "run", "params": {"message": "搜索AI PM"}, "stream": true, "id": 2}
← {"type": "agent_event", "id": 2, "event": {"type": "thinking", "turn": 1}}
← {"type": "agent_event", "id": 2, "event": {"type": "tool_call", "name": "fetch_xhs", ...}}
← {"type": "agent_event", "id": 2, "event": {"type": "text_done", "text": "..."}}
← {"type": "rpc_result", "id": 2, "success": true, "result": "..."}
```

**Python 端的关键设计**：`print()` 被重定向到 stderr（`sys.stdout = sys.stderr`），保证 stdout 只走 JSON-RPC 协议，模块内部日志不会污染通信通道。

### Memory 系统

`MemoryManager`（`redclaw/memory.py`）提供可扩展的记忆架构：

```
MemoryManager
  ├─ MemoryProvider (抽象接口)
  │   ├─ prefetch(query)     → 检索相关记忆
  │   ├─ sync(input, output) → 写入新记忆
  │   ├─ build_prompt()      → 生成注入 prompt 的记忆块
  │   └─ on_session_end()    → 会话结束持久化
  │
  └─ BuiltinMemoryProvider (~/.reddy/memory/)
      ├─ user.md      → 用户偏好 / 角色
      ├─ feedback.md  → 用户反馈 / 规则
      ├─ project.md   → 项目上下文
      └─ reference.md → 外部资源引用
```

每次对话流程中的记忆参与：
1. **Prefetch**：用户输入 → 检索相关记忆 → 注入 System Prompt
2. **Sync**：LLM 输出后 → 自动提取可记忆信息 → 写入文件
3. **Session End**：对话结束 → 持久化会话摘要

### LLM 后端

支持双后端，通过环境变量 `LLM_API` 切换：

| 后端 | 端点 | 协议 | 特点 |
|------|------|------|------|
| **MiniMax**（默认）| `api.minimaxi.com/anthropic/v1/messages` | Anthropic Messages API | 原生 `tools` 参数、`tool_use` content block |
| **DeepSeek** | `api.deepseek.com/v1` | OpenAI Chat Completions | 文本解析模式，正则提取工具调用 |

### XHS 数据获取架构 (v2 — API 优先)

参考 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) 的 **xhshow 纯算法签名** 方案，Reddy 的 XHS 数据获取从纯浏览器自动化升级为 **API 优先 + CDP 回退** 混合架构：

```
           ┌──────────────────────────┐
           │     XHSClient (门面)      │
           │                          │
           │  search_feeds()          │
           │  get_feed_detail()       │
           │  login_qrcode()          │
           └──────────┬───────────────┘
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
   ┌─────────────┐         ┌─────────────┐
   │ XHSApiClient │         │  CDP 回退    │
   │ (httpx)      │         │              │
   │              │         │ cdp.py       │
   │ sign.py      │         │ search.py    │
   │ xhshow 签名   │         │ feed_detail  │
   │              │         │ login.py     │
   │ X-S/X-T/     │         │              │
   │ X-S-Common   │         │ HTML 提取     │
   │              │         │ __INITIAL_   │
   │ REST API 调用 │         │ STATE__      │
   └──────┬───────┘         └──────┬───────┘
          │                        │
          │  有 Cookie → API 直达   │  Cookie 过期/失败 → CDP
          │                        │
    ┌─────┴─────┐            ┌─────┴─────┐
    │ 登录态来源  │            │ 浏览器管理  │
    │           │            │           │
    │ Playwright│            │ CDP       │
    │ browser.py│            │ Chrome    │
    │ login_pw  │            │ --remote- │
    │           │            │ debugging │
    │ persistent│            │ -port     │
    │ _context  │            │           │
    │ (持久化)   │            │           │
    └───────────┘            └───────────┘
```

**核心原理：**
- **签名**：使用 [xhshow](https://github.com/Cloxl/xhshow) 纯 Python 算法生成 X-S / X-T / X-S-Common 请求头，**无需浏览器执行 JS**
- **Cookie**：通过 Playwright 登录一次，Cookie（含 a1）自动持久化到 `browser_data/xhs/`，重启后保持登录态
- **API 优先**：有 Cookie 时直接 httpx + 算法签名调用小红书 REST API，速度远快于浏览器页面加载
- **CDP 回退**：API 触发验证码或 Cookie 过期时，自动回退到 Chrome CDP HTML 提取

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
│   │   └── telegram.py
│   ├── modules/
│   │   ├── xhs_tools.py            # fetch_xhs + xhs_login handlers
│   │   ├── xhs_search_and_save.py  # Legacy batch search
│   │   ├── ocr.py                  # Umi-OCR auto-start + API
│   │   ├── telegram_tools.py       # Gateway start/stop/status
│   │   ├── cron_tools.py           # Scheduled task scheduler
│   │   └── fetcher.py              # Platform fetcher factory
│   └── xhs/
│       ├── client.py         # XHSClient: API优先 + CDP回退 (v2)
│       ├── api.py            # XHSApiClient: httpx + xhshow签名
│       ├── sign.py           # xhshow 纯算法签名 (X-S/X-T/X-S-Common)
│       ├── api_adapters.py   # API JSON → models dataclass
│       ├── browser.py        # Playwright 持久化浏览器
│       ├── login_pw.py       # Playwright 登录 (QR/手机)
│       ├── login.py          # CDP 登录 (保留, 回退)
│       ├── cdp.py            # 原生 CDP WebSocket 客户端
│       ├── search.py         # CDP 搜索 (保留, 回退)
│       ├── feed_detail.py    # CDP 详情 + 评论加载 (保留, 回退)
│       ├── bridge.py         # [DEPRECATED] Chrome扩展桥接
│       ├── bridge_server.py  # [DEPRECATED] WebSocket中继
│       └── models.py         # Dataclasses
└── 经验/               # Saved note JSON files (by session)
```

## Setup

```bash
cd reddy
pip install -e .          # Python deps
playwright install chromium  # Browser for XHS login
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
- API-first: direct REST API calls with xhshow algorithm signatures

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
- **Python**: `xhshow`, `httpx`, `openai`, `playwright`, `websockets`, `requests`
- **External**: Umi-OCR (auto-discovered), Chromium (via `playwright install chromium`)

## Acknowledgements

- [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) — XHS API-first architecture reference: xhshow signature integration, Playwright login persistence, anti-crawl patterns
- [xhshow](https://github.com/Cloxl/xhshow) — Pure Python XHS signature algorithm (X-S / X-T / X-S-Common)
- [xiaohongshu-skills](https://github.com/autoclaw-cc/xiaohongshu-skills) — Original XHS CDP browser automation core: search, feed detail, login, anti-crawl
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — ReAct agent architecture: tool registry, tool use loop, structured thinking/action/observation cycle
- [Umi-OCR](https://github.com/hiroi-sora/Umi-OCR) — Offline OCR engine (PaddleOCR)

"""Redclaw Agent - 基于 Hermes Harness 架构的垂直情报Agent"""

import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any, Callable

import httpx

# ============== LLM 配置 ==============
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = "https://api.minimaxi.com/anthropic/v1/messages"
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your-key")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"

CURRENT_API = os.getenv("LLM_API", "minimax")


def get_model_name():
    if CURRENT_API == "minimax" and MINIMAX_API_KEY:
        return MINIMAX_MODEL
    return DEEPSEEK_MODEL

try:
    from openai import OpenAI
    _openai_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    HAS_LLM = True
except ImportError:
    _openai_client = None
    HAS_LLM = False


# ============== Tool Registry (Hermes风格) ==============

class ToolEntry:
    __slots__ = ("name", "toolset", "schema", "handler", "description", "emoji")
    def __init__(self, name, toolset, schema, handler, description="", emoji=""):
        self.name = name
        self.toolset = toolset
        self.schema = schema
        self.handler = handler
        self.description = description
        self.emoji = emoji


class ToolRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
            cls._instance._lock = __import__('threading').RLock()
        return cls._instance

    def register(self, name: str, toolset: str, schema: dict, handler: Callable,
                 description: str = "", emoji: str = ""):
        with self._lock:
            self._tools[name] = ToolEntry(name, toolset, schema, handler, description, emoji)

    def get(self, name: str) -> Optional[ToolEntry]:
        with self._lock:
            return self._tools.get(name)

    def get_all(self) -> List[ToolEntry]:
        with self._lock:
            return list(self._tools.values())

    def get_definitions(self) -> List[dict]:
        result = []
        for entry in self.get_all():
            result.append({
                "type": "function",
                "function": {
                    "name": entry.name,
                    "description": entry.description,
                    "parameters": entry.schema
                }
            })
        return result

    def dispatch(self, name: str, args: dict) -> str:
        entry = self.get(name)
        if not entry:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            result = entry.handler(args)
            if result is None:
                return json.dumps({"success": True})
            return json.dumps(result) if isinstance(result, dict) else str(result)
        except Exception as e:
            return json.dumps({"error": str(e)})


registry = ToolRegistry()


# ============== 数据层 (SQLite) ==============

def _get_db():
    db_path = Path.home() / ".reddy" / "reddy.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            radar_id TEXT DEFAULT 'default',
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            author TEXT DEFAULT '',
            platform TEXT DEFAULT '',
            url TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS radars (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            keywords TEXT DEFAULT '[]',
            platforms TEXT DEFAULT '[]',
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            prompt TEXT NOT NULL,
            interval_minutes INTEGER NOT NULL DEFAULT 60,
            enabled INTEGER DEFAULT 1,
            last_run REAL,
            next_run REAL,
            created_at REAL
        );
    """)
    conn.commit()
    return conn

_db = None
def _db_conn():
    global _db
    if _db is None:
        _db = _get_db()
    return _db


# ============== 内置工具 handlers ==============

def _save_post(args):
    db = _db_conn()
    post_id = args.get("id") or f"post_{datetime.now().timestamp()}"
    title = args.get("title", "")
    content = args.get("content", "")
    radar_id = args.get("radar_id", "default")
    author = args.get("author", "")
    platform = args.get("platform", "")
    url = args.get("url", "")
    tags = json.dumps(args.get("tags", []), ensure_ascii=False)
    now = datetime.now().timestamp()

    db.execute(
        "INSERT OR REPLACE INTO posts (id, radar_id, title, content, author, platform, url, tags, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (post_id, radar_id, title, content, author, platform, url, tags, now),
    )
    db.commit()
    return {"success": True, "id": post_id}


def _search_posts(args):
    db = _db_conn()
    query = args.get("query", "")
    radar_id = args.get("radar_id")
    limit = args.get("limit", 10)

    if not query:
        return {"error": "未提供搜索关键词"}

    like = f"%{query}%"
    if radar_id:
        rows = db.execute(
            "SELECT * FROM posts WHERE (title LIKE ? OR content LIKE ? OR author LIKE ? OR tags LIKE ?) AND radar_id=? ORDER BY created_at DESC LIMIT ?",
            (like, like, like, like, radar_id, limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM posts WHERE title LIKE ? OR content LIKE ? OR author LIKE ? OR tags LIKE ? ORDER BY created_at DESC LIMIT ?",
            (like, like, like, like, limit),
        ).fetchall()

    results = []
    for r in rows:
        results.append({
            "id": r["id"], "title": r["title"],
            "content": r["content"][:200],
            "author": r["author"], "platform": r["platform"],
            "radar_id": r["radar_id"],
        })
    return {"results": results, "count": len(results), "query": query}


def _create_radar(args):
    db = _db_conn()
    radar_id = args.get("radar_id") or f"radar_{int(datetime.now().timestamp())}"
    name = args.get("name", "")
    keywords = json.dumps(args.get("keywords", []), ensure_ascii=False)
    platforms = json.dumps(args.get("platforms", []), ensure_ascii=False)
    now = datetime.now().timestamp()

    db.execute(
        "INSERT OR REPLACE INTO radars (id, name, keywords, platforms, created_at) VALUES (?,?,?,?,?)",
        (radar_id, name, keywords, platforms, now),
    )
    db.commit()
    return {"success": True, "id": radar_id, "name": name}


def _get_radar(args):
    db = _db_conn()
    radar_id = args.get("radar_id", "default")
    row = db.execute("SELECT * FROM radars WHERE id=?", (radar_id,)).fetchone()
    if not row:
        return {"error": f"雷达不存在: {radar_id}"}
    return {
        "id": row["id"], "name": row["name"],
        "keywords": json.loads(row["keywords"]),
        "platforms": json.loads(row["platforms"]),
    }


def _list_radars(args):
    db = _db_conn()
    rows = db.execute("SELECT id, name, keywords, created_at FROM radars ORDER BY created_at DESC").fetchall()
    radars = []
    for r in rows:
        post_count = db.execute("SELECT COUNT(*) FROM posts WHERE radar_id=?", (r["id"],)).fetchone()[0]
        radars.append({"id": r["id"], "name": r["name"], "keywords": json.loads(r["keywords"]), "post_count": post_count})
    return {"radars": radars, "count": len(radars)}


def _generate_brief(args):
    db = _db_conn()
    radar_id = args.get("radar_id", "default")
    date_str = args.get("date", datetime.now().strftime("%Y-%m-%d"))

    radar = db.execute("SELECT * FROM radars WHERE id=?", (radar_id,)).fetchone()
    radar_name = radar["name"] if radar else radar_id

    rows = db.execute(
        "SELECT title, content, author, platform FROM posts WHERE radar_id=? ORDER BY created_at DESC LIMIT 20",
        (radar_id,),
    ).fetchall()

    if not rows:
        return {"success": True, "brief": f"# {radar_name} 日报 ({date_str})\n\n暂无内容", "post_count": 0}

    md = [f"# {radar_name} 日报 ({date_str})\n"]
    for i, r in enumerate(rows, 1):
        md.append(f"## {i}. {r['title']}")
        md.append(f"- 作者: {r['author'] or '未知'}  平台: {r['platform'] or '未知'}")
        md.append(f"- {r['content'][:150]}...")
        md.append("")
    return {"success": True, "brief": "\n".join(md), "post_count": len(rows)}


def _read_note(args):
    """Read full note content from SQLite."""
    db = _db_conn()
    note_id = args.get("note_id", "")
    if not note_id:
        return {"error": "note_id required"}

    row = db.execute("SELECT * FROM posts WHERE id=?", (note_id,)).fetchone()
    if not row:
        row = db.execute("SELECT * FROM posts WHERE id LIKE ?", (f"{note_id}%",)).fetchone()
    if not row:
        return {"error": f"note not found: {note_id}"}

    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "author": row["author"],
        "platform": row["platform"],
        "url": row["url"],
        "tags": json.loads(row["tags"]) if row["tags"] else [],
        "created_at": row["created_at"],
    }


def _list_notes(args):
    """List saved notes, newest first."""
    db = _db_conn()
    limit = args.get("limit", 20)
    platform = args.get("platform")
    offset = args.get("offset", 0)

    if platform:
        rows = db.execute(
            "SELECT id, title, author, content, platform, url, created_at FROM posts WHERE platform=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (platform, limit, offset),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, title, author, content, platform, url, created_at FROM posts ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "title": r["title"],
            "author": r["author"] or "",
            "platform": r["platform"] or "",
            "summary": (r["content"] or "")[:120],
            "url": r["url"] or "",
        })
    return {"notes": results, "count": len(results), "offset": offset}


def _read_file(args):
    """Read any text file from allowed paths."""
    file_path = args.get("path", "")
    max_chars = args.get("max_chars", 5000)

    if not file_path:
        return {"error": "path required"}

    from pathlib import Path
    p = Path(file_path).expanduser().resolve()

    # Allow: reddy project, .reddy home dir, 经验 dir
    allowed = [
        Path(__file__).parent.parent,          # reddy project root
        Path.home() / ".reddy",                 # config & db
        Path(__file__).parent.parent.parent / "经验",  # notes output
    ]
    if not any(p == a or str(p).startswith(str(a) + os.sep) for a in allowed):
        return {"error": f"path not allowed: {p}"}

    if not p.exists():
        return {"error": f"file not found: {p}"}

    try:
        text = p.read_text(encoding="utf-8")[:max_chars]
        return {"path": str(p), "content": text, "size": len(text), "truncated": len(text) >= max_chars}
    except Exception as e:
        return {"error": f"read failed: {e}"}


def _list_files(args):
    """List files in a directory."""
    dir_path = args.get("path", "")
    glob = args.get("glob", "*")

    from pathlib import Path
    base = Path(__file__).parent.parent.parent / "经验"
    p = base / dir_path if dir_path else base

    if not p.exists():
        return {"error": f"directory not found: {p}"}

    try:
        files = sorted(p.rglob(glob), key=lambda f: f.stat().st_mtime, reverse=True)[:50]
        result = []
        for f in files:
            if f.is_file():
                result.append({
                    "name": f.name,
                    "path": str(f),
                    "size": f.stat().st_size,
                })
        return {"files": result, "count": len(result), "base": str(p)}
    except Exception as e:
        return {"error": str(e)}


# ============== 注册内置工具 ==============

def _register_builtin_tools():
    registry.register(
        name="save_post", toolset="data",
        schema={"type": "object", "properties": {
            "id": {"type": "string", "description": "帖子ID（可选，自动生成）"},
            "radar_id": {"type": "string", "description": "关联雷达ID"},
            "title": {"type": "string", "description": "标题"},
            "content": {"type": "string", "description": "正文内容"},
            "author": {"type": "string", "description": "作者"},
            "platform": {"type": "string", "description": "来源平台"},
            "url": {"type": "string", "description": "原文链接"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签"},
        }, "required": ["title", "content"]},
        handler=_save_post,
        description="保存帖子到本地数据库", emoji="💾",
    )
    registry.register(
        name="search_posts", toolset="data",
        schema={"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词（支持全文检索）"},
            "radar_id": {"type": "string", "description": "限定雷达范围"},
            "limit": {"type": "integer", "default": 10, "description": "返回条数"},
        }, "required": ["query"]},
        handler=_search_posts,
        description="全文搜索已保存的帖子", emoji="🔍",
    )
    registry.register(
        name="create_radar", toolset="radar",
        schema={"type": "object", "properties": {
            "radar_id": {"type": "string", "description": "雷达ID（可选）"},
            "name": {"type": "string", "description": "雷达名称"},
            "keywords": {"type": "array", "items": {"type": "string"}, "description": "监控关键词"},
            "platforms": {"type": "array", "items": {"type": "string"}, "description": "监控平台"},
        }, "required": ["name"]},
        handler=_create_radar,
        description="创建情报雷达", emoji="🆕",
    )
    registry.register(
        name="get_radar", toolset="radar",
        schema={"type": "object", "properties": {"radar_id": {"type": "string"}}, "required": ["radar_id"]},
        handler=_get_radar,
        description="获取雷达配置", emoji="📡",
    )
    registry.register(
        name="list_radars", toolset="radar",
        schema={"type": "object", "properties": {}},
        handler=_list_radars,
        description="列出所有雷达", emoji="📋",
    )
    registry.register(
        name="read_note", toolset="data",
        schema={"type": "object", "properties": {
            "note_id": {"type": "string", "description": "笔记ID (noteId)"},
        }, "required": ["note_id"]},
        handler=_read_note,
        description="读取笔记完整内容", emoji="📖",
    )
    registry.register(
        name="list_notes", toolset="data",
        schema={"type": "object", "properties": {
            "limit": {"type": "integer", "default": 20, "description": "返回条数"},
            "platform": {"type": "string", "description": "按平台过滤 (e.g. xiaohongshu)"},
            "offset": {"type": "integer", "default": 0, "description": "偏移量"},
        }},
        handler=_list_notes,
        description="列出已保存的笔记", emoji="📋",
    )
    registry.register(
        name="read_file", toolset="io",
        schema={"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "max_chars": {"type": "integer", "default": 5000, "description": "最大返回字符数"},
        }, "required": ["path"]},
        handler=_read_file,
        description="读取文本文件内容（限 reddy 目录内）", emoji="📄",
    )
    registry.register(
        name="list_files", toolset="io",
        schema={"type": "object", "properties": {
            "path": {"type": "string", "description": "目录路径（相对经验目录）"},
            "glob": {"type": "string", "default": "*", "description": "文件名匹配 (e.g. *.json)"},
        }},
        handler=_list_files,
        description="列出经验目录中的文件", emoji="📂",
    )
    registry.register(
        name="generate_brief", toolset="report",
        schema={"type": "object", "properties": {
            "radar_id": {"type": "string", "description": "雷达ID"},
            "date": {"type": "string", "description": "日期 (YYYY-MM-DD)"},
        }, "required": ["radar_id"]},
        handler=_generate_brief,
        description="为雷达生成日报摘要", emoji="📊",
    )


# ============== 注册所有工具 ==============

_register_builtin_tools()

from redclaw.modules.xhs_tools import register_xhs_tools
register_xhs_tools(registry)

from redclaw.modules.ocr import register_ocr_tools
register_ocr_tools(registry)

from redclaw.modules.telegram_tools import register_telegram_tools
register_telegram_tools(registry)

from redclaw.modules.cron_tools import register_cron_tools
register_cron_tools(registry)


# ============== Memory System ==============
from redclaw.memory import MemoryProvider, BuiltinMemoryProvider, MemoryManager


def get_memory_dir():
    memory_dir = Path.home() / ".reddy" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir


# ============== AIAgent Harness (ReAct模式 + Memory) ==============

class AIAgent:
    def __init__(self, system_prompt: str = None, session_id: str = None):
        self.model = get_model_name()
        self.session_id = session_id or datetime.now().strftime("%Y%m%d%H%M%S")
        self.tools = registry.get_definitions()
        self.messages = []

        memory_dir = get_memory_dir()
        self.memory_manager = MemoryManager(memory_dir)
        self.memory_manager.initialize_all(self.session_id)

        memory_tools = self.memory_manager.get_all_tool_schemas()
        self.all_tools = self.tools + memory_tools

        if system_prompt:
            self.system = system_prompt
        else:
            self.system = """你是一个垂直情报Agent助手，代号Reddy。
你可以使用工具完成任务。

可用工具：
{tools}

{memory_block}

用中文回答，保持简洁有条理。
如果需要调用工具，请直接使用工具调用。"""

    def _format_tools(self) -> str:
        lines = []
        for tool in self.all_tools:
            func = tool["function"]
            lines.append(f"- {func['name']}: {func['description']}")
        return "\n".join(lines)

    def _build_system_prompt(self) -> str:
        tool_list = self._format_tools()
        memory_block = self.memory_manager.build_system_prompt()
        return self.system.format(tools=tool_list, memory_block=memory_block)

    def _prefetch_memory(self, query: str) -> str:
        return self.memory_manager.prefetch_all(query, session_id=self.session_id)

    def run(self, user_input: str) -> str:
        if not HAS_LLM:
            return "LLM未配置，请设置 MINIMAX_API_KEY 或 DEEPSEEK_API_KEY"

        memory_context = self._prefetch_memory(user_input)
        system_prompt = self._build_system_prompt()
        if memory_context:
            system_prompt = system_prompt + "\n\n" + memory_context

        if CURRENT_API == "minimax":
            self.messages = [{"role": "user", "content": user_input}]
            self._system = system_prompt
        else:
            self.messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ]

        max_turns = 10
        for turn in range(max_turns):
            content = self._call_llm()
            if content is None:
                return "Error: LLM returned no content"

            tool_name, tool_args = self._parse_tool_call(content)

            if tool_name:
                result_str = self._dispatch_tool(tool_name, tool_args)
                self.messages.append({"role": "assistant", "content": content})
                self.messages.append({
                    "role": "user",
                    "content": f"观察: {result_str}\n\n根据以上结果继续完成任务。"
                })
                self.memory_manager.sync_all(user_input, content, session_id=self.session_id)
            else:
                self.memory_manager.sync_all(user_input, content, session_id=self.session_id)
                return content

        return "达到最大轮次限制"

    def _call_llm(self) -> str:
        if CURRENT_API == "minimax" and MINIMAX_API_KEY:
            return self._call_anthropic()
        else:
            return self._call_openai()

    def _call_anthropic(self) -> str:
        payload = {
            "model": MINIMAX_MODEL,
            "messages": self.messages,
            "system": getattr(self, '_system', ''),
            "max_tokens": 1500,
            "temperature": 0.7,
        }
        headers = {
            "X-Api-Key": MINIMAX_API_KEY,
            "Content-Type": "application/json",
        }
        resp = httpx.post(MINIMAX_BASE_URL, json=payload, headers=headers, timeout=120)
        if resp.status_code != 200:
            raise Exception(f"API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        for block in data.get("content", []):
            if block.get("type") == "text":
                return block["text"]
        return ""

    def _call_openai(self) -> str:
        response = _openai_client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            temperature=0.7,
            max_tokens=1500
        )
        return response.choices[0].message.content or ""

    def _parse_tool_call(self, text: str) -> tuple:
        import re
        action_match = re.search(r'行动:\s*(\w+)', text)
        if not action_match:
            action_match = re.search(r'action:\s*(\w+)', text)
        if not action_match:
            return None, {}

        tool_name = action_match.group(1)
        param_match = re.search(r'参数:\s*(\{[\s\S]*?\})', text)
        if param_match:
            try:
                return tool_name, json.loads(param_match.group(1))
            except json.JSONDecodeError:
                pass
        return tool_name, {}

    # ============== Hermes-style streaming ==============

    def run_stream(self, user_input: str, on_event=None) -> str:
        if not on_event:
            on_event = lambda t, d: None

        if not HAS_LLM:
            return "LLM未配置"

        on_event("session_start", {"session_id": self.session_id, "model": self.model})

        memory_context = self._prefetch_memory(user_input)
        system_prompt = self._build_system_prompt()
        if memory_context:
            system_prompt += "\n\n" + memory_context

        self.messages = [{"role": "user", "content": user_input}]
        self._system = system_prompt

        max_turns = 10
        for turn in range(max_turns):
            on_event("thinking", {"turn": turn + 1})
            response = self._call_anthropic_with_tools()

            tool_calls = [b for b in response.get("content", []) if b.get("type") == "tool_use"]

            if tool_calls:
                self.messages.append({"role": "assistant", "content": response["content"]})
                tool_results = []
                for tc in tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc.get("input", {})
                    tool_id = tc.get("id", f"tool_{turn}")

                    on_event("tool_call", {"name": tool_name, "args": tool_args})
                    result_str = self._dispatch_tool(tool_name, tool_args)
                    on_event("tool_result", {"name": tool_name, "result": result_str})

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_str
                    })

                self.messages.append({"role": "user", "content": tool_results})
                continue

            full_text = ""
            for b in response.get("content", []):
                if b.get("type") == "text":
                    full_text += b.get("text", "")

            tool_name, tool_args = self._parse_tool_call(full_text)
            if tool_name:
                on_event("tool_call", {"name": tool_name, "args": tool_args})
                result_str = self._dispatch_tool(tool_name, tool_args)
                on_event("tool_result", {"name": tool_name, "result": result_str})
                self.messages.append({"role": "assistant", "content": full_text})
                self.messages.append({"role": "user", "content": f"观察: {result_str}\n\n根据以上结果继续完成任务。"})
                continue

            self.memory_manager.sync_all(user_input, full_text, session_id=self.session_id)
            on_event("text_done", {"text": full_text})
            return full_text

        return "达到最大轮次限制"

    def _call_anthropic_with_tools(self) -> dict:
        anthropic_tools = []
        for t in self.all_tools:
            func = t.get("function", {})
            anthropic_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}})
            })

        payload = {
            "model": MINIMAX_MODEL,
            "messages": self.messages,
            "system": getattr(self, '_system', ''),
            "max_tokens": 2000,
            "temperature": 0.7,
        }
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        headers = {
            "X-Api-Key": MINIMAX_API_KEY,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        resp = httpx.post(MINIMAX_BASE_URL, json=payload, headers=headers, timeout=120)
        if resp.status_code != 200:
            raise Exception(f"API error {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _dispatch_tool(self, tool_name: str, tool_args: dict) -> str:
        if self.memory_manager._tool_to_provider.get(tool_name):
            return self.memory_manager.handle_tool_call(tool_name, tool_args)
        return registry.dispatch(tool_name, tool_args)

    def end_session(self) -> None:
        self.memory_manager.on_session_end(self.messages)
        self.memory_manager.shutdown_all()


def create_agent(system_prompt: str = None, session_id: str = None) -> AIAgent:
    return AIAgent(system_prompt, session_id)


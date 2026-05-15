"""Reddy Memory System - 基于 Hermes Memory 架构"""

import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Memory Provider Abstract Base
# ---------------------------------------------------------------------------

class MemoryProvider(ABC):
    """Memory provider abstract base class - Hermes 风格"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'builtin', 'session')"""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if provider is ready"""

    @abstractmethod
    def initialize(self, session_id: str, **kwargs) -> None:
        """Initialize for a session"""

    def system_prompt_block(self) -> str:
        """Return text for system prompt"""
        return ""

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Recall relevant context before each turn"""
        return ""

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Persist a completed turn"""
        pass

    @abstractmethod
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return tool schemas this provider exposes"""
        return []

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        """Handle a tool call"""
        return json.dumps({"error": f"Provider {self.name} does not handle {tool_name}"})

    def shutdown(self) -> None:
        """Clean shutdown"""

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Called when session ends"""

    def on_session_switch(self, new_session_id: str, *, parent_session_id: str = "", reset: bool = False, **kwargs) -> None:
        """Called when session_id changes"""


# ---------------------------------------------------------------------------
# Builtin Memory Provider (Session + Long-term)
# ---------------------------------------------------------------------------

class BuiltinMemoryProvider(MemoryProvider):
    """Reddy 内置记忆provider - 基于文件存储"""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._session_id = ""
        self._session_file = None
        self._memory_file = memory_dir / "memory.json"
        self._session_turns = 0
        self._load_memory()

    @property
    def name(self) -> str:
        return "builtin"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id
        self._session_file = self.memory_dir / f"session_{session_id}.json"
        self._session_turns = 0
        # Load existing session if any
        if self._session_file.exists():
            try:
                data = json.loads(self._session_file.read_text())
                self._session_turns = len([m for m in data.get("messages", []) if m.get("role") == "user"])
            except:
                pass

    def _load_memory(self) -> None:
        """Load long-term memory"""
        if self._memory_file.exists():
            try:
                self._memory = json.loads(self._memory_file.read_text())
            except:
                self._memory = {"facts": [], "preferences": {}, "sessions": []}
        else:
            self._memory = {"facts": [], "preferences": {}, "sessions": []}

    def _save_memory(self) -> None:
        """Save long-term memory"""
        self._memory_file.write_text(json.dumps(self._memory, ensure_ascii=False, indent=2))

    def system_prompt_block(self) -> str:
        """返回记忆系统说明"""
        return """<memory-system>
你有一个持久记忆系统，可以记住重要的事实和偏好。

可用工具:
- memory_add: 添加重要信息到记忆
- memory_search: 搜索相关记忆
- memory_list: 列出所有记忆

重要信息会被持久保存，在你每次对话时可供检索。
</memory-system>"""

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Prefetch relevant memories"""
        if not query or not self._memory.get("facts"):
            return ""

        query_lower = query.lower()
        relevant = []

        for fact in self._memory.get("facts", []):
            fact_text = fact.get("content", "").lower()
            # Simple keyword matching
            if any(kw in query_lower or kw in fact_text for kw in query_lower.split()[:5]):
                relevant.append(fact.get("content", ""))

        if relevant:
            return "<memory-context>\n[相关记忆]:\n" + "\n".join(f"• {r}" for r in relevant[-5:]) + "\n</memory-context>"
        return ""

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Save turn to session history"""
        self._session_turns += 1

        session_data = {
            "session_id": session_id or self._session_id,
            "turns": self._session_turns,
            "messages": []
        }

        # Load existing session data
        if self._session_file and self._session_file.exists():
            try:
                session_data = json.loads(self._session_file.read_text())
            except:
                pass

        # Add new message
        timestamp = datetime.now().isoformat()
        session_data["messages"].append({
            "role": "user",
            "content": user_content,
            "timestamp": timestamp
        })
        session_data["messages"].append({
            "role": "assistant",
            "content": assistant_content,
            "timestamp": timestamp
        })
        session_data["last_update"] = timestamp

        # Save session
        if self._session_file:
            self._session_file.write_text(json.dumps(session_data, ensure_ascii=False, indent=2))

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return memory tool schemas"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "memory_add",
                    "description": "添加重要信息到持久记忆",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "要记忆的内容"},
                            "category": {"type": "string", "description": "分类: fact/preference/info", "default": "fact"}
                        },
                        "required": ["content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_search",
                    "description": "搜索相关记忆",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "搜索关键词"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_list",
                    "description": "列出所有记忆",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            }
        ]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        """Handle memory tool calls"""
        if tool_name == "memory_add":
            category = args.get("category", "fact")
            content = args.get("content", "")

            if not content:
                return json.dumps({"success": False, "error": "content is required"})

            self._memory.setdefault("facts", []).append({
                "content": content,
                "category": category,
                "created_at": datetime.now().isoformat(),
                "session_id": self._session_id
            })
            self._save_memory()

            return json.dumps({"success": True, "message": f"已添加记忆: {content[:50]}..."})

        elif tool_name == "memory_search":
            query = args.get("query", "").lower()
            if not query:
                return json.dumps({"success": False, "error": "query is required"})

            results = []
            for fact in self._memory.get("facts", []):
                if query in fact.get("content", "").lower():
                    results.append(fact)

            return json.dumps({
                "success": True,
                "results": results[-10:],
                "count": len(results)
            })

        elif tool_name == "memory_list":
            facts = self._memory.get("facts", [])
            return json.dumps({
                "success": True,
                "facts": facts[-20:],
                "count": len(facts)
            })

        return json.dumps({"success": False, "error": f"Unknown tool: {tool_name}"})

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """End of session - could extract key info"""
        if not messages:
            return

        # Extract potential key info from last few exchanges
        recent = messages[-6:]  # Last 3 exchanges
        summary_parts = []

        for msg in recent:
            content = msg.get("content", "")
            if len(content) > 100:
                summary_parts.append(content[:100] + "...")

        if summary_parts:
            self._memory.setdefault("sessions", []).append({
                "session_id": self._session_id,
                "summary": summary_parts,
                "ended_at": datetime.now().isoformat()
            })
            self._save_memory()

    def shutdown(self) -> None:
        """Cleanup"""
        pass


# ---------------------------------------------------------------------------
# Memory Manager
# ---------------------------------------------------------------------------

class MemoryManager:
    """Orchestrates memory providers - Hermes 风格"""

    def __init__(self, memory_dir: Path):
        self._providers: List[MemoryProvider] = []
        self._tool_to_provider: Dict[str, MemoryProvider] = {}
        self._memory_dir = memory_dir

        # Add built-in provider
        builtin = BuiltinMemoryProvider(memory_dir)
        self.add_provider(builtin)

    def add_provider(self, provider: MemoryProvider) -> None:
        """Register a memory provider"""
        self._providers.append(provider)

        for schema in provider.get_tool_schemas():
            tool_name = schema.get("function", {}).get("name", "")
            if tool_name and tool_name not in self._tool_to_provider:
                self._tool_to_provider[tool_name] = provider

        logger.info(f"Memory provider '{provider.name}' registered")

    def initialize_all(self, session_id: str, **kwargs) -> None:
        """Initialize all providers for session"""
        for provider in self._providers:
            try:
                provider.initialize(session_id, **kwargs)
            except Exception as e:
                logger.warning(f"Provider {provider.name} init failed: {e}")

    def build_system_prompt(self) -> str:
        """Collect system prompt blocks from all providers"""
        parts = []
        for provider in self._providers:
            try:
                block = provider.system_prompt_block()
                if block and block.strip():
                    parts.append(block)
            except Exception as e:
                logger.debug(f"Provider {provider.name} system_prompt_block failed: {e}")
        return "\n\n".join(parts)

    def prefetch_all(self, query: str, *, session_id: str = "") -> str:
        """Collect prefetch context from all providers"""
        parts = []
        for provider in self._providers:
            try:
                result = provider.prefetch(query, session_id=session_id)
                if result and result.strip():
                    parts.append(result)
            except Exception as e:
                logger.debug(f"Provider {provider.name} prefetch failed: {e}")
        return "\n\n".join(parts)

    def sync_all(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Sync turn to all providers"""
        for provider in self._providers:
            try:
                provider.sync_turn(user_content, assistant_content, session_id=session_id)
            except Exception as e:
                logger.warning(f"Provider {provider.name} sync_turn failed: {e}")

    def get_all_tool_schemas(self) -> List[Dict[str, Any]]:
        """Collect tool schemas from all providers"""
        schemas = []
        seen = set()
        for provider in self._providers:
            try:
                for schema in provider.get_tool_schemas():
                    name = schema.get("function", {}).get("name", "")
                    if name and name not in seen:
                        schemas.append(schema)
                        seen.add(name)
            except Exception as e:
                logger.warning(f"Provider {provider.name} get_tool_schemas failed: {e}")
        return schemas

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        """Route tool call to correct provider"""
        provider = self._tool_to_provider.get(tool_name)
        if not provider:
            return json.dumps({"error": f"No memory provider handles {tool_name}"})
        try:
            return provider.handle_tool_call(tool_name, args, **kwargs)
        except Exception as e:
            logger.error(f"Provider {provider.name} handle_tool_call failed: {e}")
            return json.dumps({"error": f"Memory tool '{tool_name}' failed: {e}"})

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Notify all providers of session end"""
        for provider in self._providers:
            try:
                provider.on_session_end(messages)
            except Exception as e:
                logger.debug(f"Provider {provider.name} on_session_end failed: {e}")

    def shutdown_all(self) -> None:
        """Shutdown all providers"""
        for provider in reversed(self._providers):
            try:
                provider.shutdown()
            except Exception as e:
                logger.warning(f"Provider {provider.name} shutdown failed: {e}")
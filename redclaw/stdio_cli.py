#!/usr/bin/env python3
"""
Reddy Python Backend - Hermes 架构 stdio 通信层
支持流式事件: agent_event (thinking/tool_call/tool_result/text_done)
"""

import sys
import json
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Reserve the real stdout for JSON RPC only.
# Redirect Python's default print() to stderr so modules like
# xhs_search_and_save can print progress without corrupting the protocol.
_rpc_out = sys.stdout
sys.stdout = sys.stderr

from redclaw.agent import (
    registry,
    create_agent as create_redclaw_agent,
    HAS_LLM,
)


def emit(payload):
    """Write JSON line to the RPC channel (original stdout)."""
    _rpc_out.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _rpc_out.flush()


def emit_event(request_id, event_type, data):
    """Emit an agent_event during streaming run"""
    emit({"type": "agent_event", "id": request_id, "event": {"type": event_type, **data}})


def emit_rpc(request_id, response):
    """Emit final rpc_result"""
    response["id"] = request_id
    emit(response)


def cmd_init():
    tools = registry.get_definitions()
    return {"success": True, "has_llm": HAS_LLM, "tools": tools}


def cmd_list_tools():
    tools = registry.get_definitions()
    return {
        "success": True,
        "tools": [
            {"name": t["function"]["name"], "description": t["function"]["description"]}
            for t in tools
        ],
    }


def cmd_dispatch(name, args):
    result = registry.dispatch(name, args)
    try:
        return {"success": True, "result": json.loads(result)}
    except Exception:
        return {"success": True, "result": result}


def cmd_run(message, request_id, session_id=None):
    """Non-streaming run (legacy)"""
    if not HAS_LLM:
        return {"success": False, "error": "LLM not configured"}
    try:
        agent = create_redclaw_agent(session_id=session_id)
        result = agent.run(message)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cmd_run_stream(message, request_id, session_id=None):
    """Streaming run with agent_event emissions"""
    if not HAS_LLM:
        emit_event(request_id, "error", {"message": "LLM not configured"})
        emit_rpc(request_id, {"success": False, "error": "LLM not configured"})
        return

    try:
        agent = create_redclaw_agent(session_id=session_id)

        def on_event(event_type, data):
            emit_event(request_id, event_type, data)

        result = agent.run_stream(message, on_event)
        emit_rpc(request_id, {"success": True, "result": result})
    except Exception as e:
        emit_event(request_id, "error", {"message": str(e)})
        emit_rpc(request_id, {"success": False, "error": str(e)})


def main():
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            request = json.loads(line.strip())
            cmd = request.get("cmd")
            params = request.get("params", {})
            request_id = request.get("id")
            stream = request.get("stream", False)

            if cmd == "init":
                response = cmd_init()
                response["id"] = request_id
                emit(response)

            elif cmd == "run":
                if stream:
                    cmd_run_stream(
                        params.get("message", ""),
                        request_id,
                        session_id=params.get("session_id"),
                    )
                else:
                    response = cmd_run(
                        params.get("message", ""),
                        request_id,
                        session_id=params.get("session_id"),
                    )
                    response["id"] = request_id
                    emit(response)

            elif cmd == "list_tools":
                response = cmd_list_tools()
                response["id"] = request_id
                emit(response)

            elif cmd == "dispatch":
                response = cmd_dispatch(params.get("name", ""), params.get("args", {}))
                response["id"] = request_id
                emit(response)

            else:
                emit({"id": request_id, "success": False, "error": f"Unknown: {cmd}"})

        except json.JSONDecodeError as e:
            emit({"success": False, "error": f"JSON parse error: {e}"})
        except Exception as e:
            emit({"success": False, "error": str(e)})


if __name__ == "__main__":
    main()

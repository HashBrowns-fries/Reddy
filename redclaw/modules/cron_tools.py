"""Scheduled Tasks (Cron) — background scheduler for recurring agent prompts.

Supports interval-based scheduling. Tasks persist in SQLite across restarts.
"""

import json
import sys
import time
import threading
from datetime import datetime
from pathlib import Path


class Scheduler:
    """Background scheduler that runs agent prompts on a timer."""

    def __init__(self):
        self._running = False
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()
        self._running = True
        self._thread = t

    def stop(self):
        self._running = False

    @property
    def running(self):
        return self._running

    def _loop(self):
        while self._running:
            try:
                self._tick()
            except Exception as e:
                print(f"[cron] tick error: {e}", file=sys.stderr)
            time.sleep(30)  # check every 30 seconds

    def _tick(self):
        from redclaw.agent import _db_conn
        db = _db_conn()
        now = datetime.now().timestamp()

        rows = db.execute(
            "SELECT * FROM scheduled_tasks WHERE enabled=1 AND (next_run IS NULL OR next_run <= ?)",
            (now,),
        ).fetchall()

        for row in rows:
            task = dict(row)
            with self._lock:
                self._execute(task)

    def _execute(self, task: dict):
        from redclaw.agent import _db_conn, create_agent
        db = _db_conn()
        now = datetime.now().timestamp()

        print(f"[cron] running: {task['name']}", file=sys.stderr)

        try:
            agent = create_agent(session_id=f"cron_{task['id']}")
            result = agent.run(task["prompt"])
        except Exception as e:
            result = f"Cron error: {e}"
            print(f"[cron] {task['name']}: {e}", file=sys.stderr)

        # Update last_run / next_run
        interval = task.get("interval_minutes", 60)
        next_run = now + interval * 60
        db.execute(
            "UPDATE scheduled_tasks SET last_run=?, next_run=? WHERE id=?",
            (now, next_run, task["id"]),
        )
        db.commit()

        # Save result as a note
        note_id = f"cron_{task['id']}_{int(now)}"
        db.execute(
            "INSERT OR REPLACE INTO posts (id, radar_id, title, content, author, platform, url, tags, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (note_id, "cron", f"[Cron] {task['name']} — {datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M')}",
             result or "", "Reddy Cron", "cron", "", json.dumps(["cron", task.get("name", "")], ensure_ascii=False), now),
        )
        db.commit()


_scheduler = Scheduler()


# ── Tool handlers ─────────────────────────────────────────

def _schedule_task(args: dict) -> dict:
    from redclaw.agent import _db_conn
    db = _db_conn()

    name = args.get("name", "")
    prompt = args.get("prompt", "")
    interval = args.get("interval_minutes", args.get("interval", 60))

    if not name or not prompt:
        return {"error": "name and prompt required"}

    task_id = f"cron_{int(datetime.now().timestamp())}"
    now = datetime.now().timestamp()

    db.execute(
        "INSERT INTO scheduled_tasks (id, name, prompt, interval_minutes, enabled, last_run, next_run, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (task_id, name, prompt, int(interval), 1, None, now, now),
    )
    db.commit()

    if not _scheduler.running:
        _scheduler.start()

    return {
        "success": True, "id": task_id, "name": name,
        "interval_minutes": int(interval),
        "message": f"Scheduled '{name}' every {interval}min",
    }


def _list_tasks(args: dict) -> dict:
    from redclaw.agent import _db_conn
    db = _db_conn()
    rows = db.execute(
        "SELECT * FROM scheduled_tasks ORDER BY created_at DESC"
    ).fetchall()

    tasks = []
    for r in rows:
        tasks.append({
            "id": r["id"], "name": r["name"],
            "prompt": r["prompt"][:100],
            "interval_minutes": r["interval_minutes"],
            "enabled": bool(r["enabled"]),
            "last_run": r["last_run"],
            "next_run": r["next_run"],
            "created_at": r["created_at"],
        })
    return {"tasks": tasks, "count": len(tasks)}


def _delete_task(args: dict) -> dict:
    from redclaw.agent import _db_conn
    db = _db_conn()
    task_id = args.get("id", "") or args.get("name", "")
    if not task_id:
        return {"error": "id or name required"}

    row = db.execute("SELECT * FROM scheduled_tasks WHERE id=? OR name=?", (task_id, task_id)).fetchone()
    if not row:
        return {"error": f"task not found: {task_id}"}

    db.execute("DELETE FROM scheduled_tasks WHERE id=?", (row["id"],))
    db.commit()
    return {"success": True, "deleted": row["name"]}


def _cron_status(args: dict) -> dict:
    from redclaw.agent import _db_conn
    db = _db_conn()
    count = db.execute("SELECT COUNT(*) as c FROM scheduled_tasks WHERE enabled=1").fetchone()["c"]
    rows = db.execute("SELECT id, name, next_run FROM scheduled_tasks WHERE enabled=1 ORDER BY next_run ASC LIMIT 5").fetchall()
    upcoming = [{"name": r["name"], "id": r["id"]} for r in rows]

    return {
        "running": _scheduler.running,
        "active_tasks": count,
        "upcoming": upcoming,
    }


def register_cron_tools(registry):
    registry.register(
        name="schedule_task", toolset="cron",
        schema={"type": "object", "properties": {
            "name": {"type": "string", "description": "Task name"},
            "prompt": {"type": "string", "description": "Agent prompt to run on schedule"},
            "interval_minutes": {"type": "integer", "default": 60, "description": "Interval in minutes"},
        }, "required": ["name", "prompt"]},
        handler=_schedule_task,
        description="Schedule a recurring agent task", emoji="⏰",
    )
    registry.register(
        name="list_tasks", toolset="cron",
        schema={"type": "object", "properties": {}},
        handler=_list_tasks,
        description="List all scheduled tasks", emoji="📋",
    )
    registry.register(
        name="delete_task", toolset="cron",
        schema={"type": "object", "properties": {
            "id": {"type": "string", "description": "Task ID or name to delete"},
        }, "required": ["id"]},
        handler=_delete_task,
        description="Delete a scheduled task", emoji="🗑",
    )
    registry.register(
        name="cron_status", toolset="cron",
        schema={"type": "object", "properties": {}},
        handler=_cron_status,
        description="Check cron scheduler status", emoji="🕐",
    )

import os
import re
import json
import time
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from openai import OpenAI
# from dotenv import load_dotenv
from context_compact import *
from task import ToolsThread
from tools import *

# -----------------------------------------------------------------------------
# 环境加载
# -----------------------------------------------------------------------------
# load_dotenv(override=True)

WORKDIR = Path.cwd()
client = OpenAI(
    api_key="sk-1f7bfcabb7874aa48813eddef5b3044c",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    # model="qwen3.6-plus"
)
MODEL = "qwen3.5-35b-a3b"


# -----------------------------------------------------------------------------
# Git Repo Root 检测
# -----------------------------------------------------------------------------
def detect_repo_root(cwd: Path) -> Optional[Path]:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            return None
        root = Path(r.stdout.strip())
        return root if root.exists() else None
    except Exception:
        return None


REPO_ROOT = detect_repo_root(WORKDIR) or WORKDIR

SYSTEM = (
    f"You are a coding agent at {WORKDIR}. "
    "Use task + worktree tools for multi-task work. "
    "For parallel or risky changes: create tasks, allocate worktree lanes, "
    "run commands in those lanes, then choose keep/remove for closeout. "
    "Use worktree_events when you need lifecycle visibility."
)


# -----------------------------------------------------------------------------
# EventBus  记录worktree的不同事件
# -----------------------------------------------------------------------------
class EventBus:
    def __init__(self, event_log_path: Path, max_lines: int = 2000):
        self.path = event_log_path
        self.max_lines = max_lines
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def emit(
            self,
            event: str,
            task: Optional[Dict] = None,
            worktree: Optional[Dict] = None,
            error: Optional[str] = None,
    ):
        payload = {
            "event": event,
            "ts": time.time(),
            "task": task or {},
            "worktree": worktree or {},
        }
        if error:
            payload["error"] = error
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)
        self._rotate()

    def _rotate(self):
        lines = self.path.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) > self.max_lines:
            kept = lines[-self.max_lines:]
            self.path.write_text("".join(kept), encoding="utf-8")

    def list_recent(self, limit: int = 20) -> str:
        n = max(1, min(int(limit), 200))
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return "[]"
        recent = lines[-n:]
        items = []
        for line in recent:
            try:
                items.append(json.loads(line))
            except Exception:
                items.append({"event": "parse_error", "raw": line})
        return json.dumps(items, indent=2, ensure_ascii=False)


# -----------------------------------------------------------------------------
# TaskManager 多任务team中，agent可以创建任务，并且关联worktree
# -----------------------------------------------------------------------------
class TaskManager:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save({"tasks": [], "next_id": 1})

    def _load(self) -> Dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"tasks": [], "next_id": 1}

    def _save(self, data: Dict[str, Any]):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def create(self, subject: str, description: str = "") -> str:
        data = self._load()
        task_id = data["next_id"]
        task = {
            "id": task_id,
            "subject": subject,
            "description": description,
            "status": "pending",
            "owner": "",
            "worktree": None,
            "created_at": time.time(),
        }
        data["tasks"].append(task)
        data["next_id"] = task_id + 1
        self._save(data)
        return json.dumps(task, indent=2, ensure_ascii=False)

    def exists(self, task_id: int) -> bool:
        data = self._load()
        return any(t["id"] == task_id for t in data["tasks"])

    def get(self, task_id: int) -> str:
        data = self._load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                return json.dumps(t, indent=2, ensure_ascii=False)
        return f"Task {task_id} not found"

    def list_all(self) -> str:
        data = self._load()
        tasks = data["tasks"]
        if not tasks:
            return "No tasks."
        lines = []
        for t in tasks:
            wt = f" worktree={t['worktree']}" if t.get("worktree") else ""
            lines.append(f"[{t['status']}] {t['id']}: {t['subject']} (owner={t['owner']}){wt}")
        return "\n".join(lines)

    def update(self, task_id: int, status: Optional[str] = None, owner: Optional[str] = None):
        data = self._load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                if status is not None:
                    t["status"] = status
                if owner is not None:
                    t["owner"] = owner
                self._save(data)
                return f"Updated task {task_id}"
        return f"Task {task_id} not found"

    def bind_worktree(self, task_id: int, name: str, owner: str = ""):
        data = self._load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                t["worktree"] = name
                t["owner"] = owner or t["owner"]
                self._save(data)
                return f"Bound task {task_id} to worktree {name}"
        return f"Task {task_id} not found"

    def unbind_worktree(self, task_id: int):
        data = self._load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                t["worktree"] = None
                self._save(data)
                return f"Unbound worktree from task {task_id}"
        return f"Task {task_id} not found"


# -----------------------------------------------------------------------------
# 全局实例
# -----------------------------------------------------------------------------
TASKS = TaskManager(REPO_ROOT / ".tasks" / "tasks.json")
EVENTS = EventBus(REPO_ROOT / ".worktrees" / "events.jsonl")


# -----------------------------------------------------------------------------
# WorktreeManager
# -----------------------------------------------------------------------------
class WorktreeManager:
    def __init__(self, repo_root: Path, tasks: TaskManager, events: EventBus):
        self.repo_root = repo_root
        self.tasks = tasks
        self.events = events
        self.dir = repo_root / ".worktrees"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "index.json"
        if not self.index_path.exists():
            self._save_index({"worktrees": []})
        self.git_available = self._is_git_repo()

    def _is_git_repo(self) -> bool:
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _load_index(self) -> Dict:
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {"worktrees": []}

    def _save_index(self, data: Dict):
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.index_path)

    def _find(self, name: str) -> Optional[Dict]:
        idx = self._load_index()
        for wt in idx.get("worktrees", []):
            if wt.get("name") == name:
                return wt
        return None

    def _validate_name(self, name: str):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", name or ""):
            raise ValueError("名称只能是字母数字._-，长度1-40")

    def sync_with_git(self):
        idx = self._load_index()
        existing = []
        try:
            out = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            lines = out.strip().splitlines()
            for line in lines:
                parts = line.split()
                if len(parts) >= 1:
                    existing.append(parts[0])
        except Exception:
            pass

        changed = False
        for wt in idx.get("worktrees", []):
            p = wt.get("path")
            if p and Path(p).exists() and p in existing:
                continue
            if wt.get("status") == "active":
                wt["status"] = "missing"
                changed = True
        if changed:
            self._save_index(idx)

    def create(self, name: str, task_id: Optional[int] = None, base_ref: str = "HEAD") -> str:
        self.sync_with_git()
        self._validate_name(name)
        if self._find(name):
            raise ValueError(f"Worktree {name} 已存在")
        if task_id is not None and not self.tasks.exists(task_id):
            raise ValueError(f"Task {task_id} 不存在")

        path = self.dir / name
        branch = f"wt/{name}"
        self.events.emit(
            "worktree.create.before",
            task={"id": task_id} if task_id else None,
            worktree={"name": name, "base_ref": base_ref},
        )
        try:
            self._run_git(["worktree", "add", "-b", branch, str(path), base_ref])
            entry = {
                "name": name,
                "path": str(path),
                "branch": branch,
                "task_id": task_id,
                "status": "active",
                "created_at": time.time(),
            }
            idx = self._load_index()
            idx["worktrees"].append(entry)
            self._save_index(idx)
            if task_id is not None:
                self.tasks.bind_worktree(task_id, name)
            self.events.emit("worktree.create.after", task={"id": task_id}, worktree=entry)
            return json.dumps(entry, indent=2, ensure_ascii=False)
        except Exception as e:
            self.events.emit("worktree.create.failed", error=str(e))
            raise

    def _run_git(self, args: list[str]) -> str:
        if not self.git_available:
            raise RuntimeError("非 Git 仓库")
        r = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            msg = (r.stdout + r.stderr).strip()
            raise RuntimeError(msg or "git 命令失败")
        return (r.stdout + r.stderr).strip() or "(no output)"

    def list_all(self) -> str:
        self.sync_with_git()
        idx = self._load_index()
        wts = idx.get("worktrees", [])
        if not wts:
            return "No worktrees."
        lines = []
        for wt in wts:
            task = f" task={wt['task_id']}" if wt.get("task_id") is not None else ""
            lines.append(f"[{wt.get('status')}] {wt['name']} -> {wt['path']} ({wt.get('branch')}){task}")
        return "\n".join(lines)

    def status(self, name: str) -> str:
        self.sync_with_git()
        wt = self._find(name)
        if not wt:
            return f"不存在 worktree: {name}"
        path = Path(wt["path"])
        if not path.exists():
            return f"路径不存在: {path}"
        try:
            r = subprocess.run(
                ["git", "status", "--short", "--branch"],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or "clean"
        except Exception as e:
            return f"Error: {e}"

    def run(self, name: str, command: str) -> str:
        dangerous = {"rm -rf", "sudo", "shutdown", "reboot", "mkfs", "> /dev/sd", "dd if="}
        if any(p in command for p in dangerous):
            return "危险命令已拦截"
        wt = self._find(name)
        if not wt:
            return f"不存在 worktree: {name}"
        path = Path(wt["path"])
        if not path.exists():
            return f"路径不存在: {path}"
        try:
            r = subprocess.run(
                command,
                shell=True,
                cwd=path,
                capture_output=True,
                text=True,
                timeout=300,
            )
            out = (r.stdout + r.stderr).strip()
            return out[:50000] if out else "(no output)"
        except subprocess.TimeoutExpired:
            return "超时(300s)"
        except Exception as e:
            return f"Error: {e}"

    def remove(self, name: str, force: bool = False, complete_task: bool = False) -> str:
        self.sync_with_git()
        wt = self._find(name)
        if not wt:
            return f"不存在 worktree: {name}"
        self.events.emit("worktree.remove.before", worktree={"name": name})
        try:
            args = ["worktree", "remove"]
            if force:
                args.append("--force")
            args.append(wt["path"])
            self._run_git(args)
            if complete_task and wt.get("task_id") is not None:
                tid = wt["task_id"]
                self.tasks.update(tid, status="completed")
                self.tasks.unbind_worktree(tid)
                self.events.emit("task.completed", task={"id": tid})
            idx = self._load_index()
            for item in idx["worktrees"]:
                if item["name"] == name:
                    item["status"] = "removed"
                    item["removed_at"] = time.time()
            self._save_index(idx)
            self.events.emit("worktree.remove.after", worktree={"name": name})
            return f"已移除 worktree: {name}"
        except Exception as e:
            self.events.emit("worktree.remove.failed", error=str(e))
            return f"失败: {e}"

    def keep(self, name: str) -> str:
        wt = self._find(name)
        if not wt:
            return f"不存在 worktree: {name}"
        idx = self._load_index()
        for item in idx["worktrees"]:
            if item["name"] == name:
                item["status"] = "kept"
                item["kept_at"] = time.time()
        self._save_index(idx)
        self.events.emit("worktree.keep", worktree={"name": name})
        return f"已保留 worktree: {name}"


WORKTREES = WorktreeManager(REPO_ROOT, TASKS, EVENTS)


# -----------------------------------------------------------------------------
# 文件与命令工具
# -----------------------------------------------------------------------------
def safe_path(p: str) -> Path:
    base = WORKDIR.resolve()
    path = (base / p).resolve()
    if not path.is_relative_to(base):
        raise ValueError("禁止访问工作区外路径")
    return path


def run_bash(command: str) -> str:
    dangerous = {"rm -rf", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sd"}
    if any(p in command for p in dangerous):
        return "危险命令已拦截"
    try:
        r = subprocess.run(
            command,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "超时(120s)"
    except Exception as e:
        return f"Error: {e}"


def run_read(path: str, limit: Optional[int] = None) -> str:
    try:
        p = safe_path(path)
        lines = p.read_text(encoding="utf-8").splitlines()
        if limit and len(lines) > limit:
            lines = lines[:limit] + [f"... (+{len(lines) - limit} lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        p = safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"写入 {p} 成功"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        p = safe_path(path)
        c = p.read_text(encoding="utf-8")
        if old_text not in c:
            return "未找到匹配文本"
        c = c.replace(old_text, new_text, 1)
        p.write_text(c, encoding="utf-8")
        return f"编辑 {p} 成功"
    except Exception as e:
        return f"Error: {e}"


# -----------------------------------------------------------------------------
# OpenAI 格式工具定义
# -----------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command in the current workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace exact text in file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_create",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_list",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_get",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "integer"}},
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_update",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                    "owner": {"type": "string"},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_bind_worktree",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "worktree": {"type": "string"},
                    "owner": {"type": "string"},
                },
                "required": ["task_id", "worktree"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "worktree_create",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "task_id": {"type": "integer"},
                    "base_ref": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "worktree_list",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "worktree_status",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "worktree_run",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "command": {"type": "string"},
                },
                "required": ["name", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "worktree_remove",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "force": {"type": "boolean"},
                    "complete_task": {"type": "boolean"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "worktree_keep",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "worktree_events",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
        },
    }
]

TOOL_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "task_create": TASKS.create,
    "task_list": lambda **kw: TASKS.list_all(),
    "task_get": TASKS.get,
    "task_update": TASKS.update,
    "task_bind_worktree": TASKS.bind_worktree,
    "worktree_create": WORKTREES.create,
    "worktree_list": lambda **kw: WORKTREES.list_all(),
    "worktree_status": WORKTREES.status,
    "worktree_run": WORKTREES.run,
    "worktree_remove": WORKTREES.remove,
    "worktree_keep": WORKTREES.keep,
    "worktree_events": EVENTS.list_recent,
}


# -----------------------------------------------------------------------------
# OpenAI 流式 + 工具调用主循环
# -----------------------------------------------------------------------------
def agent_loop(messages: List[Dict[str, Any]], max_steps: int = 12):
    steps = 0
    while steps < max_steps:
        steps += 1
        full_text = ""
        tool_calls = []

        try:
            with client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "system", "content": SYSTEM}, *messages],
                    tools=TOOLS,
                    stream=True,
                    max_tokens=8000,
            ) as stream:
                for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue

                    # 文本增量
                    if delta.content:
                        print(delta.content, end="", flush=True)
                        full_text += delta.content

                    # 工具调用
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx >= len(tool_calls):
                                tool_calls.append({
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                })
                            if tc.id:
                                tool_calls[idx]["id"] = tc.id
                            if tc.function.name:
                                tool_calls[idx]["function"]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls[idx]["function"]["arguments"] += tc.function.arguments

        except Exception as e:
            err = f"\n\nAPI Error: {e}"
            print(err, flush=True)
            messages.append({"role": "assistant", "content": full_text + err})
            return

        # 构造 assistant 消息
        assistant_msg: Dict[str, Any] = {"role": "assistant", "content": full_text}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        # 无工具调用则退出
        if not tool_calls:
            print("\n", flush=True)
            return

        # 执行工具
        print("\n" + "-" * 50, flush=True)
        tool_results = []
        for tc in tool_calls:
            func = tc["function"]
            name = func["name"]
            try:
                args = json.loads(func["arguments"])
            except Exception:
                args = {}
            print(f"🔧 {name} {args}", flush=True)

            handler = TOOL_HANDLERS.get(name)
            try:
                res = handler(**args) if handler else f"Unknown tool: {name}"
            except Exception as e:
                res = f"Error: {e}"

            print(f"✅ {str(res)[:300]}\n", flush=True)
            tool_results.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": str(res),
            })

        messages.extend(tool_results)
        print("-" * 50 + "\n", flush=True)

    messages.append({"role": "assistant", "content": "\nReached max tool steps."})


# -----------------------------------------------------------------------------
# 入口
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Repo root: {REPO_ROOT}")
    if not WORKTREES.git_available:
        print("⚠️ Not in a git repo — worktree functions disabled.")

    history = []
    while True:
        try:
            query = input("\033[36ms12 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        query = query.strip()
        if not query or query.lower() in ("q", "exit", "quit"):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history, max_steps=12)
        print()

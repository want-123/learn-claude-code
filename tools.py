import json
import os
import subprocess
from pathlib import Path
from typing import List

from skill_loader import SKILLSLOADER
from util import OpenAiClient

WORKPATH = Path.cwd()


class ToDoManager:
    def __init__(self, items: list = None):
        self.items = []

    def update(self, items: list) -> str:
        if len(items) > 20:
            raise ValueError("超过最大任务数 20")
        validated = []
        in_progress_count = 0

        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))

            if not text:
                raise ValueError("任务text不能为空")
            if status not in ["pending", "in_progress", "completed"]:
                raise ValueError("任务状态不合法")

            if status == "in_progress":
                in_progress_count += 1

            validated.append({
                "id": item_id,
                "text": text,
                "status": status
            })
        if in_progress_count > 1:
            raise ValueError("处于 in_progress 状态的任务数量超过1")

        self.items = validated
        return self.render()

    def render(self):
        if not self.items:
            raise ValueError("没有 todo list")
        lines = []
        done = 0
        for item in self.items:
            if item.get("status") == "completed":
                done += 1
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]"
            }[item.get("status")]
            lines.append(f"{marker} #{item['id']}: {item['text']}")

        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


"""
基础tools
"""


def run_glob(pattern: str) -> str:
    """查找匹配模式的文件"""
    import glob
    try:
        files = glob.glob(pattern, recursive=True)
        if not files:
            return f"没有找到匹配 '{pattern}' 的文件"
        return f"找到 {len(files)} 个文件:\n" + "\n".join(files[:200])
    except Exception as e:
        return f"Error: {str(e)}"


def safe_path(p: str) -> Path:
    path = (WORKPATH / p).resolve()
    if not path.is_relative_to(WORKPATH):
        raise ValueError(f"不在路径沙箱之内")
    return path


def run_read(path: str, limit: int = None) -> str:
    try:
        fp = safe_path(path)
        if not fp.is_file():
            return f"Error: {path} 不是文件"
        text = fp.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"..({len(lines) - limit} more lines)"]
        if lines is None or len(lines) == 0:
            lines = ["该文件无内容"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error reading: {str(e)}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return f"写了{len(content)} bytes 到 {path}"
    except Exception as e:
        return f"Error : {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text(encoding="utf-8", errors="replace")
        if old_text not in content:
            return f"Error 修改内容不存在"
        fp.write_text(content.replace(old_text, new_text))
        return f"完成修改 {path}"
    except Exception as e:
        return f"Exception {e}"


def run_bash(command: str, tool_name: str) -> str:
    if tool_name != "bash":
        return "执行工具错误！"
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(
            command,
            shell=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,  # 确保文本模式
            errors="replace",  # 🔥 核心修复：编码错误自动替换
            timeout=15
        )
        # 🔥 安全截取，防止超长导致 PyUnicode_New 报错
        out = (r.stdout + r.stderr)[:50000].strip()
        return out if out else "(命令执行成功，无输出)"
    except subprocess.TimeoutExpired:
        return "Error: 执行超时 (15s)"
    except Exception as e:
        return f"Error: {str(e)}"


""""
子agent tool
"""


def run_subagent(prompt: str) -> str:
    client = OpenAiClient(
        api="sk-1f7bfcabb7874aa48813eddef5b3044c",
        baseUrl="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.6-plus"
    )
    submessages = [{"role": "assistant",
                    "content": f"You are a coding subagent at {WORKPATH}. Complete the given task, then summarize your findings. Skills available:{SKILLSLOADER.get_descriptions()}"},
                   {"role": "user", "content": prompt}]
    rounds_since_todo = 0
    for _ in range(30):
        response = client.chat(messages=submessages, tools=CHILD_TOOLS)
        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        submessages.append({
            "role": "assistant",
            "content": message.content or ""
        })
        # print("==================================================")
        # print("当前回复 : ", message)
        # print("==================================================")

        if finish_reason != "tool_calls" and message.tool_calls is None:
            print("【subagent最终回答】", message.content)
            break

        use_todo = False
        print("==================================================")
        print("subagent当前tools : ", message.tool_calls)
        print("==================================================")
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except:
                tool_args = {}

            handler = TOOLS_HANDLERS.get(tool_name)
            print("==================================================")
            print("subagent执行命令：", tool_name)
            try:
                output = handler(**tool_args) if handler else f"未知工具 {tool_name}"
            except Exception as e:
                output = f"工具执行失败: {str(e)}"
            print("subagent执行结果：", output)
            print("==================================================\n")

            submessages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(output)[:50000]
            })

        #     if tool_name == "todo":
        #         use_todo = True
        #
        # rounds_since_todo = 0 if use_todo else rounds_since_todo + 1
        # if rounds_since_todo >= 3:
        #     messages.append({
        #         "role": "user",
        #         "content": "Please update your todos and focus on current task."
        #     })
        #     rounds_since_todo = 0
    summary = "".join(message.content if message.content else "no summary")
    print("==================================================\n")
    print("subagent sunmmary", summary)
    print("==================================================\n")
    return summary


TODO = ToDoManager()

CHILD_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "执行shell命令",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "shell命令"},
                    "tool_name": {"type": "string", "description": "工具名称"}
                },
                "required": ["command", "tool_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_read",
            "description": "读取文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "limit": {"type": "integer", "description": "读取长度限制"}
                },
                "required": ["path", "limit"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_write",
            "description": "写入文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "要写入的内容"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_edit",
            "description": "编辑修改文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "old_text": {"type": "string", "description": "要替换的旧内容"},
                    "new_text": {"type": "string", "description": "新内容"}
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "Update task list. Track progress on multi-step tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "List of task items to update or track",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "text": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}
                            },
                            "required": ["id", "text", "status"]
                        }
                    }
                },
                "required": ["items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "Load specialized knowledge by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Skill name to load"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compact",
            "description": "Trigger manual conversation compression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "What to preserve in the summary"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_glob",
            "description": "使用glob模式查找文件（如 skills/**/*.py）",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "glob模式，支持 ** 递归匹配，如 skills/**/*.py"
                    }
                },
                "required": ["pattern"]
            }
        }
    },
]

PARENT_TOOLS = CHILD_TOOLS + [
    {
        "type": "function",
        "function": {
            "name": "run_subagent",
            "description": "Spawn a subagent with fresh context. It shares the filesystem but not conversation history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The main instruction/prompt for the subagent to execute"
                    },
                    "description": {
                        "type": "string",
                        "description": "Short description of the task"
                    }
                },
                "required": [
                    "prompt"
                ]
            }
        }
    }
]

TOOLS_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"], kw["tool_name"]),
    "run_read": lambda **kw: run_read(kw["path"], kw["limit"]),
    "run_write": lambda **kw: run_write(kw["path"], kw["content"]),
    "run_edit": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo": lambda **kw: TODO.update(kw["items"]),
    "run_subagent": lambda **kw: run_subagent(kw["prompt"]),
    "load_skill": lambda **kw: SKILLSLOADER.get_content(kw["name"]),
    "run_glob": lambda **kw: run_glob(kw["pattern"]),
}
TOOLS_TASK_HANDLERS = {
    "bash": run_bash,
    "run_read": run_read,
    "run_write": run_write,
    "run_edit": run_edit,
    "todo": TODO.update,
    "run_subagent": run_subagent,
    "load_skill": SKILLSLOADER.get_content,
    "run_glob": run_glob,
}

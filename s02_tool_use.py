import json
import os
import subprocess
from pathlib import Path
from typing import List
from util import OpenAiClient

WORKPATH = Path.cwd()

# 路径沙箱
def safe_path(p: str) -> Path:
    path = (WORKPATH / p).resolve()
    if not path.is_relative_to(WORKPATH):
        raise ValueError(f"不在路径沙箱之内")
    return path
def run_read(path: str, limit: int = None) -> str:
    text = safe_path(path).read_text()
    lines = text.splitlines()
    if limit and limit < len(lines):
        lines = lines[:limit] + [f"..({len(lines) - limit} more lines)"]
    return "\n".join(lines)[:50000]
def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"写了{len(content)} bytes 到 {path}"
    except Exception as e:
        return f"Error : {e}"
def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
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
            text=True,
            timeout=120
        )
        out = (r.stdout + r.stderr).strip()
        return out[:5000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

TOOLS = [
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
    }
]

TOOLS_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"], kw["tool_name"]),
    "run_read": lambda **kw: run_read(kw["path"], kw["limit"]),
    "run_write": lambda **kw: run_write(kw["path"], kw["content"]),
    "run_edit": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"])
}


def agent_loop(messages: List):
    client = OpenAiClient(
        api="sk-1f7bfcabb7874aa48813eddef5b3044c",
        baseUrl="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.5-flash"
    )

    # 🔥 强制规则：让AI必须自动重试失败的命令
    # messages.insert(0, {
    #     "role": "system",
    #     "content": "你是一个自动执行命令的Agent。如果命令执行失败（如命令不存在、权限不足），请自动修复命令并重新调用工具执行，直到成功为止。不要直接回答！"
    # })

    while True:
        response = client.chat(messages=messages, tools=TOOLS)
        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        # 把AI回复加入消息
        messages.append({
            "role": "assistant",
            "content": message.content or ""
        })

        # 结束条件：不是工具调用才结束
        if finish_reason != "tool_calls":
            print("【最终回答】", message.content)
            return

        # 执行工具
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            handler = TOOLS_HANDLERS.get(tool_name)

            print("==================================================")
            print("执行命令：", tool_name)
            output = handler(**tool_args) if handler else f"位置工具 {tool_name}"
            print("执行结果：", output)
            print("==================================================\n")

            # 工具返回
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output
            })

if __name__ == "__main__":
    SYSTEM = f"你是一个coding Agent，你的的WORKPATH是{WORKPATH}，你需要利用tools解决问题，不需要解释"
    history = []
    history.append({"role": "system", "content": SYSTEM})
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()
import json
import os
import subprocess
from typing import List
from util import OpenAiClient

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute."
                    }
                },
                "required": ["command"]
            }
        }
    }
]

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

def agent_loop(messages: List):
    client = OpenAiClient(
        api="",
        baseUrl="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.5-flash"
    )

    # 🔥 强制规则：让AI必须自动重试失败的命令
    messages.insert(0, {
        "role": "system",
        "content": "你是一个自动执行命令的Agent。如果命令执行失败（如命令不存在、权限不足），请自动修复命令并重新调用工具执行，直到成功为止。不要直接回答！"
    })

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
            command = tool_args["command"]

            print("==================================================")
            print("执行命令：", command)
            output = run_bash(command, tool_name)
            print("执行结果：", output)
            print("==================================================\n")

            # 工具返回
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output
            })

if __name__ == "__main__":
    history = []
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
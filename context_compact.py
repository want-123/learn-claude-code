import json
import time
from pathlib import Path
from util import OpenAiClient

THRESHOLD = 50000
WORKPATH = Path.cwd()
TRANSCRIPT_DIR = WORKPATH / ".transcripts"
KEEP_RECENT = 3
PRESERVE_RESULT_TOOLS = {"read_file"}


def estimate_tokens(messages: list) -> int:
    """Rough token count: ~4 chars per token."""
    return len(str(messages)) // 4


# 第一层上下文压缩：对旧的工具调用结果进行压缩
def micro_compact(messages: list) -> list:
    tool_results = []
    for msg_id, msg in enumerate(messages):
        if msg["role"] == "tool":
            tool_results.append(msg)
    if len(tool_results) < KEEP_RECENT:
        return messages
    to_clear = tool_results[:-KEEP_RECENT]

    for msg in to_clear:
        if not isinstance(msg["content"], str) or len(msg["content"]) < 100:
            continue
        tool_name = next(iter(json.loads(msg["content"]).keys()))
        if tool_name in PRESERVE_RESULT_TOOLS:
            continue
        msg["content"] = json.dumps({f"{tool_name}": f"Previous: used {tool_name}"})

    return messages


# 第二层压缩
def auto_compact(messages: list) -> list:
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    tpath = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(tpath, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    print(f"已持久化messages至{tpath}")
    # 摘要压缩
    conversation_text = json.loads(messages)
    client = OpenAiClient(
        api="sk-1f7bfcabb7874aa48813eddef5b3044c",
        baseUrl="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.5-flash"
    )

    response = client.chat(messages=[
        {"role": "user", "content": "Summarize this conversation for continuity. Include: "
                                    "1) What was accomplished, 2) Current state, 3) Key decisions made. "
                                    "Be concise but preserve critical details.\n\n" + conversation_text}
    ])
    summary = str(response.choices[0].message.content, "No summary generated.")
    return [
        {"role": "user", "content": f"[Conversation compressed. Transcript: {tpath}]\n\n{summary}"}
    ]

from skill_loader import *
from tools import *
WORKPATH = Path.cwd()

# 主agent
def agent_loop(messages: List):
    client = OpenAiClient(
        api="sk-1f7bfcabb7874aa48813eddef5b3044c",
        baseUrl="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.5-flash"
    )

    rounds_since_todo = 0
    while True:
        response = client.chat(messages=messages, tools=PARENT_TOOLS)
        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        messages.append({
            "role": "assistant",
            "content": message.content or ""
        })
        print("==================================================")
        print("当前回复 : ", message)
        print("==================================================")

        if finish_reason != "tool_calls" and message.tool_calls is None:
            print("【最终回答】", message.content)
            return

        use_todo = False
        print("==================================================")
        print("当前tools : ", message.tool_calls)
        print("==================================================")
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except:
                tool_args = {}

            handler = TOOLS_HANDLERS.get(tool_name)
            print("==================================================")
            print("执行命令：", tool_name)
            try:
                output = handler(** tool_args) if handler else f"未知工具 {tool_name}"
            except Exception as e:
                output = f"工具执行失败: {str(e)}"
            print("执行结果：", output)
            print("==================================================\n")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(output)
            })

            if tool_name == "todo":
                use_todo = True

        rounds_since_todo = 0 if use_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            messages.append({
                "role": "user",
                "content": "Please update your todos and focus on current task."
            })
            rounds_since_todo = 0

if __name__ == "__main__":
    SYSTEM = f"""你是一个Coding Agent，工作目录：{WORKPATH}
规则：
1. 多任务必须先调用 todo 工具创建任务列表
2. 只能读写文件，不能读文件夹
3. 严格按任务顺序执行
4. 调用 todo 后必须展示任务状态
Skills available:
{SKILLSLOADER.get_descriptions()}
"""
    history = [{"role": "system", "content": SYSTEM}]
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt) as e:
            print(f"出现错误：\n {e}")
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        print()
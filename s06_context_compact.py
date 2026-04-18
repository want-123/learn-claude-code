import concurrent.futures

from context_compact import *
from task import ToolsThread
from tools import *

WORKPATH = Path.cwd()


# 主agent
def agent_loop(messages: List):
    client = OpenAiClient(
        api="sk-1f7bfcabb7874aa48813eddef5b3044c",
        baseUrl="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.6-plus"
    )

    rounds_since_todo = 0
    executor = ToolsThread()
    while True:
        print("----------------执行micro_compact---------------")
        micro_compact(messages=messages)
        if estimate_tokens(messages) > THRESHOLD:
            print("------------------执行auto_compact------------------")
            messages[:] = auto_compact(messages)
            print("------------------auto_compact-------------------")
        response = client.chat(messages=messages, tools=PARENT_TOOLS)
        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        messages.append({
            "role": "assistant",
            "content": message.content or ""
        })
        print("==================================================")
        print("当前回复 response: ", response)
        print("==================================================")
        manual_compact = False

        if finish_reason != "tool_calls" and message.tool_calls is None:
            # 模型可能结束回答
            # 基于任务items判断任务是否继续
            if TODO.items:
                all_cpmpleted = all(item["status"] == "completed" for item in TODO.items)
            if all_cpmpleted:
                print("【最终回答】", message.content)
                return
            else:
                messages.append({
                    "role": "user",
                    "content": "请检查当前任务清单是否以全部完成，若未完成请继续，若完成请更新task list"
                })
                continue
        use_todo = False
        print("==================================================")
        print("当前tools : ", message.tool_calls)
        print("==================================================")
        task_list = []
        kwargs = []
        tools_id_name = []
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except:
                tool_args = {}
            task_list.append(TOOLS_TASK_HANDLERS.get(tool_name))
            kwargs.append(tool_args)
            tools_id_name.append({tool_call.id: tool_name})
            if tool_name == "todo":
                use_todo = True
        outputs = executor.work(tasks=task_list, kwargs=kwargs)
        for i, output in enumerate(outputs):
            tool_id = next(iter(tools_id_name[i].keys()))
            tool_name = tools_id_name[i].get(tool_id)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": json.dumps({f"{tool_name}": output})
            })

        # for tool_call in message.tool_calls:
        #     tool_name = tool_call.function.name
        #     try:
        #         tool_args = json.loads(tool_call.function.arguments)
        #     except:
        #         tool_args = {}
        #     print("==================================================")
        #     print("执行命令：", tool_name)
        #     if tool_name == "compact":
        #         manual_compact = True
        #         if manual_compact:
        #             print("----------------执行manual_compact-------------------")
        #             messages[:] = auto_compact(messages)
        #         output = "执行了manual compact"
        #     else:
        #         handler = TOOLS_HANDLERS.get(tool_name)
        #         try:
        #             output = handler(**tool_args) if handler else f"未知工具 {tool_name}"
        #         except Exception as e:
        #             output = f"工具执行失败: {str(e)}"
        #     print("执行结果：", output)
        #     print("==================================================\n")
        #     messages.append({
        #         "role": "tool",
        #         "tool_call_id": tool_call.id,
        #         "content": json.dumps({f"{tool_name}": output})
        #     })
        #
        #     if tool_name == "todo":
        #         use_todo = True

        rounds_since_todo = 0 if use_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            messages.append({
                "role": "user",
                "content": "Please update your todos and focus on current task."
            })
            rounds_since_todo = 0


if __name__ == "__main__":
    print(f"--------------------工作路径是{WORKPATH}----------------------")
    SYSTEM = f"""你是一个Coding Agent，工作目录：{WORKPATH}
规则：
1. 多任务必须先调用 todo 工具创建任务列表
2. 读写文件只能在工作目录下进行，绝对不能自己编造、猜测、生成任何不在列表中的路径。
3. 严格按任务顺序执行
4. 调用 todo 后必须展示任务状态
Skills available:
{SKILLSLOADER.get_descriptions()}
注意：
- 在调用 run_read 之前，必须先确认文件存在
- 如果 run_read 返回错误，不要编造新路径，而要用其他工具查找正确路径
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

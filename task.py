import concurrent.futures
from concurrent.futures import Future
from types import FunctionType
from typing import Callable, List


class ToolsThread:
    def __init__(self, max_workers: int = 5):
        # 修复拼写错误
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

    def work(
            self,
            tasks: List[FunctionType],  # 函数列表
            kwargs: List[dict],  # 每个函数对应的参数字典
            batch_size: int = 5  # 每批执行多少个
    ) -> List:

        task_len = len(tasks)
        futures = []
        output = []
        index = 0

        while index < task_len:
            # 每一批的范围
            end_idx = min(index + batch_size, task_len)
            # 批量提交
            for j in range(index, end_idx):
                future = self.executor.submit(tasks[j], **kwargs[j])
                futures.append(future)

            index = end_idx
        for future in concurrent.futures.as_completed(futures):
            output.append(future.result())
        return output

    def shutdown(self):
        self.executor.shutdown(wait=True)

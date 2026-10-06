import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading


class NativeWorker:
    """Queue bounded before submission; cancellation NEVER releases physical inference ownership."""

    def __init__(self, name):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)
        self.lock = threading.Lock()
        self.inflight = None

    async def run(self, fn, *args):
        if self.inflight is not None and not self.inflight.done():
            raise RuntimeError("native_worker_busy")

        def work():
            with self.lock:
                return fn(*args)

        future = asyncio.get_running_loop().run_in_executor(self.executor, work)
        self.inflight = future
        return await asyncio.shield(future)

    async def close(self):
        if self.inflight:
            await asyncio.shield(self.inflight)
        self.executor.shutdown(wait=True, cancel_futures=True)

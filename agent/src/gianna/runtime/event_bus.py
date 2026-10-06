import asyncio


class EventBus:
    def __init__(self, capacity=256):
        self.capacity = capacity
        self.subscribers = set()
        self.latest = None

    def publish(self, event):
        self.latest = event
        for queue in list(self.subscribers):
            if queue.full():
                # Explicit disconnect on saturation; no silently truncated speech/control stream.
                self.subscribers.remove(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(
                    {"kind": "saturation", "data": {"message": "Reconectá la consola"}}
                )
                continue
            queue.put_nowait(event)

    def subscribe(self):
        queue = asyncio.Queue(self.capacity)
        self.subscribers.add(queue)
        if self.latest:
            queue.put_nowait(self.latest)
        return queue

    def clear(self):
        self.latest = None
        for queue in self.subscribers:
            while not queue.empty():
                queue.get_nowait()

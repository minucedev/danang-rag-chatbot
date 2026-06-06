"""Pub/sub log realtime cho SSE — dùng chung giữa orchestrator và engines (tránh circular import)."""
from __future__ import annotations
import asyncio


class _LogBus:
    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=4000)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def publish(self, line: str) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass


log_bus = _LogBus()

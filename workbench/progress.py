"""In-memory stage-event broker for generation progress (SSE).

One channel per task. Events are kept so a late subscriber (page refresh,
reconnect) gets the full history; the channel closes on done/error.
"""

from __future__ import annotations

import json
import threading
import time


class Channel:
    def __init__(self):
        self.events: list[dict] = []
        self.closed = False
        self.cond = threading.Condition()

    def emit(self, kind: str, data: dict | None = None):
        with self.cond:
            if self.closed:
                return
            self.events.append({"seq": len(self.events), "kind": kind,
                                "data": data or {}, "at": time.time()})
            self.cond.notify_all()

    def close(self):
        with self.cond:
            self.closed = True
            self.cond.notify_all()


class Broker:
    def __init__(self):
        self._channels: dict[str, Channel] = {}
        self._lock = threading.Lock()

    def channel(self, key: str, reset: bool = False) -> Channel:
        with self._lock:
            if reset or key not in self._channels:
                self._channels[key] = Channel()
            return self._channels[key]

    def get(self, key: str) -> Channel | None:
        with self._lock:
            return self._channels.get(key)


BROKER = Broker()


def sse_format(ev: dict) -> str:
    return f"event: {ev['kind']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"

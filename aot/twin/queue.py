# coding=utf-8
"""서버별 작업 큐. 한 원격 노드가 여러 서버를 맡을 수 있게 하되 서로 막지 않는다 (계획서 §4).

- 서버마다 FIFO 하나, 서버 사이는 돌아가며(round-robin) 꺼낸다 → 느린 서버 하나가 다른 서버를 굶기지 않는다.
- 한 서버는 동시에 작업 하나만 돈다(서버 쪽 쓰기 경쟁·부하 방지).
- 같은 대상의 대기 작업은 합친다(최신 것만 남김) → 서버가 느려져도 큐가 무한히 쌓이지 않는다.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple


@dataclass
class Job:
    server_id: str
    target_key: Tuple
    enqueued_at: float


class ServerQueues:
    def __init__(self, max_per_server: int = 64):
        self._max = max_per_server
        self._qs: "OrderedDict[str, Deque[Job]]" = OrderedDict()
        self._busy: set = set()
        self._cv = threading.Condition()
        self._closed = False
        self.dropped = 0
        self.coalesced = 0

    def put(self, job: Job) -> None:
        with self._cv:
            q = self._qs.setdefault(job.server_id, deque())
            for i, old in enumerate(q):
                if old.target_key == job.target_key:
                    q[i] = job                      # 같은 대상의 낡은 작업은 새 것으로 바꾼다
                    self.coalesced += 1
                    self._cv.notify()
                    return
            if len(q) >= self._max:
                q.popleft()                          # 가득 차면 가장 오래된 것을 버린다(낡은 예측은 가치가 낮다)
                self.dropped += 1
            q.append(job)
            self._cv.notify()

    def _pick(self) -> Optional[Job]:
        for sid in list(self._qs):
            q = self._qs[sid]
            if q and sid not in self._busy:
                job = q.popleft()
                self._qs.move_to_end(sid)            # 방금 꺼낸 서버를 뒤로 → 돌아가며
                self._busy.add(sid)
                return job
        return None

    def get(self, timeout: Optional[float] = None) -> Optional[Job]:
        end = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            while True:
                if self._closed:
                    return None
                job = self._pick()
                if job:
                    return job
                left = None if end is None else end - time.monotonic()
                if left is not None and left <= 0:
                    return None
                self._cv.wait(left)

    def done(self, job: Job) -> None:
        with self._cv:
            self._busy.discard(job.server_id)
            self._cv.notify_all()

    def pending(self, server_id: Optional[str] = None) -> int:
        with self._cv:
            if server_id is not None:
                return len(self._qs.get(server_id, ()))
            return sum(len(q) for q in self._qs.values())

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()

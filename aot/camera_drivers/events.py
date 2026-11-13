# coding=utf-8
"""CameraEvent 인터페이스 (설계 §3.4). P1 은 값 객체만 둔다. 버스·디스패처는 P4."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class CameraEvent:
    camera_id: str
    kind: str                      # capabilities.EVENT_KINDS | 'unknown' | 'cv.<이름>'
    received_at_utc: datetime      # 서버 시각 — 판정은 이 값으로
    enhanced: str = ''             # '' | 'people' | 'vehicle'
    raw_type: str = ''
    camera_time_epoch: Optional[int] = None


@dataclass(frozen=True)
class Heartbeat:
    interval_s: int = 30


class CameraEventBus:
    """데몬 안의 메모리 큐(설계 §3.4). 상한을 넘기면 가장 오래된 것부터 버리고 버린 수를 센다.
    생산자(구독 스레드)는 기다리지 않는다. 소비자는 스레드 하나가 get() 으로 꺼낸다."""

    MAXSIZE = 1000

    def __init__(self, maxsize=None):
        import collections
        import threading
        self.maxsize = maxsize or self.MAXSIZE
        self._q = collections.deque()
        self._cond = threading.Condition()
        self.dropped = 0

    def publish(self, event):
        with self._cond:
            while len(self._q) >= self.maxsize:
                self._q.popleft()
                self.dropped += 1
            self._q.append(event)
            self._cond.notify()

    def get(self, timeout=1.0):
        with self._cond:
            if not self._q:
                self._cond.wait(timeout)
            return self._q.popleft() if self._q else None

    def __len__(self):
        with self._cond:
            return len(self._q)

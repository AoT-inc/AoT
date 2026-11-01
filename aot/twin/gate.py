# coding=utf-8
"""서비스가 보는 전역 설정 — 켜짐·잠금·실행 시각·하트비트 (배포 제안 §2·§3, S1 과의 접점).

정본은 S1 의 `aot.utils.twin_gate`(`twin_enabled`·`twin_supported`·`read_heartbeat`)와
`Misc.twin_enabled`·`Misc.twin_run_times`·`Misc.twin_heartbeat` 이다. 이 모듈은 그것을 감싸기만 한다:

- 서비스 코드는 `Gate` 하나만 안다 → 시험은 `FakeGate` 로 DB 없이 돈다.
- `aot.utils.twin_gate` 나 Misc 열이 아직 없으면(마이그레이션 전) **꺼짐**으로 본다 — 서비스는 떠 있어도 일하지 않는다.
- 잠금 판정은 서버 화면과 **같은 함수**(`twin_supported`)를 부른다(이중 잠금, 제안 §3).

flask·DB 는 호출 시점에만 import 한다(`import aot.twin.gate` 는 아무것도 끌어오지 않는다).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_RUN_TIMES = ("06:10", "18:10")          # 제안 §4 기본값(현지)

# 하트비트 status — S1 계약(`aot.utils.twin_gate` 머리말)의 어휘: running | idle | locked | error.
# 서비스 안의 상태는 더 잘게 가르지만, 쓰는 값은 이 넷뿐이다.
HB_STARTING = "idle"
HB_LOCKED = "locked"            # 낮은 사양 — 일하지 않는다
HB_DISABLED = "idle"            # 전역 플래그 꺼짐 — 플래그만 가끔 본다(S1: idle = 떠 있으나 꺼짐·대기)
HB_IDLE = "running"             # 켜짐, 다음 예약 시각을 기다림(S1: running = 정상 가동·계산 가능)
HB_RUNNING = "running"          # 회차 실행 중
HB_ERROR = "error"              # 켜짐, 마지막 회차에 실패가 있었다

# twin_gate.TWIN_HEARTBEAT_INTERVAL_S 와 같다(화면은 180 초 넘게 낡으면 "실행 중이 아님")
HEARTBEAT_INTERVAL_S = 60.0


def parse_run_times(raw) -> List[str]:
    """`Misc.twin_run_times` → ["HH:MM", …]. 문자열("06:10,18:10")·JSON 목록 문자열·목록 모두 받는다.
    비었거나 읽을 수 없으면 기본값."""
    from . import schedule as sch
    items: List[str] = []
    if isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    elif isinstance(raw, str) and raw.strip():
        s = raw.strip()
        if s.startswith("["):
            try:
                items = [str(x) for x in json.loads(s)]
            except ValueError:
                items = []
        else:
            items = [p for p in (x.strip() for x in s.replace(";", ",").split(",")) if p]
    try:
        parsed = sch.parse_run_at(items)
    except ValueError:
        logger.warning("트윈: 실행 시각 %r 를 읽을 수 없다 — 기본값 %s", raw, DEFAULT_RUN_TIMES)
        parsed = ()
    if not parsed:
        return list(DEFAULT_RUN_TIMES)
    return [f"{h:02d}:{m:02d}" for h, m in parsed]


class Gate:
    """서비스가 쓰는 네 가지. 실제 구현은 `DbGate`, 시험은 `FakeGate`."""

    def supported(self) -> Tuple[bool, Optional[str]]:
        raise NotImplementedError

    def enabled(self) -> bool:
        raise NotImplementedError

    def run_times(self) -> List[str]:
        raise NotImplementedError

    def write_heartbeat(self, hb: Dict[str, object]) -> None:
        raise NotImplementedError


@dataclass
class FakeGate(Gate):
    is_supported: bool = True
    locked_reason: Optional[str] = None
    is_enabled: bool = False
    times: List[str] = field(default_factory=lambda: list(DEFAULT_RUN_TIMES))
    beats: List[Dict[str, object]] = field(default_factory=list)
    calls: Dict[str, int] = field(default_factory=dict)

    def _count(self, k):
        self.calls[k] = self.calls.get(k, 0) + 1

    def supported(self):
        self._count("supported")
        return self.is_supported, (None if self.is_supported else (self.locked_reason or "low_spec"))

    def enabled(self):
        self._count("enabled")
        return self.is_enabled

    def run_times(self):
        self._count("run_times")
        return parse_run_times(self.times)

    def write_heartbeat(self, hb):
        self.beats.append(dict(hb))


_SHARED_APP = None


class LazyApp:
    """flask 앱은 필요할 때 한 번만 만든다 — 잠긴 기기(파이)에서는 앱 전체를 올리지 않는다.

    factory 없이 만든 것끼리는 **프로세스에 앱 하나**를 함께 쓴다 — 서비스의 대상 계획(DbCatalog)과 내장 통로의
    예보 계열 읽기(`EmbeddedSource.read_forecast`)가 앱을 두 번 올리지 않게."""

    def __init__(self, factory=None):
        self._factory = factory
        self._app = None

    def get(self):
        global _SHARED_APP
        if self._app is None:
            if self._factory is None:
                if _SHARED_APP is None:
                    from aot.aot_flask.app import create_app
                    _SHARED_APP = create_app()
                self._app = _SHARED_APP
            else:
                self._app = self._factory()
        return self._app


class DbGate(Gate):
    """이 기기의 DB(Misc) — 모두 `aot.utils.twin_gate`(S1 정본)를 거친다. 읽기 실패는 꺼짐으로 본다(원칙 1).

    twin_gate 는 앱 문맥 밖에서도 돈다(데몬식 독립 세션). 그래도 어떤 함수가 앱 문맥을 요구하면(RuntimeError)
    그때 앱을 만들어 다시 부른다 — 잠긴 기기에서는 앱 전체를 올리지 않는다."""

    def __init__(self, app: Optional[LazyApp] = None):
        self._app = app or LazyApp()

    @staticmethod
    def _tg():
        try:
            from aot.utils import twin_gate
            return twin_gate
        except ImportError:
            return None

    def _call(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except RuntimeError as e:                                # "Working outside of application context"
            if "context" not in str(e):
                raise
            with self._app.get().app_context():
                return fn(*a, **kw)

    def supported(self):
        tg = self._tg()
        if tg is None:
            return False, "twin_gate_missing"
        try:
            r = self._call(tg.twin_supported)
        except Exception as e:                                   # 판정 실패도 잠금
            logger.warning("트윈: 잠금 판정 실패: %s", e)
            return False, f"check_failed: {type(e).__name__}"
        if isinstance(r, tuple):
            ok, reason = bool(r[0]), (r[1] if len(r) > 1 else None)
        else:
            ok, reason = bool(r), None
        return ok, (None if ok else (reason or "low_spec"))

    def enabled(self):
        """플래그 AND 잠기지 않음(twin_gate.twin_enabled)."""
        tg = self._tg()
        if tg is None:
            return False
        try:
            return bool(self._call(tg.twin_enabled))
        except Exception as e:
            logger.warning("트윈: 플래그 읽기 실패 — 꺼짐으로 본다: %s", e)
            return False

    def run_times(self):
        tg = self._tg()
        try:
            raw = self._call(tg.run_times) if tg is not None else None
        except Exception as e:
            logger.warning("트윈: 실행 시각 읽기 실패 — 기본값: %s", e)
            raw = None
        return parse_run_times(raw)

    def write_heartbeat(self, hb):
        """`heartbeat()` 한 장(epoch 초) → twin_gate.write_heartbeat(at·last_run_at 은 ISO UTC 로 찍힌다)."""
        import datetime as _dt
        tg = self._tg()
        if tg is None:
            return

        def dt(t):
            return _dt.datetime.fromtimestamp(float(t), _dt.timezone.utc) if t else None
        try:
            self._call(tg.write_heartbeat, status=hb["status"], version=hb.get("version", ""),
                       sites=hb.get("sites", 0), plots=hb.get("plots", 0),
                       last_run_at=dt(hb.get("last_run_at")), failures=hb.get("failures", 0),
                       locked_reason=hb.get("locked_reason"), now=dt(hb.get("at")))
        except Exception as e:                                   # 하트비트 실패가 서비스를 멈추지 않는다
            logger.warning("트윈: 하트비트 쓰기 실패: %s", e)


def heartbeat(status: str, version: str, sites: int = 0, plots: int = 0,
              last_run_at: Optional[float] = None, failures: int = 0,
              locked_reason: Optional[str] = None, now: Optional[float] = None) -> Dict[str, object]:
    """하트비트 한 장(서비스 안의 모양 — 시각은 epoch 초). DB 에는 `DbGate` 가 ISO UTC 로 바꿔 쓴다."""
    return {"at": float(now if now is not None else time.time()), "status": status, "version": version,
            "sites": int(sites), "plots": int(plots),
            "last_run_at": (float(last_run_at) if last_run_at else None),
            "failures": int(failures), "locked_reason": locked_reason}

# coding=utf-8
"""배포형 서비스 `aot_twin` — 켜져 있을 때만 일하는 별도 프로세스 (배포 제안 §1·§2·§3·§5, S2).

    시작 ─ 잠금 판정(twin_supported) ─ 잠김 → 하트비트 locked 를 쓰고 일하지 않음(이중 잠금, 제안 §3)
                       — serve() 는 바로 돌아오고, 프로세스는 직접 설치면 exit 0, Docker 면 `sleep infinity`(__main__.park_if_locked)
      │
      └─ 루프: 플래그(twin_enabled)를 `poll_s` 마다 본다
           ├─ 꺼짐 → 하트비트 disabled, 아무것도 하지 않음(데이터는 지우지 않는다)
           └─ 켜짐 → 대상 계획(discovery.build_plan, `refresh_s` 마다 다시) → 대지마다 예약 시각에 실행
                      실행 시각 = Misc.twin_run_times(대지 현지) + 대지마다 몇 분씩 분산

- 통로는 **내장**이다: 같은 기기의 DB·Influx 를 직접 읽고 `env_twin*` 를 Influx 에 직접 쓴다
  (`sources.embedded`). 원격 REST·수신 API 는 개발용(`--config` JSON 경로)으로만 남는다.
- 어느 대지의 실패도 다른 대지·서비스를 멈추지 않는다(원칙 1). 실패한 대지는 `retry_s` 간격으로
  `max_retries` 번 다시 하되 다음 예약 시각을 넘지 않는다(`node.serve_scheduled` 와 같은 규칙).
- 하트비트 {at, status, version, sites, plots, last_run_at, failures, locked_reason} 를 `Misc.twin_heartbeat`
  에 `heartbeat_s`(60 초) 마다(상태가 바뀌면 바로) 쓴다 — 꺼져 있거나 잠겨 있어도. 설정 화면은 180 초 넘게
  낡으면 "서비스가 실행 중이 아님" 으로 본다(S1 계약). status 는 running·idle·locked·error 넷.

DB·flask 는 `DbGate`·`DbCatalog` 가 맡고, 이 모듈의 루프는 주입받은 것만 부른다 → 시험은 가짜로 돈다.
"""
from __future__ import annotations

import logging
import threading
import time
import zlib
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import bench, schedule as sched
from .scenario_queue import ScenarioQueue
from .scenario_run import run_scenario
from .discovery import SERVER_ID, SitePlan, SiteInfo, build_plan
from .gate import (Gate, HB_DISABLED, HB_ERROR, HB_IDLE, HB_LOCKED, HB_RUNNING, HB_STARTING,
                   HEARTBEAT_INTERVAL_S, heartbeat)
from .node import JobReport, TwinNode
from .settings import NodeSettings, ServerSettings

logger = logging.getLogger(__name__)


def stagger_minutes(site_id: str, window_min: int) -> int:
    """대지마다 고정된 분산(0 … window_min-1 분). id 의 해시라 대지가 늘거나 줄어도 남의 시각이 바뀌지 않는다."""
    if window_min <= 1:
        return 0
    return zlib.crc32(site_id.encode("utf-8")) % int(window_min)


def shifted_run_at(run_at: Sequence[str], minutes: int) -> Tuple[Tuple[int, int], ...]:
    """["06:10", …] 을 `minutes` 분 뒤로(자정을 넘으면 다음 날 같은 시각 — 하루 주기라 같다)."""
    out = []
    for h, m in sched.parse_run_at(run_at):
        t = (h * 60 + m + int(minutes)) % (24 * 60)
        out.append((t // 60, t % 60))
    return tuple(sorted(set(out)))


@dataclass
class ServiceSettings:
    poll_s: float = 60.0                  # 플래그를 보는 간격(꺼져 있을 때도) — '가끔'
    heartbeat_s: float = HEARTBEAT_INTERVAL_S   # 상태가 그대로여도 이 간격으로(화면은 180 초 넘게 낡으면 '멈춤')
    refresh_s: float = 3600.0             # 대상 계획(대지·구획·예보 메타)을 다시 읽는 간격
    stagger_window_min: int = 20          # 대지마다 0~19 분 분산
    run_on_enable: bool = True            # 켜지거나 기동한 직후 대지마다 한 번(분산 그대로) 따라잡기
    retry_s: float = 900.0
    max_retries: int = 4
    force_tier: Optional[str] = None
    scenario_poll_s: float = 10.0         # 켜져 있을 때 대기 중인 시나리오(what-if)를 보는 간격
    scenarios_per_step: int = 3           # 한 걸음에 돌리는 시나리오 수 — 정기 실행을 굶기지 않게


@dataclass
class _SiteState:
    plan: SitePlan
    run_at: Tuple[Tuple[int, int], ...]
    next_at: float
    retries: int = 0
    last_run_at: Optional[float] = None
    failures: int = 0                     # 마지막 회차에서 실패한 대상 수


ChannelFactory = Callable[[SitePlan], Tuple[object, object]]


def _embedded_channel(plan: SitePlan):
    from .gate import LazyApp
    from .sources.embedded import EmbeddedSink, EmbeddedSource
    return EmbeddedSource(SERVER_ID, plan.targets), EmbeddedSink(SERVER_ID, app=LazyApp())


class TwinService:
    def __init__(self, gate: Gate, sites: Callable[[], Sequence[SiteInfo]],
                 forecast_channels: Callable[[str], Sequence[Mapping]],
                 overrides: Callable[[], Mapping], version: str = "",
                 settings: Optional[ServiceSettings] = None,
                 channel_factory: ChannelFactory = _embedded_channel,
                 clock: Callable[[], float] = time.time,
                 prewarm: Optional[Callable[[], object]] = None,
                 scenarios: Optional[ScenarioQueue] = None):
        self.gate = gate
        self.scenarios = scenarios            # what-if 시나리오 대기열(없으면 시나리오를 돌리지 않는다)
        self._sites = sites
        self._forecast_channels = forecast_channels
        self._overrides = overrides
        self.version = version
        self.s = settings or ServiceSettings()
        self._channel = channel_factory
        self._clock = clock
        self._prewarm = prewarm               # 켜져 있을 때만, 걸음마다 부른다(스스로 칸당 한 번만 일한다)
        self._stop = threading.Event()
        self.locked_reason: Optional[str] = None
        self.capability: Optional[bench.Capability] = None
        self.state: Dict[str, _SiteState] = {}
        self._planned_at: Optional[float] = None
        self._run_times: List[str] = []
        self._was_enabled = False
        self._hb_status: Optional[str] = None
        self._hb_at = 0.0
        self.reports: List[JobReport] = []

    # ── 하트비트 ─────────────────────────────────────────────────────────
    def _beat(self, status: str, force: bool = False) -> None:
        now = self._clock()
        if not force and status == self._hb_status and now - self._hb_at < self.s.heartbeat_s:
            return
        last = max((st.last_run_at for st in self.state.values() if st.last_run_at), default=None)
        hb = heartbeat(status, self.version, sites=len(self.state),
                       plots=sum(len(st.plan.targets) for st in self.state.values()),
                       last_run_at=last, failures=sum(st.failures for st in self.state.values()),
                       locked_reason=self.locked_reason, now=now)
        self.gate.write_heartbeat(hb)
        self._hb_status, self._hb_at = status, now

    def _status(self) -> str:
        return HB_ERROR if any(st.failures for st in self.state.values()) else HB_IDLE

    # ── 계획 ─────────────────────────────────────────────────────────────
    def refresh_plan(self, now: float) -> None:
        """대상 계획을 다시 만든다. 대지마다 다음 실행 시각은 유지하고(새 대지는 따라잡기 또는 다음 예약)."""
        try:
            plans = build_plan(self._sites(), self._overrides(), self._forecast_channels)
        except Exception:
            logger.exception("트윈: 대상 계획 실패 — 이전 계획을 그대로 쓴다")
            self._planned_at = now
            return
        run_times = self.gate.run_times()
        new: Dict[str, _SiteState] = {}
        for p in plans:
            ra = shifted_run_at(run_times, stagger_minutes(p.site_id, self.s.stagger_window_min))
            old = self.state.get(p.site_id)
            if old is not None and old.run_at == ra:
                old.plan = p
                new[p.site_id] = old
                continue
            nxt = self._first_run(now, p, ra) if old is None else self._next(now, ra, p.timezone)
            new[p.site_id] = _SiteState(p, ra, nxt,
                                        last_run_at=old.last_run_at if old else None,
                                        failures=old.failures if old else 0)
            for n in p.notes:
                logger.info("트윈 대지 %s: %s", p.name or p.site_id, n)
        gone = set(self.state) - set(new)
        if gone:
            logger.info("트윈: 꺼진 대지 %d 곳 — 더 돌지 않는다(데이터는 그대로)", len(gone))
        self.state, self._planned_at, self._run_times = new, now, run_times
        logger.info("트윈 계획: 대지 %d · 구획 %d · 실행 시각 %s (대지마다 0~%d 분 분산)",
                    len(new), sum(len(s.plan.targets) for s in new.values()), ",".join(run_times),
                    max(0, self.s.stagger_window_min - 1))

    def _next(self, now: float, run_at, tz: str) -> float:
        try:
            return sched.next_run(now, run_at, tz)
        except Exception:                                          # 모르는 시간대 → UTC
            return sched.next_run(now, run_at, "UTC")

    def _first_run(self, now: float, plan: SitePlan, run_at) -> float:
        if self.s.run_on_enable:
            return now + 60.0 * stagger_minutes(plan.site_id, self.s.stagger_window_min) / 4.0
        return self._next(now, run_at, plan.timezone)

    # ── 실행 ─────────────────────────────────────────────────────────────
    def run_site(self, st: _SiteState) -> List[JobReport]:
        plan = st.plan
        if not plan.targets:
            return []
        ch = self._channel(plan)
        ns = NodeSettings(enabled=True, force_tier=self.s.force_tier,
                          servers=[ServerSettings(SERVER_ID, "embedded")])
        node = TwinNode(ns, channels={SERVER_ID: ch}, clock=self._clock)
        if self.capability is None:
            self.capability = node.startup_bench()
        node.capability = self.capability
        return node.run_once()

    def run_due(self, now: float) -> int:
        """예약 시각이 된 대지를 차례로 돌린다. 돌린 대지 수."""
        n = 0
        for sid in sorted(self.state, key=lambda k: self.state[k].next_at):
            st = self.state[sid]
            if st.next_at > now or self._stop.is_set():
                continue
            if not self.gate.enabled():                           # 회차 사이에 꺼졌으면 거기서 멈춘다
                return n
            self._beat(HB_RUNNING, force=True)
            try:
                reps = self.run_site(st)
            except Exception:
                logger.exception("트윈 대지 %s 실행 실패", sid)
                reps = None
            n += 1
            t = self._clock()
            self.reports.extend(reps or [])
            upcoming = self._next(t, st.run_at, st.plan.timezone)
            ok = reps is not None and all(r.error is None and r.rejected == 0 for r in reps)
            st.failures = 0 if ok else (len(st.plan.targets) if reps is None else
                                        sum(1 for r in reps if r.error is not None or r.rejected))
            if ok:
                st.last_run_at, st.retries, st.next_at = t, 0, upcoming
                logger.info("트윈 대지 %s: %d 건 완료, 다음 %s", st.plan.name or sid, len(reps),
                            time.strftime("%m-%d %H:%M", time.localtime(upcoming)))
            elif st.retries < self.s.max_retries:
                st.retries += 1
                st.next_at = min(t + self.s.retry_s, upcoming)
                logger.warning("트윈 대지 %s: 실패 %d 건(%d/%d) — 다시", sid, st.failures, st.retries,
                               self.s.max_retries)
            else:
                logger.error("트윈 대지 %s: %d 번 연속 실패 — 다음 예약 시각까지 쉰다", sid, st.retries + 1)
                st.retries, st.next_at = 0, upcoming
                st.last_run_at = t
        return n

    # ── what-if 시나리오 ──────────────────────────────────────────────────
    def _find_target(self, kind: str, target_id: str):
        """계획에서 (종류, 대상 id) 의 대상과 그 대지 상태를 찾는다."""
        for st in self.state.values():
            for t in st.plan.targets:
                if t.kind.value == kind and t.target_id == target_id:
                    return st, t
        return None, None

    def _capability_for(self, st: _SiteState):
        """정기 실행과 같은 능력 판정(앙상블 크기·지평) — 시나리오가 기본 예측과 같은 조건으로 돈다."""
        if self.capability is None:
            node = TwinNode(NodeSettings(enabled=True, force_tier=self.s.force_tier,
                                         servers=[ServerSettings(SERVER_ID, "embedded")]),
                            channels={SERVER_ID: self._channel(st.plan)}, clock=self._clock)
            self.capability = node.startup_bench()
        return self.capability

    def run_scenario_once(self, scn: Dict[str, object]) -> bool:
        """꺼낸 시나리오 한 건을 돌려 결과를 대기열에 적는다 → 성공 여부. 어떤 실패도 서비스로 번지지 않는다."""
        sid = str(scn.get("id"))
        tgt = scn.get("target") or {}
        kind, tid = str(tgt.get("kind")), str(tgt.get("id"))
        try:
            st, spec = self._find_target(kind, tid)
            if spec is None and self._clock() - (self._planned_at or 0.0) > 60.0:
                self.refresh_plan(self._clock())               # 방금 켠 대상일 수 있다
                st, spec = self._find_target(kind, tid)
            if spec is None:
                self.scenarios.failed(sid, "트윈 대상이 아님(꺼져 있거나 계획에 없음)")
                return False
            src, sink = self._channel(st.plan)
            cap = self._capability_for(st)
            out = run_scenario(spec, src, sink, cap, self._clock(), self.scenarios.prepare(scn), period_s=cap.period_s)
        except Exception as e:                                  # noqa: BLE001
            logger.exception("트윈 시나리오 %s 실행 실패", sid)
            self.scenarios.failed(sid, "%s: %s" % (type(e).__name__, e))
            return False
        if out.ok:
            self.scenarios.done(sid, out)
            logger.info("트윈 시나리오 %s: 완료(%s %s, 점 %d)", sid, kind, tid[:8], out.points)
        else:
            self.scenarios.failed(sid, out.reason)
            logger.warning("트윈 시나리오 %s: 실패 — %s", sid, out.reason)
        return out.ok

    def run_scenarios(self) -> int:
        """대기 중인 시나리오를 오래된 것부터 `scenarios_per_step` 건까지. 돌린 수."""
        if self.scenarios is None:
            return 0
        n = 0
        while n < self.s.scenarios_per_step and not self._stop.is_set():
            if not self.gate.enabled():
                break
            try:
                scn = self.scenarios.claim()
            except Exception:                                   # noqa: BLE001 — DB 가 잠깐 안 되어도 서비스는 산다
                logger.exception("트윈 시나리오 대기열 읽기 실패")
                break
            if scn is None:
                break
            self._beat(HB_RUNNING, force=True)
            self.run_scenario_once(scn)
            n += 1
        return n

    # ── 한 걸음 / 루프 ───────────────────────────────────────────────────
    def step(self) -> float:
        """한 번 둘러본다. 다음에 깰 때까지 쉴 초를 돌려준다."""
        now = self._clock()
        if self.locked_reason is not None:
            self._beat(HB_LOCKED)
            return self.s.heartbeat_s
        if not self.gate.enabled():
            if self._was_enabled:
                logger.info("트윈: 꺼졌다 — 일하지 않고 플래그만 본다")
            self._was_enabled = False
            self.state.clear()
            self._planned_at = None
            self._beat(HB_DISABLED)
            return min(self.s.poll_s, self.s.heartbeat_s)
        if not self._was_enabled:
            logger.info("트윈: 켜졌다 — 대상 계획을 만든다")
            self._was_enabled = True
        if (self._planned_at is None or now - self._planned_at >= self.s.refresh_s
                or self.gate.run_times() != self._run_times):
            self.refresh_plan(now)
        if self._prewarm is not None:
            try:
                self._prewarm()
            except Exception:                                      # 미리 채우기 실패가 트윈을 멈추지 않는다
                logger.exception("예보 계열 미리 채우기 실패")
        self._beat(self._status())
        self.run_due(now)
        ran = self.run_scenarios()
        self._beat(self._status(), force=(bool(self.reports) or bool(ran)) and self._hb_status == HB_RUNNING)
        now = self._clock()
        nxt = min((st.next_at for st in self.state.values()), default=now + self.s.poll_s)
        wait = min(self.s.poll_s, self.s.heartbeat_s, nxt - now)
        if self.scenarios is not None:
            wait = min(wait, self.s.scenario_poll_s)
        return max(1.0, wait)

    def start(self) -> bool:
        """시작 시 잠금 판정. 잠겼으면 False(일하지 않는다)."""
        self._beat(HB_STARTING, force=True)
        ok, reason = self.gate.supported()
        if not ok:
            self.locked_reason = reason or "low_spec"
            logger.warning("트윈: 이 기기는 잠겨 있다(%s) — 일하지 않고 종료한다(다시 시작하지 않는다)",
                           self.locked_reason)
            self._beat(HB_LOCKED, force=True)
            return False
        if self.scenarios is not None:                          # 잠기지 않은 기기에서만 DB 를 연다
            try:
                self.scenarios.recover()
            except Exception:                                   # noqa: BLE001
                logger.exception("트윈 시나리오: 멈춘 작업 복구 실패")
        return True

    def serve(self, max_steps: Optional[int] = None) -> int:
        """상주. 잠긴 기기는 하트비트 `locked` 를 쓴 뒤 바로 돌아온다. 잠금은 기기 고정값(파이 모델·기기 메모리)이라
        다시 떠도 같은 결과다. 돌아온 뒤의 프로세스 처리는 `__main__.park_if_locked` 가 한다 — 직접 설치(systemd
        `Restart=on-failure`)는 exit 0 으로 끝나 되살아나지 않고, Docker(`restart: unless-stopped`)는 종료하면
        무한 재시작하므로 `sleep infinity` 로 바뀐다(docker `on-failure` 는 재부팅 뒤 안 돌아오므로 쓰지 않는다).
        화면은 낡아 가는 `locked` 하트비트가 아니라 앱 쪽 `twin_supported` 로 '잠김' 을 보인다."""
        if not self.start():
            return 0
        steps = 0
        while not self._stop.is_set() and (max_steps is None or steps < max_steps):
            try:
                wait = self.step()
            except Exception:                                      # 어떤 실패도 프로세스를 죽이지 않는다
                logger.exception("트윈 서비스 한 걸음 실패")
                wait = self.s.poll_s
            steps += 1
            if max_steps is not None and steps >= max_steps:
                break
            self._wait(wait)
        return steps

    def _wait(self, seconds: float) -> None:
        end = self._clock() + seconds
        while not self._stop.is_set():
            left = end - self._clock()
            if left <= 0:
                return
            self._stop.wait(min(left, 30.0))

    def run_all_once(self) -> List[JobReport]:
        """`--once`: 잠금·플래그를 지키고, 켜진 대지를 예약과 무관하게 한 번씩."""
        if not self.start():
            return []
        if not self.gate.enabled():
            self._beat(HB_DISABLED, force=True)
            return []
        now = self._clock()
        self.refresh_plan(now)
        for st in self.state.values():
            st.next_at = now
        self.run_due(now)
        self._beat(self._status(), force=True)
        return list(self.reports)

    def stop(self) -> None:
        self._stop.set()


def _prewarm_forecast_series(app):
    """대지 예보 계열 캐시를 미리 채운다 — 일별 사다리가 Influx 를 40번 읽는 0.7~1.1초를 실행 시각에 겪지 않게.
    켜져 있고 잠기지 않은 걸음에서만 불리므로 잠긴 기기에서는 앱을 올리지 않는다."""
    from aot.space import forecast_series
    return forecast_series.prewarm_if_new_window(app.get())


def build_db_service(overrides_path: Optional[str] = None, settings: Optional[ServiceSettings] = None):
    """이 기기의 DB 로 서비스를 조립한다. flask 앱(구획·도형 조회용)은 켜져 있고 잠기지 않았을 때 처음
    대상 계획을 만들 때 한 번 만든다 — 잠긴 기기에서는 앱을 올리지 않는다."""
    from aot.config import AOT_VERSION

    from .discovery import DbCatalog, combine, load_overrides
    from .gate import DbGate, LazyApp
    from .scenario_queue import DbScenarioQueue

    app = LazyApp()
    cat = DbCatalog(app)
    # 정본은 DB 의 대지·구획 트윈 설정(S3). 개발용 JSON 은 명시했을 때만 그 위에 겹친다.
    return TwinService(DbGate(app), cat.sites, cat.forecast_channels,
                       overrides=lambda: combine(cat.overrides(), load_overrides(overrides_path)),
                       version=str(AOT_VERSION),
                       settings=settings,
                       prewarm=lambda: _prewarm_forecast_series(app),
                       scenarios=DbScenarioQueue(app))

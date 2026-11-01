# coding=utf-8
"""TwinNode — 설정 → 통로 조립 → 시작 시 벤치 → 서버별 큐 → 실행 → 쓰기.

원칙 1: 어떤 실패도 노드 밖으로 번지지 않는다. 서버가 안 닿으면 그 서버만 건너뛰고,
결과에는 유효기한이 붙어 있어 노드가 멈추면 소비자가 알아서 무시한다.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import bench, engine, models, schedule as sched
from .interfaces import TwinModel, TwinSink, TwinSource
from .output import flatten, run_act_points
from .queue import Job, ServerQueues
from .settings import NodeSettings, ServerSettings
from .sources.remote import RemoteSink, RemoteSource, RestClient
from .types import Status, TargetSpec

logger = logging.getLogger(__name__)

Channel = Tuple[TwinSource, TwinSink]


@dataclass
class JobReport:
    server_id: str
    target_key: tuple
    status: Optional[Status]
    reason: str = ""
    points: int = 0
    written: int = 0
    rejected: int = 0
    error: Optional[str] = None
    elapsed_s: float = 0.0
    info: Dict[str, object] = field(default_factory=dict)      # 모델 요약 + 앞 7 일 띠(사람용)


def _bands(out, days: int = 8) -> Dict[str, object]:
    """발행 하나의 앞 며칠 p10/p50/p90 (노지 `theta_sensor`·`theta_root`, 시설 `T`) — 기록·CLI 용."""
    if out is None:
        return {}
    for grid, var in (("daily", "theta_sensor"), ("daily", "theta_root"), ("fast", "T")):
        q = out.quantiles.get(grid, {}).get(var)
        if q:
            n = min(days, len(out.grids[grid]))
            return {"band_var": var, "band_t": [float(t) for t in out.grids[grid][:n]],
                    "band": {k: [round(float(v), 2) for v in q[k][:n]] for k in ("p10", "p50", "p90") if k in q}}
    return {}


def build_channel(s: ServerSettings, env=None, remote_write: bool = False) -> Optional[Channel]:
    """서버 설정 하나 → (소스, 싱크). off 면 None.

    remote_write: 원격 싱크의 쓰기를 켠다 — 시험(계약을 받는 가짜 서버)만 쓴다. 설정에는 칸이 없다(원격 쓰기는
    비활성, `sources.remote.REMOTE_WRITE_DISABLED`).
    """
    if s.mode == "off":
        return None
    if s.mode == "embedded":
        from .sources.embedded import EmbeddedSink, EmbeddedSource     # 지연 import: flask·DB 필요
        return EmbeddedSource(s.server_id, s.targets), EmbeddedSink(s.server_id)
    client = RestClient(s.url, s.api_key(env), timeout_s=s.timeout_s, verify_tls=s.verify_tls)
    return (RemoteSource(s.server_id, client, s.targets, s.ping_path),
            RemoteSink(s.server_id, client, s.ingest_path, write_enabled=remote_write))


class TwinNode:
    def __init__(self, settings: NodeSettings, channels: Optional[Dict[str, Channel]] = None,
                 clock: Callable[[], float] = time.time, env=None, remote_write: bool = False):
        settings.validate()
        self.settings = settings
        self._clock = clock
        self.channels: Dict[str, Channel] = channels if channels is not None else {}
        if channels is None:
            for s in settings.servers:
                ch = build_channel(s, env, remote_write=remote_write)
                if ch:
                    self.channels[s.server_id] = ch
        self.queues = ServerQueues()
        self.capability = bench.FULL
        self.reports: List[JobReport] = []
        self._targets: Dict[tuple, TargetSpec] = {}
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()

    # ── 시작: 벤치 → 기능 축소 (원칙 5) ───────────────────────────────
    def startup_bench(self) -> bench.Capability:
        forced = bench.forced(self.settings.force_tier, self.settings.period_s)
        if forced:
            self.capability = forced
            return forced
        n = max(1, sum(len(src.list_targets()) for src, _ in self.channels.values()))
        spec = next((t for src, _ in self.channels.values() for t in src.list_targets()), None)
        kind = spec.kind.value if spec else "facility"
        model = models.get(kind, (spec.options.get("model") if spec else None))
        plan = engine.GRID_PLANS[spec.kind if spec else engine.TargetKind.FACILITY][0]
        x0 = model.init_state(spec, 0.0, {}) if spec else {}
        per = bench.measure(lambda: engine.run_member_fn(model, x0, {}, {}, plan, plan.n_points(1.0)))
        self.capability = bench.decide(per, n_targets=n, period_s=self.settings.period_s)
        logger.info("트윈 벤치: 멤버 1개 %.3fs → %s (앙상블 %d, 지평 %.0f%%, 주기 %.0fs)",
                    per, self.capability.tier, self.capability.ensemble_size,
                    self.capability.horizon_frac * 100, self.capability.period_s)
        return self.capability

    # ── 한 번 돌리기 ────────────────────────────────────────────────
    def enqueue_all(self) -> int:
        """각 서버의 대상마다 작업을 큐에 넣는다. 서버가 안 닿으면 그 서버는 건너뛴다."""
        n = 0
        for sid, (src, _) in self.channels.items():
            try:
                if not src.ping():
                    logger.warning("트윈: 서버 %s 응답 없음 — 이번 주기 건너뜀", sid)
                    continue
                targets = src.list_targets()
            except Exception as e:
                logger.warning("트윈: 서버 %s 점검 실패: %s", sid, e)
                continue
            for t in targets:
                self._targets[t.key] = t
                self.queues.put(Job(sid, t.key, self._clock()))
                n += 1
        return n

    def process(self, job: Job) -> JobReport:
        spec = self._targets[job.target_key]
        src, sink = self.channels[job.server_id]
        rep = JobReport(job.server_id, job.target_key, None)
        t_start = time.time()
        try:
            name = spec.options.get("model")
            model: TwinModel = models.get(spec.kind.value, name)
            res = engine.run_target(spec, src, model, self.capability, self._clock(),
                                    period_s=self.capability.period_s)
            rep.status, rep.reason = res.status, res.reason
            rep.elapsed_s = time.time() - t_start
            rep.info = dict(res.info)
            rep.info.update(_bands(res.output))
            pts = run_act_points(res.output, res.act) + flatten(res.output)   # 작동 시계열(과거 상태 + 앞날 계획) 먼저, 머리말은 마지막
            rep.info["effects"] = list(res.effects)
            rep.points = len(pts)
            wr = sink.write(pts)
            rep.written, rep.rejected, rep.error = wr.written, wr.rejected, wr.error
        except Exception as e:                                         # 번지지 않게 가둔다
            logger.exception("트윈 작업 실패 %s", job.target_key)
            rep.error = f"{type(e).__name__}: {e}"
        with self._lock:
            self.reports.append(rep)
        return rep

    def drain(self, max_jobs: int = 10_000) -> List[JobReport]:
        """큐를 비울 때까지 현재 스레드에서 처리(시험·단발 실행용)."""
        out = []
        for _ in range(max_jobs):
            job = self.queues.get(timeout=0)
            if job is None:
                break
            try:
                out.append(self.process(job))
            finally:
                self.queues.done(job)
        return out

    def run_once(self) -> List[JobReport]:
        self.enqueue_all()
        return self.drain()

    # ── 상시 실행 ───────────────────────────────────────────────────
    def _worker(self):
        while not self._stop.is_set():
            job = self.queues.get(timeout=1.0)
            if job is None:
                continue
            try:
                self.process(job)
            finally:
                self.queues.done(job)

    # ── 정기 실행: 벽시계 시각에 한 번씩 (하루 1~2회) ───────────────────────────
    @staticmethod
    def cycle_ok(reps: List[JobReport]) -> bool:
        """이번 회차를 다시 해 볼 필요가 없는가. 서버가 안 닿아 한 건도 못 돌았거나, 오류·쓰기 거부가 있으면 아니다.
        UNSYNCED·NOT_TWINNABLE 은 정상 결과다(머리말이 발행된다) — 다시 해도 같으니 재시도하지 않는다."""
        return bool(reps) and all(r.error is None and r.rejected == 0 for r in reps)

    def _wait_until(self, t: float) -> None:
        """`t`(epoch) 까지 쉰다. 시계가 건너뛰어도 따라가도록 짧게 끊어 기다린다."""
        while not self._stop.is_set():
            left = t - self._clock()
            if left <= 0:
                return
            self._stop.wait(min(left, 60.0))

    def serve_scheduled(self, max_cycles: Optional[int] = None) -> int:
        """`schedule.run_at` 시각마다 `run_once()`. 실패하면 `retry_s` 간격으로 `max_retries` 번 다시 하고
        그래도 안 되면 다음 예약 시각까지 쉰다. 작업은 이 스레드에서 차례로 돈다(워커 스레드 없음)."""
        sc = self.settings.schedule
        run_at = sched.parse_run_at(sc.run_at)
        self.startup_bench()
        nxt = self._clock() if sc.run_on_start else sched.next_run(self._clock(), run_at, sc.timezone)
        retries, cycles = 0, 0
        while not self._stop.is_set() and (max_cycles is None or cycles < max_cycles):
            self._wait_until(nxt)
            if self._stop.is_set():
                break
            try:
                reps = self.run_once()
            except Exception:                                              # 노드 밖으로 번지지 않게
                logger.exception("트윈 정기 실행 실패")
                reps = []
            cycles += 1
            now = self._clock()
            upcoming = sched.next_run(now, run_at, sc.timezone)
            if self.cycle_ok(reps):
                logger.info("트윈 정기 실행 완료: %d 건, 다음 %s", len(reps),
                            time.strftime("%m-%d %H:%M", time.localtime(upcoming)))
                retries, nxt = 0, upcoming
            elif retries < sc.max_retries:
                retries += 1
                nxt = min(now + sc.retry_s, upcoming)
                logger.warning("트윈 정기 실행 실패(%d/%d) — %.0f 초 뒤 다시", retries, sc.max_retries, nxt - now)
            else:
                logger.error("트윈 정기 실행이 %d 번 연속 실패 — 다음 예약 시각까지 쉰다", retries + 1)
                retries, nxt = 0, upcoming
        return cycles

    def serve(self):
        if self.settings.schedule.run_at:
            try:
                self.serve_scheduled()
            finally:
                self.stop()
            return
        self.startup_bench()
        for i in range(max(1, self.settings.workers)):
            th = threading.Thread(target=self._worker, name=f"twin-worker-{i}", daemon=True)
            th.start()
            self._threads.append(th)
        try:
            while not self._stop.is_set():
                self.enqueue_all()
                self._stop.wait(self.capability.period_s)
        finally:
            self.stop()

    def stop(self):
        self._stop.set()
        self.queues.close()

# coding=utf-8
"""물 결과를 저장하는 예약 작업 — 데몬이 시간마다 부른다(`aot_daemon.timer_water_net`).

**닫힌 것만 쓴다.** 켠 실행은 끝난 시각이 정시(`H`)를 넘기 전이면 진행 중이라 쓰지 않고, 하루는 그 날이
끝나고 `CLOSE_GRACE_S`(12시간)가 지났으며 그 날 켠 실행이 전부 끝났을 때만 닫힌다(기록은 꺼질 때 찍힌다).
그래서 어제의 `water_day` 는 다음 날 정오가 지나서 생긴다. 닫힌 날에만 일 합계(`water_day`)를 쓰고, 그 점이 있는
날을 일지가 저장값으로 읽는다(`water_net_link.plot_water`). 진행 중인 날은 읽을 때 계산한다.

* 계산은 `plot_water(full=True, stored=False)` 하나다 — 일지가 읽을 때 푸는 함수와 같다.
* **멱등:** 이미 저장된 `(구획, 장치, 켠 시각)` 은 다시 쓰지 않고, 닫힌 날은 건너뛴다. 돌려도 값이
  같고, 도면을 바꾼 뒤에도 과거 실행은 그때의 `network_rev` 로 남는다.
* 데몬 재시작·장애로 놓친 날은 `CATCHUP_DAYS` 까지만 따라잡는다. 그보다 오래된 빈 날은 일지가 읽을
  때 계산하고, 저장하려면 수동 백필(`aot/scripts/water_backfill.py`)을 쓴다. 자동으로 돌지 않는다.
* 제어 루프를 막지 않도록 낮은 우선순위 스레드에서 한 구획씩 돈다. 끄려면 `AOT_WATER_JOB=0`.
"""
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from aot.functions.utils.water_net import result as R

logger = logging.getLogger('aot.water_job')

CATCHUP_DAYS = 3
# 하루를 닫기 전에 기다리는 시간. `duration_time` 은 **꺼질 때** 켠 시각으로 찍혀서(`base_output.py`,
# `runtime.get_operational_intervals`) 켜져 있는 동안의 실행은 아직 보이지 않는다. 자정 직후에 닫으면 그날 밤
# 켜서 돌고 있던 실행이 나중에 도착해도 닫힌 날이 건너뛰어져 저장에서 영구히 빠진다. 실측(사본 60일 5,912건):
# 최대 9.6시간, p99 1.5시간이라 12시간을 둔다. **그보다 오래 도는 실행이 자정을 넘기면 그 날에서 빠진다**(한계).
CLOSE_GRACE_S = R.CLOSE_GRACE_S
_run_lock = threading.Lock()


def enabled() -> bool:
    return os.environ.get('AOT_WATER_JOB', '1') != '0'


def _text(epoch) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def closed_horizon(now) -> float:
    """닫힌 것으로 치는 시각 — 지금을 정시로 내린 값."""
    return int(now // 3600) * 3600.0


def plots_to_store(since_day: date, plot_ids=None) -> list:
    """저장할 구획. 끝난 구획은 따라잡을 기간 안에 끝난 것만."""
    from aot.databases.models import GeoPlot

    query = GeoPlot.query
    if plot_ids:
        query = query.filter(GeoPlot.unique_id.in_(list(plot_ids)))
    return [p for p in query.all() if p.ended_on is None or p.ended_on >= since_day]


def store_day(plot, day: date, tz, now, write=True) -> dict:
    """구획의 하루를 푼다 → 요약. 닫혔으면 실행과 일 합계를 쓰고, 아니면 닫힌 실행만 쓴다."""
    from aot.utils import water_store
    from aot.utils.water_net_link import plot_water

    a, b = water_store.day_bounds(day, tz)
    horizon = closed_horizon(now)
    end = min(b, horizon)
    out = {'plot': plot.unique_id, 'day': day.isoformat(), 'runs_written': 0, 'closed': False,
           'skipped': None}
    if end <= a:
        out['skipped'] = 'future'
        return out
    water = plot_water(plot, _text(a), _text(end), tz, full=True, stored=False)
    if water.result is None:
        out['skipped'] = 'no-flow' if not water.flows else 'unsolved'
        return out
    rows = water.result['runs']
    done = [r for r in rows if r['t1'] <= horizon]
    kept = {(r['output_id'], round(r['t0'])): r for r in water_store.read_runs(plot.unique_id, a, b)}
    fresh = [r for r in done if (r['output_id'], round(r['t0'])) not in kept]
    out['runs'] = len(done)
    out['closed'] = b + CLOSE_GRACE_S <= horizon and len(done) == len(rows)
    if write and fresh:
        water_store.write_runs(plot.unique_id, fresh, now=now)
    out['runs_written'] = len(fresh)
    if out['closed']:
        merged = [kept.get((r['output_id'], round(r['t0'])), r) for r in done]
        values = R.day_values(merged, water.tally, water.area_m2)
        out['litres'] = values.get(0, 0.0)
        out['design_litres'] = values.get(1, 0.0)
        revs = {r.get('network_rev') for r in merged if r.get('fed')}
        rev = R.MIXED_REV if len(revs) > 1 else (next(iter(revs)) if revs else '')
        if write:
            water_store.write_day(plot.unique_id, a, values, rev)
    return out


def process_plot(plot, now=None, since_day: Optional[date] = None, until_day: Optional[date] = None,
                 write=True) -> List[dict]:
    """구획의 ``[since_day, until_day]`` 중 닫히지 않은 날을 차례로 푼다. 이미 닫힌 날은 건너뛴다."""
    from aot.utils import water_store
    from aot.utils.timekit import tz_of
    from aot.utils.timekit import to_tz

    now = time.time() if now is None else float(now)
    tz = tz_of(plot.unique_id)
    today = to_tz(datetime.fromtimestamp(now, timezone.utc), tz).date()
    until_day = min(until_day or today, today)
    since_day = since_day or (today - timedelta(days=CATCHUP_DAYS))
    if plot.started_on and since_day < plot.started_on:
        since_day = plot.started_on
    if plot.ended_on and until_day > plot.ended_on:
        until_day = plot.ended_on
    if until_day < since_day:
        return []
    first = water_store.day_bounds(since_day, tz)[0]
    last = water_store.day_bounds(until_day, tz)[1]
    closed = set(water_store.read_days(plot.unique_id, first, last))
    out = []
    day = since_day
    while day <= until_day:
        if round(water_store.day_bounds(day, tz)[0]) not in closed:
            out.append(store_day(plot, day, tz, now, write=write))
        day += timedelta(days=1)
    return out


def run_due(now=None, since_day: Optional[date] = None, plot_ids=None, write=True,
            skip_busy=True, sleep_between=0.2) -> List[dict]:
    """모든 구획을 한 번씩 훑는다 → 하루 요약들. 앱 컨텍스트 안에서 부른다. 이미 돌고 있으면 빈 목록."""
    from aot.utils.fc_cal import job as load

    if not _run_lock.acquire(blocking=False):
        return []
    try:
        now = time.time() if now is None else float(now)
        since = since_day or (datetime.fromtimestamp(now, timezone.utc).date()
                              - timedelta(days=CATCHUP_DAYS + 1))
        out = []
        judged = False
        for plot in plots_to_store(since, plot_ids):
            # 첫 구획 앞에서 한 번만 본다(구획마다 보면 이 작업 자신의 CPU 로 남은 구획을
            # 미루고, 미룸 상한이 구획마다 새로 세어져 N 구획에 N×6시간이 걸린다).
            if skip_busy and not judged:
                judged = True
                if load.busy('water_job'):
                    break                               # 미룬 까닭은 resource_pressure 가 남긴다
            try:
                out.extend(process_plot(plot, now, since_day, write=write))
            except Exception:                               # noqa: BLE001 — 한 구획의 오류가 다른 구획을 막지 않는다
                logger.exception('[water_job] 구획 저장 실패: %s', getattr(plot, 'unique_id', None))
                try:
                    from aot.aot_flask.extensions import db
                    db.session.rollback()
                except Exception:                           # noqa: BLE001
                    pass
            if sleep_between:
                time.sleep(sleep_between)
        return out
    finally:
        _run_lock.release()


def run_in_thread(app):
    """데몬이 부르는 진입 — 낮은 우선순위 스레드에서 `run_due` 를 돌린다(이미 돌고 있으면 새로 안 띄운다)."""
    if not enabled() or _run_lock.locked():
        return None

    def _target():
        from aot.utils.fc_cal import job as load

        load.lower_priority()
        try:
            with app.app_context():
                done = run_due()
                wrote = sum(d.get('runs_written', 0) for d in done)
                logger.info('[water_job] %d일 처리, 실행 %d건 저장, 닫힌 날 %d', len(done), wrote,
                            sum(1 for d in done if d.get('closed')))
        except Exception:                                   # noqa: BLE001
            logger.exception('[water_job] 예약 작업 실패')

    t = threading.Thread(target=_target, name='water_net_store', daemon=True)
    t.start()
    return t

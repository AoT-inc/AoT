# coding=utf-8
"""물 결과 저장 — 측정 `water_run`(실행별, `aot_calc`)·`water_day`(일 합계, `aot_hist`).

모양과 채널 번호는 `water_net.result` 가 정한다(단일 출처). 여기는 Influx 에 쓰고 읽는 일만 한다.

* 실행은 **켠 시각**에 `output_id` 태그와 함께 쓴다. 같은 구획·같은 장치·같은 시각은 이미 있으면
  다시 쓰지 않는다 — 도면이 바뀐 뒤에도 과거 값은 그때의 `network_rev` 로 남는다.
* 일 합계는 **닫힌 날에만** 쓴다. 점이 있다는 것이 "이 날은 저장값으로 읽어도 된다" 는 표식이다.
* `aot_calc` 의 보존(기본 60일)보다 오래된 실행은 쓰지 않는다 — 보존 밖의 점은 Influx 가 거절한다.
  그보다 오래된 날은 일 합계만 남고, 일지는 그 날을 읽을 때 계산한다.
* 읽기·쓰기 모두 호출하는 쪽이 실패를 삼킬 수 있게 예외를 그대로 올린다.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from aot.functions.utils.water_net import result as R
from aot.utils.fc_store import Pt

logger = logging.getLogger('aot.water_store')

NO_REV = 'none'


def _write(points) -> int:
    if not points:
        return 0
    from aot.utils import influx
    return int(influx.write_influxdb_points(points))


def run_keep_seconds() -> float:
    """`water_run` 을 쓸 수 있는 가장 오래된 시각까지의 길이(초). 하루 여유를 둔다."""
    from aot.utils import influx_layers
    days = influx_layers.desired_retention_days().get(influx_layers.LAYER_CALC, 60)
    return max(1, int(days) - 1) * 86400.0


def run_points(plot_id, rows) -> List[Pt]:
    out = []
    for row in rows:
        tags = R.run_tags(row)
        tags['network_rev'] = tags['network_rev'] or NO_REV
        for ch, value in R.run_values(row).items():
            out.append(Pt(R.M_RUN, str(plot_id), ch, float(row['t0']), value, tags))
    return out


def write_runs(plot_id, rows, now=None) -> int:
    """실행들을 쓴다 → 쓴 점 수. 보존 밖의 오래된 실행은 건너뛴다."""
    floor = (now if now is not None else datetime.now(timezone.utc).timestamp()) - run_keep_seconds()
    return _write(run_points(plot_id, [r for r in rows if r['t0'] >= floor]))


def read_runs(plot_id, t0, t1) -> List[dict]:
    """``t0 <= 켠 시각 < t1`` 인 저장된 실행 → 실행 칸들(시각순).

    같은 장치·같은 시각이 두 도면 판으로 남아 있으면 먼저 읽은 것 하나만 쓴다.
    """
    from aot.utils import influx

    points = influx.read_layer_points(R.M_RUN, str(plot_id), {}, t0, t1 - 0.001)
    grouped: Dict[tuple, dict] = {}
    for ts, value, tags in points:
        try:
            channel = int(tags.get('channel'))
        except (TypeError, ValueError):
            continue
        key = (round(ts), tags.get('output_id'), tags.get('network_rev'))
        box = grouped.setdefault(key, {'ts': ts, 'tags': tags, 'values': {}})
        box['values'][channel] = value
    seen = set()
    rows = []
    for key in sorted(grouped, key=lambda k: (k[0], str(k[1]))):
        if key[:2] in seen:
            continue
        seen.add(key[:2])
        box = grouped[key]
        rows.append(R.run_from_stored(box['ts'], box['tags'], box['values']))
    return rows


def write_day(plot_id, day_epoch, values, rev) -> int:
    """닫힌 하루의 합계 → 쓴 점 수."""
    tags = {'network_rev': rev or NO_REV, 'level': R.LEVEL_L0, 'basis': R.BASIS_DESIGN}
    return _write([Pt(R.M_DAY, str(plot_id), ch, float(day_epoch), float(v), tags)
                   for ch, v in values.items()])


def read_days(plot_id, t0, t1) -> Dict[int, dict]:
    """``t0 <= 날짜 0시 < t1`` 인 닫힌 날 → ``{0시 epoch: {'values': {채널: 값}, 'network_rev'}}``."""
    from aot.utils import influx

    out: Dict[int, dict] = {}
    for ts, value, tags in influx.read_layer_points(R.M_DAY, str(plot_id), {}, t0, t1 - 0.001):
        try:
            channel = int(tags.get('channel'))
        except (TypeError, ValueError):
            continue
        box = out.setdefault(round(ts), {'values': {}, 'network_rev': tags.get('network_rev')})
        box['values'][channel] = value
    return out


def day_bounds(day, tz):
    """현지 날짜 → UTC epoch ``(0시, 다음 0시)``."""
    from aot.utils.timekit import local_day_bounds_utc
    a, b = local_day_bounds_utc(day, day, tz)
    return _epoch(a), _epoch(b)


def _epoch(text) -> float:
    return datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()


def local_days(t0, t1, tz) -> list:
    """``[t0, t1)`` 에 **통째로** 들어가는 현지 날짜들 — 걸친 날은 뺀다."""
    from aot.utils.timekit import to_tz

    day = to_tz(datetime.fromtimestamp(t0, timezone.utc), tz).date()
    out = []
    for _ in range(4000):
        a, b = day_bounds(day, tz)
        if b > t1:
            break
        if a >= t0:
            out.append(day)
        day += timedelta(days=1)
    return out


def covered_days(plot_id, t0, t1, tz) -> Dict[object, dict]:
    """``[t0, t1)`` 안의 닫힌 날 → ``{날짜: 일 합계}``. 보존 밖으로 지워진 실행의 날은 뺀다."""
    now = datetime.now(timezone.utc).timestamp()
    wanted = [d for d in local_days(t0, t1, tz) if day_bounds(d, tz)[0] >= now - run_keep_seconds()]
    if not wanted:
        return {}
    first, last = day_bounds(wanted[0], tz)[0], day_bounds(wanted[-1], tz)[1]
    marks = read_days(plot_id, first, last)
    out = {}
    for day in wanted:
        box = marks.get(round(day_bounds(day, tz)[0]))
        if box is not None:
            out[day] = box
    return out

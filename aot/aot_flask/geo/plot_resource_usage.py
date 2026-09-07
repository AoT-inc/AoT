# coding=utf-8
"""구획의 자원 장치가 **얼마나 돌았고 물이 얼마나 나갔나** — 모달 [현황]용.

[현황]의 자원 칸은 지금까지 "무엇이 그 역할을 맡는가"(함수 이름)와 "지금 도는가"
까지만 말했다. 그런데 물을 주는 일에서 사람이 실제로 묻는 것은 그 다음이다 —
**오늘 얼마나 줬나.** 그 답이 화면에 없으면 밸브를 찾아 이력을 눌러 보거나 일지를
뽑아야 하는데, 둘 다 "오늘 물 줬던가" 를 확인하려고 할 일이 아니다.

일지(`geo/journal`)가 이미 그 답을 낸다. 여기서 하는 일은 **같은 정본을 같은
방식으로 이어 붙이는 것뿐**이다:

| 무엇 | 정본 |
|------|------|
| 이 구획에 닿는 출력 | `plot_context.actuators_for_plot` |
| 얼마나 돌았나 | `runtime.get_operational_seconds_by_day` |
| 물이 얼마나 나갔나 | `plot_journal.irrigation_flow_for_plot` |

⚠ **여기서 새 판정을 만들지 말 것.** 특히 "이 구획의 장치가 무엇인가" 와 "노즐이
  몇 개인가" 는 각각 한 벌씩만 있어야 한다 — 갈라지면 일지와 모달이 같은 밸브에
  **다른 물량**을 적는데, 그 어긋남은 에러가 아니라 그럴듯한 숫자로 나타난다.

## 무엇이 관수인지는 **판정하지 않는다 — 사람이 밝힌 것만 믿는다**

`Output` 에는 "관수/난방" 같은 의미 분류가 없다(`output_type` 은 통신방식이다).
그래서 근거를 사람이 밝힌 것 하나로 한정한다 — **시설 피팅의 종류**
(`plot_context.resource_fitting_kinds()`, `irrigation_status` 가 쓰는 것과 같은
어휘). 종류가 그 명부에 없는 시설 장치(측창·환풍기 …)는 자원이 아니므로 뺀다 —
넣으면 [자원] 칸이 그 시설의 액추에이터 목록이 되고, 정작 물 이야기가 묻힌다.

⚠ **노지의 영역 밸브(`kind=None`)는 빼지 않는다.** 노지에는 "이 출력이 관수다"
  를 말해 주는 어휘가 아직 없어서(`functions_for_role` 의 `no-facility`) 종류로
  거를 수가 없다 — 실측(김제)에서 영역에 묶인 출력은 전부 범용 on/off 였다.
  거기서는 일지와 같은 규칙을 쓴다: **가동시간은 닿는 장치 전부에 대해 싣고**
  물량은 설계 유량을 아는 장치에만 붙인다. 화면 문구를 "관수했다" 로 쓰지 말 것.

프로그램이 `role='irrigation'` 으로 선언한 것이 있으면 그 사실만 `roles` 로
표시한다(선언이지 판정이 아니다).

## 물량은 추정이다

설계 유량(시설의 배관 도면 · 노지 지도의 이미터) × 가동시간 × 구획 몫이고
유량계 실측이 아니다. 화면이 늘 그렇게 말해야 한다 — 실측과 같은 신뢰도로
읽히면 사람이 그 숫자로 시비 농도를 정한다.

## 0 과 "기록 없음" 은 다르다

`get_operational_seconds_by_day` 는 기록이 없는 버킷을 **빼고** 준다. 창 안에
버킷이 하나도 없는 장치는 `has_records=False` 로 낸다 — 그것을 `0` 으로 찍으면
"오늘 안 줬다"(사실)와 "이 장치의 기록이 아예 없다"(확인이 필요한 상태)가 같은
얼굴이 된다.
"""
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

#: 창 길이. 화면 문구(`Last 7 days`)가 이 숫자를 글자로 갖고 있으므로 바꾸려면
#: 문구도 함께 바꿔야 한다 — 번역 문구에 치환자를 두지 않기 위해서다.
WINDOW_DAYS = 7


def usage_for_plot(plot, days=WINDOW_DAYS):
    """구획 → 자원 장치의 가동시간·물량.

    ::

        {'days', 'today', 'unassigned_areas',
         'devices': [{'output_id', 'name', 'roles',
                      'seconds_today', 'seconds_window',
                      'litres_today', 'litres_window',
                      'share', 'source', 'has_records'}],
         'totals': {'seconds_today', 'seconds_window',
                    'litres_today', 'litres_window', 'share',
                    'water_partial', 'has_records', 'estimated'}}

    ⚠ 물량 합에 유량 근거가 없는 장치는 **빠진다**. 빠졌다는 사실을
      (`water_partial`) 함께 말하지 않으면 그 합이 전체인 줄로 읽힌다.
    """
    from aot.aot_flask.geo import plot_context
    from aot.utils.device_tz import resolve_location_tz
    from aot.utils.timekit import as_tz, local_day_bounds_utc

    empty = {'days': days, 'today': None, 'unassigned_areas': 0,
             'devices': [], 'totals': _fold([])}
    if plot is None:
        return empty

    try:
        actuators, unassigned = plot_context.actuators_for_plot(plot)
    except Exception:                                       # noqa: BLE001
        logger.exception('[자원사용] 구획 액추에이터 조회 실패')
        return empty
    if not actuators:
        return dict(empty, unassigned_areas=unassigned)

    tz = as_tz(resolve_location_tz(getattr(plot, 'unique_id', None)))
    today = _today_in(tz)
    start = today - timedelta(days=max(int(days), 1) - 1)
    start_str, end_str = local_day_bounds_utc(start, today, tz)

    flows = _flows_for(plot)
    roles = _roles_by_output(plot)
    kinds = plot_context.resource_fitting_kinds()

    devices = []
    seen = set()
    for a in actuators:
        oid = a.get('output_id')
        kind = a.get('kind')
        # 종류를 아는데 자원 어휘가 아니면 뺀다(측창·환풍기 …). 종류를 모르는
        # 것(노지 영역 밸브)은 남긴다 — 위 문단의 이유다.
        if kind is not None and kind not in kinds:
            continue
        # 같은 출력이 두 경로로 올 수 있다(노지 영역 + 시설 피팅). 두 번 세면
        # 가동시간도 물량도 두 배가 되는데, 숫자가 그럴듯해서 티가 안 난다.
        if not oid or oid in seen:
            continue
        seen.add(oid)
        by_day = _seconds_by_day(oid, start_str, end_str, tz)
        devices.append(_device_row(oid, a.get('name'), by_day, today,
                                   flows.get(oid), roles.get(oid)))
    devices.sort(key=lambda d: (str(d.get('name') or ''), d['output_id']))
    return {'days': days, 'today': today.isoformat(),
            'unassigned_areas': unassigned,
            'devices': devices, 'totals': _fold(devices)}


def _today_in(tz):
    """그 구획의 **현지 오늘**. 서버 날짜로 판정하면 자정 전후가 어긋난다."""
    from datetime import datetime

    import pytz

    return datetime.now(pytz.utc).astimezone(tz).date()


def _roles_by_output(plot):
    """프로그램이 **선언한** 역할 → `{output_id: [역할, …]}`.

    판정이 아니라 선언이다 — "이 장치가 관수다" 가 아니라 "이 단계는 관수를
    요구하고, 이 자리에서 그 역할로 잡히는 것이 이 장치다". 못 찾으면 비운다.
    """
    from aot.aot_flask.geo import plot_context

    try:
        stage = plot_context.stage_of(plot)
    except Exception:                                       # noqa: BLE001
        logger.debug('[자원사용] 단계 조회 실패', exc_info=True)
        return {}
    out = {}
    for r in ((stage or {}).get('resources') or []):
        role = r.get('role')
        if not role or not r.get('found'):
            continue
        try:
            outputs, reason = plot_context.outputs_for_role(role, plot)
        except Exception:                                   # noqa: BLE001
            logger.debug('[자원사용] 역할 출력 조회 실패(%s)', role,
                         exc_info=True)
            continue
        if reason != 'ok':
            continue
        for oid in outputs:
            out.setdefault(oid, []).append(role)
    return out


def _flows_for(plot):
    """설계 유량 → `{output_id: {'lph', 'share', 'source'}}`. 실패하면 `{}`.

    일지와 **같은 함수**다. 여기서 다시 세면 같은 밸브의 물량이 화면마다
    달라지는데, 이 저장소는 이미 그 실패(노즐 계수 규칙 두 벌)로 크게 데었다.
    """
    from aot.aot_flask.geo.plot_journal import irrigation_flow_for_plot

    try:
        return irrigation_flow_for_plot(plot) or {}
    except Exception:                                       # noqa: BLE001
        logger.debug('[자원사용] 설계 유량 조회 실패', exc_info=True)
        return {}


def _seconds_by_day(output_id, start_str, end_str, tz):
    """출력 하나의 `{date: 초}`. 채널은 0 이다(`actuators_for_plot` 가 채널을
    내지 않는다 — 그쪽 주석이 이 사실을 밝히라고 적어 두었다)."""
    from aot.utils.runtime import get_operational_seconds_by_day

    try:
        return get_operational_seconds_by_day(
            output_id, start_str, end_str, tz=tz, granularity='day') or {}
    except Exception:                                       # noqa: BLE001
        logger.debug('[자원사용] 가동시간 조회 실패(%s)', output_id,
                     exc_info=True)
        return {}


def _device_row(output_id, name, by_day, today, flow, roles):
    secs_today = float(by_day.get(today) or 0.0)
    secs_window = float(sum(by_day.values()))
    row = {
        'output_id': output_id,
        'name': name,
        'roles': sorted(roles or []),
        'seconds_today': int(round(secs_today)),
        'seconds_window': int(round(secs_window)),
        'has_records': bool(by_day),
        'litres_today': None,
        'litres_window': None,
        'share': None,
        'source': None,
    }
    lph = (flow or {}).get('lph')
    if lph:
        share = float(flow.get('share', 1.0) or 1.0)
        row['share'] = share
        row['source'] = flow.get('source')
        row['litres_today'] = round(secs_today / 3600.0 * float(lph) * share, 1)
        row['litres_window'] = round(
            secs_window / 3600.0 * float(lph) * share, 1)
    return row


def _fold(devices):
    """장치 행들 → 합계.

    ⚠ 물량 합에는 유량 근거가 있는 장치만 든다. 근거가 없는 장치를 0 으로
      더하면 그 합이 전체인 줄로 읽히므로 `water_partial` 로 함께 말한다.
    """
    with_water = [d for d in devices if d['litres_window'] is not None]
    has_water = bool(with_water)
    # 몫은 **전부 같을 때만** 낸다. 서로 다른 몫을 하나로 적으면 그 숫자가 어느
    # 장치의 것인지 알 수 없는데, 화면은 그것을 전체의 몫으로 읽는다.
    shares = {d['share'] for d in with_water}
    return {
        'seconds_today': sum(d['seconds_today'] for d in devices),
        'seconds_window': sum(d['seconds_window'] for d in devices),
        'litres_today': (round(sum(d['litres_today'] for d in with_water), 1)
                         if has_water else None),
        'litres_window': (round(sum(d['litres_window'] for d in with_water), 1)
                          if has_water else None),
        'share': shares.pop() if len(shares) == 1 else None,
        'water_partial': has_water and len(with_water) != len(devices),
        'has_records': any(d['has_records'] for d in devices),
        # 유량계 실측이 아니다 — 화면이 늘 그렇게 말해야 한다.
        'estimated': has_water,
    }

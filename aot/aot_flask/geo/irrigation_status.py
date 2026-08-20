# coding=utf-8
"""마지막 관수가 언제였나 — 노지에서 가장 자주 하는 판단.

"오늘 물을 줬던가" 는 화면을 열자마자 답이 나와야 하는 질문인데, 지금은
장치 목록에서 밸브를 찾아 이력을 눌러 봐야 알 수 있다.

## **무엇이 관수인지 시스템이 아는 경우에만 센다**

노지에서 영역에 묶인 출력은 대부분 범용 on/off 다 — 그 장치가 물을 주는지
빛을 주는지 시스템은 모른다(`plot_context.valves_for_plot` 주석 참조: 김제
실측에서 전부 `virtual_on_off_single` 이었다). 그것을 "관수" 라고 부르면
화면이 없는 사실을 지어내는 것이 된다.

그래서 근거를 **사람이 종류를 밝힌 둘**로 한정한다:

1. **시설의 관수 피팅** — `irrigation_valve`/`irrigation_layer` 로 배치된 것
2. **프로그램 단계가 선언한 관수 함수**(P6, `role='irrigation'`) → 그 함수의
   액션이 켜는 출력

둘 다 사람이 "이건 관수다" 라고 말해 둔 것이라, 화면이 그렇게 불러도 된다.
근거가 없으면 **아무 말도 하지 않는다**(`source=None`).
"""
import logging

logger = logging.getLogger(__name__)

_IRRIGATION_FITTING_KINDS = ('irrigation_valve', 'irrigation_layer')
_LOOKBACK_DAYS = 30


def _outputs_from_facility(facility_uuid):
    """시설에 배치된 관수 피팅의 출력 uuid 집합."""
    if not facility_uuid:
        return set()
    try:
        from aot.databases.models import GeoFacility
        fac = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    except Exception as exc:                                # noqa: BLE001
        logger.debug('[irrigation] 시설 조회 실패: %s', exc)
        return set()
    out = set()
    for f in ((fac.fittings if fac else None) or []):
        if not isinstance(f, dict):
            continue
        if f.get('kind') in _IRRIGATION_FITTING_KINDS and f.get('actuator_id'):
            out.add(f['actuator_id'])
    return out


def _outputs_from_plot_program(plot):
    """구획의 현재 단계가 **관수로 선언한** 함수가 켜는 출력 uuid 집합.

    선언은 P6 의 역할(`resource_defs` + 단계 덮어쓰기)이고, 그 역할을 맡는 함수는
    현장이 기하로 푼다(`plot_context.functions_for_role`). 그 함수의 액션
    (`function_actions.do_unique_id`)이 가리키는 출력을 본다 — 함수가 무엇을
    켜는지는 그 표가 정본이다.
    """
    if plot is None:
        return set()
    try:
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import Actions
    except Exception:                                       # noqa: BLE001
        return set()
    st = plot_context.stage_of(plot)
    if not st or st.get('state') != 'running':
        return set()
    # P6 재설계(2026-08-20): 단계는 역할만 선언하고 함수는 현장이 푼다. 그래서
    # 여기 오는 것은 이미 **이 자리에서 찾힌** 함수 목록이다.
    fn_ids = []
    for r in (st.get('resources') or []):
        if r.get('role') != 'irrigation' or not r.get('found'):
            continue
        for fn in (r.get('functions') or []):
            if fn.get('id'):
                fn_ids.append(fn['id'])
    if not fn_ids:
        return set()
    out = set()
    try:
        rows = Actions.query.filter(Actions.function_id.in_(fn_ids)).all()
    except Exception as exc:                                # noqa: BLE001
        logger.debug('[irrigation] 액션 조회 실패: %s', exc)
        return set()
    for a in rows:
        ref = (a.do_unique_id or '').strip()
        if ref:
            # 'uuid,channel' 형태도 온다 — 출력 uuid 만 본다.
            out.add(ref.split(',')[0])
    return out


def _last_run(output_uuid):
    """그 출력이 마지막으로 켜진 시각과 지속 시간 → (epoch|None, sec|None)."""
    try:
        from aot.utils import runtime
        started = runtime.get_started_at(output_uuid, 0,
                                         lookback_days=_LOOKBACK_DAYS)
        dur = runtime.get_last_duration(output_uuid, 0,
                                        lookback_days=_LOOKBACK_DAYS)
        return started, dur
    except Exception as exc:                                # noqa: BLE001
        logger.debug('[irrigation] 이력 조회 실패(%s): %s', output_uuid, exc)
        return None, None


def last_irrigation(facility_uuid=None, plot=None):
    """마지막 관수 → dict|None.

    `{'at': epoch, 'hours_ago': float, 'duration_s': int|None,
      'device': 이름, 'source': 'facility'|'program'}`

    근거가 없으면 **None** — "관수 기록 없음" 이라고 말하지 않는다. 기록이
    없는 것과 무엇이 관수인지 모르는 것은 다르고, 뒤쪽을 앞쪽처럼 말하면
    사용자는 장치가 안 돈 줄 안다.
    """
    import time

    outs = {}
    for oid in _outputs_from_facility(facility_uuid):
        outs[oid] = 'facility'
    for oid in _outputs_from_plot_program(plot):
        outs.setdefault(oid, 'program')
    if not outs:
        return None

    best = None
    for oid, source in outs.items():
        at, dur = _last_run(oid)
        if not at:
            continue
        if best is None or at > best['at']:
            best = {'at': at, 'duration_s': int(dur) if dur else None,
                    'output_uuid': oid, 'source': source}
    if best is None:
        # 관수 장치는 있는데 30일 안에 기록이 없다 — 그것도 사실이다.
        return {'at': None, 'hours_ago': None, 'duration_s': None,
                'device': None, 'source': list(outs.values())[0]}

    try:
        from aot.databases.models import Output
        row = Output.query.filter_by(unique_id=best['output_uuid']).first()
        best['device'] = row.name if row else None
    except Exception:                                       # noqa: BLE001
        best['device'] = None
    best['hours_ago'] = round((time.time() - best['at']) / 3600.0, 1)
    best.pop('output_uuid', None)
    return best

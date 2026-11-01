# coding=utf-8
"""MCP 읽기 도구의 응답 계약을 실제 DB 로 점검한다(읽기 전용).

2026-10-08~09 외부 AI(Sonnet) 점검을 네 차례 돌며 고친 것들이 다시 깨지지 않았는지를
사람이 대화로 확인하지 않고 한 번에 본다. 단위 테스트는 가짜 데이터로 규칙을 고정하고,
이 검사는 **지금 이 설치의 실제 데이터**로 응답을 만들어 본다 — 데이터가 늘거나
바뀌어서 깨지는 것(응답 상한·이름 겹침 등)은 단위 테스트가 못 본다.

검사 6종:
  utc-time        측정·장치 시각에 '+00:00'·'Z'·epoch 숫자가 섞이지 않는가
  cap-structure   상한에 걸려도 트리 children·요약 sensors 가 통째로 빠지지 않는가(+여유)
  id-agreement    트리 장치 ID 가 실제 장치이고, 시설 ID 두 개가 도구 사이에 맞는가
  ambiguity       두 곳 이상인 이름을 읽기 도구가 하나로 고르지 않고 되묻는가
  pressure-unit   기상 입력(OWM·KMA)의 기압 단위가 kPa 인가
  forecast-mark   예보 모델 입력이 요약·날씨에서 data_origin='model' 로 표시되는가

    python3 -m aot.scripts.check_mcp_contract           # 사람이 읽는 출력
    python3 -m aot.scripts.check_mcp_contract --json    # 기계 판독

종료 0=정상, 1=문제 발견, 2=검사 실패. 쓰기·제어 도구는 부르지 않는다.
"""

import argparse
import json
import re
import sys

_UTC_ISO = re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)(?!\d)')
#: 'Z' 만 보는 판 — 농장 시간대가 UTC+0 이면(영국 겨울 등) '+00:00' 이 정상 현지 표기다.
_Z_ISO = re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z(?!\w)')
#: 응답 상한 대비 이 비율을 넘으면 '여유 부족' 으로 경고한다(실패는 아니다).
_MARGIN_WARN = 0.85


class Memo:
    """같은 조회를 검사마다 다시 부르지 않는다 — 구역 센서 요약·장치 신선도는
    장치 수만큼 시계열을 읽어 한 번에 수 초가 든다(처음 짠 판이 67초였다)."""

    def __init__(self, S):
        self.S, self._got = S, {}

    def get(self, key, fn):
        if key not in self._got:
            self._got[key] = fn()
        return self._got[key]

    def zone_summary(self):
        return self.get('zone', lambda: self.S.get_zone_sensor_summary())

    def tree(self, full=False):
        return self.get('tree0' if full else 'tree', lambda: (
            self.S.get_spatial_tree(depth=0) if full else self.S.get_spatial_tree()))

    def control(self):
        return self.get('control', lambda: self.S.get_control_state())


class Report:
    def __init__(self):
        self.items = []

    def add(self, check, ok, detail, level='error'):
        self.items.append({'check': check, 'ok': bool(ok),
                           'level': 'ok' if ok else level, 'detail': detail})

    @property
    def failed(self):
        return [i for i in self.items if i['level'] == 'error']


def _walk(obj, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, '%s.%s' % (path, k) if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, '%s[%d]' % (path, i))
    else:
        yield path, obj


def _farm_is_utc():
    from datetime import datetime
    from aot.utils.device_tz import resolve_location_tz
    try:
        return datetime.now(resolve_location_tz(None)).utcoffset().total_seconds() == 0
    except Exception:                                       # noqa: BLE001
        return False


def check_utc_time(S, rep, M, farm_is_utc=None):
    """도구 응답 어디에도 UTC 표기 시각이 없어야 한다(장치·장소 현지로 바뀐다)."""
    if farm_is_utc is None:
        farm_is_utc = _farm_is_utc()
    pattern = _Z_ISO if farm_is_utc else _UTC_ISO
    calls = {
        'get_zone_sensor_summary()': lambda: M.zone_summary(),
        'get_control_state()': lambda: M.control(),
        'get_device_freshness()': lambda: S.get_device_freshness(),
        'get_anomalies()': lambda: S.get_anomalies(),
    }
    for name, fn in calls.items():
        try:
            out = fn()
        except Exception as e:                              # noqa: BLE001
            rep.add('utc-time', False, '%s 실패: %s' % (name, e))
            continue
        bad = [p for p, v in _walk(out)
               if isinstance(v, str) and pattern.search(v)]
        bad += [p for p, v in _walk(out)
                if p.endswith('.ts') and isinstance(v, (int, float))]
        rep.add('utc-time', not bad,
                '%s: %s' % (name, ('UTC/epoch 시각 %d곳: %s' % (len(bad), ', '.join(bad[:4])))
                            if bad else '현지 시각만'))


def check_cap_structure(S, rep, M):
    """상한에 걸려도 구조가 남는가 — 지금 크기와 여유도 함께 본다."""
    from aot.tools.tool_execution import (_MAX_RESPONSE_TOKENS, _cap_result,
                                          _estimate_tokens)
    import copy
    cases = (('get_spatial_tree(depth=0)', lambda: copy.deepcopy(M.tree(full=True)),
              'hierarchy', 'children'),
             ('get_spatial_tree()', lambda: copy.deepcopy(M.tree()), 'hierarchy', 'children'),
             ('get_zone_sensor_summary()', lambda: copy.deepcopy(M.zone_summary()),
              'zones', 'sensors'))
    for name, fn, top, sub in cases:
        try:
            raw = fn()
        except Exception as e:                              # noqa: BLE001
            rep.add('cap-structure', False, '%s 실패: %s' % (name, e))
            continue
        tokens = _estimate_tokens(json.dumps(raw, ensure_ascii=False))
        capped = _cap_result(raw, name, max_tokens=_MAX_RESPONSE_TOKENS)
        stripped = sub in (capped.get('%s_fields_omitted' % top) or '')
        rep.add('cap-structure', not stripped,
                '%s: %d토큰/상한 %d — %s' % (
                    name, tokens, _MAX_RESPONSE_TOKENS,
                    '하위 목록이 통째로 빠짐' if stripped else '구조 유지'))
        if not stripped and tokens > _MAX_RESPONSE_TOKENS * _MARGIN_WARN:
            rep.add('cap-structure', False,
                    '%s: 상한의 %d%% — 여유가 적다(뒤쪽 항목부터 잘린다)'
                    % (name, int(100 * tokens / _MAX_RESPONSE_TOKENS)), level='warn')


def check_id_agreement(S, rep, M):
    from aot.databases.models import (Conditional, CustomController, Function,
                                      GeoFacility, Input, Output, PID, Trigger)
    real = set()
    for m in (Input, Output, CustomController, Function, PID, Trigger, Conditional):
        real |= {r[0] for r in m.query.with_entities(m.unique_id).all()}
    tree = M.tree(full=True).get('hierarchy') or []
    dev_nodes, fac_nodes = [], []

    def walk(ns):
        for n in ns:
            if n.get('type') in ('aot_device', 'device'):
                dev_nodes.append(n)
            elif n.get('type') == 'facility':
                fac_nodes.append(n)
            walk(n.get('children') or [])
    walk(tree)
    ghosts = [n['name'] for n in dev_nodes if n.get('unique_id') not in real]
    rep.add('id-agreement', not ghosts,
            '트리 장치 %d개 중 실제 장치 ID 가 아닌 것 %d개%s' % (
                len(dev_nodes), len(ghosts),
                (' (지도 참조가 지워진 장치를 가리킴: %s)' % ', '.join(ghosts[:4])) if ghosts else ''),
            level='warn')
    shape_of = {f.unique_id: f.shape_uuid for f in GeoFacility.query.all()}
    wrong = [n['name'] for n in fac_nodes
             if n.get('facility_id') and shape_of.get(n['facility_id']) != n['unique_id']]
    rep.add('id-agreement', not wrong,
            '트리 시설 %d곳의 facility_id ↔ 도형 ID%s' % (
                len(fac_nodes), (' 불일치: %s' % ', '.join(wrong)) if wrong else ' 일치'))
    cs = M.control().get('coordinators') or []
    bad = []
    for c in cs:
        place = c.get('facility_place_id')
        if c.get('facility_id') and place:
            again = S.get_control_state(facility_id=place).get('coordinators') or []
            if not any(x.get('function_id') == c['function_id'] for x in again):
                bad.append(c.get('facility_name'))
    rep.add('id-agreement', not bad,
            '제어 상태 %d개를 트리의 시설 ID 로 다시 찾기%s' % (
                len(cs), (' 실패: %s' % ', '.join(bad)) if bad else ' — 모두 찾음'))


def check_ambiguity(S, rep, M):
    """두 곳 이상인 장소 이름 하나를 골라 세 도구가 되묻는지 본다."""
    tree = M.tree().get('hierarchy') or []
    named = []

    def walk(ns):
        for n in ns:
            if n.get('use_name') or n.get('map'):
                named.append(n['name'])
            walk(n.get('children') or [])
    walk(tree)
    if not named:
        rep.add('ambiguity', True, '이름이 겹치는 장소가 없어 건너뜀')
        return
    name = sorted(set(named))[0]
    for label, fn in (('resolve_target', lambda: S.resolve_target_tool(target_name=name)),
                      ('search_devices', lambda: S.search_devices(query=name)),
                      ('get_weather', lambda: S.get_weather_tool(zone_name=name))):
        try:
            out = fn()
        except Exception as e:                              # noqa: BLE001
            rep.add('ambiguity', False, '%s(%r) 실패: %s' % (label, name, e))
            continue
        asked = out.get('status') == 'needs_disambiguation'
        rep.add('ambiguity', asked, '%s(%r): %s' % (
            label, name, '후보를 돌려줌' if asked else '하나로 정함(되묻지 않음)'))


def check_pressure_unit(S, rep, M):
    from aot.databases.models import DeviceMeasurements, Input
    drivers = ('OPENWEATHERMAP_CALL_WEATHER', 'OPENWEATHERMAP_CALL_ONECALL', 'KMA_weather_500')
    rows = (DeviceMeasurements.query.join(
        Input, Input.unique_id == DeviceMeasurements.device_id)
        .filter(Input.device.in_(drivers), DeviceMeasurements.measurement == 'pressure')
        .with_entities(Input.name, DeviceMeasurements.unit,
                       DeviceMeasurements.conversion_id).all())
    bad = [n for n, u, conv in rows if u != 'kPa' and not conv]
    rep.add('pressure-unit', not bad, '기상 입력 기압 %d개%s' % (
        len(rows), (' 중 kPa 아님: %s' % ', '.join(bad)) if bad else ' 모두 kPa'))


def check_forecast_mark(S, rep, M):
    from aot.databases.models import Input
    from aot.utils.inputs import model_input_drivers
    models = model_input_drivers()
    if not models:
        rep.add('forecast-mark', False, "data_origin='model' 을 선언한 드라이버가 없다")
        return
    model_ids = {r[0] for r in Input.query.filter(Input.device.in_(list(models)))
                 .with_entities(Input.unique_id).all()}
    out = M.zone_summary()
    seen = [d for z in out.get('zones') or [] for d in z.get('sensors') or []
            if d.get('device_id') in model_ids]
    unmarked = [d['device_name'] for d in seen if d.get('data_origin') != 'model']
    rep.add('forecast-mark', not unmarked, '요약에 나온 예보 장치 %d개%s' % (
        len(seen), (' 중 표시 없음: %s' % ', '.join(unmarked)) if unmarked else ' 모두 표시'))


CHECKS = (check_utc_time, check_cap_structure, check_id_agreement,
          check_ambiguity, check_pressure_unit, check_forecast_mark)


def run(S):
    rep, memo = Report(), Memo(S)
    for fn in CHECKS:
        try:
            fn(S, rep, memo)
        except Exception as e:                              # noqa: BLE001
            rep.add(fn.__name__.replace('check_', '').replace('_', '-'), False,
                    '검사 자체가 실패: %s' % e)
    return rep


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    from aot.start_flask_ui import app

    # 요청 컨텍스트 안에서 돈다 — 도구는 실제로 요청 안에서 불리고, 드라이버
    # 목록처럼 번역 문자열을 만드는 경로는 요청 밖에서 다르게(실패로) 동작한다.
    with app.test_request_context():
        try:
            from aot.tools.aot_data_tool_service import AoTDataToolService as S
            import aot.ai.services.tool_providers as tp
            tp.bind_all()
            rep = run(S)
        except Exception as exc:                            # noqa: BLE001
            print('ERROR: 검사 실패 — %s' % exc, file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps({'items': rep.items, 'failed': len(rep.failed)},
                         ensure_ascii=False, indent=1))
    else:
        mark = {'ok': 'OK  ', 'warn': 'WARN', 'error': 'FAIL'}
        for i in rep.items:
            print('%s [%s] %s' % (mark[i['level']], i['check'], i['detail']))
        print('\n문제 %d건' % len(rep.failed) if rep.failed else '\n문제 없음')
    return 1 if rep.failed else 0


if __name__ == '__main__':
    sys.exit(main())

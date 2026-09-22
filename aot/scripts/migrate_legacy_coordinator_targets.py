# coding=utf-8
"""코디네이터 옵션에 남은 옛 목표(VPD·CO₂·DLI·GDD·시작일)를 프로그램·구획으로 옮긴다.

## 왜 필요한가

`fe6e37b4`(2026-08-19)가 env_coordinator 옵션에서 `target_vpd`·`vpd_sp_type`·
`vpd_method_id`·`target_co2`·`co2_sp_type`·`co2_method_id`·`dli_target`·
`gdd_target_daily`·`schedule_start_time` 을 **이관 코드 없이** 뺐다(근거: "배포
서버 중 쓰는 곳이 하나도 없어"). 그 전제가 틀렸다 — 적어도 현장 서버 하나가
VPD Method 곡선(DailyMultiPoint)으로 제어하고 있었다.

이제 목표는 **시설 구획(GeoPlot)의 프로그램(GeoProgram) 단계**에서만 온다
(`coordinator_plot.control_targets`). 구획이 없는 시설의 코디네이터는 업그레이드
뒤 목표가 조용히 **guide 범위 중앙값**으로 바뀌고, 그 값을 향해 장비를 능동적으로
움직인다. CO₂ 축은 통째로 빠진다. 에러도 로그도 화면 경고도 없다.

옛 키는 옵션 JSON 에 **그대로 남아 있다**(저장 화면이 다시 쓰기 전까지). 이
스크립트가 그 값을 읽어 프로그램 하나 + 시설 구획 하나를 만든다.

## 대응 (옛 코드의 해석을 그대로 따른다 — `fe6e37b4^` 의 `_helpers_mixin`)

    vpd_sp_type='method' + vpd_method_id   →  프로그램 targets_methods.vpd
    vpd_sp_type='static' + target_vpd > 0  →  단계 targets.vpd
    co2_sp_type='method' + co2_method_id   →  프로그램 targets_methods.co2
    co2_sp_type='static' + target_co2 > 0  →  단계 targets.co2
    dli_target > 0                         →  단계 targets.dli
    gdd_target_daily > 0                   →  프로그램 photosynthesis.gdd_daily
    schedule_start_time(날짜)              →  구획 started_on

- **곡선을 쓰던 축의 숫자(`target_vpd`)는 옮기지 않는다.** 옛 코드는 method 일 때
  그 값을 읽지 않았다(곡선이 실패하면 마지막 곡선 값을 붙들었다). 옮겨 두면 지금
  화면에는 안 보이다가 누가 곡선을 떼는 순간 아무도 고른 적 없는 숫자가 목표가
  된다.
- **0 은 목표가 아니다.** 옛 코드에서 `target_vpd`·`target_co2` 0 은 그 축을 끈
  것이고, `dli_target`·`gdd_target_daily` 0 은 "작물 프리셋 기본값" 이었다 —
  프리셋 값을 여기서 지어내지 않는다.
- ⚠ `target_co2` 1000 · `target_vpd` 0.8 은 옛 **기본값**이라 사람이 고른 값이
  아닐 수 있다. 그래도 옛 코드는 그 값으로 **실제로 돌았다** — 옮기는 것이 업그레이드
  전 동작을 되살리는 길이다. 미리보기가 값을 전부 찍으니 거기서 확인한다.
- **곡선이 사라졌으면 묶지 않는다.** `create_program` 이 죽은 참조를 거절하고,
  옛 코드도 그때는 목표 없이 돌았다. 그 사실을 줄에 찍는다.
- 시작일이 없고 곡선을 쓰던 설치는 옛 코드가 `method_start_time`(첫 평가 시각)부터
  주차를 셌다 — 그 날짜를 쓴다. 그것도 없으면 오늘로 두고 그렇게 말한다.
  `schedule_week_offset` 이 있으면 그만큼 시작일을 당긴다(설계문서 D19: 주차
  보정은 이제 `started_on` 을 고치는 것이다).

**단계는 하나만 만든다(기간 없음 = 끝까지).** 옛 옵션은 단일 목표였다. 없던 단계
구분을 이관하면서 지어내면 그때부터 목표가 날짜에 따라 저절로 바뀐다 — 사람이
결정하지 않은 변화다.

쓰기는 게이트웨이(`program_io.create_program`·`plot_io.save_plot`)만 지나간다.
`source='user'` — 사람이 옵션에 적었던 값이라 AI 검토 게이트 대상이 아니다.

## 건드리지 않는 것

- **시설에 구획이 이미 있으면 아무것도 하지 않는다**(끝난 구획·계획만 있어도).
  사람의 데이터에 합치면 어느 값이 누구의 것인지 알 수 없게 된다 — 목록에만 올린다.
- 시설이 지정되지 않았거나 없는 시설을 가리키면 수동 대상이다.
- 한 시설에 옛 목표를 가진 코디네이터가 둘 이상이면 수동 대상이다 — 시설 구획은
  하나만 자동 선택되므로(R3·R4) 어느 쪽 목표를 옮길지 여기서 고를 수 없다.
- 꺼진 코디네이터는 기본으로 건너뛴다(`--include-inactive` 로 포함). 지금 동작이
  바뀌지 않았고, 켜지 않을 옛 설정으로 시설에 구획을 만들 이유가 없다.
- **옛 키를 지우지 않는다.** 기록이다 — 무엇에서 옮겼는지의 근거가 사라지면 안 된다.

## 다시 돌려도 한 번만 만든다 — 표식은 프로그램의 `source_ref`

`source_ref='legacy-coordinator-targets:<코디네이터 uuid>'`. 고른 이유:

- 이름은 사람이 고칠 수 있다(`update_program`). 이름에 표식을 두면 이름을 바꾸는
  순간 다음 실행이 두 벌을 만든다. `source_ref` 는 수정 경로가 없는 출처 기록이다.
- 코디네이터 옵션에 깃발을 두면 "옛 키를 건드리지 않는다" 를 어기고, 옵션은 저장
  화면이 통째로 다시 쓰므로 깃발이 사라질 수 있다.
- 구획이 생기면 (c) 규칙으로도 걸리지만, 표식이 있어야 "이미 옮김" 과 "원래
  사람이 만든 구획" 을 구분해 말할 수 있다.

구획 생성이 실패하면 방금 만든 프로그램을 지운다 — 반쯤 옮긴 상태를 남기지 않는다.

    python3 -m aot.scripts.migrate_legacy_coordinator_targets            # 미리보기
    python3 -m aot.scripts.migrate_legacy_coordinator_targets --apply    # 실제 반영

종료 0=옮길 것 없음/성공, 1=옮길 것 있음(미리보기), 2=실패(반영·확인 실패 포함).
⚠ `--apply` 전에 DB 를 백업할 것.
⚠ 앱을 띄우므로 DB 스키마가 최신으로 올라간다(앱 기동과 같다).
⚠ 반영 뒤 켜져 있는 코디네이터를 재시작할 필요는 없다 — 목표는 매 사이클 읽는다.
"""

import argparse
import json
import logging
import re
import sys
from datetime import date, timedelta

MARKER_PREFIX = 'legacy-coordinator-targets:'

# 분류 — 화면에 찍는 말과 1:1 이다.
TARGET = 'target'              # 옮긴다
DONE = 'done'                  # 이미 옮김(표식 있음)
NONE = 'none'                  # 옛 목표 없음
NO_FACILITY = 'no-facility'    # 시설 미지정
FACILITY_MISSING = 'facility-missing'
HAS_PLOT = 'has-plot'          # 사람이 만든 구획이 이미 있음
SHARED = 'shared'              # 한 시설에 옛 목표 코디네이터가 여럿
INACTIVE = 'inactive'

LABEL = {
    NONE: '옛 목표 없음',
    NO_FACILITY: '시설 미지정 — 수동',
    FACILITY_MISSING: '연결된 시설을 찾을 수 없음 — 수동',
    HAS_PLOT: '이미 구획이 있음 — 건드리지 않음',
    SHARED: '같은 시설에 옛 목표를 가진 코디네이터가 여럿 — 수동',
    INACTIVE: '꺼져 있음 — 건너뜀(--include-inactive 로 포함)',
}


def _pos(v):
    """양수면 float, 아니면 None — 옛 코드에서 0·빈 값은 "목표 없음" 이었다."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _start_date(raw):
    """`schedule_start_time` → date | None. 날짜만 있으면 그대로(시설 현지 날짜다)."""
    raw = (raw or '').strip() if isinstance(raw, str) else ''
    if not raw:
        return None
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    try:
        from dateutil.parser import isoparse
        return isoparse(raw).date()
    except (ValueError, TypeError):
        return None


def legacy_targets(opts):
    """옵션 dict → 옛 목표 dict. DB 를 보지 않는다(순수 함수).

    `{'vpd': {'value'|'method': …}, 'co2': …, 'dli': float, 'gdd_daily': float,
      'start': date|None, 'week_offset': float, 'ignored': [문장…]}`
    축이 없으면 키가 없다.
    """
    out = {'ignored': []}
    for axis, sp_key, val_key, m_key in (
            ('vpd', 'vpd_sp_type', 'target_vpd', 'vpd_method_id'),
            ('co2', 'co2_sp_type', 'target_co2', 'co2_method_id')):
        sp = (opts.get(sp_key) or 'static')
        if sp == 'method':
            mid = (opts.get(m_key) or '').strip() if isinstance(opts.get(m_key), str) else ''
            if mid:
                out[axis] = {'method': mid}
            if _pos(opts.get(val_key)) is not None:
                out['ignored'].append(
                    '%s=%g 는 곡선을 쓰던 축이라 옛 코드도 읽지 않았음 — 옮기지 않음'
                    % (val_key, float(opts.get(val_key))))
        else:
            v = _pos(opts.get(val_key))
            if v is not None:
                out[axis] = {'value': v}
    dli = _pos(opts.get('dli_target'))
    if dli is not None:
        out['dli'] = dli
    gdd = _pos(opts.get('gdd_target_daily'))
    if gdd is not None:
        out['gdd_daily'] = gdd
    out['start'] = _start_date(opts.get('schedule_start_time'))
    try:
        out['week_offset'] = float(opts.get('schedule_week_offset') or 0.0)
    except (TypeError, ValueError):
        out['week_offset'] = 0.0
    return out


def has_targets(lt):
    return any(k in lt for k in ('vpd', 'co2', 'dli', 'gdd_daily'))


def marker(fn_uuid):
    return MARKER_PREFIX + fn_uuid


def _options(fn):
    try:
        opts = json.loads(fn.custom_options or '{}')
    except (TypeError, ValueError):
        return {}
    return opts if isinstance(opts, dict) else {}


def collect(include_inactive=False):
    """코디네이터마다 분류한다 → [dict]. 쓰기 없음."""
    from aot.databases.models import (
        CustomController, GeoFacility, GeoPlot, GeoProgram, Method)

    rows = []
    for fn in CustomController.query.filter(
            CustomController.device == 'env_coordinator').all():
        opts = _options(fn)
        lt = legacy_targets(opts)
        item = {'uuid': fn.unique_id, 'name': fn.name or fn.unique_id,
                'active': bool(fn.is_activated), 'lt': lt, 'opts': opts,
                'facility_uuid': (opts.get('geo_facility_id') or '').strip() or None,
                'bay': (str(opts.get('bay_scope') or '').strip() or None),
                'notes': [], 'kind': None}
        rows.append(item)

        # 곡선이 실제로 있는지 — 없으면 묶지 않고 말한다(건너뛰는 줄에도 이름이
        # 나가야 사람이 어느 곡선인지 안다).
        for axis in ('vpd', 'co2'):
            mid = (lt.get(axis) or {}).get('method')
            if not mid:
                continue
            m = Method.query.filter_by(unique_id=mid).first()
            if m is None:
                item['notes'].append('%s 곡선(%s…)을 찾을 수 없음 — 묶지 않음. '
                                     '옛 코드도 이때는 %s 목표 없이 돌았다'
                                     % (axis.upper(), mid[:8], axis.upper()))
                lt.pop(axis)
            else:
                lt[axis]['method_name'] = m.name
                lt[axis]['method_type'] = m.method_type

        prog = GeoProgram.query.filter_by(source_ref=marker(fn.unique_id)).first()
        if prog is not None:
            item['kind'] = DONE
            item['program'] = prog.name
            used = GeoPlot.query.filter_by(program_uuid=prog.unique_id).count()
            if not used:
                item['notes'].append('이관한 프로그램을 쓰는 구획이 없음 — 사람이 '
                                     '해제·삭제했다면 그대로 둔다')
            continue
        if not has_targets(lt):
            item['kind'] = NONE
            continue
        if not fn.is_activated and not include_inactive:
            item['kind'] = INACTIVE
            continue
        if not item['facility_uuid']:
            # 옛 속성 이름으로만 저장된 경우를 따로 말한다 — 제어는 이 키를 안 본다.
            if opts.get('geo_facility_id_device_id'):
                item['notes'].append('시설이 옛 키(geo_facility_id_device_id)에만 '
                                     '있음 — 제어는 geo_facility_id 를 읽는다')
            item['kind'] = NO_FACILITY
            continue
        fac = GeoFacility.query.filter_by(unique_id=item['facility_uuid']).first()
        if fac is None:
            item['kind'] = FACILITY_MISSING
            continue
        item['facility'] = fac.name or fac.unique_id
        n = GeoPlot.query.filter(
            GeoPlot.facility_uuid == item['facility_uuid']).count()
        if n:
            item['kind'] = HAS_PLOT
            item['notes'].append('구획 %d개' % n)
            continue

        item['started_on'], why = _started_on(fn, lt)
        item['notes'].extend(why)
        item['kind'] = TARGET

    # 한 시설에 옮길 코디네이터가 둘 이상이면 어느 쪽도 자동으로 옮기지 않는다.
    by_fac = {}
    for it in rows:
        if it['kind'] == TARGET:
            by_fac.setdefault(it['facility_uuid'], []).append(it)
    for items in by_fac.values():
        if len(items) > 1:
            for it in items:
                it['kind'] = SHARED
                it['notes'].append('함께: ' + ', '.join(
                    o['name'] for o in items if o is not it))
    return rows


def _started_on(fn, lt):
    """구획 시작일 → (date, [설명]). 옛 코드가 주차를 세던 기준을 따른다."""
    notes = []
    start = lt.get('start')
    if start is None:
        uses_curve = any((lt.get(a) or {}).get('method') for a in ('vpd', 'co2'))
        mst = getattr(fn, 'method_start_time', None)
        if uses_curve and mst:
            start = _start_date(str(mst))
            if start is not None:
                notes.append('시작일이 없어 곡선 첫 평가일(method_start_time)로 둠')
    if start is None:
        start = date.today()
        notes.append('시작일이 없어 오늘로 둠 — 주차 곡선이면 구획 시작일을 확인할 것')
    off = lt.get('week_offset') or 0.0
    if off:
        days = int(round(off * 7))
        start = start - timedelta(days=days)
        notes.append('주차 보정 %g주 → 시작일을 %d일 당김' % (off, days))
    return start, notes


def describe(lt, started_on=None):
    """옮길 값 한 줄."""
    parts = []
    for axis, unit in (('vpd', 'kPa'), ('co2', 'ppm')):
        a = lt.get(axis)
        if not a:
            continue
        if 'method' in a:
            parts.append("%s 곡선 '%s'" % (axis.upper(), a.get('method_name') or a['method'][:8]))
        else:
            parts.append('%s %g %s' % (axis.upper(), a['value'], unit))
    if 'dli' in lt:
        parts.append('DLI %g' % lt['dli'])
    if 'gdd_daily' in lt:
        parts.append('GDD %g/일' % lt['gdd_daily'])
    if started_on is not None:
        parts.append('시작 %s' % started_on.isoformat())
    return ' · '.join(parts)


def build_payloads(item):
    """(프로그램 페이로드, 구획 페이로드 틀) — 구획의 program_uuid 는 생성 뒤 채운다."""
    lt = item['lt']
    opts = item['opts']
    stage_targets = {}
    methods = {}
    for axis in ('vpd', 'co2'):
        a = lt.get(axis)
        if not a:
            continue
        if 'method' in a:
            methods[axis] = a['method']
        else:
            stage_targets[axis] = a['value']
    if 'dli' in lt:
        stage_targets['dli'] = lt['dli']
    stage = {'key': 'legacy', 'name': 'Migrated targets', 'days': None}
    if stage_targets:
        stage['targets'] = stage_targets
    subject = (str(opts.get('crop_preset') or '').strip() or item['name'])
    program = {
        'name': '%s — migrated targets' % item['name'],
        'kind': 'vegetation',
        'subject': subject,
        'stages': [stage],
        'targets_methods': methods or None,
        'photosynthesis': ({'gdd_daily': lt['gdd_daily']}
                           if 'gdd_daily' in lt else None),
        'source_ref': marker(item['uuid']),
        'source_note': ('env_coordinator "%s" options (target_vpd, vpd_sp_type, '
                        'vpd_method_id, target_co2, co2_sp_type, co2_method_id, '
                        'dli_target, gdd_target_daily, schedule_start_time) — '
                        'removed without migration in fe6e37b4' % item['name']),
    }
    plot = {
        'facility_uuid': item['facility_uuid'],
        'kind': 'vegetation',
        'subject': subject,
        'started_on': item['started_on'].isoformat(),
    }
    if item.get('bay'):
        plot['bay_id'] = item['bay']
    return program, plot


def apply_one(item):
    """프로그램 → 구획. 구획이 실패하면 프로그램을 지운다 → error|None."""
    from aot.aot_flask.geo.plot_io import save_plot
    from aot.aot_flask.geo.program_io import create_program, delete_program

    prog_payload, plot_payload = build_payloads(item)
    prog, err = create_program(prog_payload, source='user')
    if err:
        return '프로그램 생성 실패 — %s' % err
    plot_payload['program_uuid'] = prog['unique_id']
    plot, err = save_plot(plot_payload)
    if err:
        _d, derr = delete_program(prog['unique_id'])
        tail = '' if not derr else ' (프로그램 되돌리기도 실패: %s)' % derr
        return '구획 생성 실패 — %s%s' % (err, tail)
    return None


def verify(item):
    """`control_targets` 로 실제로 풀리는 목표를 본다 → (한 줄, 실패 이유|None)."""
    from aot.aot_flask.geo.coordinator_plot import control_targets
    from aot.databases.models import CustomController, Method

    fn = CustomController.query.filter_by(unique_id=item['uuid']).first()
    t = control_targets(fn)
    if t.get('reason') != 'ok':
        return None, '목표가 풀리지 않음 (reason=%s)' % t.get('reason')

    def _axis(axis, unit):
        a = t.get(axis) or {}
        if a.get('method_id'):
            m = Method.query.filter_by(unique_id=a['method_id']).first()
            return "곡선 '%s'" % (m.name if m else a['method_id'][:8])
        if a.get('value') is not None:
            return '%g %s' % (a['value'], unit)
        return '없음'

    st = t.get('stage') or {}
    line = ('구획 %s · 단계 %s/%s · VPD %s · CO₂ %s · DLI %s · GDD %s' % (
        t.get('plot_name'), st.get('index'), st.get('total'),
        _axis('vpd', 'kPa'), _axis('co2', 'ppm'),
        '없음' if t.get('dli') is None else '%g' % t['dli'],
        '없음' if t.get('gdd_daily') is None else '%g/일' % t['gdd_daily']))

    # 옮긴 값이 그대로 풀리는지 — 하나라도 어긋나면 실패로 올린다.
    lt = item.get('lt') or {}
    miss = []
    for axis in ('vpd', 'co2'):
        want = lt.get(axis)
        if not want:
            continue
        got = t.get(axis) or {}
        if 'method' in want and got.get('method_id') != want['method']:
            miss.append(axis)
        if 'value' in want and got.get('value') != want['value']:
            miss.append(axis)
    if 'dli' in lt and t.get('dli') != lt['dli']:
        miss.append('dli')
    if 'gdd_daily' in lt and t.get('gdd_daily') != lt['gdd_daily']:
        miss.append('gdd_daily')
    return line, ('옮긴 값과 다름: ' + ', '.join(miss)) if miss else None


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true', help='실제로 반영한다')
    ap.add_argument('--include-inactive', action='store_true',
                    help='꺼진 코디네이터도 옮긴다')
    args = ap.parse_args(argv)

    # 기동 로그가 보고서 머리를 덮지 않게 INFO 만 끈다(경고·오류는 그대로).
    logging.disable(logging.INFO)
    # 앱은 여기서 띄운다 — 모듈 머리에서 띄우면 순수 함수만 검사하려 해도 앱
    # 전체가 기동한다. `start_flask_ui` 는 MCP 서버까지 띄우므로 쓰지 않는다.
    try:
        from aot.aot_flask.app import create_app
        app = create_app()
    except Exception as exc:                                 # noqa: BLE001
        print(f'ERROR: 앱을 띄울 수 없음 — {exc}', file=sys.stderr)
        return 2
    with app.app_context():
        return run(apply=args.apply, include_inactive=args.include_inactive)


def run(apply=False, include_inactive=False, out=None):
    """앱 컨텍스트 안에서 부른다(테스트도 이 입구를 쓴다) → 종료 코드."""
    out = out or sys.stdout

    def say(s=''):
        print(s, file=out)

    try:
        rows = collect(include_inactive=include_inactive)
    except Exception as exc:                                 # noqa: BLE001
        print(f'ERROR: 조회 실패 — {exc}', file=sys.stderr)
        return 2

    failed = False
    for it in rows:
        if it['kind'] in (TARGET, DONE):
            continue
        head = f'  건너뜀  {it["name"]}: {LABEL[it["kind"]]}'
        if it['kind'] != NONE and has_targets(it['lt']):
            head += f' [{describe(it["lt"])}]'
        say(head)
        for n in it['notes']:
            say(f'          - {n}')
    for it in rows:
        if it['kind'] != DONE:
            continue
        say(f'  이미 옮김 {it["name"]}: 프로그램 "{it["program"]}"')
        for n in it['notes']:
            say(f'          - {n}')
        line, err = verify(dict(it, lt={}))
        say(f'          확인: {line}' if line else f'          확인 실패: {err}')

    targets = [r for r in rows if r['kind'] == TARGET]
    for it in targets:
        say(f'  대상    {it["name"]} → 시설 "{it["facility"]}": '
            f'{describe(it["lt"], it["started_on"])}')
        for n in it['notes'] + it['lt']['ignored']:
            say(f'          - {n}')

    if not targets:
        say('옮길 것이 없습니다.')
        return 0

    if not apply:
        say(f'\n미리보기입니다. {len(targets)}건을 옮기려면 --apply 를 붙이세요.')
        say('⚠ DB 를 먼저 백업하세요. 옛 옵션 값은 지우지 않습니다.')
        return 1

    done = 0
    for it in targets:
        try:
            err = apply_one(it)
        except Exception as exc:                             # noqa: BLE001
            err = f'반영 실패 — {exc}'
        if err:
            failed = True
            say(f'  실패    {it["name"]}: {err}')
            continue
        line, verr = verify(it)
        if verr:
            failed = True
            say(f'  확인 실패 {it["name"]}: {verr}' + (f' ({line})' if line else ''))
            continue
        done += 1
        say(f'  옮김    {it["name"]}: {line}')

    say(f'\n{done}건 옮겼습니다. 옛 옵션 값은 그대로 두었습니다(기록).')
    say('목표는 매 사이클 구획에서 읽으므로 코디네이터를 재시작할 필요는 없습니다.')
    return 2 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

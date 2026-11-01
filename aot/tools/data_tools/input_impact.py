# -*- coding: utf-8 -*-
"""입력(센서)을 끄기 전에 보여 줄 영향 — 이 입력의 측정값을 쓰는 것과 놓인 곳.

DB 참조로 찾는다(PID·조건·트리거의 측정 칸, 함수 옵션 JSON 의 id, 통합 환경 제어의 시설).
**자동으로 끄지 않는다** — 사람이 보고 승인하는 되읽기에 싣기만 한다. 찾지 못했다고 안전하다는 뜻은
아니다(참조가 자유 형식인 함수는 id 가 글에 들어 있을 때만 잡힌다). 실패해도 되읽기를 막지 않는다.
"""
import json
import logging

logger = logging.getLogger(__name__)

#: 되읽기에 이름까지 싣는 영향 항목 수 — 나머지는 개수로.
SHOWN_MAX = 4


def _blob(value):
    """JSON 글자를 다시 직렬화해 id 가 든 글을 찾기 좋게. 깨졌으면 원문."""
    raw = value or ''
    if not raw:
        return ''
    try:
        return json.dumps(json.loads(raw))
    except (TypeError, ValueError):
        return str(raw)


def _facility_ids(input_id):
    """이 입력이 센서 역할로 매인 시설들의 id (통합 환경 제어가 시설로 센서를 읽는다)."""
    try:
        from aot.aot_flask.geo import device_binding
        rows = device_binding.bindings_for_device(input_id)
    except Exception:                                       # noqa: BLE001
        logger.warning('[input_impact] 바인딩 조회 실패 (%s)', input_id, exc_info=True)
        return set()
    return {str(b.spatial_id).split(':')[0] for b in rows
            if b.spatial_kind in ('sensor_role', 'weather', 'fitting', 'actuator') and b.spatial_id}


def dependents(input_id):
    """이 입력의 측정값을 쓰는 것들.

    {'active': [{'kind', 'name'}…], 'inactive': 꺼진 채 쓰는 것의 수, 'widgets': 위젯 수}.
    kind: pid · condition · trigger · function · env_control · input. 조회가 부분적으로 실패해도
    찾은 것은 돌려준다."""
    from aot.databases.models import (
        Conditional, ConditionalConditions, CustomController, Input, PID, Trigger, Widget)
    found, off = [], 0

    def add(kind, name, active):
        nonlocal off
        if active:
            found.append({'kind': kind, 'name': name or '?'})
        else:
            off += 1

    steps = []

    def pids():
        for r in PID.query.all():
            if (r.measurement or '').split(',')[0] == input_id:
                add('pid', r.name, r.is_activated)
    steps.append(pids)

    def conditions():
        seen = set()
        for c in ConditionalConditions.query.all():
            if (c.measurement or '').split(',')[0] != input_id or c.conditional_id in seen:
                continue
            seen.add(c.conditional_id)
            parent = Conditional.query.filter_by(unique_id=c.conditional_id).first()
            if parent is not None:
                add('condition', parent.name, parent.is_activated)
    steps.append(conditions)

    def triggers():
        for t in Trigger.query.all():
            if (t.measurement or '').split(',')[0] == input_id:
                add('trigger', t.name, t.is_activated)
    steps.append(triggers)

    def functions():
        fac = _facility_ids(input_id)
        for fn in CustomController.query.all():
            blob = _blob(fn.custom_options)
            coordinator = fn.device == 'env_coordinator'
            if input_id in blob or (coordinator and any(f in blob for f in fac)):
                add('env_control' if coordinator else 'function', fn.name, fn.is_activated)
    steps.append(functions)

    def inputs():
        for r in Input.query.filter(Input.unique_id != input_id).all():
            if input_id in (r.calibrate_sensor_measure or '') or input_id in _blob(r.custom_options):
                add('input', r.name, r.is_activated)
    steps.append(inputs)

    widgets = [0]

    def widget_count():
        for w in Widget.query.all():
            if input_id in (w.input_ids_measurements or '') or input_id in _blob(w.custom_options):
                widgets[0] += 1
    steps.append(widget_count)

    for step in steps:
        try:
            step()
        except Exception:                                   # noqa: BLE001
            logger.warning('[input_impact] %s 조회 실패', step.__name__, exc_info=True)
    return {'active': found, 'inactive': off, 'widgets': widgets[0]}


_KIND_WORD = {'pid': 'PID', 'condition': 'condition', 'trigger': 'trigger',
              'function': 'function', 'env_control': 'environment control', 'input': 'input'}


def where(input_id):
    """이 입력이 놓인 곳 — 지도 경로('지도 > 구역 > 이름'에서 이름을 뗀 앞부분). 모르면 ''."""
    try:
        from aot.tools.domain import targets
        path = (targets._by_id(input_id) or {}).get('path') or ''
    except Exception:                                       # noqa: BLE001
        logger.warning('[input_impact] 위치 조회 실패 (%s)', input_id, exc_info=True)
        return ''
    head, sep, _name = path.rpartition(' > ')
    return head if sep else ''


def readback(input_id, active):
    """승인 되읽기 한 줄 — 서버가 풀어 낸 이름과 동작, 놓인 곳, (끌 때) 영향.

    예: "Turn OFF input 'Soil A' (Farm > Zone 1). It is used by 2 running items: PID 'Temp' ·
    environment control 'Coord' — they lose this reading. Nothing is turned off with it."
    입력을 못 찾으면 None."""
    from aot.databases.models import Input
    row = Input.query.filter_by(unique_id=input_id).first()
    if row is None:
        return None
    place = where(input_id)
    text = "Turn %s input '%s'%s." % ('ON' if active else 'OFF', row.name,
                                      " (%s)" % place if place else "")
    if active:
        return text
    imp = dependents(input_id)
    items = imp['active']
    if items:
        shown = " · ".join("%s '%s'" % (_KIND_WORD.get(i['kind'], i['kind']), i['name'])
                           for i in items[:SHOWN_MAX])
        more = len(items) - SHOWN_MAX
        text += (" WARNING: %d running item%s read it: %s%s — they lose this reading while it is off; "
                 "nothing is turned off with it." % (
                     len(items), '' if len(items) == 1 else 's', shown,
                     " and %d more" % more if more > 0 else ""))
    else:
        text += " No running item was found using its readings."
    if imp['widgets']:
        text += " Shown on %d widget%s." % (imp['widgets'], '' if imp['widgets'] == 1 else 's')
    return text

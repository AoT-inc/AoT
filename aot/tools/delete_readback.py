# -*- coding: utf-8 -*-
"""삭제 승인 문구의 되읽기 — 어느 것을 지우는지 서버가 id 에서 찾아 말한다.

노트 삭제(`mcp_safety_gate._note_delete_readback`)와 같은 원칙이다. 사용자가 '이 대상을 지우는 게 맞다' 를
알아보게 **서버가 id 로 찾은 이름·놓인 곳·영향**만 쓴다(AI 가 쓴 `_title` 이나 인자 글은 쓰지 않는다 —
요청은 승인이 아니다). 대상을 못 찾으면 그렇다고 말한다(지워질 것이 없다). 조회가 깨져도 승인 흐름을 막지
않고 '확인하지 못했다' 로 말한다 — 모르면서 아는 척하지 않는다.

영향은 읽기 전용 조회다. 자동으로 무엇을 끄거나 바꾸지 않는다.
"""
import logging

logger = logging.getLogger(__name__)

#: 영향 항목을 이름까지 싣는 수 — 나머지는 개수로.
SHOWN_MAX = 4

#: 도구 → (동작 이름, 종류 이름, 대상 id 를 받는 인자)
SPECS = {
    'delete_input': ('입력 삭제', '입력', 'input_id'),
    'delete_output': ('출력 삭제', '출력', 'output_id'),
    'delete_plot': ('구획 삭제', '구획', 'plot_id'),
    'delete_program': ('프로그램 삭제', '프로그램', 'program_id'),
    'delete_widget': ('위젯 삭제', '위젯', 'widget_id'),
    'delete_tab': ('탭 삭제', '탭', 'tab_id'),
    'delete_ai_agent': ('AI 에이전트 삭제', 'AI 에이전트', 'agent_id'),
    'delete_geo_shape': ('지도 도형 삭제', '지도 도형', 'shape_id'),
    'delete_gis_input': ('GIS 입력 삭제', 'GIS 입력', 'layer_id'),
}

#: 게이트의 read_back_text 가 이 도구들에 이 모듈을 쓴다.
TOOLS = frozenset(SPECS)

_PAGE_WORD = {'input': '입력', 'output': '출력', 'function': '함수', 'dashboard': '위젯',
              'program': '프로그램'}


def _names(items, key=lambda x: x):
    """'a · b · c 외 N' 꼴로 줄인다."""
    names = [str(key(i) or '?') for i in items]
    text = ' · '.join("'%s'" % n for n in names[:SHOWN_MAX])
    if len(names) > SHOWN_MAX:
        text += ' 외 %d' % (len(names) - SHOWN_MAX)
    return text


def _place(target_id):
    """놓인 곳 — 지도 경로에서 대상 이름을 뗀 앞부분. 모르면 ''."""
    try:
        from aot.tools.domain import targets
        path = (targets._by_id(target_id) or {}).get('path') or ''
    except Exception:                                       # noqa: BLE001
        logger.warning('[delete_readback] 위치 조회 실패 (%s)', target_id, exc_info=True)
        return ''
    head, sep, _name = path.rpartition(' > ')
    return head if sep else ''


def _used_by_output(output_id):
    """이 출력을 쓰는 것들 — (이름 있는 실행 항목 목록, 위젯 수). 조회가 일부 깨져도 찾은 것은 준다."""
    from aot.databases.models import Actions, CustomController, PID, Widget
    from aot.tools.data_tools.input_impact import _blob
    found, widgets = [], 0
    try:
        for p in PID.query.all():
            if output_id in (p.raise_output_id, p.lower_output_id):
                found.append('PID \'%s\'' % (p.name or '?'))
    except Exception:                                       # noqa: BLE001
        logger.warning('[delete_readback] PID 조회 실패', exc_info=True)
    try:
        n = Actions.query.filter_by(do_unique_id=output_id).count()
        if n:
            found.append('조건·트리거 동작 %d건' % n)
    except Exception:                                       # noqa: BLE001
        logger.warning('[delete_readback] 동작 조회 실패', exc_info=True)
    try:
        for fn in CustomController.query.all():
            if output_id in _blob(fn.custom_options):
                found.append('함수 \'%s\'' % (fn.name or '?'))
    except Exception:                                       # noqa: BLE001
        logger.warning('[delete_readback] 함수 조회 실패', exc_info=True)
    try:
        widgets = sum(1 for w in Widget.query.all()
                      if output_id in (w.output_ids or '') or output_id in _blob(w.custom_options))
    except Exception:                                       # noqa: BLE001
        logger.warning('[delete_readback] 위젯 조회 실패', exc_info=True)
    return found, widgets


def _input(arg):
    from aot.databases.models import Input
    from aot.tools.data_tools import input_impact
    row = Input.query.filter_by(unique_id=arg).first()
    if row is None:
        return None
    parts = [row.name, _place(arg)]
    imp = input_impact.dependents(arg)
    items = imp['active']
    if items:
        shown = ' · '.join("%s '%s'" % (input_impact._KIND_WORD.get(i['kind'], i['kind']), i['name'])
                           for i in items[:SHOWN_MAX])
        more = len(items) - SHOWN_MAX
        parts.append('실행 중 %d개가 이 입력의 값을 읽고 있습니다: %s%s — 값을 잃습니다'
                     % (len(items), shown, ' 외 %d' % more if more > 0 else ''))
    else:
        parts.append('이 입력을 쓰는 실행 중 항목은 찾지 못했습니다')
    if imp['widgets']:
        parts.append('위젯 %d개에 표시 중' % imp['widgets'])
    return parts


def _output(arg):
    from aot.databases.models import Output
    row = Output.query.filter_by(unique_id=arg).first()
    if row is None:
        return None
    parts = [row.name, _place(arg)]
    found, widgets = _used_by_output(arg)
    if found:
        more = len(found) - SHOWN_MAX
        parts.append('이 출력을 쓰는 것: %s%s' % (
            ' · '.join(found[:SHOWN_MAX]), ' 외 %d' % more if more > 0 else ''))
    else:
        parts.append('이 출력을 쓰는 항목은 찾지 못했습니다')
    if widgets:
        parts.append('위젯 %d개에 표시 중' % widgets)
    return parts


def _plot(arg):
    from aot.databases.models import GeoPlot
    row = GeoPlot.query.filter_by(unique_id=arg).first()
    if row is None:
        return None
    name = row.name or row.subject
    parts = [name, _place(arg)]
    sub = '·'.join(x for x in (row.subject, row.variety) if x and x != name)
    if sub:
        parts.append(sub)
    parts.append('%s 시작%s' % (row.started_on, ', %s 종료' % row.ended_on if row.ended_on else ', 재배 중'))
    try:
        from aot.databases.models.scheduler import SchedulerJobMeta
        jobs = SchedulerJobMeta.query.filter(
            SchedulerJobMeta.target_id == arg,
            SchedulerJobMeta.state.in_(('DRAFT', 'PENDING', 'RUNNING'))).count()
        if jobs:
            parts.append('이 구획의 일정 %d건이 함께 내려집니다' % jobs)
    except Exception:                                       # noqa: BLE001
        logger.warning('[delete_readback] 구획 일정 조회 실패', exc_info=True)
    parts.append('기록이 사라져 연작 판단에 못 씁니다 (수확이 끝난 것은 삭제 말고 종료)')
    return parts


def _program(arg):
    from aot.databases.models import GeoPlot, GeoProgram
    row = GeoProgram.query.filter_by(unique_id=arg).first()
    if row is None:
        return None
    parts = [row.name, '·'.join(x for x in (row.subject, row.variety) if x)]
    used = GeoPlot.query.filter_by(program_uuid=arg).count()
    if used:
        parts.append('쓰는 구획 %d건 — 이 상태로는 삭제되지 않고 거절됩니다' % used)
    else:
        parts.append('쓰는 구획 없음')
    return parts


def _widget(arg):
    from aot.databases.models import Dashboard, Widget
    row = Widget.query.filter_by(unique_id=arg).first()
    if row is None:
        return None
    dash = Dashboard.query.filter_by(unique_id=row.tab_id).first()
    parts = [(row.name or '').strip() or row.graph_type or '이름 없음',
             '대시보드 %s' % dash.name if dash is not None else '']
    if row.graph_type:
        parts.append('종류 %s' % row.graph_type)
    return parts


def _tab(arg):
    from aot.databases.models import (
        Conditional, CustomController, Function, Input, Output, PID, Tab, Trigger, Widget)
    row = Tab.query.filter_by(unique_id=arg).first()
    if row is None:
        return None
    kind = row.page_type or '?'
    parts = [row.name, '%s 페이지의 탭' % _PAGE_WORD.get(kind, kind)]
    models = {'input': (Input,), 'output': (Output,), 'dashboard': (Widget,),
              'function': (Trigger, Conditional, PID, CustomController, Function)}.get(kind)
    if models is None:
        parts.append('안의 항목은 지우지 않고 기본 탭으로 옮겨집니다' if kind == 'program'
                     else '소속 항목은 확인하지 못했습니다')
        return parts
    items = []
    for m in models:
        try:
            items.extend(m.query.filter_by(tab_id=arg).all())
        except Exception:                                   # noqa: BLE001
            logger.warning('[delete_readback] 탭 안 항목 조회 실패 (%s)', m.__name__, exc_info=True)
    if items:
        parts.append('안의 %s %d개도 함께 지워집니다: %s' % (
            _PAGE_WORD.get(kind, kind), len(items), _names(items, lambda i: getattr(i, 'name', None))))
    else:
        parts.append('안에 항목 없음')
    return parts


def _ai_agent(arg):
    from aot.databases.models.ai import AIAgent
    row = AIAgent.query.filter_by(unique_id=arg).first()
    if row is None:
        return None
    parts = [row.name, '%s' % (row.specialty or row.role or '')]
    parts.append('켜져 있음' if row.is_activated else '꺼져 있음')
    parts.append('MCP 접근 설정도 함께 지워집니다')
    return parts


def _geo_shape(arg):
    from aot.databases.models import GeoFacility, GeoShape
    from aot.space.device_membership import place_label
    row = GeoShape.query.filter_by(unique_id=arg).first()
    if row is None:
        return None
    name = place_label(row) or '이름 없음'
    parts = [name, _place(arg), '종류 %s' % row.type]
    try:
        kids = GeoShape.query.filter_by(parent_id=row.id).count()
        if kids:
            parts.append('안쪽 도형 %d개' % kids)
        fac = GeoFacility.query.filter_by(shape_uuid=arg).count()
        if fac:
            parts.append('이 도형의 시설 정보도 함께 정리됩니다')
        if row.device_id:
            parts.append('장치가 연결된 도형입니다')
    except Exception:                                       # noqa: BLE001
        logger.warning('[delete_readback] 도형 영향 조회 실패', exc_info=True)
    return parts


def _gis_input(arg):
    from aot.databases.models import GeoLayer
    row = GeoLayer.query.filter_by(unique_id=arg).first()
    if row is None:
        return None
    return [row.name, '종류 %s' % row.type, '켜져 있음' if row.is_activated else '꺼져 있음']


_FINDERS = {
    'delete_input': _input, 'delete_output': _output, 'delete_plot': _plot,
    'delete_program': _program, 'delete_widget': _widget, 'delete_tab': _tab,
    'delete_ai_agent': _ai_agent, 'delete_geo_shape': _geo_shape,
    'delete_gis_input': _gis_input,
}


def readback(tool_name, arguments):
    """삭제 승인 되읽기 한 줄. 이 모듈이 맡는 도구가 아니면 None.

    형식: "{동작}: '{이름}' · {놓인 곳} · {영향} · 되돌릴 수 없습니다"
    대상을 못 찾으면 "{동작} — 해당 {종류}을(를) 찾지 못했습니다", 조회가 깨지면 확인하지 못했다고 말한다."""
    spec = SPECS.get(tool_name)
    if spec is None:
        return None
    action, kind, id_arg = spec
    target = str((arguments or {}).get(id_arg) or '').strip()
    if not target:
        return '%s — 지울 %s이(가) 정해지지 않았습니다' % (action, kind)
    try:
        parts = _FINDERS[tool_name](target)
    except Exception:                                       # noqa: BLE001
        logger.exception('[delete_readback] %s 되읽기 실패', tool_name)
        return '%s — 대상을 확인하지 못했습니다. 무엇이 지워질지 모르는 채로 승인하지 마세요' % action
    if parts is None:
        return '%s — 해당 %s을(를) 찾지 못했습니다 (지워질 것이 없습니다)' % (action, kind)
    name, rest = parts[0], [p for p in parts[1:] if p]
    text = "%s: '%s'" % (action, (name or '').strip() or '이름 없음')
    for p in rest:
        text += ' · ' + p
    return text + ' · 되돌릴 수 없습니다'

# -*- coding: utf-8 -*-
"""옛 이름 → 새 이름 별칭표 — 설계 plans/mcp_redesign_20261103.md §2-3·§9.

op 를 합치거나 인자 이름을 표준으로 바꿀 때 옛 이름을 **조용히** 받는다. 목록·스키마·help 에는 새 이름만
실려 토큰이 늘지 않는다. 옛 이름이 실제로 쓰인 호출에만 응답에 `renamed` 한 줄("새 이름은 이것")이 붙는다.

영구 수용이 아니다(2026-11-03 사용자 결정): 기본 표면을 도메인으로 바꾼 뒤 2주 안에 이 표를 비우는 정리 PR 을
낸다. 그래서 모든 항목이 `since`(등록일)를 갖고, `rows()` 가 '옛 이름 → 등록일' 표를 준다 — 지울 때 이 표만 본다.

표는 셋이다.
- `OP_ALIASES`: (도구, 옛 op) → 새 op + 그 별칭으로 불렀을 때만 쓰는 인자 이름 바꾸기(`rename`) · 고정 인자(`fixed`).
- `ARG_ALIASES`: 옛 인자 이름 → 새 이름. 새 이름을 받는 op 에만 적용된다(그 op 가 옛 이름을 아직 스스로 받으면 건드리지 않는다).
- `OP_ARG_ALIASES`: (도구, op) 안에서만 뜻이 있는 인자 별칭 — 같은 이름이 op 마다 다른 뜻일 때.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass(frozen=True)
class OpAlias:
    op: str                                            # 정식 op 이름
    since: str                                         # 등록일(YYYY-MM-DD) — 일괄 제거의 기준
    rename: Dict[str, str] = field(default_factory=dict)   # 옛 인자 이름 → 새 이름 (이 별칭으로 불렀을 때만)
    fixed: Dict[str, Any] = field(default_factory=dict)    # 호출이 주지 않은 인자의 고정값(예 state='on')
    #: 정식 op 가 다른 도구에 있을 때 그 도구(읽기↔쓰기를 넘지 않는다 — 시험이 본다). 비면 같은 도구.
    tool: str = ''
    #: 새 인자 이름 → 값 바꾸기(rename 으로 옮긴 값에 적용: target_b → candidates 는 목록으로).
    convert: Dict[str, Callable[[Any], Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ArgAlias:
    new: str
    since: str
    #: 옛 이름의 값을 새 이름의 값으로(단위가 이름에 있던 것: duration_minutes=15 → '15m').
    convert: Optional[Callable[[Any], Any]] = None


#: (도구, 옛 op) → 정식 op. 정식 이름만 명부(`OPS`)에 있다 — 시험이 별칭이 실제 op 를 가리키는지 본다.
_D = '2026-11-03'


def _as_list(v):
    return v if isinstance(v, (list, tuple)) else [v]


OP_ALIASES: Dict[Tuple[str, str], OpAlias] = {
    # 2026-10-30 체험: measure.now → unknown_op. 모델이 "지금 값" 을 보고 now 를 짐작한다.
    ('measure', 'now'): OpAlias('latest', since='2026-10-30'),
    # ── 재설계 PR 3 (2026-11-03): 합쳐서 없어진 op ─────────────────────────────────────────────────────────
    ('measure', 'summary'): OpAlias('latest', since=_D),                                  # 대상 없음 = 곳마다 한 줄
    ('overview', 'crops'): OpAlias('plots', since=_D, tool='find', rename={'facility_name': 'target'}, fixed={'detail': False}),
    ('overview', 'active_functions'): OpAlias('functions', since=_D, tool='find', fixed={'only_active': True}),
    ('find', 'device_location'): OpAlias('device', since=_D, tool='detail', fixed={'fields': ['location']}),
    ('find', 'distance'): OpAlias('nearest', since=_D, rename={'target_b': 'candidates'},
                                  convert={'candidates': _as_list}),
    ('find', 'device_list'): OpAlias('devices', since=_D),                                 # 검색어 없음 = 전체
    ('find', 'maps'): OpAlias('tree', since=_D),                                          # 대상 없음 = 지도별 한 줄
    ('records', 'journal'): OpAlias('journals', since=_D),                                # 일지 id 를 대상으로 = 한 건
    # ── 재설계 PR 5 (2026-11-03): 노트는 한 op — 대상이 노트 id 면 고치기 ──────────────────────────────────
    ('record', 'note_add'): OpAlias('note', since=_D),
    ('record', 'note_edit'): OpAlias('note', since=_D),
    # ── 재설계 PR 6 (2026-11-03): 값으로 안쪽 도구를 고르는 op(Op.pick_by_arg) ──────────────────────────────
    ('control', 'function_on'): OpAlias('function_set', since=_D, fixed={'state': 'on'}),
    ('control', 'function_off'): OpAlias('function_set', since=_D, fixed={'state': 'off'}),
    ('record', 'schedule_add_batch'): OpAlias('schedule_add', since=_D),                  # entries 가 있으면 일괄
    ('cultivate', 'stage_confirm'): OpAlias('stage', since=_D, fixed={'action': 'confirm'}),
    ('cultivate', 'stage_reschedule'): OpAlias('stage', since=_D, fixed={'action': 'reschedule'}),
    ('cultivate', 'stage_guidance'): OpAlias('stage', since=_D, fixed={'action': 'guidance'}),
    ('cultivate', 'stage_add'): OpAlias('stage', since=_D, fixed={'action': 'add'}),
    ('cultivate', 'stage_undo'): OpAlias('stage', since=_D, fixed={'action': 'undo'}),
    # ── 재설계 PR 7 (2026-11-03): 종류별 합치기 — 지우기 14→remove.delete, 고치기 6→configure.edit (kind 가 종류) ──
    ('remove', 'notice_delete'): OpAlias('delete', since=_D, fixed={'kind': 'notice'}),
    ('remove', 'note_delete'): OpAlias('delete', since=_D, fixed={'kind': 'note'}),
    ('remove', 'schedule_delete'): OpAlias('delete', since=_D, fixed={'kind': 'schedule'}),
    ('remove', 'plot_delete'): OpAlias('delete', since=_D, fixed={'kind': 'plot'}),
    ('remove', 'program_delete'): OpAlias('delete', since=_D, fixed={'kind': 'program'}),
    ('remove', 'input_delete'): OpAlias('delete', since=_D, fixed={'kind': 'input'}),
    ('remove', 'output_delete'): OpAlias('delete', since=_D, fixed={'kind': 'output'}),
    ('remove', 'function_delete'): OpAlias('delete', since=_D, fixed={'kind': 'function'}),
    ('remove', 'gis_input_delete'): OpAlias('delete', since=_D, fixed={'kind': 'gis_layer'}),
    ('remove', 'widget_delete'): OpAlias('delete', since=_D, fixed={'kind': 'widget'}),
    ('remove', 'tab_delete'): OpAlias('delete', since=_D, fixed={'kind': 'tab'}),
    ('remove', 'ai_agent_delete'): OpAlias('delete', since=_D, fixed={'kind': 'ai_agent'}),
    ('remove', 'shape_delete'): OpAlias('delete', since=_D, fixed={'kind': 'shape'}),
    ('configure', 'input_edit'): OpAlias('edit', since=_D, fixed={'kind': 'input'}),
    ('configure', 'output_edit'): OpAlias('edit', since=_D, fixed={'kind': 'output'}),
    ('configure', 'gis_input_edit'): OpAlias('edit', since=_D, fixed={'kind': 'gis_layer'}),
    ('configure', 'widget_edit'): OpAlias('edit', since=_D, fixed={'kind': 'widget'}),
    ('configure', 'tab_edit'): OpAlias('edit', since=_D, fixed={'kind': 'tab'}),
    ('configure', 'ai_agent_edit'): OpAlias('edit', since=_D, fixed={'kind': 'ai_agent'}),
    # ── 재설계 PR 8 (2026-11-03): 출처 일반화 — api_key 는 설정 화면에서만, 옛 SFK 전용 인자는 호환 없이 거절 ──
    ('configure', 'library_source_configure'): OpAlias('library_source', since=_D),
    ('configure', 'input_activate'): OpAlias('activate', since=_D),
    ('configure', 'gis_input_activate'): OpAlias('activate', since=_D),
}

def _minutes(v):
    return '%sm' % v if isinstance(v, (int, float)) or str(v).replace('.', '', 1).isdigit() else v


def _onoff(v):
    from aot.tools.domain import vocab
    got = vocab.onoff(v)
    return v if got is None else ('on' if got else 'off')


#: 옛 인자 이름 → 새 이름 (전역). 새 이름을 받는 op 에만 적용 — 그 op 가 옛 이름을 아직 스스로 받으면 건드리지 않는다.
ARG_ALIASES: Dict[str, ArgAlias] = {
    # 본문 글은 text (재설계 §2-2)
    'note': ArgAlias('text', _D), 'body': ArgAlias('text', _D), 'content': ArgAlias('text', _D),
    'message': ArgAlias('text', _D), 'advice': ArgAlias('text', _D), 'guidance': ArgAlias('text', _D),
    # 길이는 duration 하나 — 단위는 값에 (duration_minutes=15 → '15m')
    'duration_seconds': ArgAlias('duration', _D),
    'duration_minutes': ArgAlias('duration', _D, convert=_minutes),
    'step_duration': ArgAlias('duration', _D),
    # 켜기·끄기는 state
    'active': ArgAlias('state', _D, convert=_onoff), 'enabled': ArgAlias('state', _D, convert=_onoff),
    # 덧붙이는 행은 include_<x>, 한정은 only_<x>
    'with_sensors': ArgAlias('include_sensors', _D), 'with_options': ArgAlias('include_options', _D),
    'active_only': ArgAlias('only_active', _D),
    'program_uuid': ArgAlias('program_id', _D),
    # 기간은 period 하나 — 안쪽 도구의 안내문이 쓰던 time_range, 항목은 measurement
    'time_range': ArgAlias('period', _D),
    'sensor_type': ArgAlias('measurement', _D), 'measurement_type': ArgAlias('measurement', _D),
}

#: (도구, op) → {옛 인자 이름: 새 이름}. 그 op 안에서만 — 같은 이름이 op 마다 다른 뜻일 때.
OP_ARG_ALIASES: Dict[Tuple[str, str], Dict[str, ArgAlias]] = {
    # 노트의 제목은 title (개체의 이름은 name)
    ('record', 'note'): {'name': ArgAlias('title', _D)},
    # 작물(대상) 종류는 subject_kind — kind 는 KINDS 값 한 가지 뜻만
    ('cultivate', 'plot_create'): {'kind': ArgAlias('subject_kind', _D)},
    ('cultivate', 'plot_edit'): {'kind': ArgAlias('subject_kind', _D)},
    ('cultivate', 'program_create'): {'kind': ArgAlias('subject_kind', _D)},
    ('cultivate', 'program_edit'): {'kind': ArgAlias('subject_kind', _D)},
    ('find', 'programs'): {'kind': ArgAlias('subject_kind', _D)},
    # measure.history 의 limit 은 채널당 읽은 건수였다
    ('measure', 'history'): {'limit': ArgAlias('samples', _D)},
    # 시각 창(HH:MM)은 window_start/window_end — start/end 는 날짜일 때도 있어 이름만으로 형식을 못 짐작했다(2026-11-03 라운드 2)
    ('control', 'sequence_schedule'): {'start': ArgAlias('window_start', _D), 'end': ArgAlias('window_end', _D)},
    ('control', 'sequence_day'): {'start': ArgAlias('window_start', _D), 'end': ArgAlias('window_end', _D)},
}

#: (도구, op) → (옛 첫 칸, 옛 끝 칸, 등록일): 날짜 범위 두 칸은 `period`(FROM/TO) 하나로. 한 칸만 와도 받는다('FROM/'·'/TO').
#: 새 이름(`period`)이 이미 있으면 옛 이름은 건드리지 않는다.
PAIR_ALIASES: Dict[Tuple[str, str], Tuple[str, str, str]] = {
    ('records', 'journals'): ('date_from', 'date_to', _D),
    ('record', 'journal_create'): ('start', 'end', _D),
}


def _live(ops, tool, op):
    from aot.tools.domain.registry import find_op
    return find_op(ops, tool, op) is not None


def _ops_default():
    from aot.tools.domain.registry_data import OPS
    return OPS


def canonical(tool, op, ops=None):
    """별칭이면 (정식 도구, 정식 op), 아니면 그대로. 명부에 살아 있는 이름이 별칭보다 먼저다."""
    a = OP_ALIASES.get((tool, op))
    if a is None or _live(ops if ops is not None else _ops_default(), tool, op):
        return tool, op
    return (a.tool or tool), a.op


def canonical_op(tool, op, ops=None):
    """`canonical` 의 op 이름만."""
    return canonical(tool, op, ops)[1]


def resolve(tool, arguments, ops=None):
    """`resolve_call` 에서 도구를 뺀 것 → (새 인자, renamed). 도구가 바뀌는 별칭은 `resolve_call` 로."""
    _tool, args, renamed = resolve_call(tool, arguments, ops)
    return args, renamed


def resolve_call(tool, arguments, ops=None):
    """호출의 옛 이름을 새 이름으로 → (도구, 새 인자, renamed). 도구는 다른 도구로 합쳐진 op 일 때만 바뀐다.

    renamed 는 실제로 바꾼 것만: {'op=now': 'latest', 'note': 'text'}. 바꿀 것이 없으면 빈 dict 이고 인자는 그대로다.
    같은 새 이름이 이미 있으면 옛 이름을 덮어쓰지 않는다(호출이 둘 다 준 경우 — 새 이름이 이긴다).
    """
    args = dict(arguments or {})
    renamed = {}
    ops = ops if ops is not None else _ops_default()
    old_op = args.get('op')
    alias = OP_ALIASES.get((tool, old_op)) if old_op else None
    if alias is not None and not _live(ops, tool, old_op):
        new_tool = alias.tool or tool
        args['op'] = alias.op
        renamed['op=%s' % old_op] = alias.op if new_tool == tool else '%s.%s' % (new_tool, alias.op)
        for old, new in alias.rename.items():
            if old in args and new not in args:
                value = args.pop(old)
                conv = alias.convert.get(new)
                args[new] = conv(value) if conv else value
                renamed[old] = new
        for key, value in alias.fixed.items():
            args.setdefault(key, value)
        tool = new_tool
    from aot.tools.domain.registry import find_op
    o = find_op(ops, tool, args.get('op'))
    table = {}
    if o is not None:
        accepts = set(o.args) | set(o.extra_args)
        if any(k != 'none' for k in o.inner):
            accepts.add('target')
        for old, al in ARG_ALIASES.items():
            if al.new in accepts and old not in o.args and old not in o.extra_args:
                table[old] = al
    pair = PAIR_ALIASES.get((tool, args.get('op')))
    if pair and o is not None and o.period_pair and 'period' not in args and (pair[0] in args or pair[1] in args):
        first, last = args.pop(pair[0], None), args.pop(pair[1], None)
        if first and last:
            args['period'] = '%s/%s' % (first, last)
        else:
            args['period'] = '%s/' % first if first else '/%s' % last
        renamed['%s/%s' % (pair[0], pair[1])] = 'period'
    table.update(OP_ARG_ALIASES.get((tool, args.get('op')), {}))
    for old, al in table.items():
        if old in args and al.new not in args:
            value = args.pop(old)
            args[al.new] = al.convert(value) if al.convert else value
            renamed[old] = al.new
    return tool, args, renamed


def rows():
    """'옛 이름 → 새 이름 → 등록일' 전부 — 기본 표면 전환 2주 뒤 일괄 제거할 때 이 표를 본다."""
    out = []
    for (tool, old), a in sorted(OP_ALIASES.items()):
        out.append(('%s.%s' % (tool, old), '%s.%s' % (a.tool or tool, a.op), a.since))
        for o, n in sorted(a.rename.items()):
            out.append(('%s.%s(%s)' % (tool, old, o), n, a.since))
    for old, al in sorted(ARG_ALIASES.items()):
        out.append((old, al.new, al.since))
    for (tool, op), table in sorted(OP_ARG_ALIASES.items()):
        for old, al in sorted(table.items()):
            out.append(('%s.%s(%s)' % (tool, op, old), al.new, al.since))
    for (tool, op), (a, b, since) in sorted(PAIR_ALIASES.items()):
        out.append(('%s.%s(%s/%s)' % (tool, op, a, b), 'period', since))
    return out


def usage(rows, ops=None):
    """감사 행들에서 **옛 이름이 실제로 쓰인 호출 수** → {옛 이름: [횟수, 마지막 시각]}.

    rows: (tool_name, params(dict 또는 JSON 글), timestamp) 들 — `mcp_audit_log` 의 도메인 도구 행. 도메인 도구가 아닌 행·
    JSON 이 깨진 행은 건너뛴다. 같은 호출이 이름을 여럿 쓰면 이름마다 센다. 별칭 제거 전에(기본 표면 전환 2주 뒤) 이 표가
    0 에 가까운지 본다 — 0 이면 `rows()` 표를 비워도 된다."""
    import json
    from aot.tools.domain.registry import DOMAIN_TOOLS
    out = {}
    for tool, params, stamp in rows:
        if tool not in DOMAIN_TOOLS:
            continue
        if isinstance(params, str):
            try:
                params = json.loads(params or '{}')
            except (TypeError, ValueError):
                continue
        if not isinstance(params, dict):
            continue
        try:
            new_tool, new_args, renamed = resolve_call(tool, params, ops)
        except Exception:                                    # noqa: BLE001 — 집계가 호출을 깨면 안 된다
            continue
        for old in renamed:
            # `rows()` 의 이름과 같게: 'op=note_add' → 'record.note_add', op 안에서만 뜻이 있는 인자 → 'record.note(name)'.
            if old.startswith('op='):
                key = '%s.%s' % (tool, old[3:])
            elif old in OP_ARG_ALIASES.get((new_tool, new_args.get('op')), {}):
                key = '%s.%s(%s)' % (new_tool, new_args.get('op'), old)
            elif (new_tool, new_args.get('op')) in PAIR_ALIASES and '/' in old:
                key = '%s.%s(%s)' % (new_tool, new_args.get('op'), old)
            else:
                key = old
            hit = out.setdefault(key, [0, None])
            hit[0] += 1
            if stamp is not None and (hit[1] is None or stamp > hit[1]):
                hit[1] = stamp
    return out

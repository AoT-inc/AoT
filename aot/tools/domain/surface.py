# -*- coding: utf-8 -*-
"""도메인 도구의 tools/list 항목 — 설계 docs/design/mcp-domain-surface.md §4·§6.

명부에서 **이 키가 닿는 operation 만** 골라 도구 14개의 항목을 만든다. 닿는지는
지금 표면과 같은 규칙이다(역할로 숨긴 도구 `_hidden_tools` · 묶음 `tool_in_profile`).
operation 의 안쪽 도구가 하나도 안 닿으면 그 operation 은 싣지 않고, 일부 종류만
닿으면 그 종류만 남긴다. operation 이 하나도 없는 도구는 목록에 없다.

설명은 "언제 쓰나" 한 줄씩(§6). 쓰기는 필수 인자와 위험(효과·승인)을 싣는다(§3-2).
가벼움(lite)은 쓰기의 "언제 쓰나" 줄을 빼고 필수 인자·위험만 남긴다(§4).
"""
import re

from aot.tools.domain.registry import (
    DESTRUCTIVE_TOOLS, READ_TOOLS, WRITE_TOOLS, DOMAIN_TOOLS, VOCAB, Op)

#: 도구 머리 — 한 줄 목적(목록에 실린다). '언제 부르나·무엇을 하나' 만 적는다(설계 plans/mcp_act_say_split_design.md §3).
#: 예외 하나: 응답 계약(next·say) 규약과 언어 규칙을 진입 도구 overview 머리에 **한 번** 싣는다 — 서버 안내문을 모델에
#: 주지 않는 호스트(claude.ai 커넥터, 2026-10-26 첫 한마디가 영어로 나옴)가 호출 전에 보는 유일한 곳이다.
#: 'ALL tools' 로 범위를 밝힌다 — claude.ai 가 overview 전용 규칙으로 읽었다(10-29 사용자 확인).
CONTRACT_RULE = ("For ALL tools' results: next = follow-up calls, make those the question needs, never spoken; "
                 "say = tell the user in their language "
                 "(ask: ask, then wait). Never narrate tools.")
HEADERS = {
    'overview': "Status at a glance: map, site, zone, facility, plot, or whole farm. " + CONTRACT_RULE,
    'measure': "Sensor and output values: now, over a period, compared across places.",
    'weather': "Weather, forecast and local time of a place.",
    'find': "Find things: resolve a name, list devices/places/plots/maps, distance.",
    'detail': "Everything about a device, plot, function, program, or widget.",
    'records': "Notes, notices, journals, schedules, advice, knowledge, references.",
    'screen_view': "What the user's open AoT page shows right now.",
    'help': "Arguments, examples and rules of one operation: help(target='control.device_set').",
    'control': "Run devices and automation; every operation changes the field.",
    'record': "Write notes, notices, journals, schedules, advice.",
    'cultivate': "Plots, their stages and growing programs.",
    'configure': "Set up devices, functions, dashboards, maps, AI agents, tool profile.",
    'screen': ("Change the user's open AoT page, or show a result card (op=card). "
               "When asked to see or open something, call it even if you know the answer — "
               "a reply alone moves nothing."),
    'remove': "Delete things; no other tool deletes.",
}

#: 사람이 보는 이름(MCP annotations.title) — 호스트의 허락 창·설정 화면에 나온다.
#: annotations 안에 두어 모델이 받는 목록(크기 상한)에는 들지 않는다.
TITLES = {
    'overview': 'Status overview', 'measure': 'Sensor values', 'weather': 'Weather',
    'find': 'Find', 'detail': 'Details', 'records': 'Read records',
    'screen_view': 'Current screen', 'help': 'Help', 'control': 'Run devices',
    'record': 'Write records', 'cultivate': 'Plots and programs',
    'configure': 'Setup', 'screen': 'Change screen', 'remove': 'Delete',
}


def annotations_for(tool):
    """MCP 도구 표시 — claude.ai 는 이것으로 허락 창을 정한다(2026-10-14 확인).

    읽기 전용은 매번 묻지 않고, 파괴적인 도구는 늘 묻는다. 표시가 없으면 MCP 규격의
    기본값이 '파괴적' 이라 쓰기 도구에 '항상 허용' 이 먹지 않았다 — 그래서 쓰기 도구는
    파괴적이지 않음을 명시하고, 지우기는 `remove` 하나에 모아 그것만 파괴적이라 한다.
    AoT 안의 승인(안쪽 도구의 승인 요구)은 이 표시와 별개로 그대로 거친다.
    """
    ann = {"title": TITLES[tool]}
    if tool in READ_TOOLS:
        ann["readOnlyHint"] = True
    else:
        ann.update(readOnlyHint=False, destructiveHint=tool in DESTRUCTIVE_TOOLS,
                   openWorldHint=False)
    return ann

#: 공통 어휘의 스키마(§3) — 한 번만 정의한다.
VOCAB_SCHEMA = {
    'target': {"description": "Name, id or 'place > name'; a list for several where the op allows"},
    'period': {"type": "string", "description": "now|24h|7d|today|yesterday|tomorrow|"
                                              "this_week|YYYY-MM-DD|FROM/TO"},
    'at': {"type": "string", "description": "date/time; writes fix it to absolute"},
    'measurement': {"type": "string", "description": "everyday word: "
                                                   "temperature, soil moisture, rain"},
    'value': {"description": "value to set"},
    'query': {"type": "string"},
    'limit': {"type": "integer"},
    'fields': {"type": "array", "items": {"type": "string"}},
    'text': {"type": "string"},
    'title': {"type": "string"},
    'duration': {"description": "seconds, or 90s|15m|2h"},
    'state': {"description": "on|off"},
    'offset': {"type": "integer"},
    'samples': {"type": "integer"},
}

#: `help` 의 어휘표 — 같은 이름은 같은 뜻(재설계 §2-1). 도구 목록에는 싣지 않는다(토큰 0): 인자 없는 `help` 의 답에만.
#: op 별로 읽는 방식이 다른 낱말은 `help(target='tool.op')` 의 shared_args 가 그 op 의 뜻을 덧붙인다.
VOCAB_HELP = {
    'target': "name, id or 'place > name' of what to act on; a list where the op allows several",
    'text': "the body text (note, notice, schedule work, advice, card, stage guidance, knowledge)",
    'title': "a short heading; the name of a thing stays `name`",
    'period': "now|24h|7d|today|yesterday|tomorrow|this_week|YYYY-MM-DD|FROM/TO - a span of days or a look-back",
    'at': "one moment: YYYY-MM-DD, or with a time",
    'duration': "a length: seconds as a number, or 90s|15m|2h|1h30m - the same everywhere, whatever unit the op runs on",
    'state': "on|off to switch something; true/false and 1/0 are read the same",
    'limit': "how many rows to return",
    'offset': "rows to skip - the next_offset of the previous page",
    'samples': "points per channel spread over the period (measure.history); limit is rows elsewhere",
    'measurement': "everyday word: temperature, soil moisture, rain",
    'fields': "which facets of ONE thing to add to its brief answer",
    'include_<x>': "add a part to the answer (include_ended, include_past, include_options ...)",
    'only_<x>': "narrow the answer (only_active ...)",
    'kind': "a kind of target (KINDS); the crop/subject kind is `subject_kind`",
}

#: 화면 따라가기를 호출마다 정하는 인자(`_show_on_screen`)를 스키마에 싣는 도구 — 읽기 중 사고가 난 둘뿐이다
#: (2026-11-03 사용자 결정; 나머지 읽기는 서버 안내문 한 문장). 값은 양방향: 'off' 는 끄고 'on' 은 켠다.
SHOW_ARG = '_show_on_screen'
SHOW_ARG_TOOLS = ('measure', 'detail')
SHOW_ARG_SCHEMA = {"description": "off|on: follow on screen"}

#: 고르는 값이 정해진 고유 인자 — 스키마에 enum 으로 싣는다(모델은 목록에 있는 값만 안심하고 쓴다).
#: 설명이 `a|b|c` 낱말 나열뿐인 인자(screen.action·cultivate.action)도 enum 으로 싣는다 — 한 줄짜리
#: 나열은 읽기 어렵고 타입도 없었다(2026-11-09 claude.ai 점검 12·13번).
_ENUM_ARGS = {}
#: 읽기 도구 중 `at` 이 화면을 옮기는 것 — 예보는 사용자가 말한 시각으로 지도 시간 슬라이더를 옮긴다(조회 한 번으로).
_READ_AT = {'weather': "the time the user names (local); the map moves there"}
_PIPE_LIST = re.compile(r'^[a-z_]+(?:\|[a-z_]+)+$')


def _arg_schema(arg, desc):
    """고유 인자 하나의 스키마 — 정해진 값이면 enum, 아니면 설명만."""
    if arg in _ENUM_ARGS:
        return {"type": "string", "enum": _ENUM_ARGS[arg], "description": desc}
    if arg == 'focus':          # max|min|rain_start 또는 시각(HH:MM·ISO) — enum 이 아니라 문자열
        return {"type": "string", "description": desc}
    if _PIPE_LIST.match(desc or ''):
        return {"type": "string", "enum": desc.split('|')}
    return {"description": desc}

_EFFECT_MARK = {'physical': 'physical', 'automation': 'automation',
                'config': 'setup', 'permission': 'access', 'record': 'record',
                'screen': 'screen'}


def _reachable(o, ok):
    """이 키가 닿는 종류만 남긴 operation, 하나도 없으면 None."""
    inner = {k: v for k, v in o.inner.items() if ok(v)}
    if not inner:
        return None
    if inner == o.inner:
        return o
    return Op(**dict(o.__dict__, inner=inner,
                     target_arg={k: v for k, v in o.target_arg.items() if k in inner}))


def _target_note(tool, ops_t):
    """target 인자 설명 — 읽기는 여러 개, 쓰기는 하나(여러 개를 받는 operation 만 이름으로 밝힌다).

    쓰기는 `dispatch.plan` 이 한 번에 하나만 받는다("ONE target per call"). 예외는 `Op.expand_write`·`fan_write`
    (control.device_set 의 장치 목록, configure.sequence_create 의 출력 목록 …)."""
    base = "Name, id or 'place > name'; "
    if tool in READ_TOOLS:
        return base + "a list for several"
    several = [o.op for o in ops_t if (o.expand_write or o.fan_write) and o.inner.keys() - {'none'}]
    if several:
        return base + "a list only in " + ", ".join(several) + "; else one"
    return base + "one per call"


def _line(o, lite, approval):
    if o.tool in READ_TOOLS:
        return "%s — %s" % (o.op, o.use)
    needs = [r for r in o.required]
    risk = [_EFFECT_MARK.get(o.effect, o.effect)]
    if any(n in approval for n in o.inner_tools):
        risk.append('approval')
    tail = " [%s]" % "; ".join(risk)
    args = " (needs: %s)" % ", ".join(needs) if needs else ""
    if lite:
        return "%s%s%s" % (o.op, args, tail)
    return "%s — %s%s%s" % (o.op, o.use, args, tail)


def entries(ops, ok, approval, lite=False):
    """도메인 도구 항목 목록. `ok(inner_tool_name)` 은 이 키가 그 도구에 닿는가."""
    by = {}
    for o in ops:
        r = _reachable(o, ok)
        if r is not None:
            by.setdefault(o.tool, []).append(r)
    out = []
    for tool in DOMAIN_TOOLS:
        ops_t = by.get(tool)
        if not ops_t:
            continue
        if tool == 'help':
            # help 는 operation 을 고르는 도구가 아니라 하나뿐인 조회다 — op 목록·필수 op 없이 target 하나.
            out.append({"name": tool, "description": HEADERS[tool],
                        "inputSchema": {"type": "object",
                                        "properties": {"target": {"description": "tool.op, e.g. find.resolve; a tool name lists its ops"}},
                                        "required": [], "additionalProperties": True},
                        "annotations": annotations_for(tool)})
            continue
        lines = [HEADERS[tool], "op:"] + [_line(o, lite, approval) for o in ops_t]
        if tool in WRITE_TOOLS:
            lines.append("[effect, approval]: approval = a person approves in AoT first.")
        props = {'op': {"type": "string", "enum": [o.op for o in ops_t]}}
        if any(o.inner.keys() - {'none'} for o in ops_t):
            props['target'] = {"description": _target_note(tool, ops_t)}
        for o in ops_t:
            if (o.period_field or o.period_pair) and 'period' not in props:
                props['period'] = VOCAB_SCHEMA['period']
            for word in o.args:
                if word in VOCAB_SCHEMA and word not in props:
                    props[word] = VOCAB_SCHEMA[word]
                    if word == 'at' and tool in READ_TOOLS:
                        props[word] = {"type": "string", "description": _READ_AT.get(tool, "date/time")}   # 'writes fix it' 는 쓰기 얘기
                elif word in o.renamed and word not in props:
                    props[word] = {"description": o.renamed[word]}
            # 고유 인자는 필수인 것과 동작에 꼭 필요한 것(`shown`)만 스키마에 싣는다.
            # 나머지 선택 인자는 `help` 가 이름·뜻을 주고, 실행은 그대로 받는다. 모델은
            # 스키마에 없는 인자를 넣지 않는다 — 꼭 필요한 것을 빼면 그 동작은 못 한다.
            for arg in tuple(o.required) + tuple(o.shown):
                if arg in o.extra_args and arg not in props:
                    props[arg] = _arg_schema(arg, o.extra_args[arg])
        if tool in SHOW_ARG_TOOLS:
            props[SHOW_ARG] = SHOW_ARG_SCHEMA
        if any(set(o.extra_args) - set(o.required) - set(o.shown) for o in ops_t):
            lines.append("More args: help(target='%s.<op>')." % tool)
        entry = {"name": tool, "description": "\n".join(lines),
                 "inputSchema": {"type": "object", "properties": props,
                                 "required": ["op"],
                                 "additionalProperties": True}}
        entry["annotations"] = annotations_for(tool)
        out.append(entry)
    return out


def for_key(app, role, profile):
    """그 키(역할·묶음)의 도메인 도구 목록 — tools/list 가 쓴다."""
    from aot.tools import tool_execution as te
    from aot.tools import tool_registry as R
    from aot.tools.domain import contract
    from aot.tools.domain.registry_data import OPS
    hidden = te._hidden_tools(role)
    profile = te._effective_profile(profile)
    # 가벼움은 도메인 표면에서 운영과 합친다(2026-10-14 사용자 결정) — 새 틀에서는 둘의
    # 차이가 작다(벤치 입력 중앙값 48K 대 52K). 같은 도구에 닿는 묶음이라 목록도 같다.
    if te._is_lite(profile):
        profile = te._effective_profile(R.TOOL_PROFILE_OPERATIONS)
    lite = False

    def ok(name):
        return name not in hidden and R.tool_in_profile(name, profile, via_domain=True)

    ops = OPS
    if not contract.writes_enabled():
        ops = [o for o in OPS if o.tool not in WRITE_TOOLS]     # fail-closed
    return entries(ops, ok, set(R.approval_required_tools()), lite=lite)


__all__ = ['entries', 'for_key', 'annotations_for', 'HEADERS', 'TITLES', 'VOCAB_SCHEMA', 'VOCAB_HELP', 'VOCAB']

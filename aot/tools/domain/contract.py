# -*- coding: utf-8 -*-
"""명부 계약 검사 — 설계 docs/design/mcp-domain-surface.md §9-2.

명부(`registry_data.OPS`)를 **지금 도구 표면**과 대조한다. 문제가 하나라도 있으면
`writes_enabled()` 가 False 가 되어 도메인 쓰기 operation 은 목록에도 실행에도
나가지 않는다(fail-closed). 읽기는 계속 쓸 수 있다 — 읽기 문제는 그 operation 만
빠진다.

보는 것(차단 조건):
- 매핑 완전성: 지금 쓰기 도구마다 **정확히 한 번**(미매핑·중복 0), 읽기 도구는
  적어도 한 번, 없는 도구를 가리키지 않는다.
- 효과 일치: 읽기 도메인 도구는 읽기 도구만, 쓰기 도메인 도구는 쓰기 도구만(화면
  조작은 `ACTS_WITHOUT_SAVING`). 물리 도구(`PHYSICAL_TOOLS`)는 effect 'physical'.
- 승인 일관: 한 operation 안의 안쪽 도구들은 승인 요구가 같다 — 섞이면 목록의
  위험 표시가 일부에 거짓말이 된다. 승인 요구 자체는 명부에 칸이 없다(안쪽 도구
  에서 물려받는다 — 낮출 수단이 없다).
- 인자: 명부가 가리키는 안쪽 인자 이름이 실제 스키마에 있다. 고유 인자에는 이유가 있다.
- 확장: `expand_write` 는 목록 인자를 가진 쓰기 도구에만. `fan_write` 는 목록을 못 받는 물리 제어에만.
- 형식: 도구·종류·효과가 어휘 안, op 이름이 도구 안에서 고유, `use` 90자 이하.
"""
import logging

from aot.tools.domain.slim import DOMAIN_WORDS

from aot.tools.domain.registry import (
    DESTRUCTIVE_TOOLS, DOMAIN_TOOLS, EFFECTS, KINDS, READ_TOOLS, is_vocab)

logger = logging.getLogger(__name__)

#: 실행 장치(목록에 싣지 않는 위임 도구) — 명부 대상이 아니다.
MACHINERY = frozenset({'use_tool', 'read_tool', 'open_drawer'})


#: 도메인 표면에서 따로 부르지 않는 읽기 안쪽 도구 → 그 일을 맡은 op. 합친 op 가 다른 안쪽 도구로 같은 일을 하면
#: 옛 도구는 "미매핑 읽기 도구" 가 된다. 인앱 AI 도 도메인 명부만 보므로(26-11 5단계) 이런 도구는 지운다 —
#: 남은 것은 인앱 프롬프트·계획기가 아직 이름으로 부르는 것뿐이다.
#: 여기에 적어야 미매핑 검사를 면한다 — 이유(맡은 op)가 있고, 실제 도구이며, 아직 어느 op 도 부르지 않을 때만.
COVERED_ELSEWHERE = {
    'get_device_list': 'find.devices (no keyword = every device)',
}


def catalog():
    """이름 → MCP 정의(앱 없이 만든 카탈로그 — 테스트와 같은 원천)."""
    from aot.tools import tool_registry as R
    from aot.tools import tool_execution as te
    from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
    out = {t['tool_name']: {'name': t['tool_name'],
                            'description': t['description'],
                            'inputSchema': t['input_schema']}
           for t in R.virtual_tools()}
    out['get_sensor_reading'] = N._schema_get_sensor_reading([])
    out['list_available_devices'] = N._schema_list_available_devices([])
    out['set_output_state'] = N._schema_set_output_state([])
    for t in te._EXTRA_TOOLS:
        out[t['name']] = dict(t)
    return out


def _handler_names(name):
    from aot.tools.tool_execution import _handler_param_names
    return _handler_param_names(name)


def handler_arg_names(name):
    """스키마에 싣지 않고 처리기만 이름으로 받는 인자들(예 get_plot 의 recent_days)."""
    return _handler_names(name) if name else set()


def _props(defn):
    return set(((defn or {}).get('inputSchema') or {}).get('properties') or {})


def _props_full(defn):
    return ((defn or {}).get('inputSchema') or {}).get('properties') or {}


def _array_props(defn):
    props = ((defn or {}).get('inputSchema') or {}).get('properties') or {}
    return {k for k, v in props.items() if (v or {}).get('type') == 'array'}


def _expand(ops, out, approval):
    """검사 단위 (Op, 꼬리표) — 값으로 안쪽 도구를 고르는 op(`Op.pick_by_arg`)는 가지마다 따로 검사하고,
    합친 op 자체에는 가지 사이의 약속(같은 효과·같은 승인 요구·이름·합집합)만 본다. 그 밖의 op 는 그대로 하나."""
    parents = set()
    for o in ops:
        tag = '%s.%s' % (o.tool, o.op)
        pk = o.pick_by_arg
        if pk is None:
            yield o, tag
            continue
        if tag in parents:
            out.append('%s: duplicate op name' % tag)
        parents.add(tag)
        if not pk.branches:
            out.append('%s: pick_by_arg without branches' % tag)
        if pk.normalize not in ('', 'onoff'):
            out.append('%s: unknown pick normalize %r' % (tag, pk.normalize))
        if pk.arg not in o.args and pk.arg not in o.extra_args:
            out.append('%s: pick argument %r is not an argument of the op' % (tag, pk.arg))
        effects = {b.effect for b in pk.branches.values()}
        # 가지의 효과가 다르면(지우기: 기록·설정) 목록 표시는 그중 하나로 — 가지에 없는 효과를 말하면 거짓이다.
        if o.effect not in effects or (len(effects) > 1 and not pk.infer):
            out.append('%s: branches differ in effect from the op (%s)' % (tag, o.effect))
        names, mix = set(), set()
        for value, b in pk.branches.items():
            if (b.tool, b.op) != (o.tool, o.op) or b.pick_by_arg is not None:
                out.append('%s[%s]: a branch is the same op without a pick of its own' % (tag, value))
            for n in b.inner.values():
                names.add(n)
                mix.add(n in approval)
        if len(mix) > 1:
            out.append('%s: branches mix approval and no-approval inner tools' % tag)
        for kind, n in o.inner.items():
            if n not in names:
                out.append('%s: kind %r points at %r which no branch uses' % (tag, kind, n))
        for value, b in pk.branches.items():
            yield b, '%s[%s]' % (tag, value or 'none')


def problems(ops=None, cat=None):
    """명부 문제 목록(문자열). 빈 목록이면 계약을 지킨다."""
    from aot.tools import mcp_safety_gate as gate
    from aot.tools import tool_registry as R
    if ops is None:
        from aot.tools.domain.registry_data import OPS as ops
    cat = cat if cat is not None else catalog()
    out = []
    facades = set(getattr(R, 'MCP_FACADES', {}))
    screen = set(getattr(R, 'ACTS_WITHOUT_SAVING', ()))
    approval = set(R.approval_required_tools())

    def is_write(name):
        return gate.classify_permission(name) == 'write'

    seen_ops, write_seen, read_seen = set(), {}, set()
    for o, tag in _expand(ops, out, approval):
        if o.tool not in DOMAIN_TOOLS:
            out.append('%s: unknown domain tool' % tag)
        if tag in seen_ops:
            out.append('%s: duplicate op name' % tag)
        seen_ops.add(tag)
        if o.effect not in EFFECTS:
            out.append('%s: unknown effect %r' % (tag, o.effect))
        if len(o.use or '') > 90 or not (o.use or '').strip():
            out.append('%s: use line missing or over 90 chars' % tag)
        if not o.inner:
            out.append('%s: no inner tool' % tag)
        for kind in o.inner:
            if kind not in KINDS:
                out.append('%s: unknown target kind %r' % (tag, kind))
        for kind in o.target_arg:
            if kind not in o.inner:
                out.append('%s: target_arg for kind %r it does not accept' % (tag, kind))
        for kind, vals in o.defaults_by_kind.items():
            if kind not in o.inner:
                out.append('%s: defaults for kind %r it does not accept' % (tag, kind))
            props = _props(cat.get(o.inner.get(kind)))
            # 스키마에 싣지 않는 처리기 인자(예: get_sensor_detail 의 brief)도 기본값으로 켤 수 있다 —
            # 도메인 표면만 켜고 인앱 AI 등 다른 소비자의 응답은 그대로 두는 길이다.
            hidden = _handler_names(o.inner.get(kind)) if o.inner.get(kind) else set()
            for arg in vals:
                if arg not in props and arg not in hidden:
                    out.append('%s: default arg %r not in the inner schema' % (tag, arg))
        for arg, table in o.kinds_by_arg.items():
            if arg not in o.extra_args and arg not in o.args:
                out.append('%s: kinds_by_arg on %r which it does not take' % (tag, arg))
            for value, kinds in table.items():
                for kind in kinds:
                    if kind not in o.inner:
                        out.append('%s: kinds_by_arg %s=%s names kind %r it does not '
                                   'accept' % (tag, arg, value, kind))
        for k in o.shown:
            if k not in o.extra_args:
                out.append('%s: shown arg %r is not an extra arg' % (tag, k))
        for k, why in o.extra_args.items():
            if not str(why or '').strip():
                out.append('%s: extra arg %r has no reason' % (tag, k))
            if k in ('op', 'target'):
                out.append('%s: extra arg %r collides with the domain %r — rename it '
                           'through args + renamed' % (tag, k, k))
        for word in o.args:
            if word in ('op', 'target'):
                out.append('%s: args key %r is reserved' % (tag, word))
            elif not is_vocab(word) and not str(o.renamed.get(word) or '').strip():
                out.append('%s: args key %r is not a shared word and has no '
                           'renamed reason' % (tag, word))
        inner_approval = set()
        for kind, name in o.inner.items():
            if name in MACHINERY or name in facades:
                out.append('%s: maps machinery/facade %r (map the inner tools)' % (tag, name))
                continue
            defn = cat.get(name)
            if defn is None:
                out.append('%s: inner tool %r does not exist' % (tag, name))
                continue
            props = _props(defn)
            ta = o.target_arg.get(kind)
            # 스키마에 싣지 않는 처리기 인자(find.controllable 의 place_id)도 대상 칸으로 쓸 수 있다.
            if ta and ta not in props and ta not in _handler_names(name):
                out.append('%s: %s has no arg %r (target for %s)' % (tag, name, ta, kind))
            writing = is_write(name) or name in screen
            if o.tool in READ_TOOLS:
                if writing:
                    out.append('%s: read tool routes to write tool %r' % (tag, name))
                if o.effect != 'read':
                    out.append('%s: read tool with effect %r' % (tag, o.effect))
                read_seen.add(name)
            else:
                if not writing:
                    out.append('%s: write tool routes to read tool %r' % (tag, name))
                if o.effect == 'read':
                    out.append('%s: write op with effect read' % tag)
                # 대상 없이 고정 인자('none' 기본값)로 같은 안쪽 도구를 부르는 별칭 작업(screen.card =
                # screen_action 의 post)은 매핑 한 번 규칙을 깨지 않는다 — 본 작업이 이미 그 도구를 맡는다.
                if not (o.defaults_by_kind or {}).get('none'):
                    write_seen.setdefault(name, set()).add(tag)
            if name in gate.PHYSICAL_TOOLS and o.effect != 'physical':
                out.append('%s: physical tool %r not marked physical' % (tag, name))
            # 지우는 안쪽 도구는 지우는 도메인 도구에만 — 섞이면 그 도구의 MCP 표시
            # (destructiveHint)가 거짓이 된다. 이름으로 가른다: 지우는 안쪽 도구는 전부
            # delete_·remove_ 로 시작한다.
            if name.startswith(('delete_', 'remove_')) != (o.tool in DESTRUCTIVE_TOOLS):
                out.append('%s: %r — deleting inner tools belong only in %s'
                           % (tag, name, '/'.join(DESTRUCTIVE_TOOLS)))
            inner_approval.add(name in approval)
        # 같은 operation 안에서 승인 요구가 섞이지 않는다.
        if len(inner_approval) > 1:
            out.append('%s: mixes approval and no-approval inner tools' % tag)
        # 공통 어휘·고유 인자가 가리키는 안쪽 인자가 실제로 있는가.
        all_props = set().union(*(_props(cat.get(n)) for n in o.inner.values())) \
            if o.inner else set()
        # 스키마에 싣지 않는 숨은 인자(처리기가 이름으로 받는 별칭, 예 screen_action 의
        # card)도 처리기 서명에 있으면 맞는 이름이다.
        handler_names = set()
        for n in o.inner.values():
            handler_names |= _handler_names(n)
        for word, arg in o.args.items():
            if o.slim and word in DOMAIN_WORDS:
                continue                    # 이 층이 처리하는 낱말(slim.py) — 안쪽 도구는 모른다
            if arg not in all_props and arg not in handler_names:
                out.append('%s: arg %r → %r not in inner schema' % (tag, word, arg))
        for arg in o.extra_args:
            if arg not in all_props and arg not in handler_names:
                out.append('%s: extra arg %r not in inner schema' % (tag, arg))
        # 기간 — 공통 낱말을 안쪽 인자로 그대로 넘기지 않는다(2026-10-14 웹 시험: 예보에
        # hours='tomorrow'). 모양을 적고, 그 모양이 안쪽 인자의 형식과 맞아야 한다.
        if 'period' in o.args:
            from aot.tools.domain.vocab import PERIOD_FORMS
            form = o.period_form
            if form not in PERIOD_FORMS:
                out.append('%s: period mapped without a period_form' % tag)
            else:
                for name in set(o.inner.values()):
                    props = _props_full(cat.get(name))
                    if o.args['period'] not in props:
                        continue            # 이 종류의 안쪽 도구는 기간을 받지 않는다
                    prop = props[o.args['period']] or {}
                    typ = prop.get('type')
                    want = {'lookback': 'string', 'days': 'integer', 'span': 'string',
                            'forecast': 'integer', 'range': 'string'}[form]
                    if form == 'range' and 'FROM/TO' not in str(prop.get('description')):
                        # 날짜 구간을 받는다고 안쪽 도구가 스스로 말해야 한다.
                        out.append('%s: period_form range but %s.%s does not take FROM/TO'
                                   % (tag, name, o.args['period']))
                    if typ != want or (form == 'span') != bool(prop.get('enum')):
                        out.append('%s: period_form %r does not fit %s.%s (%s)' % (
                            tag, form, name, o.args['period'], typ))
                if form == 'forecast' and 'at' not in o.args:
                    out.append('%s: forecast period needs the start argument (at)' % tag)
        elif o.period_form:
            out.append('%s: period_form without a period argument' % tag)
        for name in o.period_pair:
            if name not in all_props and name not in handler_names:
                out.append('%s: period_pair %r not in inner schema' % (tag, name))
        if o.period_pair and (o.period_field or 'period' in o.args):
            out.append('%s: period_pair together with another period route' % tag)
        if o.expand_write:
            if o.tool in READ_TOOLS:
                out.append('%s: expand_write on a read tool' % tag)
            arrays = set().union(*(_array_props(cat.get(n)) for n in o.inner.values()))
            if not arrays:
                out.append('%s: expand_write but no list argument' % tag)
        if o.fan_write:
            # 대상마다 안쪽 호출을 따로 거는 것은 물리 제어 하나뿐이고, 안쪽 도구가 목록을 받으면 expand_write 다.
            if o.effect != 'physical':
                out.append('%s: fan_write on a non-physical operation' % tag)
            if o.expand_write:
                out.append('%s: fan_write and expand_write together' % tag)
            if set().union(*(_array_props(cat.get(n)) for n in o.inner.values())):
                out.append('%s: fan_write but the inner tool already takes a list' % tag)

    # 매핑 완전성 — 지금 표면 전수.
    for name in sorted(cat):
        if name in MACHINERY or name in facades:
            continue
        if is_write(name) or name in screen:
            tags = write_seen.get(name, set())
            if not tags:
                out.append('unmapped write tool %r' % name)
            elif len(tags) > 1:
                out.append('write tool %r mapped more than once: %s' % (name, sorted(tags)))
        elif name in COVERED_ELSEWHERE:
            if name in read_seen:
                out.append('read tool %r is mapped again - drop it from COVERED_ELSEWHERE' % name)
        elif name not in read_seen and name != 'get_tool_detail':
            out.append('unmapped read tool %r' % name)
    return out


_STATE = {}


def writes_enabled(refresh=False):
    """명부가 계약을 지킬 때만 True — 아니면 도메인 쓰기는 켜지지 않는다."""
    if refresh or 'ok' not in _STATE:
        try:
            found = problems()
        except Exception as exc:                            # noqa: BLE001
            logger.exception('[domain] 명부 검사 실패 — 쓰기를 끈다')
            found = ['contract check failed: %s' % exc]
        _STATE['ok'] = not found
        _STATE['problems'] = found
        if found:
            logger.error('[domain] 명부 계약 위반 %d건 — 도메인 쓰기를 끈다: %s',
                         len(found), found[:5])
    return _STATE['ok']


def last_problems():
    writes_enabled()
    return list(_STATE.get('problems') or [])

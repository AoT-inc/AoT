# -*- coding: utf-8 -*-
"""도메인 도구 호출 → 안쪽 도구 호출 — 설계 docs/design/mcp-domain-surface.md §2-3·§9.

여기서 하는 일은 셋뿐이다:
1. operation 을 명부에서 찾는다(없으면 거절).
2. `target` 을 한 번 풀고(`targets.resolve`) operation 의 `accepts` 와 대조한다.
   쓰기는 **펼치지도 올리지도 않는다** — 그릇·여러 대상·모호함은 게이트 앞에서 거절.
3. 안쪽 도구 인자를 만들어 **지금 실행층(`_execute_tool`)으로만** 부른다.
   승인·권한·그룹 스코프·감사는 안쪽 도구 이름으로 거기서 일어난다. 이 모듈은
   승인 판정을 하지 않는다 — 두 번째 판정자를 만들지 않는다.

쓰기 호출에는 해석 결과의 스냅샷(`_domain_target`)을 인자에 실어 보낸다. 승인 행에
그대로 저장되고(`params_json`), 승인 실행 직전 `targets.changed` 가 비교한다.
처리기에는 넘어가지 않는다(`tool_execution._dispatch_virtual_tool` 이 뺀다).
"""
import json
from dataclasses import replace
import logging
import re

from aot.tools.domain import act_say, contract, renames, server_card, server_viz, session_rules, slim, targets
from aot.utils.timekit import FARM, today_at
from aot.tools.domain.registry import (
    ID_ONLY_KINDS, PLACE_KINDS, READ_TOOLS, WRITE_TOOLS, find_op)

PLACE_KINDS_ALL = PLACE_KINDS

logger = logging.getLogger(__name__)

#: 해석 스냅샷을 싣는 인자 이름 — 승인 스냅샷에는 남고 처리기에는 안 간다.
SNAPSHOT_KEY = '_domain_target'
#: 응답에 덧붙일 틀의 해석(어느 대상·어떤 기간으로 읽었나). `_run` 이 안쪽 호출 전에
#: 떼어 응답에 싣는다 — 안쪽 도구에는 가지 않는다.
META_KEY = '_domain_meta'
#: 지도 밖의 화면 대상 — `kind` 로 말하면 그 종류로 좁힌다.
_SCREEN_KINDS = frozenset({'widget', 'dashboard', 'tab'})
#: 목록 인자로 한 번에 넘길 수 있는 수(안쪽 도구의 상한)와 펼쳐 읽을 전체 상한.
_LIST_CHUNK = 10
_LIST_TOTAL = 40


def _ops():
    from aot.tools.domain.registry_data import OPS
    return OPS


#: 숨은 별칭(op·인자 이름·고정 인자)은 `renames` 표에 있다 — 목록·스키마·help 에는 새 이름만 실려 토큰이 늘지 않는다.
#: 정식 이름만 명부(`OPS`)에 있고, 시험이 별칭이 실제 op/인자를 가리키는지 본다.
def canonical(tool, op):
    return renames.canonical(tool, op)


#: 계산뿐인 조회 — 특정 대상을 읽어 보여 주는 것이 아니라 대상을 재료로 계산·해석만 한다(2026-11-03 사용자 결정).
#: 기본으로 사용자 화면을 따라가지 않는다. 호출이 `_show_on_screen` 을 **명시**('on'·화면 id)하면 따른다 — 양방향.
#: 나머지 읽기(detail.*·measure.latest 의 대상 지정 …)는 지금처럼 기본으로 따라가고 'off' 로 끈다.
NO_FOLLOW_OPS = frozenset({
    ('find', 'nearest'), ('find', 'distance'), ('find', 'address'),
    ('find', 'resolve'), ('find', 'aliases'),
})


def effective_show(tool, op, show):
    """이 호출의 화면 따라가기 값 — 계산뿐인 op 는 명시한 'on'·화면 id 가 아니면 'off'."""
    if (tool, op) not in NO_FOLLOW_OPS:
        return show
    from aot.tools import screen_follow
    return show if screen_follow.show_is_explicit_on(show) else 'off'


def _error(message, **extra):
    body = dict({"status": "error", "message": message}, **extra)
    return [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]


def _kind_lookup(accepts):
    """이 operation 이 받는 대상 종류를 찾는 길 한 줄 — "takes function, not a facility" 다음에 무엇을 부를지."""
    ways = {'function': "find(op='functions')", 'plot': "find(op='plots')",
            'device': "find(op='devices', query=<word>)", 'input': "find(op='devices', query=<word>)",
            'output': "find(op='devices', query=<word>)", 'zone': "find(op='tree')", 'site': "find(op='tree')",
            'facility': "find(op='tree')", 'map': "find(op='maps')"}
    found = [ways[k] for k in accepts if k in ways]
    return ("%s finds the %s" % (found[0], accepts[0])) if found else "find(op='resolve', target=<name>)"


def _where_to_look(kinds):
    """없는 대상을 찾을 길 한 줄(`unknown_target` 의 `next.call`) — 받는 종류마다 찾는 호출, 모르는 종류면 resolve."""
    ways = []
    for k in kinds:
        w = _kind_lookup([k])
        if w.startswith('find(op=') and ' finds ' in w:
            w = w.split(' finds ')[0]
            if w not in ways:
                ways.append(w)
    head = " or ".join(ways[:2]) if ways else "find(op='resolve', target=<name>)"
    return head + " finds it; call again with its path or id"


def _cue(c):
    """후보 한 건의 경로 — 종류가 경로에 드러나지 않으면(지도·함수처럼 이름뿐) 종류를 앞에 붙인다.
    같은 이름이 지도·입력 탭·대시보드 탭에 겹칠 때 어느 것인지 가려지도록('map > 영양')."""
    path = c.get('path') or c.get('name') or '?'
    if ' > ' in str(path) or not c.get('kind'):
        return path
    return "%s > %s" % (c['kind'], path)


def _kinds_said(cands):
    """후보를 종류가 보이게 한 줄로 — 'dashboard > 영양; input tabs > 영양; map > 영양'."""
    return "; ".join(str(_cue(c) if c.get('path') else "%s %s" % (c.get('kind'), c.get('name')))
                     for c in cands[:6]) + ("; …" if len(cands) > 6 else "")


def _candidates(cands):
    out = []
    for c in cands:
        d = dict({k: c.get(k) for k in ('kind', 'name', 'id')}, path=_cue(c))
        if c.get('matched') == 'alias':
            d.update(matched_by='alias', alias=c.get('alias'))
        if c.get('on_screen'):
            d['on_screen'] = True
        out.append(d)
    return out


def _ambiguous_note(cands):
    """후보 정렬(`targets.rank`)이 알게 된 것 — 되묻는 말에 덧붙이는 한 줄."""
    note = ""
    if cands and cands[0].get('on_screen'):
        note += " The first is on the dashboard the user is looking at."
    kinds = {c.get('kind') for c in cands}
    if 'widget' in kinds and len(kinds) > 1:
        note += " A widget is a graph/card on a dashboard — for a graph, it is the widget."
    return note


def _children_of(target):
    """그릇 안의 대상 — 쓰기에서 그릇이 오면 고르라고 보이는 후보."""
    from aot.databases.models import GeoShape
    if target['kind'] == 'map':
        rows = GeoShape.query.filter(GeoShape.geo_id == target['id'],
                                     GeoShape.type == 'site').all()
    elif target['kind'] in ('site', 'zone'):
        from aot.space.device_membership import PlaceIndex
        idx = PlaceIndex()
        rows = [s for s in idx.shapes if s.type in ('zone', 'facility')
                and s.unique_id != target['id']
                and target['id'] in idx.chain_uids(s)]
    else:
        rows = []
    out = []
    for r in rows[:20]:
        t = targets._of_shape(r)
        if t is not None:
            out.append(t)
    return out


#: 이름만 받는 안쪽 인자 — 틀이 id 대신 "그것 하나만 가리키는 이름" 을 넘긴다.
NAME_PARAMS = frozenset({'target_name', 'target_names', 'area_name', 'zone_name'})


def _verified_name(target):
    """대상을 그것 하나만 가리키는 이름으로 — 안쪽 이름 해석(`_resolve_note_target`)을
    거쳐 같은 id 로 되돌아오는 것만. 이름 · '지도 이름' · 경로 순으로 시험한다."""
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    tries = [target.get('name')]
    if target.get('map'):
        tries.append('%s %s' % (target['map'], target.get('name')))
    path = target.get('path') or ''
    if ' > ' in path:
        tries.append(path.replace(' > ', ' '))
    want = target['id']
    for cand in tries:
        if not cand:
            continue
        try:
            got = S._resolve_note_target(cand)[0]
        except Exception:                                   # noqa: BLE001
            got = None
        if got and str(got).split('::')[0] == want:
            return cand
    return None


def _arg_is_list(inner, arg):
    if not arg:
        return False
    from aot.tools.domain.contract import catalog
    prop = ((catalog().get(inner) or {}).get('inputSchema') or {}) \
        .get('properties', {}).get(arg) or {}
    return prop.get('type') == 'array'


def _descendants(target):
    """그릇 아래의 장소 전부(대지·구역·시설) — 읽기 펼치기가 깊이를 고른다."""
    from aot.space.device_membership import PlaceIndex
    from aot.databases.models import GeoShape
    idx = PlaceIndex()
    if target['kind'] == 'map':
        rows = [s for s in GeoShape.query.filter(GeoShape.geo_id == target['id']).all()
                if (s.type or '') in ('site', 'zone', 'facility')]
    elif target['kind'] in ('site', 'zone'):
        rows = [s for s in idx.shapes if s.type in ('zone', 'facility')
                and s.unique_id != target['id'] and target['id'] in idx.chain_uids(s)]
    else:
        rows = []
    out = []
    for r in rows:
        t = targets._of_shape(r, idx)
        if t is not None:
            out.append(t)
    return out


_DEVICE_KINDS = ('input', 'output', 'device')
_PLACE_SHAPE_KINDS = ('site', 'zone', 'facility')


def _ancestors(target):
    """작은 것(시설·구획·장치) → 감싸는 장소, 가까운 것부터(§2-3 '올려 답한다')."""
    from aot.space.device_membership import PlaceIndex, maps_for_device, zone_for_device
    from aot.databases.models import GeoFacility, GeoPlot, GeoShape
    idx = PlaceIndex()
    shapes = []
    kind = target['kind']
    if kind in _PLACE_SHAPE_KINDS:
        sh = idx.by_uid.get(target['id'])
        if sh is not None:
            shapes = list(reversed(idx.chain(sh)))[1:]
    elif kind == 'plot':
        row = GeoPlot.query.filter(GeoPlot.unique_id == target['id']).first()
        if row is not None:
            if getattr(row, 'facility_uuid', None):
                fac = GeoFacility.query.filter(GeoFacility.unique_id == row.facility_uuid).first()
                fsh = idx.by_uid.get(fac.shape_uuid) if fac is not None else None
                if fsh is not None:
                    shapes.append(fsh)
            cont = idx.plot_container(row)
            if cont is not None:
                shapes.extend(reversed(idx.chain(cont)))
    elif kind in _DEVICE_KINDS:
        for m in maps_for_device(target['id']):
            z = zone_for_device(target['id'], m)
            if z is not None:
                zsh = idx.by_uid.get(z.unique_id) or z
                shapes.extend(reversed(idx.chain(zsh)))
                break
        if not shapes:
            # 장치 영역 도형(type='device' — 밸브가 덮는 구역 등)은 장치 행이 아니라 도형이다.
            # 이름으로 풀리면 이 id 가 온다 — 도형 계층으로 감싸는 장소를 찾는다.
            sh = idx.by_uid.get(target['id'])
            if sh is not None:
                shapes = list(reversed(idx.chain(sh)))[1:]
    out, seen = [], set()
    for sh in shapes:
        t = targets._of_shape(sh, idx)
        if t is not None and t['id'] not in seen:
            seen.add(t['id'])
            out.append(t)
    return out


def _device_ids_in(target):
    """장소(지도·대지·구역·시설·구획) 안의 장치 id — 지금 소속 판정 그대로."""
    from aot.space.device_membership import device_ids_in_area
    ids = []
    if target['kind'] == 'map':
        places = [c for c in _descendants(target) if c['kind'] == 'site']
    elif target['kind'] == 'plot':
        places = _ancestors(target)[:1]
    else:
        places = [target]
    for p in places:
        got = device_ids_in_area(p['id'], include_references=False) or ()
        for d in sorted(got):
            d = str(d).split('::')[0]
            if d not in ids:
                ids.append(d)
    return ids


def _plots_in(target):
    """장소 안의 재배 중 구획 — 지금 소속 판정(PlaceIndex.plot_within·시설 지정) 그대로."""
    from aot.space.device_membership import PlaceIndex
    from aot.databases.models import GeoFacility, GeoPlot
    idx = PlaceIndex()
    rows = GeoPlot.query.filter(GeoPlot.ended_on.is_(None)).all()
    if target['kind'] == 'map':
        rows = [r for r in rows if r.geo_id == target['id']]
    else:
        fac_ids = set()
        if target['kind'] == 'facility':
            fac_ids = {f.unique_id for f in GeoFacility.query.filter(
                GeoFacility.shape_uuid == target['id']).all()}
        rows = [r for r in rows if (getattr(r, 'facility_uuid', None) in fac_ids)
                or idx.plot_within(r, target['id'])]
    return [targets._of_plot(r, idx) for r in rows]


def _device_targets(ids, kinds):
    from aot.databases.models import CustomController, Input, Output
    try:
        from aot.utils.functions import device_module_names
        complex_names = set(device_module_names() or ())
    except Exception:                                      # noqa: BLE001
        complex_names = None
    out = []
    for d in ids:
        for model, kind in ((Input, 'input'), (Output, 'output'), (CustomController, 'device')):
            if kind not in kinds:
                continue
            r = model.query.filter(model.unique_id == d).first()
            # 시설 안의 환경제어 같은 *함수*(CustomController)는 장치가 아니다 — 출력 상태를
            # 시설 이름으로 물으면 그것이 잡혀 오류가 났다(2026-10-28 점검).
            if r is not None and model is CustomController and complex_names is not None \
                    and r.device not in complex_names:
                continue
            if r is not None:
                out.append({'kind': kind, 'id': r.unique_id, 'name': r.name, 'path': r.name})
                break
    return out


def plan(tool, arguments, ops=None, user=None, session=None):
    """도메인 호출 → ('call', inner, inner_args) | ('refuse', 본문 블록).

    실행과 분리해 두어 테스트가 "게이트 앞에서 거절되는가" 를 실행 없이 본다.
    user: 부른 사용자 uuid — 같은 이름 후보를 그가 지금 보는 화면으로 늘어놓고, 읽기·화면 이동은 맥락이 하나만 가리키면
    그것으로 간다. session: 대화 열쇠 — 이 대화가 최근 가리킨 대상(맥락 근거의 하나).
    """
    notes = {}
    verdict = _plan(tool, arguments, ops, user, session, notes)
    if verdict[0] == 'refuse':
        return verdict
    if notes.get('seen'):
        targets.remember(user, session, notes['seen'])
    if notes.get('picks'):
        picked = {"picked_by": "context", "picked": notes['picks']}
        if verdict[0] == 'call':
            verdict[2].setdefault(META_KEY, {}).update(picked)
        elif verdict[0] == 'fanout':
            verdict[3].update(picked)
        elif verdict[0] == 'filter':
            verdict[3].update(picked)
    return verdict


def _context_pickable(tool, o):
    """맥락으로 하나를 고를 수 있는 호출 — 읽기, 그리고 화면만 바꾸는 화면 조작. 물리 제어·기록·삭제·설정은 늘 되묻는다."""
    return tool in READ_TOOLS or (tool == 'screen' and o.effect == 'screen')


def _plan(tool, arguments, ops, user, session, notes):
    ops = ops if ops is not None else _ops()
    tool, arguments, _renamed = renames.resolve_call(tool, arguments, ops)
    op_name = arguments.pop('op', None)
    o = find_op(ops, tool, op_name)
    if o is None:
        names = sorted(x.op for x in ops if x.tool == tool)
        return 'refuse', _error("%s needs 'op' — one of: %s." % (tool, ", ".join(names)),
                                reason_code='unknown_op')
    writing = tool in WRITE_TOOLS
    if writing and not contract.writes_enabled():
        return 'refuse', _error(
            "Writes through %s are switched off: the operation registry failed its "
            "safety check. Nothing was run." % tool, reason_code='registry_check_failed')
    missing = _missing_required(o, arguments)
    if missing:
        return 'refuse', _error(
            "%s.%s needs %s — nothing was run. help(target='%s.%s') lists the "
            "arguments." % (tool, o.op, ", ".join(missing), tool, o.op),
            reason_code='missing_argument')
    if o.period_pair and 'period' in arguments:
        pair = _pair_range(arguments.pop('period'))
        if isinstance(pair, list):
            return 'refuse', pair
        arguments['_pair'] = pair                 # `_inner_args` 가 안쪽 두 칸으로 푼다(밑줄 인자는 거절 대상이 아니다)
    infer_kinds = None
    if o.pick_by_arg is not None:
        # 같은 종류 안에서 인자 값이 안쪽 도구를 고른다(재설계 PR 6) — 고른 가지 Op 가 이 호출의 명부다.
        merged = o
        o, refused = _pick_branch(o, arguments)
        if refused is None and merged.pick_by_arg.infer and o.inner == merged.inner:
            infer_kinds = [k for k in o.inner if k != 'none']        # 종류를 안 말했다 — 대상에서 알아낸다
        if refused is not None:
            return 'refuse', refused
        missing = _missing_required(o, arguments)
        if missing:
            return 'refuse', _error(
                "%s.%s needs %s — nothing was run. help(target='%s.%s') lists the "
                "arguments." % (tool, o.op, ", ".join(missing), tool, o.op),
                reason_code='missing_argument')

    # 공통 어휘 규칙(§3): 대상을 받는데 검색어 인자가 없는 operation 에 이름이
    # `query` 로 오면 그것이 대상이다 — 모델은 "찾는다" 고 생각하면 query 에 넣는다
    # (벤치 2026-10-14: find.plots 에 query='콩4구' → 거절 → 43건 목록으로 우회).
    if ('target' not in arguments and 'query' in arguments and 'query' not in o.args
            and any(k != 'none' for k in o.inner)):
        arguments['target'] = arguments.pop('query')
    # 장소로 거르는 목록(`place_filter`)이 이름 조각 `query` 도 받을 때 — query 가 장소 하나로 풀리면 그것이 대상이다
    # (실사용 26-11-07~09: find.functions 에 query='3포장'·'육묘장3'). 장소로 안 풀리면 이름 조각으로 둔다(query='VPD').
    if ('target' not in arguments and o.place_filter and 'query' in o.args
            and isinstance(arguments.get('query'), str) and arguments['query'].strip()):
        st, _got = targets.resolve(arguments['query'], only=set(PLACE_KINDS_ALL))
        if st == 'ok':
            arguments['target'] = arguments.pop('query')
    if o.period_field and 'period' in arguments:
        from aot.tools.domain import vocab
        rng = vocab.period(arguments.pop('period'), today=today_at(FARM))
        if rng is None:
            return 'refuse', _error("period not understood — use today, tomorrow, "
                                    "this_week, YYYY-MM-DD or FROM/TO.",
                                    reason_code='bad_period')
        # 기간은 안쪽 도구가 SQL limit 로 자른 **뒤에** 거른다 — 최근 만든 20건만 읽고 그 안에서
        # 날짜를 고르면 내일 일정이 있어도 0건이 된다(2026-11-03). 기간을 줬을 땐 넉넉히 읽고
        # (`_PERIOD_SCAN`), 거른 뒤 사용자의 limit 로 자른다(`_filter_period`).
        if 'include_past' in o.extra_args and rng[0] < today_at(FARM):
            arguments['include_past'] = True
        if 'limit' in o.args:
            arguments['limit'] = _PERIOD_SCAN
    # 안쪽 도구의 대상 칸 이름(`dashboard`·`tab`·`item`·`device_id` …)으로 대상을 넘겨도
    # 받는다 — 그 칸이 받는 종류로만 좁혀서. 안쪽 도구의 안내문은 그 이름을 쓰므로("use
    # dashboard=<name>"), 안 받으면 안내와 입력이 서로 모순된다(2026-10-14 웹 시험).
    only = None
    slots = _target_slots(o)
    # 화면 대상의 종류를 `kind` 로 말하면(kind='widget') 그 종류로 좁힌다 — 안쪽 `kind`
    # 는 지도 대상(대지·구역·장치…)의 종류라 위젯·대시보드·탭을 넘기면 거절된다.
    screen_kind = arguments.get('kind')
    if screen_kind in _SCREEN_KINDS and any(screen_kind in k for k in slots.values()):
        only = {arguments.pop('kind')}
    # 인자 값이 받는 대상 종류를 정한다(명부 `kinds_by_arg`) — 화면 조작의 action 마다.
    passthru = {}
    narrow = _narrowed_kinds(o, arguments)
    if narrow is not None:
        said = ", ".join("%s=%s" % (a, arguments[a]) for a in o.kinds_by_arg
                         if a in arguments)
        if not narrow:
            if 'target' in arguments:
                return 'refuse', _error(
                    "%s.%s with %s takes no target — nothing was run. %s" % (
                        tool, o.op, said, _kinds_by_arg_hint(o)),
                    reason_code='target_not_taken')
            # 대상 칸 이름(`tab` …)은 이 값에서 틀이 푸는 대상이 아니라 안쪽이 읽는 글자다.
            passthru = {ta: arguments.pop(ta) for ta in slots if ta in arguments}
            slots = {}
        else:
            if (tool, o.op) == ('screen', 'act') and arguments.get('action') == 'map_control' \
                    and isinstance(arguments.get('target'), str):
                # 지도 조작은 화면에 열린 지도를 만진다 — 시간 옮기기에 장소 이름('김제', '3포장')이 딸려 오면 거절하지 않고 뗀다
                # (2026-10-27 기록: 거절 → 다시 부르기). 지도 위젯을 가리키는 이름이면 그대로 둔다.
                st, _w = targets.resolve(arguments['target'], accepts={'widget'}, only={'widget'})
                if st != 'ok':
                    arguments.pop('target')
            slots = {ta: ks & narrow for ta, ks in slots.items() if ks & narrow}
            only = set(narrow) if only is None else (only & narrow)
            if not only:
                return 'refuse', _error(
                    "%s.%s with %s does not take that kind — nothing was run. %s" % (
                        tool, o.op, said, _kinds_by_arg_hint(o)),
                    reason_code='target_kind_not_accepted')
    given = [ta for ta in slots if ta in arguments]
    if given:
        if 'target' in arguments or len(given) > 1:
            return 'refuse', _error(
                "Give the target once — as target or as %s, not both." % " or ".join(given),
                reason_code='target_given_twice')
        arguments['target'] = arguments.pop(given[0])
        only = slots[given[0]] if only is None else (only & slots[given[0]])
    raw = targets.listify(arguments.pop('target', None))
    resolved = []
    refs = raw if isinstance(raw, (list, tuple)) else ([raw] if raw not in (None, '') else [])
    several = o.expand_write or o.fan_write
    if writing and len(refs) > 1 and not several:
        return 'refuse', _error(
            "%s.%s acts on ONE target per call (%d given). Nothing was run — call it "
            "once per target, after the user confirms each." % (tool, o.op, len(refs)),
            reason_code='single_target_only')
    if writing and len(refs) > 1 and o.fan_write and arguments.get('_confirmation_id'):
        # 여럿을 한 번에 건 요청은 `control.confirm`(confirmation_ids)이 승인과 실행을 한 번에 한다 —
        # 번호 하나로 다시 부르는 길은 대상 하나짜리다.
        return 'refuse', _error(
            "%s.%s with several targets is approved through control.confirm "
            "(confirmation_ids) — nothing was run." % (tool, o.op),
            reason_code='single_target_only')
    limit = o.max_targets if (writing and several) else (o.max_targets if refs else 1)
    if len(refs) > max(limit, 1):
        return 'refuse', _error("At most %d targets per call (%d given)."
                                % (limit, len(refs)), reason_code='too_many_targets')
    accepts = {k for k in o.inner if k != 'none'}
    why = None
    for ref in refs:
        state, got = targets.resolve(ref, accepts=accepts, only=only)
        if state == 'ambiguous':
            # 인자에 종류가 적혀 있으면 그것으로 좁힌다(page='dashboard' 는 대시보드다 —
            # 입력 페이지의 같은 이름 탭이 아니다).
            said = {v for v in arguments.values() if isinstance(v, str) and v in accepts}
            fit = [c for c in got if c.get('kind') in said]
            if len(fit) == 1:
                state, got = 'ok', fit[0]
            elif fit:
                got = fit
        if state == 'ambiguous':
            # 이 operation 이 바로 받는 종류가 후보에 있으면 그것만 본다. 쓰기는 펼치지 않으니
            # 못 받는 종류는 애초에 후보가 아니고(지도 '영양' 과 대시보드 '영양' — 화면
            # 이동은 대시보드만 받는다), 읽기도 바로 받는 것이 있으면 펼쳐야만 닿는 것(장치)
            # 을 내밀지 않는다(2026-10-14: find.plots '장미' 에 밸브 8개). 남는 것이 하나면
            # 그것, 아니면 그것들만 되묻는다.
            fit = [c for c in got if c.get('kind') in accepts]
            if len(fit) == 1:
                state, got = 'ok', fit[0]
            elif fit:
                got = fit
            elif not writing:
                # 읽기: 후보가 전부 같은 장소 하나 안의 것이면 그 장소를 읽는다(작은 것 →
                # 감싸는 장소, §2-3). '장미' 가 장미원의 밸브 8개로 풀렸을 때(2026-10-14).
                place = _one_container(got, accepts)
                if place is not None:
                    why = "all %d matches for '%s' are inside %s %s" % (
                        len(got), ref, place['kind'], place['name'])
                    state, got = 'ok', place
        if state == 'ambiguous' and only and only <= _NAV_KINDS:
            # 화면 이동('영양' = 대시보드 '영양' 이자 입력 페이지의 탭 '영양')은 되묻지 않고 대시보드로 간다(사용자 결정
            # 2026-10-26). 후보가 이동이 받는 두 종류(대시보드·탭)뿐일 때만이다 — 같은 이름의 대지·시설·장치는 이 후보에
            # 없고(`only`), 그쪽을 가리키는 호출은 이 길을 지나지 않는다. 탭 후보는 `why` 로 응답에 남긴다.
            boards = [c for c in got if c.get('kind') == 'dashboard']
            rest = [c for c in got if c.get('kind') != 'dashboard']
            if len(boards) == 1 and rest and all(c.get('kind') == 'tab' for c in rest):
                state, got = 'ok', boards[0]
                why = "'%s' is a dashboard and also a tab (%s) — went to the dashboard" % (
                    ref, ", ".join(c.get('path') or c.get('name') or '?' for c in rest[:3]))
        if state == 'ambiguous' and only is None and (tool, o.op) == ('screen', 'act') \
                and arguments.get('action') in (None, 'navigate') \
                and {c.get('kind') for c in got} <= _NAV_KINDS:
            # action 을 안 말한 화면 이동도 같은 규칙이다 — 위 이동 규칙은 action=navigate 로 좁혀진 호출만 지났다
            # ('김제' = 대시보드 + 입력·출력·함수 탭 4개로 되물었다, 2026-11-07 실측 #6). 지도·대지가 같은 이름이면
            # 후보에 그것이 들어 있어 이 길이 아니다(되묻는다).
            boards = [c for c in got if c.get('kind') == 'dashboard']
            rest = [c for c in got if c.get('kind') != 'dashboard']
            if len(boards) == 1 and rest:
                state, got = 'ok', boards[0]
                why = "'%s' is a dashboard and also a tab (%s) — went to the dashboard" % (
                    ref, ", ".join(c.get('path') or c.get('name') or '?' for c in rest[:3]))
        if state == 'ambiguous' and _context_pickable(tool, o):
            pick = targets.context_pick(got, user, session)
            if pick is not None:
                chosen, by = pick
                rest = [c for c in got if c.get('id') != chosen.get('id')]
                state, got = 'ok', chosen
                notes.setdefault('picks', []).append({
                    "asked": str(ref), "as": _candidates([chosen])[0], "by": by,
                    "others": _candidates(rest)[:4]})
                notes['picked_ids'] = notes.get('picked_ids', set()) | {chosen.get('id')}
        if state == 'ambiguous':
            got = targets.rank(got, user)
            return 'refuse', _error(
                "'%s' names %d different things (%s) — nothing was picked. Ask which "
                "one the user means (name it by path, never show ids), then pass that candidate's id as target.%s" % (
                    ref, len(got), _kinds_said(got), _ambiguous_note(got)),
                status="needs_disambiguation", reason_code='ambiguous_target',
                candidates=_candidates(got))
        if state == 'none':
            # id 로만 가리키는 종류(메모·공지·일정·승인 번호 …)를 하나만 받으면 그 id 다.
            id_kinds = [k for k in ID_ONLY_KINDS if k in accepts and (only is None or k in only)]
            if len(id_kinds) == 1 and _looks_like_id(ref):
                state, got = 'ok', {'kind': id_kinds[0], 'id': str(ref).strip(),
                                    'name': str(ref).strip(),
                                    'path': '%s %s' % (id_kinds[0], str(ref).strip())}
        if state == 'none':
            extra = _wrong_action_next(o, tool, arguments, ref, accepts, user) \
                if narrow else {}
            msg = got.get('error') or "Unknown target %r." % ref
            if extra:
                msg += " " + extra['next']['why']
            if got.get('similar'):
                extra['similar'] = _candidates(got['similar'])
            elif 'next' not in extra and tool in READ_TOOLS:
                # 이름을 못 찾았을 때 다음 걸음 — 같은 말을 되풀이해 부르지 않게(2026-11-03 점검).
                extra['next'] = {"call": "find(op='tree') lists the places; find(op='devices', query=<word>) the devices"}
            extra.setdefault('reason_code', 'unknown_target')
            if infer_kinds and _looks_like_id(ref):
                # 종류를 안 말한 id 는 어느 종류인지 모른다 — 말하게 한다(지우기·고치기의 `kind`).
                extra.setdefault('next', {"call": "say what the id is: kind=%s" % "|".join(infer_kinds)})
                msg += " If it is an id, say what kind it is (kind=...)."
            if 'next' not in extra and not got.get('similar'):
                # 쓰기·화면 조작도 같다 — 46/76건이 screen.act 였고 오류 뒤 모델은 탐색 도구로 돌아갔다(2026-11-07 실측 #2).
                # 받는 종류에 맞는 찾는 길 한 줄. 비슷한 이름을 되묻는 안내가 있으면 그쪽이 먼저다.
                extra['next'] = {"call": _where_to_look(
                    sorted(narrow) if narrow else [k for k in o.inner if k != 'none'])}
            return 'refuse', _error(msg, **extra)
        resolved.append(got)
        if got.get('id') not in notes.get('picked_ids', ()):
            notes.setdefault('seen', []).append(got)

    if not resolved:
        if 'none' not in o.inner:
            return 'refuse', _error(
                "%s.%s needs a target: one of %s." % (
                    tool, o.op, ", ".join(k for k in o.inner if k != 'none')),
                reason_code='target_required')
        kind = 'none'
    else:
        kinds = {t['kind'] for t in resolved}
        if len(kinds) > 1:
            return 'refuse', _error("Targets of different kinds in one call: %s."
                                    % ", ".join(sorted(kinds)),
                                    reason_code='mixed_target_kinds')
        kind = kinds.pop()
        if kind not in o.inner:
            accepts = [k for k in o.inner if k != 'none']
            body = {"reason_code": 'target_kind_not_accepted',
                    "target": _candidates(resolved)[0] if len(resolved) == 1 else None}
            if writing:
                if not accepts:
                    return 'refuse', _error(
                        "%s.%s takes no target (got a %s). Nothing was run — call it "
                        "without target." % (tool, o.op, kind), **body)
                # 쓰기는 펼치지도 올리지도 않는다(§2-3) — 고르게 한다.
                kids = [c for t in resolved for c in _children_of(t)
                        if c['kind'] in o.inner]
                if kids:
                    body['candidates'] = _candidates(kids)
                pick = ("pick the ones you mean and pass them together as a list in target"
                        if o.fan_write else "pick one")
                return 'refuse', _error(
                    "%s.%s takes %s, not a %s. Nothing was run — writes never fan out "
                    "to what a %s contains; %s%s." % (
                        tool, o.op, " or ".join(accepts), kind, kind, pick,
                        " from 'candidates'" if kids else ""), **body)
            # 읽기는 그릇을 펼친다(§2-3) — 안의 대상 중 이 operation 이 받는 종류로.
            meta0 = {"target": _candidates(resolved)[0] if len(resolved) == 1 else None}
            # (1) 작은 것 → 감싸는 장소로 올린다(시설 → 구역·대지, 구획 → 구역·시설, 장치 → 장소).
            if len(resolved) == 1 and kind in ('facility', 'plot') + _DEVICE_KINDS:
                up = [a for a in _ancestors(resolved[0]) if a['kind'] in o.inner]
                if up:
                    a = up[0]
                    ta = o.target_arg.get(a['kind'])
                    args = _inner_args(o, dict(arguments), o.inner[a['kind']], ta, [a], False)
                    if isinstance(args, list):
                        return 'refuse', args
                    meta0["read_for"] = "%s %s (it contains %s)" % (
                        a['kind'], a['name'], resolved[0]['name'])
                    return 'fanout', o.inner[a['kind']], [(a, args)], meta0
            # 장소를 받는 operation 은 그릇을 안의 장소로 펼친다 — 장치·농장 전체로 빠지지
            # 않는다(2026-10-14: '영양' 개요가 농장 전체 개요로, 예보가 장치마다 갔다).
            place_ok = any(k in o.inner for k in ('site', 'zone', 'facility'))
            if place_ok:
                got = _expand_places(o, tool, arguments, resolved)
                if got is not None:
                    return got
            # (2) 장소 → 그 안의 장치(장치만 받는 operation).
            dev_kinds = [k for k in _DEVICE_KINDS if k in o.inner]
            if dev_kinds and kind in PLACE_KINDS_ALL:
                ids = []
                for t in resolved:
                    ids.extend(i for i in _device_ids_in(t) if i not in ids)
                devs = _device_targets(ids, dev_kinds)
                if not devs:
                    return 'refuse', _error("No %s inside %s." % (
                        " or ".join(dev_kinds), ", ".join(t['name'] for t in resolved)),
                        **dict(body, reason_code='nothing_inside'))
                dk = devs[0]['kind']
                same = [d for d in devs if d['kind'] == dk]
                ta = o.target_arg.get(dk)
                if _arg_is_list(o.inner[dk], ta):
                    # 안쪽 상한(10)씩 나눠 부른다 — 한 번만 부르면 19개 중 10개에서 멈춘다
                    # (2026-10-14 웹 시험: 김제 밸브 상태 19개 중 5개).
                    shown = same[:_LIST_TOTAL]
                    calls = []
                    for i in range(0, len(shown), _LIST_CHUNK):
                        part = shown[i:i + _LIST_CHUNK]
                        args = _inner_args(o, dict(arguments), o.inner[dk], ta, part, False)
                        if isinstance(args, list):
                            return 'refuse', args
                        group = {'kind': dk, 'name': ", ".join(d['name'] for d in part),
                                 'path': resolved[0].get('path')}
                        calls.append((group, args))
                    meta0["expanded_to"] = "%d %s(s) inside, %d shown" % (
                        len(same), dk, len(shown))
                    if len(same) > len(shown):
                        meta0["not_shown"] = [d['name'] for d in same[len(shown):]][:20]
                    return 'fanout', o.inner[dk], calls, meta0
                shown = same[:o.max_targets]
                calls = []
                for d in shown:
                    args = _inner_args(o, dict(arguments), o.inner[dk], ta, [d], False)
                    if isinstance(args, list):
                        return 'refuse', args
                    calls.append((d, args))
                meta0["expanded_to"] = "%d %s(s) inside, %d shown" % (len(same), dk, len(shown))
                if len(same) > len(shown):
                    meta0["not_shown"] = [d['name'] for d in same[len(shown):]][:20]
                return 'fanout', o.inner[dk], calls, meta0
            # (2b) 장소 → 그 안의 구획(구획만 받는 operation).
            if 'plot' in o.inner and kind in ('map', 'site', 'zone', 'facility'):
                plots = []
                for t in resolved:
                    plots.extend(_plots_in(t))
                if plots:
                    shown = plots[:o.max_targets]
                    ta = o.target_arg.get('plot')
                    calls = []
                    for pl in shown:
                        args = _inner_args(o, dict(arguments), o.inner['plot'], ta, [pl], False)
                        if isinstance(args, list):
                            return 'refuse', args
                        calls.append((pl, args))
                    meta0["expanded_to"] = "%d plot(s) inside, %d shown" % (len(plots), len(shown))
                    if len(plots) > len(shown):
                        meta0["not_shown"] = [p['name'] for p in plots[len(shown):]][:20]
                    return 'fanout', o.inner['plot'], calls, meta0
            # (3) 대상 없이 도는 목록 operation 에 장소가 오면 — 결과를 그 장소의 장치로 거른다.
            if 'none' in o.inner and kind in PLACE_KINDS_ALL and o.place_filter:
                # 행이 장소에 묶인 칸(예: 함수의 facility_id)으로 거른다. 쪽 나누기는 거른 뒤에 해야 하므로 안쪽 limit·offset 은 떼어
                # 두었다가 `_filter_place_rows` 가 적용한다.
                keep = _place_keys(resolved)
                page = {k: arguments[k] for k in ('limit', 'offset') if k in arguments}
                args = _inner_args(o, {k: v for k, v in arguments.items() if k not in page},
                                   o.inner['none'], None, [], False)
                if isinstance(args, list):
                    return 'refuse', args
                meta0["filtered_to"] = "functions tied to %s" % ", ".join(t['name'] for t in resolved)
                return 'filter', o.inner['none'], args, dict(
                    meta0, place_key=o.place_filter, place_ids=sorted(keep), page=page)
            if 'none' in o.inner and kind in PLACE_KINDS_ALL:
                ids = set()
                for t in resolved:
                    ids.update(_device_ids_in(t))
                args = _inner_args(o, dict(arguments), o.inner['none'], None, [], False)
                if isinstance(args, list):
                    return 'refuse', args
                meta0["filtered_to"] = "%d device(s) inside %s" % (
                    len(ids), ", ".join(t['name'] for t in resolved))
                return 'filter', o.inner['none'], args, dict(meta0, ids=sorted(ids))
            if not place_ok:
                got = _expand_places(o, tool, arguments, resolved)
                if got is not None:
                    return got
            return 'refuse', _error("%s.%s takes %s, not a %s." % (
                tool, o.op, " or ".join(accepts) or "no target", kind),
                **dict({"next": {"call": _kind_lookup(accepts)}} if accepts else {}, **body))

    inner = o.inner[kind]
    ta = o.target_arg.get(kind) if resolved else None
    if resolved and not ta:
        return 'refuse', _error("%s.%s has no target argument for %s."
                                % (tool, o.op, kind), reason_code='registry_gap')
    if writing and o.fan_write and len(resolved) > 1:
        seen, uniq = set(), []
        for t in resolved:
            if t['id'] not in seen:
                seen.add(t['id'])
                uniq.append(t)
        if len(uniq) > 1:
            calls = []
            for t in uniq:
                a = _inner_args(o, dict(arguments), inner, ta, [t], True)
                if isinstance(a, list):
                    return 'refuse', a
                a.update(passthru)
                calls.append((t, a))
            return 'fanwrite', inner, calls, {"targets": _candidates(uniq)}
        resolved = uniq
    if not writing and len(resolved) > 1 and not _arg_is_list(inner, ta):
        # 읽기 목록 — 안쪽 도구가 대상 하나만 받으면 대상마다 따로 부른다. 그대로 넘기면 첫 건만 읽히고 나머지는
        # 아무 표시 없이 빠졌다(2026-11-03 실측: overview.place 에 두 곳 → 첫 곳만).
        seen, uniq = set(), []
        for t in resolved:
            if t['id'] not in seen:
                seen.add(t['id'])
                uniq.append(t)
        if len(uniq) > 1:
            calls = []
            for t in uniq:
                a = _inner_args(o, dict(arguments), inner, ta, [t], False)
                if isinstance(a, list):
                    return 'refuse', a
                a.update(passthru)
                calls.append((t, a))
            return 'fanout', inner, calls, {"per_target": True}
        resolved = uniq
    inner_args = _inner_args(o, arguments, inner, ta, resolved, writing)
    if isinstance(inner_args, list):
        return 'refuse', inner_args
    inner_args.update(passthru)
    if why:
        inner_args.setdefault(META_KEY, {})['why'] = why
    if len(resolved) == 1:
        # 응답에 어느 대상으로 읽었는지 싣는다 — 안쪽 응답의 경로에는 지도 이름이 없을 수
        # 있다(2026-10-14 웹 시험: '육묘장' 이 영양의 것인지 답에 없었다).
        inner_args.setdefault(META_KEY, {})['target'] = _candidates(resolved)[0]
    return 'call', inner, inner_args


def _expand_places(o, tool, arguments, resolved):
    """그릇 → 그 안의 장소로 펼친 읽기(verdict), 펼칠 것이 없으면 None.

    펼치는 깊이(§2-3): 안쪽 인자가 목록이면 가장 잘게(구역) 모아 상한(10)씩 나눠,
    하나씩이면 굵게(대지) 펼쳐 따로 부른다 — 따로 부를 때만 호출이 는다.
    """
    kids = [c for t in resolved for c in _descendants(t) if c['kind'] in o.inner]
    if kids:
        def _is_list(k):
            return _arg_is_list(o.inner[k], o.target_arg.get(k))
        present = {c['kind'] for c in kids}
        batch = [k for k in ('zone', 'facility', 'site') if k in present and _is_list(k)]
        order = batch or [k for k in ('site', 'zone', 'facility', 'plot', 'output',
                                      'input') if k in present]
        kind = order[0]
        kids = [c for c in kids if c['kind'] == kind]
        ta = o.target_arg.get(kind)
        if not ta:
            return 'refuse', _error("%s.%s has no target argument for %s."
                                    % (tool, o.op, kind), reason_code='registry_gap')
        meta = {"target": _candidates(resolved)[0] if len(resolved) == 1 else None}
        if batch:
            shown = kids[:_LIST_TOTAL]
            calls = []
            for i in range(0, len(shown), _LIST_CHUNK):
                part = shown[i:i + _LIST_CHUNK]
                a = _inner_args(o, dict(arguments), o.inner[kind], ta, part, False)
                if isinstance(a, list):
                    return 'refuse', a
                group = {'kind': kind, 'name': ", ".join(c['name'] for c in part),
                         'path': resolved[0].get('path')}
                calls.append((group, a))
            meta["expanded_to"] = "%d %s(s) inside, %d shown" % (len(kids), kind, len(shown))
            if len(kids) > len(shown):
                meta["not_shown"] = [c['name'] for c in kids[len(shown):]][:20]
            return 'fanout', o.inner[kind], calls, meta
        shown = kids[:o.max_targets]
        calls = []
        for c in shown:
            a = _inner_args(o, dict(arguments), o.inner[kind], ta, [c], False)
            if isinstance(a, list):          # 거절 본문
                return 'refuse', a
            calls.append((c, a))
        meta["expanded_to"] = "%d %s(s) inside, %d shown" % (len(kids), kind,
                                                            len(shown))
        if len(kids) > len(shown):
            meta["not_shown"] = [c['name'] for c in kids[len(shown):]][:20]
        return 'fanout', o.inner[kind], calls, meta
    return None


def _one_container(cands, accepts):
    """후보(장치·구획·시설)가 모두 이 operation 이 받는 같은 장소 하나 안에 있으면 그 장소."""
    small = ('facility', 'plot') + _DEVICE_KINDS
    found = {}
    for c in cands:
        if c.get('kind') not in small or not c.get('id'):
            return None
        up = next((a for a in _ancestors(c) if a['kind'] in accepts), None)
        if up is None:
            return None
        found[up['id']] = up
        if len(found) > 1:
            return None
    return next(iter(found.values()), None)


def _looks_like_id(ref):
    """공백 없는 6자 이상의 글자 — uuid·일정 번호. 이름(띄어쓰기 있는 말)은 아니다."""
    text = str(ref or '').strip()
    return isinstance(ref, str) and len(text) >= 6 and not any(c.isspace() for c in text)


def _narrowed_kinds(o, arguments):
    """호출의 인자 값이 정하는 대상 종류(명부 `kinds_by_arg`). 정하지 않으면 None."""
    out = None
    for arg, table in o.kinds_by_arg.items():
        value = arguments.get(arg)
        if isinstance(value, str) and value in table:
            kinds = set(table[value])
            out = kinds if out is None else (out & kinds)
    return out


def _wrong_action_next(o, tool, arguments, ref, accepts, user=None):
    """`kinds_by_arg` 가 좁힌 호출이 '그 종류가 아니다' 로 거절될 때, 그 대상을 받는 다른
    값이 있으면 다시 보낼 호출을 `next` 로 알려 준다(고쳐서 실행하지는 않는다). 예:
    action=navigate + 구획 → action=open_map_item (2026-10-14 호출 기록 '김제 > 3포장').

    그 이름이 다른 종류 여럿이면(위젯 '육묘장' 과 시설 '육묘장', 2026-10-29 재시험) 고르지
    않고 후보마다 다시 보낼 호출을 달아 되묻게 한다 — 정렬은 다른 되묻기와 같다(`rank`)."""
    state, got = targets.resolve(ref, accepts=accepts)
    if state == 'ok' and isinstance(got, dict):
        cands = [got]
    elif state == 'ambiguous':
        cands = targets.rank(list(got), user)
    else:
        return {}
    routes = [(c, _route_for(o, tool, arguments, c)) for c in cands]
    routes = [(c, r) for c, r in routes if r]
    if not routes:
        return {}
    shot = ""
    if 'screen' in (o.extra_args or {}):
        # 틀은 어느 화면인지 모른다 — 값을 넣지 못하니 찾는 법만 말한다.
        # 안쪽은 열린 화면이 둘 이상이면 고르지 않고 failed 로 끝난다.
        shot = (" If more than one screen is open, add screen='<id>' "
                "(the screen value from screen_view op=current).")
    if state == 'ok':
        why, head, fixed = routes[0][1]
        return {"next": {"why": why + shot, "resend": "%s, target=%r)" % (
            head, fixed or str(ref))}}
    out = _candidates([c for c, _r in routes])
    for d, (_c, (_why, head, fixed)) in zip(out, routes):
        d['resend'] = "%s, target=%r)" % (head, fixed or str(d['id']))
    return {"status": "needs_disambiguation", "reason_code": 'ambiguous_target',
            "candidates": out,
            "next": {"why": "'%s' names %d things that open another way — ask which one the "
                            "user means, then send its resend.%s%s" % (
                                ref, len(out), _ambiguous_note([c for c, _r in routes]),
                                shot)}}


def _route_for(o, tool, arguments, cand):
    """후보 하나를 받는 다른 인자 값 → (이유, 호출 앞부분, 정해진 대상 또는 None). 없으면 None.
    위젯은 대시보드에 있어 화면 이동은 그 대시보드로 간다(강조는 그 대시보드에서만 된다).
    사용자가 이미 그 대시보드를 보고 있으면(`on_screen`) 강조다."""
    kind = cand.get('kind')
    for arg, table in o.kinds_by_arg.items():
        said = arguments.get(arg)
        if said not in table:
            continue
        if kind == 'widget' and 'dashboard' in table[said] and not cand.get('on_screen'):
            board = _board_of_widget(cand.get('id'))
            if board:
                return ("A widget is on dashboard %s — go there." % board[1],
                        "%s(op='%s', %s='%s', page='dashboard'" % (tool, o.op, arg, said),
                        board[0])
        for value, kinds in table.items():
            if value != said and kind in kinds:
                return ("A %s goes with %s=%s, not %s=%s." % (kind, arg, value, arg, said),
                        "%s(op='%s', %s='%s'" % (tool, o.op, arg, value), None)
    return None


def _board_of_widget(widget_id):
    """위젯이 놓인 대시보드 → (id, 이름). 못 찾으면 None."""
    from aot.databases.models import Dashboard, Widget
    w = Widget.query.filter(Widget.unique_id == widget_id).first() if widget_id else None
    d = Dashboard.query.filter(Dashboard.unique_id == w.tab_id).first() if w else None
    return (d.unique_id, d.name) if d is not None else None


def _kinds_by_arg_hint(o):
    """어느 값이 무엇을 대상으로 받는가 — 거절 본문에 싣는 한 줄."""
    parts = []
    for arg, table in o.kinds_by_arg.items():
        takes = ["%s=%s (%s)" % (arg, v, ", ".join(k)) for v, k in table.items() if k]
        none = [v for v, k in table.items() if not k]
        if takes:
            parts.append("A target goes with " + "; ".join(takes) + ".")
        if none:
            parts.append("%s takes no target%s." % (
                "/".join(none), " — modal_tab names a tab of the open map window "
                "in `tab` (screen_view: dialog_tabs, or underlying_dialog.tabs under a notes drawer)" if 'modal_tab' in none else ""))
    return " ".join(parts)


def _target_slots(o):
    """안쪽 대상 칸 이름 → 그 칸이 받는 종류(공통 어휘·고유 인자 이름과 겹치는 것은 뺀다)."""
    taken = set(o.args) | set(o.args.values()) | set(o.extra_args) | {'target', 'op'}
    slots = {}
    for kind, ta in o.target_arg.items():
        if ta and ta not in taken:
            slots.setdefault(ta, set()).add(kind)
    return slots


#: 호출자가 실어 보내는 게이트 메타 인자(mcp_safety_gate.META_KEYS 중 `_agent_id` 를 뺀 것 —
#: 그것은 서버가 정한다).
_CALLER_META = ('_confirmation_id', '_reason', '_title')


def _inner_prop_type(inner, arg):
    from aot.tools.domain.contract import catalog
    prop = ((catalog().get(inner) or {}).get('inputSchema') or {}).get('properties', {}).get(arg) or {}
    return prop.get('type')


def _convert_word(o, word, inner, arg, value):
    """공통 어휘의 값을 안쪽 인자의 모양으로 — `duration` 은 안쪽 단위(초·분)로, `state` 는 안쪽이 불리언이면 불리언으로.
    못 읽으면 거절 본문(list)."""
    from aot.tools.domain import vocab
    if word == 'duration':
        try:
            return vocab.duration_for(arg, value)
        except ValueError:
            return _error("duration not understood: use seconds as a number, or 90s, 15m, 2h - nothing was run.",
                          reason_code='bad_duration')
    if _inner_prop_type(inner, arg) != 'boolean':
        return value
    got = vocab.onoff(value)
    if got is None:
        return _error("state must be on or off - nothing was run.", reason_code='bad_state')
    return got


def _inner_args(o, arguments, inner, ta, resolved, writing):
    """공통 어휘·고유 인자·해석된 대상 → 안쪽 인자. 모르는 인자는 거절 본문(list)."""
    arguments = dict(arguments)
    inner_args = {}
    pair = arguments.pop('_pair', None)
    listing = pair and inner == 'list_plot_journals'
    if pair and o.period_pair and not listing:
        inner_args.update({k: v for k, v in zip(o.period_pair, pair) if v})
    if 'period' in arguments and o.period_form:
        got = _period_args(o, inner, arguments.pop('period'))
        if isinstance(got, list):
            return got
        inner_args.update(got)
    for word, arg in o.args.items():
        if o.slim and word in slim.DOMAIN_WORDS:
            if word in arguments:           # 도메인 층이 처리 — 안쪽 도구로 넘기지 않는다
                inner_args.setdefault(META_KEY, {}).setdefault('slim', {})[word] = arguments.pop(word)
            continue
        if word in arguments:
            value = arguments.pop(word)
            if word == 'measurement':
                from aot.tools.domain import vocab
                value = vocab.measurement(value)
            elif word in ('duration', 'state'):
                value = _convert_word(o, word, inner, arg, value)
                if isinstance(value, list):
                    return value
            inner_args[arg] = value
    if listing:
        # 일지 목록은 date_from/date_to 를 받지 않는다(그 둘은 일지 **한 건**을 접어 여는 인자) — 안쪽에 넘기면 조용히 무시돼
        # 기간 밖의 일지까지 나온다(2026-11-03 라운드 3). 넉넉히 읽고(안쪽 상한 200) 도메인에서 기간이 겹치는 일지만 남긴다.
        asked = inner_args.get('limit')
        inner_args['limit'] = _JOURNAL_SCAN
        inner_args.setdefault(META_KEY, {})['journal_range'] = {'range': pair, 'limit': asked}
    for arg in o.extra_args:
        if arg in arguments:
            value = arguments.pop(arg)
            if o.tool == 'weather' and arg == 'focus':
                # 틀이 쓰는 인자 — 슬라이더가 갈 시각을 응답에서 고른다(`screen_follow._focus_target`).
                # 안쪽 도구에 넘기면 "받지 않는 인자를 무시했다" 경고가 붙어 focus 가 먹히지 않은 것처럼 읽힌다.
                continue
            inner_args[arg] = value
    _decode_text_values(inner, inner_args)
    if resolved:
        from aot.tools.domain.contract import catalog
        prop = ((catalog().get(inner) or {}).get('inputSchema') or {}) \
            .get('properties', {}).get(ta) or {}
        if ta in NAME_PARAMS:
            # 이름만 받는 안쪽 인자 — id 를 넣으면 안쪽 이름 해석이 엉뚱한 곳으로 푼다
            # (2026-10-14 벤치 f32: 구역 3-1 의 uuid 안의 '1-3' 이 구역 1-3 으로 풀렸다).
            # 같은 대상으로 되돌아오는 이름만 넘긴다. 없으면 실행하지 않는다.
            names = []
            for t in resolved:
                n = _verified_name(t)
                if n is None:
                    return _error(
                        "%s.%s cannot pass %s '%s' to its inner tool by a name that "
                        "means only it — nothing was run." % (
                            o.tool, o.op, t['kind'], t['name']),
                        reason_code='no_unique_name', target=_candidates([t])[0])
                names.append(n)
            vals = names
        else:
            vals = [t['id'] for t in resolved]
        inner_args[ta] = vals if prop.get('type') == 'array' else vals[0]
        if writing:
            inner_args[SNAPSHOT_KEY] = (targets.snapshot(resolved[0]) if len(resolved) == 1
                                        else [targets.snapshot(t) for t in resolved])
    if o.defaults_by_kind:
        # 대상이 없는 작업은 'none' 칸을 쓴다(예: screen.card 는 action=post 를 스스로 정한다).
        kind = resolved[0]['kind'] if resolved else 'none'
        for arg, value in (o.defaults_by_kind.get(kind) or {}).items():
            inner_args.setdefault(arg, value)
    # 승인 흐름의 메타 인자는 안쪽 도구(게이트)가 읽는다 — 버리면 승인 뒤 다시 부른 호출이
    # 새 승인 대기를 만든다(2026-10-14 사용자 시험: 공지 작성이 승인 대기만 두 번 쌓였다).
    for k in _CALLER_META:
        if k in arguments:
            inner_args[k] = arguments[k]
    if o.tool == 'screen' and o.op == 'act' and inner_args.get('action') == 'post':
        return _error("screen.act does not post cards. Use op=card with title and message "
                      "— nothing was run.", reason_code='use_card')
    leftover = sorted(k for k in arguments if not str(k).startswith('_'))
    if leftover and not writing:
        # 쪽 나누기 어휘(limit·offset)는 모든 op 가 받는 줄 알고 붙는다(스키마가 op 합집합 한 벌 — 실측 거절 상위 1·7위).
        # 읽기에서는 거절 대신 무시하고 실행한 뒤 응답(`read_as.ignored`)에 알린다. 쓰기는 지금처럼 거절한다.
        paging = [k for k in leftover if k in _PAGING_WORDS]
        if paging:
            inner_args.setdefault(META_KEY, {})['ignored'] = paging
            leftover = [k for k in leftover if k not in _PAGING_WORDS]
    if leftover and (o.tool, o.op) == ('measure', 'soil_forecast'):
        # 이 예측은 기간 인자가 없다(트윈이 발행한 날 전체) — 거절만 하면 막다른 길이다(2026-11-03 라운드 3).
        return _error(
            "measure.soil_forecast does not take %s. It takes: op, target, plot_ids - and returns every day the twin "
            "published; pick the days you need from `days`." % ", ".join(leftover),
            reason_code='unknown_argument',
            next={"call": "measure.soil_forecast(target=<plot>) without %s; or measure.latest(target=<plot>, "
                          "measurement='soil moisture') for now, weather.forecast(target=<plot>, measurement='rain')"
                          % ", ".join(leftover)})
    if leftover:
        return _error(
            "%s.%s does not take %s. %sIt takes: %s." % (
                o.tool, o.op, ", ".join(leftover),
                _same_meaning(o, leftover) + _taken_elsewhere(o, leftover),
                # 대상을 받지 않는 operation 에 'target' 을 적으면 이름을 거기 넣으라는 말이 된다
                # (2026-10-28 점검: find.functions 가 target 을 받는다고 안내하고 거절했다).
                ", ".join(['op'] + (['target'] if (any(k != 'none' for k in o.inner) or o.place_filter) else [])
                          + sorted(set(o.args) | set(o.extra_args)))),
            reason_code='unknown_argument',
            next={"call": "help(target='%s.%s') lists what it takes" % (o.tool, o.op)})
    return inner_args


#: 읽기 op 가 모르면 무시하는 쪽 나누기 어휘 — 이 op 는 한 번에 전부 돌려주거나 다른 방식으로 자른다.
_PAGING_WORDS = frozenset({'limit', 'offset'})

#: 거절된 인자 → 뜻이 같은 말들(받는 인자 이름 기준). 그 op 가 받으면 "대신 X" 로 알려 준다.
_SAME_MEANING = {
    'duration_minutes': ('duration',), 'duration_seconds': ('duration',), 'duration_hours': ('duration',),
    'minutes': ('duration',), 'seconds': ('duration',), 'run_time': ('duration',),
    'period': ('period', 'date_from', 'window_start', 'at', 'duration'),
    'since': ('period', 'date_from', 'window_start'), 'range': ('period',), 'time_range': ('period',),
    'search': ('query',), 'keyword': ('query',), 'q': ('query',),
    'kind': ('subject_kind',),
    'active': ('state', 'only_active'), 'enabled': ('state',), 'active_only': ('only_active',),
    'count': ('limit',), 'max': ('limit',), 'top': ('limit',),
}


def _same_meaning(o, leftover):
    """받지 않는 인자와 뜻이 같은, 이 op 가 실제로 받는 인자 — "k: use X instead." (없으면 빈 글)."""
    takes = set(o.args) | set(o.extra_args)
    if any(x != 'none' for x in o.inner) or o.place_filter:
        takes.add('target')
    parts = []
    for k in leftover:
        homes = [w for w in _SAME_MEANING.get(k, ()) if w in takes and w != k]
        if not homes and k.startswith('duration'):
            homes = sorted(w for w in takes if w.startswith('duration'))
        if homes:
            parts.append("%s: use %s instead." % (k, " or ".join(homes[:2])))
    return " ".join(parts) + " " if parts else ""


def _taken_elsewhere(o, leftover):
    """받지 않는 인자를 받는 다른 operation — "use configure.activate" 안내(없거나 너무 많으면 빈 글).

    스키마의 인자 목록은 도구 하나에 있는 모든 operation 것을 합친 한 벌이라, 목록에 보인 인자를 모든 operation 이
    받는 줄 안다(2026-10-30: input_edit 에 active)."""
    parts = []
    for k in leftover:
        # 옛 이름이면 새 이름으로 찾는다 — 별칭은 그 이름을 받는 op 에서만 풀리므로 다른 op 에 넣으면 여기로 온다.
        al = renames.ARG_ALIASES.get(k)
        homes = [x.op for x in _ops() if x.tool == o.tool and x.op != o.op
                 and (k in x.extra_args or k in x.args or (al is not None and al.new in x.args))]
        if 0 < len(homes) <= 3:
            parts.append("%s: use %s%s." % (k, " or ".join("%s.%s" % (o.tool, h) for h in homes),
                                            " (as %s)" % al.new if al else ""))
    return " ".join(parts) + " " if parts else ""


def _decode_text_values(inner, inner_args):
    """안쪽 스키마가 객체·목록인 인자가 글자로 왔으면 푼다(제자리).

    도메인 스키마의 고유 인자에는 type 이 없어(§6 크기) 호스트가 객체를 JSON 글자로
    넘긴다 — 2026-10-28 claude.ai 점검: control.function_options 의 params 가 세 번
    'non-empty object' 로 거절됐다. 목록은 'plots, map' 같은 쉼표 글자도 받는다
    (tool_profile_set 의 modules 가 글자 하나씩 쪼개져 운영으로 내려갈 수 있었다).
    못 풀면 그대로 둔다 — 안쪽이 거절한다."""
    from aot.tools.domain.contract import catalog
    props = ((catalog().get(inner) or {}).get('inputSchema') or {}).get('properties') or {}
    for arg, value in list(inner_args.items()):
        want = (props.get(arg) or {}).get('type')
        if want not in ('object', 'array') or not isinstance(value, str):
            continue
        text = value.strip()
        if text[:1] in ('{', '['):
            try:
                got = json.loads(text)
            except ValueError:
                continue
            if isinstance(got, dict if want == 'object' else list):
                inner_args[arg] = got
        elif want == 'array' and text:
            inner_args[arg] = [p.strip() for p in text.split(',') if p.strip()]


def _pick_branch(o, arguments):
    """`Op.pick_by_arg` — 인자 값으로 가지 Op 를 고른다 → (가지 Op, None) | (None, 거절 본문).

    고른 인자는 가지가 안쪽에 안 넘기는 것이면(`consume`) 인자에서 뗀다. 값이 가지에 없으면 받는 값을 말한다."""
    from aot.tools.domain import vocab
    pk = o.pick_by_arg
    raw = arguments.get(pk.arg)
    if raw in (None, '', [], {}):
        key = ''
    elif pk.normalize == 'onoff':
        got = vocab.onoff(raw)
        key = None if got is None else ('on' if got else 'off')
    else:
        key = str(raw).strip().lower()
    if key in pk.synonyms:
        key = pk.synonyms[key]
    if key is not None and key not in pk.branches and '*' in pk.branches and key != '':
        key = '*'
    if key == '' and '' not in pk.branches and pk.infer:
        # 값을 안 말했다 — 합친 op 자신(모든 종류의 합집합)이 가지다: 대상에서 종류를 알아낸다.
        return replace(o, pick_by_arg=None), None
    branch = pk.branches.get(key) if key is not None else None
    if branch is None:
        allowed = sorted(k for k in pk.branches if k not in ('', '*'))
        return None, _error(
            "%s.%s: %s=%r is not one of %s — nothing was run. help(target='%s.%s') lists what each takes." % (
                o.tool, o.op, pk.arg, raw, ", ".join(allowed) or '(none)', o.tool, o.op),
            reason_code='bad_%s' % pk.arg)
    if pk.consume:
        arguments.pop(pk.arg, None)
    return branch, None


def _missing_required(o, arguments):
    """명부 `required` 중 비어 온 고유 인자(대상 제외) — help 가 필수로 알리는 것과 같다.

    처리기 인자는 기본값이 None 이라 실행층의 필수 검사를 지나, 인자 없는
    configure.input_create 가 승인 대기까지 올라갔다(2026-10-28 점검 — 승인 목록에
    params·reason 이 빈 요청이 남았다)."""
    return [r for r in o.required
            if r != 'target' and arguments.get(r) in (None, '', [], {})]


#: 일지 목록을 기간으로 거르기 전에 안쪽에서 읽는 수 — 안쪽 도구의 상한(200).
_JOURNAL_SCAN = 200


def _filter_journal_period(out, rng, limit):
    """일지 목록에서 기간이 `rng`(시작, 끝; 한쪽은 None 가능)와 **겹치는** 일지만 남긴 뒤 limit(없으면 안쪽 기본 50)로 자른다.
    기간이 없는 일지는 겹침을 알 수  없어 뺀다."""
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    rows = body.get('journals') if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return out
    start, end = rng

    def _hit(r):
        a, b = str(r.get('period_start') or '')[:10], str(r.get('period_end') or '')[:10]
        if not a or not b:
            return False
        return (end is None or a <= end) and (start is None or b >= start)

    kept = [r for r in rows if isinstance(r, dict) and _hit(r)]
    try:
        cap = max(1, int(limit)) if limit not in (None, '') else 50
    except (TypeError, ValueError):
        cap = 50
    total = len(kept)
    body['journals'] = kept[:cap]
    body['count'] = len(body['journals'])
    body['period'] = {"from": start, "to": end}
    if total > cap:
        body.update(truncated=True, total=total, note="Only the first %d journals overlapping this period are shown "
                                                      "(newest first); raise limit for more." % cap)
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def _pair_range(text):
    """`period`(날짜 범위) → ('YYYY-MM-DD' | None, 'YYYY-MM-DD' | None) 또는 거절 본문(list).
    'FROM/' 은 끝 없이, '/TO' 는 시작 없이 — 안쪽 두 칸 중 하나만 채운다."""
    from aot.tools.domain import vocab
    t = str(text or '').strip()
    if '/' in t:
        a, _, b = t.partition('/')
        if not a.strip() or not b.strip():
            half = vocab.period(a.strip() or b.strip(), today=today_at(FARM))
            if half is not None:
                return (half[0].isoformat(), None) if a.strip() else (None, half[1].isoformat())
    rng = vocab.period(t, today=today_at(FARM))
    if rng is None:
        return _error("period %r not understood — use today, yesterday, this_week, 7d, YYYY-MM-DD or "
                      "FROM/TO (days, both included)." % t, reason_code='bad_period')
    return rng[0].isoformat(), rng[1].isoformat()


def _period_args(o, inner, text):
    """공통 낱말 `period` → 안쪽 도구의 기간 인자(명부의 `period_form` 모양으로).

    거절 본문(list) 또는 안쪽 인자 dict. 쓴 기간은 META_KEY 로 응답에 실린다.
    """
    from aot.tools.domain import vocab
    from aot.tools.domain.contract import catalog, handler_arg_names
    props = set(((catalog().get(inner) or {}).get('inputSchema') or {}).get('properties') or {})
    # 스키마에 싣지 않는 처리기 인자도 기간을 받을 수 있다(새 인자 이름을 늘리지 않으려는 길 — 계약 검사도 같다).
    props |= handler_arg_names(inner)
    try:
        vals, used = vocab.period_to(o.period_form, text, today=today_at(FARM))
    except ValueError as exc:
        return _error("period %r: %s. Use now, today, yesterday, tomorrow, this_week, "
                      "24h, 7d, YYYY-MM-DD or FROM/TO." % (text, exc),
                      reason_code='bad_period')
    out = {}
    arg = o.args.get('period')
    if 'value' in vals and arg in props:
        out[arg] = vals['value']
    if 'hours' in vals and arg in props:
        out[arg] = vals['hours']
    if 'start' in vals and o.args.get('at') in props:
        out[o.args['at']] = vals['start']
    out[META_KEY] = {'period': {'asked': text, 'read': used}}
    return out


#: 기간 모양마다 실제로 읽는 범위 — 목록의 공통 설명(모든 모양)과 다른 점.
_PERIOD_NOTES = {
    'lookback': "reads back from now: a date or FROM/TO reads from that start up to now",
    'days': "reads back from now in whole days: a date or FROM/TO reads from that start up to now",
    'span': "picks daily, weekly or monthly from the length",
    'forecast': "today or later: today, tomorrow, this_week, next N days or a future FROM/TO",
    'range': ("a date, yesterday or FROM/TO reads exactly those days (both included; "
              "FROM/TO may carry T12:00 clock times); 24h/7d read back from now. "
              "Compare weeks with two calls."),
}


#: `a|b|c` 낱말 나열뿐인 설명 — 그 op 가 받는 값의 목록이다(surface._PIPE_LIST 와 같은 꼴).
_PIPE_WORDS = re.compile(r'^[a-z_]+(?:\|[a-z_]+)+$')


def _rename_args(text, o):
    """안쪽 도구 설명 속 안쪽 인자 이름 → 이 표면의 이름(`duration_seconds` → `duration`, `enabled` → `state`).

    help 가 안쪽 설명을 그대로 보여, 목록의 인자는 state·duration 인데 설명은 enabled/duration_seconds 를
    말했다(2026-11-09 claude.ai 점검). 밑줄 있는 이름은 낱말 경계로, 밑줄 없는 이름(enabled …)은 낱말이 흔해
    `/`·`=`·`,` 로 다른 인자 이름과 나란히 적힌 자리만 바꾼다."""
    for word, inner in (o.args or {}).items():
        if not inner or inner == word:
            continue
        if '_' in inner:
            text = re.sub(r'\b%s\b' % re.escape(inner), word, text)
        else:
            text = re.sub(r'(?<=[/,=])%s\b|\b%s(?=[/=,])' % (re.escape(inner), re.escape(inner)), word, text)
    return text


def _shared_doc(o, word, inner_doc):
    """공통 낱말의 도움말 — 목록의 설명과 같은 말에, 이 operation 이 그 낱말을 어떻게
    읽는지를 덧붙인다(안쪽 인자 설명을 그대로 보이면 목록과 어긋난다 — 2026-10-14:
    목록은 FROM/TO 를 받는다는데 도움말은 '1h, 24h, 7d' 만 보였다)."""
    from aot.tools.domain.surface import VOCAB_SCHEMA
    doc = dict(VOCAB_SCHEMA.get(word) or inner_doc)
    if word == 'period' and o.period_form:
        doc['here'] = _PERIOD_NOTES.get(o.period_form)
    elif word == 'period' and o.period_field:
        doc['here'] = "filters the result rows by date"
    elif word == 'fields' and (o.tool, o.op) in _FIELDS_NOTES:
        doc['here'] = _FIELDS_NOTES[(o.tool, o.op)]
    return doc


#: `fields` 가 이 operation 에서 고르는 갈래 — 기본 응답은 요약이고 갈래를 청하면 그것을 더한다.
_FIELDS_NOTES = {
    ('detail', 'widget'): "the default answer leaves out option_schema; fields=['schema'] adds it, 'all' adds everything",
    ('detail', 'map_equipment'): ("the default answer has counts, spacing, spec, drip pipes and pipe totals; "
                                  "fields=['sprinklers'] adds head positions, ['pipes'] each pipe, or 'all'"),
    ('detail', 'device'): ("the default answer is a brief; add any of: options (option keys and current values, "
                           "secrets as set/unset), connection (communication fields), measurements (channel ids "
                           "and select values), bindings, constraints, location, outputs - or all"),
}


def _off_here(ctx):
    """이 연결에서 못 부르는 operation 의 까닭 — 함수(o) → None(부를 수 있다) | dict.

    help 는 명부 전체를 설명하는데 tools/list 는 이 키가 닿는 것만 싣는다. 그 차이를
    말하지 않으면 모델은 help 에 있는 것을 부르려다 막히고 까닭을 짐작한다(2026-10-28
    점검: device_location_set 이 help 에만 있어 프로필을 두 번 바꿨다). 목록과 같은
    규칙(surface.for_key)으로 판정한다. 묶음·역할이 없는 호출자(인앱)는 늘 None."""
    from aot.tools import tool_execution as te
    from aot.tools import tool_registry as R
    profile = te._profile_enforced((ctx or {}).get('tool_profile'), (ctx or {}).get('transport'))
    role = (ctx or {}).get('role')
    if profile is None and role is None:
        return lambda o: None
    if profile is not None and te._is_lite(profile):
        profile = te._effective_profile(R.TOOL_PROFILE_OPERATIONS)
    hidden = te._hidden_tools(role)

    def off(o):
        names = set(o.inner_tools)
        if any(n not in hidden and (profile is None or R.tool_in_profile(n, profile, via_domain=True))
               for n in names):
            return None
        if names <= hidden:
            return {"callable_here": False,
                    "why": "this connection's permissions do not allow it; changing the "
                           "tool profile would not help"}
        mods = sorted({R.mcp_module_of(n) for n in names} - {None})
        if not mods:
            # 외부 연결에 내지 않는 안쪽 도구(retired) — 같은 일을 하는 operation 이 있다.
            return {"callable_here": False, "why": "not offered on external connections"}
        return {"callable_here": False, "tool_module": mods[0],
                "why": "the '%s' setup module is off in this connection's tool profile "
                       "(%s). configure.tool_profile_set can turn it on (approval); the "
                       "tool list changes after a reconnect or a new chat."
                       % (mods[0], profile)}
    return off


def _off_label(d):
    """도구 단위 help 의 짧은 표시 — 모듈 이름, 'permissions', 'not offered'."""
    if d.get('tool_module'):
        return d['tool_module']
    return 'permissions' if 'permissions' in d['why'] else 'not offered'



def _profile_card(ctx):
    """tool_profile_set 의 help 에만 싣는 것 — 지금 묶음과 묶음·모듈의 포함 관계.

    바꾸기 전에 지금 묶음을 볼 곳이 없어 모델이 configuration 에서 operations 로
    내려갔다(2026-10-28 점검 33·34). 목록에는 싣지 않는다(고정비)."""
    from aot.tools import tool_registry as R
    out = {"profiles": {
        "lite": "few tools listed, the rest reached by name; no setup modules",
        "operations": "day-to-day tools; 'modules' adds setup modules",
        "configuration": "operations plus every setup module",
    }, "modules": dict(R.TOOL_MODULE_SUMMARIES)}
    here = _this_connection(ctx)
    if here:
        out["this_connection"] = here
    return out


def _this_connection(ctx):
    """지금 묶음과 켜진·꺼진 모듈 — 묶음이 없는 호출자(인앱)는 None."""
    from aot.tools import tool_execution as te
    from aot.tools import tool_registry as R
    profile = te._profile_enforced((ctx or {}).get('tool_profile'), (ctx or {}).get('transport'))
    if profile is None:
        return None
    on = R.profile_modules(profile)
    return {"tool_profile": profile,
            "modules_on": [m for m in R.TOOL_MODULES if m in on],
            "modules_off": [m for m in R.TOOL_MODULES if m not in on]}


def _overview_card(ops, off, ctx):
    """인자 없는 `help` — 도구별 operation 이름, 못 부르는 것(까닭별), 이 연결의 묶음.

    2026-10-29 재시험: '이 연결의 도구 묶음과 켜진 모듈' 을 물으니 모델이 target 없이
    help 를 불러 'Unknown operation' 을 받았다(this_connection 은 tool_profile_set 의
    help 에만 있었다). 목록 설명은 늘리지 않고 응답에만 싣는다."""
    tools = {}
    shut = {}
    for x in ops:
        if x.tool == 'help':                  # help 는 이 카드 자신 — 'op' 라는 가짜 operation 을 싣지 않는다
            continue
        tools.setdefault(x.tool, []).append(x.op)
        d = off(x)
        if d:
            shut.setdefault(_off_label(d), []).append("%s.%s" % (x.tool, x.op))
    from aot.tools.domain.surface import VOCAB_HELP
    card = {"status": "success", "tools": tools,
            "next": "help(target='<tool>') for one tool's operations; "
                    "help(target='<tool>.<op>') for one operation's arguments",
            "vocabulary": VOCAB_HELP}
    if shut:
        card["off_here"] = shut
    here = _this_connection(ctx)
    if here:
        card["this_connection"] = here
    return card


VOCAB_SCHEMA_PERIOD = {"type": "string", "description": "now|24h|7d|today|yesterday|tomorrow|this_week|YYYY-MM-DD|FROM/TO"}


def help_card(target, ops=None, ctx=None):
    """`help(target='tool.op')` — operation 하나의 인자·위험·뜻. 명부만 읽는다(실행 없음).

    `ctx` 가 있으면 이 연결에서 부를 수 있는지도 싣는다(못 부를 때만). 도구 이름만
    오면('control') 그 도구의 operation 목록을, 아무것도 없으면 전체 요약을 준다."""
    from aot.tools import tool_registry as R
    from aot.tools.domain.registry import DOMAIN_TOOLS
    ops = ops if ops is not None else _ops()
    ref = str(target or '').strip()
    tool, _, op_name = ref.partition('.')
    tool, op_name = canonical(tool, op_name)
    off = _off_here(ctx)
    if not ref:
        return _overview_card(ops, off, ctx)
    if not op_name and tool in DOMAIN_TOOLS:
        mine = [x for x in ops if x.tool == tool]
        card = {"status": "success", "tool": tool,
                "operations": {x.op: x.use for x in mine},
                "next": "help(target='%s.<op>') for one operation's arguments" % tool}
        shut = {x.op: _off_label(off(x)) for x in mine if off(x)}
        if shut:
            card["off_here"] = shut
        return card
    o = find_op(ops, tool, op_name)
    if o is None:
        names, matched = _help_candidates(ref, tool, ops)
        card = {"status": "error", "message": "Unknown operation %r." % ref}
        if matched:
            card["operations"] = names[:60]                  # 그 도구의 전부, 이름·설명 낱말이 맞은 것, 옛 이름이 가리키는 것 순
            card["next"] = "help(target='tool.op') with one of operations; help(target='tool') lists a tool's ops"
        else:
            card["next"] = ("help(target='tool.op') with one of operations; help(target='tool') lists a tool's ops. "
                            "To find a device by name: find.devices(query='<name>').")
            card["operations"] = _ops_by_tool(ops)              # 전부 — 중간에서 자르면 control·record·… 가 빠진다
        return card
    approval = set(R.approval_required_tools())
    from aot.tools.domain.contract import catalog
    cat = catalog()
    inner_props = {}
    for name in o.inner_tools:
        inner_props.update(((cat.get(name) or {}).get('inputSchema') or {})
                           .get('properties') or {})
    def arg_doc(inner_name, why=None):
        d = dict(inner_props.get(inner_name) or {})
        if isinstance(d.get('description'), str):       # 안쪽 설명의 옛 도구 이름(resolve_target …) → 이 표면의 operation
            d['description'] = _rename_args(_rename_tools(d['description'], _inner_to_op()), o)
        if why:
            d['why_not_shared'] = why
            if _PIPE_WORDS.match(why) and 'enum' in d:
                # 안쪽 enum 에는 다른 op 몫의 값이 섞인다(screen.act 의 action 에 screen.card 의 post) — 이 op 의 목록으로.
                d['enum'] = why.split('|')
        return d
    pairs = {}
    if o.kinds_by_arg:
        # 동작 ↔ 대상 종류 짝(화면 조작) — 목록 설명이 아니라 이 카드에만 싣는다(목록 토큰은 그대로).
        pairs = {"action_target_pairs": _kinds_by_arg_hint(o),
                 "same_name_many_kinds": ("Pass the name in the slot of the kind you mean "
                                          "(see target_slots, e.g. widget='x' or dashboard='x') "
                                          "instead of target; or find.resolve first and pass the id.")}
    card = {
        **pairs,
        "status": "success", "operation": "%s.%s" % (o.tool, o.op), "use": o.use,
        "effect": _effect_label(o.effect),                    # 목록 표시([setup; approval])와 같은 이름
        "needs_approval": any(n in approval for n in o.inner_tools),
        "target_kinds": [k for k in o.inner if k != 'none'],
        "target_optional": 'none' in o.inner,
        "required": list(o.required),
        "shared_args": {w: _shared_doc(o, w, arg_doc(a)) for w, a in o.args.items()},
        "other_args": {a: arg_doc(a, why) for a, why in o.extra_args.items()},
        "several_targets": (bool(o.expand_write or o.fan_write) if o.tool in WRITE_TOOLS
                            else o.max_targets),
        # 대상은 target 하나로 넘긴다 — 아래 칸 이름으로 넘겨도 되며, 그러면 그 종류로만 찾는다.
        "target_slots": {ta: sorted(kinds) for ta, kinds in _target_slots(o).items()},
    }
    if o.period_pair:
        card["shared_args"]["period"] = dict(
            VOCAB_SCHEMA_PERIOD, here="a date range of days, both included: YYYY-MM-DD, FROM/TO, 'FROM/' (no end), "
                                      "'/TO' (no start), or this_week|7d")
    card.update(off(o) or {})
    if o.pick_by_arg is not None:
        # 같은 op 안에서 값이 동작을 고른다 — 값마다 필수와 받는 인자가 다르다(목록에는 합집합뿐).
        pk = o.pick_by_arg
        card["choose_by"] = pk.arg
        card["by_value"] = {
            (k or '(not given)'): {
                "use": b.use,
                "needs": [r for r in b.required if r != 'target'] + (['target'] if 'target' in b.required else []),
                "takes": sorted(set(b.args) | set(b.extra_args)),
                "targets": [x for x in b.inner if x != 'none'] or 'none (arguments carry them)',
            } for k, b in pk.branches.items()}
    if (o.tool, o.op) == ('configure', 'tool_profile_set'):
        card.update(_profile_card(ctx))
    if o.help_extra:                       # 형식·예시 등 help 전용 칸(목록 고정비에는 안 들어간다)
        card.update(o.help_extra)
    return card


def _effect_label(effect):
    from aot.tools.domain.surface import _EFFECT_MARK
    return _EFFECT_MARK.get(effect, effect)


def _ops_by_tool(ops):
    """{도구: [op …]} 전부 — help 와 같은 모양(가짜 help.op 는 뺀다)."""
    out = {}
    for x in ops:
        if x.tool != 'help':
            out.setdefault(x.tool, []).append(x.op)
    return out


def _help_candidates(ref, tool, ops):
    """help 가 모르는 말일 때의 후보 → (이름들, 실제로 맞은 것이 있는가). 그 도구의 operation, 옛 안쪽 도구 이름이 가리키는
    operation, 낱말이 이름·설명에 들어 있는 operation 순. 아무것도 못 찾으면 ([], False) — 호출자가 전체를 보인다."""
    import re
    from aot.tools.domain.registry import DOMAIN_TOOLS
    tags = lambda x: "%s.%s" % (x.tool, x.op)                # noqa: E731
    got = []

    def add(names):
        for n in names:
            if n not in got:
                got.append(n)
    if tool in DOMAIN_TOOLS:
        add(tags(x) for x in ops if x.tool == tool)
    word = ref.strip().lower()
    inner = _inner_to_op()
    if word in inner:
        add([inner[word]])
    terms = [t for t in re.split(r'[^a-z0-9]+', word) if len(t) > 2 and t not in ('get', 'list', 'set', 'the', 'tool')]
    if terms:
        scored = []
        for x in ops:
            hay = ("%s %s %s" % (x.tool, x.op, x.use)).lower()
            hit = sum(t in hay for t in terms)
            if hit:
                scored.append((-hit, tags(x)))
        add(n for _h, n in sorted(scored)[:8])
    got = [n for n in got if not n.startswith('help.')]
    return got, bool(got)


def gate_identity_refusal(tool_name, role):
    from aot.tools import mcp_safety_gate
    return mcp_safety_gate.identity_refusal(tool_name, role)


def run(app, tool, arguments, **ctx):
    """도메인 도구를 실행한다. 실행 경로는 `_execute_tool` 재귀 **하나뿐**이다."""
    if tool == 'help':
        # AI 를 못 쓰는 역할(Guest·Kiosk)에는 도구 목록도 내주지 않는다(역할 거절이 앞).
        refused = (gate_identity_refusal('get_tool_detail', ctx.get('role'))
                   if ctx.get('role') is not None else None)
        if refused is not None:
            return [{"type": "text", "text": json.dumps(refused, ensure_ascii=False)}]
        a = arguments or {}
        card = help_card(a.get('target') or a.get('tool_name') or a.get('query')
                         or a.get('operation'), ctx=ctx)
        return [{"type": "text", "text": json.dumps(card, ensure_ascii=False)}]
    # 대상 해석은 DB 를 읽는다 — HTTP 서버는 여기서 아직 앱 컨텍스트 밖이다
    # (안쪽 `_execute_tool` 이 자기 컨텍스트를 연다). 2026-10-14 벤치에서 모든
    # 이름 해석이 SQLAlchemy 오류로 실패했다(단위 시험은 컨텍스트 안에서 돌아 못 봤다).
    if app is not None:
        with app.app_context():
            return _run(app, tool, arguments, ctx)
    return _run(app, tool, arguments, ctx)


def _resolve_card(arguments, user=None):
    """find.resolve — 틀의 대상 해석 결과 그대로(이름 → 종류·id·경로). 읽기만 한다."""
    ref = (arguments or {}).get('target') or (arguments or {}).get('query')
    state, got = targets.resolve(ref)
    if state == 'ok':
        body = {"status": "success", "target": _candidates([got])[0],
                "matched": got.get('matched')}
        if got.get('alias'):
            body['alias'] = got['alias']
        from aot.tools.domain import aliases
        own = [a['alias'] for a in aliases.listing(got)['aliases']]
        if own:
            body['aliases'] = own
        kids = _children_of(got)
        if kids:
            body["inside"] = _candidates(kids)
    elif state == 'ambiguous':
        got = targets.rank(got, user)
        body = {"status": "needs_disambiguation", "reason_code": "ambiguous_target",
                "message": "'%s' names %d different things (%s).%s" % (
                    ref, len(got), _kinds_said(got), _ambiguous_note(got)),
                "candidates": _candidates(got)}
    elif state == 'empty':
        body = {"status": "error", "message": "find.resolve needs target (a name)."}
    else:
        body = dict(got, status="error", reason_code="unknown_target")
        if got.get('similar'):
            body['similar'] = _candidates(got['similar'])
    return [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]


def _aliases_card(arguments):
    """find.aliases — 별칭 목록(읽기). target 을 주면 그 대상의 것만."""
    from aot.tools.domain import aliases
    ref = (arguments or {}).get('target')
    target = None
    if ref:
        state, got = targets.resolve(ref)
        if state == 'ambiguous':
            return _error("'%s' names %d different things (%s) — pass the id of one."
                          % (ref, len(got), _kinds_said(got)),
                          status="needs_disambiguation", reason_code='ambiguous_target',
                          candidates=_candidates(got))
        if state != 'ok':
            return _error((got or {}).get('error') or "Unknown target %r." % ref,
                          reason_code='unknown_target')
        target = got
    return [{"type": "text", "text": json.dumps(aliases.listing(target), ensure_ascii=False)}]


def _run(app, tool, arguments, ctx):
    """도메인 호출 하나를 실행한다. 안쪽 호출이 남긴 감사 행 id 를 모아 두어, 호출이 끝난
    뒤의 화면 따라가기 결과를 그 행에 덧붙일 수 있게 한다(`_record_screen_outcome`)."""
    from aot.tools import tool_execution as te
    token = te.AUDIT_UIDS.set([])
    try:
        return _run_call(app, tool, arguments, ctx)
    finally:
        te.AUDIT_UIDS.reset(token)


def _run_call(app, tool, arguments, ctx):
    # 옛 op·인자 이름은 여기서 새 이름으로 — 이후(응답 계약·서버 카드·감사)는 정식 이름만 본다.
    tool, arguments, renamed = renames.resolve_call(tool, arguments, _ops())
    # 화면 따라가기의 호출별 옵션 — 틀이 한 번만 따라가므로 여기서 뗀다. 안쪽 호출에는
    # 'off' 를 실어 안쪽 도구가 따로 따라가지 않게 한다(창이 두 번 열리지 않게).
    from aot.tools import screen_follow
    arguments, show = screen_follow.pop_show_arg(arguments)
    # 화면 지정은 한 이름이다 — 조회는 `_show_on_screen`, 화면 조작은 `screen`. 서로의 이름도 받는다.
    if tool == 'screen':
        if show is not None and 'screen' not in arguments and \
                screen_follow._parse_show(show)[0] == 'screen':
            arguments['screen'] = show
    elif show is None and arguments.get('screen'):
        show = arguments.pop('screen')
    show = effective_show(tool, arguments.get('op'), show)
    # 화면 도구에서 지정한 화면은 이 대화의 지정 화면으로 적어 둔다 — 이후 조회가 여러 화면 속에서도 그 화면을 따라간다.
    if tool == 'screen':
        screen_follow.remember_screen(ctx.get('scope_user_uuid'), ctx.get('session_key'), arguments.get('screen'))
    # 날씨의 '답하는 시각' — 안쪽 조회는 아래 `_QUIET` 로 따라가기를 끄므로(창이 두 번 열리지 않게) 슬라이더는 틀이 옮긴다.
    arguments, answer_time = screen_follow.pop_answer_time(arguments)
    # 느린 읽기의 "조회 중" 자막은 틀이 한 번만 건다. 안쪽 호출은 `_QUIET`(show='off')라 스스로는 걸지 않는다 —
    # 여기서 AI 가 실제로 준 show 로 판정해야 AI 가 화면을 건드리지 말라고 한 호출에는 자막도 없다.
    with screen_follow.slow_read_notice(app, tool, 'read' if tool in READ_TOOLS else 'write',
                                        ctx.get('scope_user_uuid'), ctx.get('tool_profile'),
                                        ctx.get('transport'), show):
        out = _run_call_inner(app, tool, arguments, ctx, show, answer_time)
    # 날씨·장소 요약 카드는 서버가 올린다(카드 결정 A, 2026-10-29) — 올렸으면 안내(card_hint)를 뗀다.
    out = server_card.post_for(app, tool, arguments.get('op'), out, ctx, show)
    # 값 조회(measure.latest·history)는 게이지·미니그래프 카드를 서버가 올린다(2026-11-06, 같은 결정) — 텍스트는 병행.
    out = server_viz.post_for(app, tool, arguments.get('op'), out, ctx, show)
    # 출구 한 곳 — 시범 op 는 행동(next)·말하기(say)·사실(data)로 나눈다(act_say, 설계 §2-4).
    out = act_say.shape(out, tool, arguments.get('op'))
    # 꼭 할 호출이 있으면 그 하나만 맨 앞 `must` 한 줄로(F-16 ①) — 모든 op 에.
    out = act_say.lead(out)
    return _with_renamed(out, renamed)


def _with_renamed(out, renamed):
    """옛 이름이 실제 쓰인 호출에만 "새 이름은 이것" 한 줄 — status·say·next 다음, data 앞."""
    if not renamed:
        return out
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not isinstance(body, dict):
        return out
    head = {k: body[k] for k in ('must', 'status', 'say', 'next') if k in body}
    body = {**head, 'renamed': renamed, **{k: v for k, v in body.items() if k not in head}}
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


_FOCUS_SLOT = "<max|min|rain_start|HH:MM|range>"


def _focus_required(tool, arguments, ctx, show, answer_time=None):
    """도메인 예보는 화면 시간 따라가기가 가능할 때 `focus` 가 필수다(2026-11-10, 실측 0/10: AI 는 선택 인자를 안 채운다).

    없거나 모르는 값이면 처리기를 부르지 않고 같은 인자 + focus 자리표시의 다시 보낼 호출을 돌려준다(`next.resend` → `must`).
    화면이 없는 클라이언트·`_show_on_screen='off'`·인앱 AI·`_answer_time`(슬라이더 시각이 이미 정해짐)은 거절하지 않는다."""
    from aot.tools import screen_follow
    if screen_follow.focus_valid(arguments) or answer_time not in (None, ''):
        return None
    if not screen_follow.focus_required_here(ctx.get('scope_user_uuid'), ctx.get('tool_profile'),
                                             ctx.get('transport'), show):
        return None
    parts = ["%s=%r" % (k, v) for k, v in arguments.items() if k != 'focus' and not str(k).startswith('_')]
    how, screen = screen_follow._parse_show(show)
    if how == 'screen':                           # 화면 지정은 다시 보낼 호출에도 남는다
        parts.append("_show_on_screen=%r" % screen)
    parts.append("focus=" + _FOCUS_SLOT)
    given = str(arguments.get('focus') or '')
    if '<' in given or '|' in given:
        why = "focus was the placeholder; pick one value (max, min, rain_start, HH:MM or range), not the placeholder."
    else:
        why = ("forecast needs focus: what the answer points to - max, min, rain_start, an hour (HH:MM), or range "
               "for the whole span.")
    return _error(why + " Nothing was run.", reason_code='focus_required',
                  next={"resend": "%s(%s)" % (tool, ", ".join(parts))})


def _run_call_inner(app, tool, arguments, ctx, show, answer_time):
    # 역할 거절이 가장 앞이다 — 모호한 이름의 후보 목록·"이미 그 상태" 성공·인자 오류가
    # 권한 없는 호출자에게 먼저 나가면 안 된다(26-11-04 전수 실측 S1·S2). 대상 풀기·별칭
    # 목록도 같다(26-11-05: Guest·Kiosk 가 이름·id 를 받던 것). 순서: 역할 → 묶음 → 그 밖.
    refused = _role_refusal_first(tool, arguments, ctx)
    if refused is not None:
        _audit_refusal(tool, arguments, ctx, refused)
        return refused
    if tool == 'weather' and arguments.get('op') == 'forecast':
        refused = _focus_required(tool, arguments, ctx, show, answer_time)
        if refused is not None:
            _audit_refusal(tool, arguments, ctx, refused)
            return refused
    if tool == 'find' and arguments.get('op') == 'resolve':
        out = _resolve_card(arguments, ctx.get('scope_user_uuid'))
        return _follow(tool, out, _resolve_target_of(out), ctx, show, answer_time, arguments)
    if tool == 'find' and arguments.get('op') == 'aliases':
        return _aliases_card(arguments)
    verdict = plan(tool, arguments, user=ctx.get('scope_user_uuid'), session=ctx.get('session_key'))
    if verdict[0] == 'refuse':
        _audit_refusal(tool, arguments, ctx, verdict[1])
        return verdict[1]
    from aot.tools.tool_execution import _execute_tool
    if verdict[0] == 'filter':
        _f, inner, inner_args, meta = verdict
        extra = inner_args.pop(META_KEY, None) or {}
        follow_to = meta.get('target')
        out = _execute_tool(app, inner, dict(inner_args, **_QUIET), via_domain=True, **ctx)
        out = _annotate(_filter_ids(out, meta), dict({k: v for k, v in extra.items() if k != 'target'},
                                                     **{k: meta[k] for k in ('picked_by', 'picked') if k in meta}))
        return _follow(tool, out, follow_to, ctx, show, answer_time, arguments)
    if verdict[0] == 'fanout':
        # 읽기 펼치기 — 안의 대상마다 같은 안쪽 도구를 부른다(쓰기는 여기 오지 않는다).
        _f, inner, calls, meta = verdict
        results, period = [], None
        per_target = meta.get('per_target')
        o = find_op(_ops(), tool, arguments.get('op')) if per_target else None
        for child, args in calls:
            extra = args.pop(META_KEY, None) or {}
            period = period or extra.get('period')
            slim_args = extra.pop('slim', None)
            journal_range = extra.pop('journal_range', None)
            by_period = bool(o is not None and o.period_field and arguments.get('period'))
            out = _execute_tool(app, inner, dict(args, **_QUIET), via_domain=True,
                                **dict(ctx, uncapped=True) if by_period else ctx)
            if per_target:
                out = _finish_read(out, tool, arguments, o, slim_args, journal_range, extra)
            text = out[0].get('text') if isinstance(out, list) and out else None
            try:
                body = json.loads(text) if text else out
            except (TypeError, ValueError):
                body = text
            if isinstance(body, dict):
                for k in ('server_host', 'now', 'call_state'):
                    body.pop(k, None)
                _domain_hints(body)
            results.append({"target": {k: child.get(k) for k in ('kind', 'name', 'path')},
                            "result": body})
        env = dict({k: v for k, v in meta.items() if k != 'per_target'}, status="success", results=results)
        if period:
            env["period"] = period
        out = [{"type": "text", "text": json.dumps(env, ensure_ascii=False, default=str)}]
        # 펼쳐 읽었으면 사용자가 말한 그 그릇을 연다(안의 것 하나하나가 아니라).
        return _follow(tool, out, meta.get('target'), ctx, show, answer_time, arguments)
    if verdict[0] == 'fanwrite':
        # 쓰기 여럿 — 대상마다 같은 안쪽 도구를 따로 건다(승인 대기도 대상마다). 응답은 하나: 되읽기 한 줄,
        # 승인 한 번(confirmation_ids). 요청은 승인이 아니다 — 아무것도 실행되지 않았다.
        _f, inner, calls, meta = verdict
        return _fan_write(app, tool, arguments, inner, calls, ctx)
    _call, inner, inner_args = verdict
    same = _already_so(inner, inner_args)
    if same is not None:
        return same
    extra = inner_args.pop(META_KEY, None) or {}
    slim_args = extra.pop('slim', None)
    journal_range = extra.pop('journal_range', None)
    quiet = tool in READ_TOOLS
    o = find_op(_ops(), tool, arguments.get('op'))
    # 기간을 거르는 읽기는 안쪽 응답을 크기 상한으로 자르지 않는다 — 앞 일부만 남기고 거르면 기간 안의
    # 행이 사라져 count 0 에 results_truncated 가 같이 나온다(2026-11-03 시험 #2). 상한은 거른 뒤 바깥에서.
    by_period = bool(o is not None and o.period_field and arguments.get('period'))
    out = _execute_tool(app, inner, dict(inner_args, **_QUIET) if quiet else inner_args,
                        via_domain=True, uncapped=by_period, **ctx)
    out = _finish_read(out, tool, arguments, o, slim_args, journal_range, extra)
    if not quiet:
        return _approval_next(out, tool, arguments, ctx)
    return _follow(tool, out,
                   _crop_plot_target(out, tool, arguments.get('op'), extra.get('target'))
                   or _single_result(out, tool, arguments.get('op')),
                   ctx, show, answer_time, arguments)


def _finish_read(out, tool, arguments, o, slim_args, journal_range, extra):
    """안쪽 읽기 응답을 도메인 응답으로 다듬는다 — 기간 거르기·줄이기·op 별 손질·대상 이름 표시. 대상 하나짜리
    호출과 대상별로 따로 부른 읽기(`per_target`)가 같은 길을 쓴다."""
    by_period = bool(o is not None and o.period_field and arguments.get('period'))
    if by_period:
        out = _filter_period(out, o, arguments['period'], arguments.get('limit'))
    if o is not None and o.slim:
        out = slim.apply(out, o.slim, slim_args or {})
    if journal_range:
        out = _filter_journal_period(out, journal_range['range'], journal_range['limit'])
    if (tool, arguments.get('op')) == ('measure', 'soil_forecast'):
        out = _unavailable_next(out)
    elif (tool, arguments.get('op')) == ('measure', 'water_estimate'):
        out = _estimate_window_iso(out, arguments.get('duration'))
    elif tool == 'weather':
        out = _weather_origin(out)
    elif (tool, arguments.get('op')) == ('measure', 'latest'):
        out = _latest_tidy(out, bool(arguments.get('measurement')))
    return _annotate(_name_resolved_ids(out, extra), extra)


#: 주 채널이 아닌 보조 채널(배터리·전파 세기) — 대표값이 이것이면 "센서의 값"으로 읽히면 안 된다.
_AUX_CHANNELS = frozenset({'electrical_potential', 'battery', 'battery_level', 'battery_voltage',
                           'rssi', 'signal_strength', 'signal_quality', 'lqi', 'snr'})
_REPRESENTATIVE = ('measurement', 'timestamp', 'value', 'unit')


def _latest_tidy(out, asked_measurement):
    """measure.latest 의 두 가지 손질(2026-11-03 라운드 2 #6).
    1) 항목을 안 정했는데 주 채널(온도·습도 …)이 끊겨 `silent_channels` 가 있고 최상위 대표값이 보조 채널(배터리)이면,
       대표값 칸을 비우고 `channels` 만 둔다 — 배터리 3.7 V 가 "온습도_1 의 값"으로 읽히지 않게. 끊긴 채널이 없는 센서
       (진짜 배터리 채널뿐인 센서)는 그대로다.
    2) 옛 키 `time_range` 는 이 표면의 이름 `period` 로(값이 없으면 뺀다). `period` 가 이미 있으면 그쪽이 이긴다."""
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not isinstance(body, dict) or body.get('status') == 'error':
        return out
    changed = False
    if not asked_measurement and body.get('silent_channels') and body.get('measurement') in _AUX_CHANNELS:
        for k in _REPRESENTATIVE:
            body.pop(k, None)
        if isinstance(body.get('note'), str):
            body['note'] = body['note'].replace(
                "The value above is from another channel of this device.",
                "No main reading is given: only the other channels listed in `channels` reported.")
        changed = True
    if 'time_range' in body:
        old = body.pop('time_range')
        if old is not None and 'period' not in body:
            body['period'] = old
        changed = True
    if not changed:
        return out
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def _weather_origin(out):
    """날씨 응답의 `weather_source` 는 그대로 두고, 값이 예보 모델이면 최상위에서 읽히게 `weather_data_origin` 을 더한다
    (2026-11-03 라운드 2 #5 — `weather_device.data_origin` 은 한 겹 안이라 `weather_source: weather_station` 만 읽은 AI 가
    모델 값을 관측으로 읽었다). 출처를 고르는 로직은 건드리지 않는다."""
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    dev = body.get('weather_device') if isinstance(body, dict) else None
    origin = dev.get('data_origin') if isinstance(dev, dict) else None
    if origin not in ('model', 'observed') or 'weather_data_origin' in body:
        return out
    pos = list(body).index('weather_source') + 1 if 'weather_source' in body else len(body)
    items = list(body.items())
    body = dict(items[:pos] + [('weather_data_origin', origin)] + items[pos:])
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def _estimate_window_iso(out, duration):
    """`window` 의 유닉스 초(float) → 그 구획 시계의 ISO(+오프셋), 호출이 준 `duration` 을 돌려준다(2026-11-03 라운드 2 #4).
    시각은 timekit 으로만 — aware UTC 에서 구획 시계로(`iso_at`), 고정 오프셋·naive 섞기 없음."""
    from aot.utils.timekit import iso_at
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not isinstance(body, dict):
        return out
    changed = False
    for one in [body] + [r for r in (body.get('results') or []) if isinstance(r, dict)]:
        win = one.get('window')
        if not isinstance(win, dict) or not all(isinstance(win.get(k), (int, float)) for k in ('from', 'to')):
            continue
        where = one.get('plot')
        one['window'] = {k: iso_at(win[k], where) for k in ('from', 'to')}
        if duration not in (None, ''):
            one['duration'] = duration
        changed = True
    if not changed:
        return out
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def _unavailable_next(out):
    """트윈이 예측을 못 낸 응답(`unavailable`)에 막다른 길을 없앤다 — 지금 값과 비 예보로 답할 길(2026-11-03 라운드 2 #3)."""
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not isinstance(body, dict) or body.get('status') != 'unavailable' or 'next' in body:
        return out
    who = body.get('plot')
    who = "'%s'" % who if who else '<plot>'
    head = {'status': 'unavailable'}
    head['next'] = {"call": "measure.latest(target=%s, measurement='soil moisture') for the current reading; "
                            "weather.forecast(target=%s, measurement='rain') for coming rain" % (who, who)}
    body = {**head, **{k: v for k, v in body.items() if k not in head}}
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def _role_refusal_first(tool, arguments, ctx):
    """op 의 안쪽 도구가 **전부** 이 호출자의 역할로 거절되면 그 거절 본문(블록), 아니면 None.

    판정은 게이트의 `role_refusal` 하나다(두 번째 판정자를 만들지 않는다). 가지가 여럿인 op 는
    하나라도 쓸 수 있으면 통과시켜 안쪽 게이트가 가른다. 승인 응답(`respond_to_confirmation`)은
    항목별 판정이라 여기서 보지 않는다."""
    try:
        from aot.tools import mcp_safety_gate as gate
        from aot.tools import tool_execution as te
        if ctx.get('role') is None:        # 인증을 끈 연결 — 안쪽 게이트가 같은 판정을 한다
            return None
        o = find_op(_ops(), tool, (arguments or {}).get('op'))
        if o is None:
            return None
        inner = [t for t in o.inner_tools if t != 'respond_to_confirmation']
        if not inner or len(inner) != len(o.inner_tools):
            return None
        bodies = [gate.identity_refusal(t, ctx.get('role')) for t in inner]
        if not any(b is None for b in bodies):
            return [{"type": "text", "text": json.dumps(bodies[0], ensure_ascii=False)}]
        # 역할 다음은 도구 묶음 — "이미 그 상태" 단축·인자 오류가 묶음 밖 호출에 먼저 답하지 않게.
        # 안쪽 도구가 전부 묶음 밖일 때만(하나라도 쓸 수 있으면 안쪽 판정에 맡긴다).
        profiled = [te._profile_refusal(t, ctx.get('tool_profile'), ctx.get('transport'),
                                        role=ctx.get('role'), via_domain=True) for t in inner]
        if not any(b is None for b in profiled):
            return [{"type": "text", "text": json.dumps(profiled[0], ensure_ascii=False)}]
        return None
    except Exception:                                       # noqa: BLE001
        logger.exception('[domain] role-first check failed (passed on to the gate)')
        return None


def _already_so(inner, inner_args):
    """이미 요청한 상태면 아무것도 하지 않고 그렇다고 답한다 — 승인도 청하지 않는다(입력 켜기/끄기)."""
    if inner != 'activate_input':
        return None
    from aot.tools.aot_data_tool_service import AoTDataToolService
    got = AoTDataToolService.input_activation_state(
        input_id=inner_args.get('input_id'), active=inner_args.get('active', True))
    if not got or not got['same']:
        return None
    body = {"status": "success", "unchanged": True, "name": got['name'],
            "is_activated": got['is_activated'],
            "message": "'%s' is already %s - nothing was changed or asked." % (
                got['name'], "on" if got['is_activated'] else "off")}
    return [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]


def _fan_write(app, tool, arguments, inner, calls, ctx):
    """대상 여럿의 물리 제어(`Op.fan_write`) — 대상마다 안쪽 호출을 걸고 승인 대기를 하나의 응답으로 묶는다.

    승인 규칙은 그대로다: 서버가 푼 대상을 되읽고(say.ask), 사용자의 승인 뒤에만 `control.confirm` 이
    그 번호들을 승인·실행한다. 안쪽 도구가 거절한 대상(AI 제외·숫자 오류 …)은 `not_requested` 에 이유와 함께
    남고 되읽기에서 빠진다 — 일부만 승인 대기가 되었음을 사용자에게 말해야 한다(say.tell)."""
    from aot.tools.tool_execution import _execute_tool
    asked, refused = [], []
    for child, args in calls:
        args.pop(META_KEY, None)
        out = _execute_tool(app, inner, args, via_domain=True, **ctx)
        try:
            body = json.loads(out[0]['text'])
        except (TypeError, ValueError, KeyError, IndexError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        entry = {k: child.get(k) for k in ('kind', 'name', 'path')}
        if body.get('status') == 'pending_approval' and body.get('confirmation_id'):
            entry.update(confirmation_id=body['confirmation_id'],
                         read_back=body.get('confirm_with_user'))
            asked.append(entry)
        else:
            entry.update(status=body.get('status') or 'error',
                         reason_code=body.get('reason_code'),
                         message=body.get('message') or body.get('error'))
            refused.append({k: v for k, v in entry.items() if v is not None})
    return act_say.batch_pending(asked, refused)


#: 화면 이동이 받는 대상 종류 — 같은 이름이 둘 다에 있으면 대시보드가 기본이다(`plan` 의 이름 중복 규칙).
_NAV_KINDS = frozenset({'dashboard', 'tab'})
#: 안쪽 호출에 싣는 따라가기 끔 — 틀이 한 번만 따라간다.
_QUIET = {'_show_on_screen': 'off'}
#: 지도 창을 열지 않고 지도만 그 대상 가운데로 옮기는 읽기 — 창이 측정값 패널(날씨 값)을
#: 가린다(2026-10-25 사용자: "날씨 설명에서는 모달창을 열지 않고 해당 대지·시설만 중심으로").
_CENTER_ONLY_TOOLS = frozenset({'weather'})
#: 화면에 열 수 있는 대상 종류(지도 창 또는 그 장치의 위젯 강조).
_FOLLOW_KINDS = frozenset({'site', 'zone', 'facility', 'plot', 'input', 'output', 'device'})


#: 슬라이더를 서버가 옮기는 읽기(2026-10-26) → 그 읽기를 대신하는 안쪽 예보 도구. 안쪽 호출은 따라가기를 끈 채 돌므로
#: (`_QUIET`) 예전에는 도메인 `weather` 에서 서버 슬라이더가 한 번도 움직이지 않았다.
_SLIDER_TOOLS = {'weather': 'get_weather_forecast'}


def _follow(tool, out, target, ctx, show, answer_time=None, arguments=None):
    """창 따라가기(`_follow_place`) 뒤에, 날씨면 지도 시간 슬라이더도 서버가 먼저 옮긴다(응답에는 힌트만 싣는다)."""
    if tool == 'screen_view':
        return _follow_focus(out, arguments, ctx, show)
    out = _follow_place(tool, out, target, ctx, show)
    inner = _SLIDER_TOOLS.get(tool)
    if inner is None or not _ran_ok(out):
        return out
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not isinstance(body, dict):
        return out
    from aot.tools import screen_follow
    moved = screen_follow.follow_time(
        inner, arguments or {}, body, ctx.get('scope_user_uuid'), ctx.get('tool_profile'),
        ctx.get('transport'), show=show, answer_time=answer_time, session_key=ctx.get('session_key'))
    if not moved:
        return out
    logger.info('[AoTMCP] map time slider: %s', moved.get('slider'))
    if act_say.applies(tool, (arguments or {}).get('op')):
        # 계약 op — 지도 시간은 글이 아니라 기계용 next 한 칸이다(보이는 시각 + 다른 시각을 말할 때의 호출).
        when = screen_follow.time_next_for(ctx.get('scope_user_uuid'), moved)
        if not when:
            return out
        body['next'] = dict(body['next'] if isinstance(body.get('next'), dict) else {}, map_time=when)
        return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])
    hint = screen_follow.time_hint_for(ctx.get('scope_user_uuid'), moved, domain=True)
    if not hint:
        return out
    body = {'time_hint': hint, **{k: v for k, v in body.items() if k != 'time_hint'}}     # 맨 앞 — 끝에 두면 묻힌다
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


#: screen_view focus 의 예약어 — 위젯·카드 이름이 아니라 목록·지도 보기다(그 화면에는 이미 보이는 것들).
_FOCUS_WORDS = frozenset({'map', 'maps', 'widgets', 'all', 'tabs'})


def _follow_focus(out, arguments, ctx, show):
    """screen_view 가 focus=<위젯·카드 이름> 으로 한 곳을 설명하려 하면 사용자 화면도 그 자리로 간다.

    위젯·카드가 화면 밖이면 스크롤하고(이미 보이면 그대로) 테두리를 건다 — 게이트는 다른 따라가기와 같다(화면 조작 허용,
    기기별 따라가기, `_show_on_screen`). 화면이 스크롤한 결과는 기다리지 않는다: 못 보이면 다음 get_screen 의
    `scroll_miss` 가 알린다.
    """
    ref = str((arguments or {}).get('focus') or '').strip()
    if not ref or ref.lower() in _FOCUS_WORDS or not _ran_ok(out):
        return out
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    likely = body.get('likely') if isinstance(body, dict) else None
    if not isinstance(likely, dict) or not likely.get('focus') or \
            str(likely['focus']).startswith("'%s' is not on this screen" % ref):
        return out                  # 그 화면에 없는 이름 — 무엇을 가리킬지 모른다
    from aot.tools import screen_follow
    trace = []
    shown = screen_follow.follow_focus(ref, ctx.get('scope_user_uuid'), ctx.get('tool_profile'),
                                       ctx.get('transport'), show=show, trace=trace,
                                       session_key=ctx.get('session_key'))
    _record_screen_outcome(screen_follow.audit_note(shown, trace))
    if not shown:
        return out
    body['screen'] = shown
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def _follow_place(tool, out, target, ctx, show):
    """읽기가 대상 하나를 풀었으면 그것을 사용자 화면(대시보드 지도 위젯)에 연다.

    어떤 읽기 operation 이든 — 안쪽 도구 이름 목록에 기대지 않는다(2026-10-14 사용자:
    "지도 위젯에서라고 해도 텍스트로만 설명한다"). 막는 겹(화면 조작 허용·기기별
    따라가기)은 `screen_follow` 그대로다. 응답이 실패면 열지 않는다.

    결과(열었음 · [허용] 카드 · 넣어 둠 · 열지 않음 + 이유, 조용히 건너뛴 이유)는 이 호출의
    감사 행에도 남긴다.
    """
    if tool not in READ_TOOLS:
        return out
    from aot.tools import screen_follow
    if not isinstance(target, dict) or target.get('kind') not in _FOLLOW_KINDS \
            or not target.get('id'):
        # 대상이 없거나 여럿이면 무엇을 열지 짐작하지 않는다 — 그 사실만 기록에 남긴다.
        if screen_follow.eligible(ctx.get('scope_user_uuid'), ctx.get('tool_profile'),
                                  ctx.get('transport'), show) and _ran_ok(out):
            _record_screen_outcome('screen:skipped no single target to open')
        return out
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not _ran_ok(out, body):
        return out
    trace = []
    shown = screen_follow.follow_resolved(
        target['kind'], target['id'], ctx.get('scope_user_uuid'), ctx.get('tool_profile'),
        ctx.get('transport'), show=show, trace=trace, session_key=ctx.get('session_key'),
        **({'center_only': True} if tool in _CENTER_ONLY_TOOLS else {}))
    _record_screen_outcome(screen_follow.audit_note(shown, trace))
    if not shown:
        return out
    if isinstance(body, dict):
        body['screen'] = shown
    elif isinstance(body, list):
        body = {"results": body, "screen": shown}
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def _ran_ok(out, body=None):
    """응답이 실제로 실행된 읽기인가 — 실패·거절·미실행이면 화면도 따라가지 않는다."""
    if body is None:
        try:
            body = json.loads(out[0]['text'])
        except (TypeError, ValueError, KeyError, IndexError):
            return False
    return not (isinstance(body, dict) and (
        body.get('status') in _NOT_RUN or body.get('error')
        or body.get('call_state') in ('failed', 'refused')))


def _record_screen_outcome(note):
    """따라가기 결과를 이 호출이 남긴 감사 행(마지막 안쪽 호출)의 result_summary 에 붙인다."""
    if not note:
        return
    try:
        from aot.mcp_server import audit
        from aot.tools import tool_execution as te
        uids = te.AUDIT_UIDS.get()
        if uids:
            audit.append_result_summary(uids[-1], note)
    except Exception:                                       # noqa: BLE001
        logger.debug('[domain] screen outcome audit failed', exc_info=True)


def _resolve_target_of(out):
    """find.resolve 의 응답에서 풀린 대상(하나일 때)."""
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    return body.get('target') if body.get('status') == 'success' else None


#: 대상 없이 찾았는데 결과가 하나뿐인 목록 — 그것을 연다('검정콩' 구획 찾기).
_SINGLE_ROW_KEYS = (('plots', 'plot'),)
#: 대상이 결과의 행마다 달려 있는 읽기 — 행들이 가리키는 대상이 **하나**면 그것을 연다
#: (노트 검색: 노트마다 target_id 가 붙는다. 사용자 결정 2026-10-20).
_ROWS_WITH_TARGET = {('records', 'notes'): ('results', 'target_id')}


def _single_result(out, tool=None, op=None):
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    if not isinstance(body, dict):
        return None
    for key, kind in _SINGLE_ROW_KEYS:
        rows = body.get(key)
        if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) \
                and not body.get('truncated'):
            uid = rows[0].get('unique_id') or rows[0].get('id')
            if uid:
                return {'kind': kind, 'id': uid}
    spec = _ROWS_WITH_TARGET.get((tool, op))
    if spec:
        rows = body.get(spec[0])
        if isinstance(rows, list) and rows:
            ids = {str(r.get(spec[1])) for r in rows
                   if isinstance(r, dict) and r.get(spec[1])}
            # 일부 행에 대상이 없으면(대상 없는 노트) 그 결과는 하나를 가리킨다고 할 수 없다.
            if len(ids) == 1 and all(isinstance(r, dict) and r.get(spec[1]) for r in rows):
                return _kind_of_id(ids.pop())
    return None


def _crop_plot_target(out, tool, op, target):
    """find.plots(옛 overview.crops)를 시설로 물었는데 그 시설에 구획이 하나뿐이면 화면에는 시설이 아니라 그 작물 구획을 연다.
    작물을 물은 사람은 작물 상태를 보려는 것이다(2026-10-28 점검: 육묘장3 의 작물을 묻자 시설이 떴다).
    구획이 여럿이면 하나를 고르지 않고 시설 그대로 둔다."""
    if (tool, op) not in (('overview', 'crops'), ('find', 'plots')) or not isinstance(target, dict) \
            or target.get('kind') != 'facility':
        return target
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return target
    rows = body.get('facility_bay_plots') if isinstance(body, dict) else None
    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) \
            and rows[0].get('unique_id'):
        return {'kind': 'plot', 'id': str(rows[0]['unique_id'])}
    return target


def _kind_of_id(ident):
    """id → {'kind', 'id'} — 지도 도형·구획·장치·시설. 모르거나 열 창이 없으면 None."""
    from aot.tools import screen_follow
    try:
        hit = screen_follow._by_id(ident)
    except Exception:                                       # noqa: BLE001
        return None
    if hit is None or hit[0] not in _FOLLOW_KINDS:
        return None
    return {'kind': hit[0], 'id': hit[1]}


def _audit_refusal(tool, arguments, ctx, body):
    """틀이 안쪽 도구를 부르기 전에 거절한 호출도 호출 기록에 남긴다.

    안 남기면 거절은 기록 어디에도 없다 — 안쪽 도구만 기록되기 때문이다(2026-10-14 웹
    시험: '모르는 인자' 로 막힌 화면 이동이 기록에 없어 원인을 대화 쪽에서만 볼 수 있었다).
    """
    try:
        from aot.mcp_server import audit
        from aot.tools import tool_execution as te
        text = body[0].get('text') if isinstance(body, list) and body else ''
        try:
            info = json.loads(text) if text else {}
        except (TypeError, ValueError):
            info = {}
        fields = {}
        if te._quality_ledger_enabled():
            fields = {"session_key": te.session_key_hash(ctx.get('session_key')),
                      "transport": ctx.get('transport'), "call_state": "refused"}
        audit.record_call(
            tool_name='%s.%s' % (tool, (arguments or {}).get('op') or '?'),
            params=arguments, agent_id=ctx.get('agent_id') or 'unknown',
            permission='write' if tool in WRITE_TOOLS else 'read',
            result_summary=info.get('reason_code') or info.get('status') or 'refused',
            error=(info.get('message') or info.get('error') or '')[:500], **fields)
    except Exception:                                       # noqa: BLE001
        logger.exception('[domain] refusal audit failed')


def _name_resolved_ids(out, extra):
    """오류 문구에 서버가 푼 id 가 그대로 나오면 사용자가 준 이름으로 바꾼다 —
    `could not locate '5133d6ca-…'` 는 사용자가 무엇을 말했는지 알 수 없다(2026-11-03 시험 #6)."""
    target = (extra or {}).get('target')
    if not isinstance(target, dict) or not target.get('id') or not target.get('name'):
        return out
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not isinstance(body, dict) or body.get('status') != 'error':
        return out
    changed = False
    for key in ('message', 'error'):
        text = body.get(key)
        if isinstance(text, str) and str(target['id']) in text:
            body[key] = text.replace(str(target['id']), str(target['name']))
            changed = True
    if not changed:
        return out
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def _annotate(out, extra):
    """안쪽 응답에 틀의 해석을 싣고, 안쪽 도구 이름으로 된 다음 단계 안내를 도메인
    operation 이름으로 바꾼다. JSON 이 아니면 그대로 둔다."""
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not isinstance(body, dict):
        return out
    if extra and body.get('status') not in _NOT_RUN and body.get('call_state') not in (
            'failed', 'refused'):
        # 안쪽이 거절·실패하면 실지 않는다 — 쓰이지 않은 대상을 쓴 것처럼 보이게 된다
        # (2026-10-14: 위젯이 필요하다는 오류에 센서가 read_as 로 붙었다).
        body["read_as"] = extra
    _domain_hints(body)
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def _approval_next(out, tool, arguments, ctx=None):
    """승인 대기 응답에 이 표면의 다음 단계를 싣는다.

    게이트의 안내문은 안쪽 이름(`respond_to_confirmation`, "같은 도구를 다시")으로 적혀
    있어, 도메인 표면의 모델은 승인할 길을 찾지 못하고 같은 쓰기를 다시 불러 승인 대기만
    쌓았다(2026-10-14 사용자 시험). 승인은 `control.confirm`, 실행은 같은 operation 을
    같은 인자 + `_confirmation_id` 로.
    """
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not isinstance(body, dict) or body.get('status') != 'pending_approval' \
            or not body.get('confirmation_id'):
        return out
    cid = body['confirmation_id']
    # 같은 요청의 대기가 이미 있었다(게이트가 새로 만들지 않고 돌려줌, F-16 ⑤) — 이 대화가 이미 되읽어 물었으면
    # 다시 묻지 않게 표시를 남기고, 다른 대화가 만든 대기면 표시를 떼어 여기서 처음 되읽게 한다.
    user, session = (ctx or {}).get('scope_user_uuid'), (ctx or {}).get('session_key')
    if body.pop('already_asked', None) and session_rules.was_asked(user, session, cid):
        body['already_asked'] = True
    session_rules.remember_asked(user, session, cid)
    again = {k: v for k, v in (arguments or {}).items()
             if k not in ('op', '_confirmation_id')}
    body['next'] = {
        "1_ask": "Read back confirm_with_user (the target as the system resolved it, and the action), end with "
                 "'If this is right, please approve.' in the user's language, and wait for their answer. "
                 "Their request alone is not approval; it may have matched the wrong target.",
        "2_answer": "control(op='confirm', target='%s', decision='approve' or 'reject') - approving also "
                    "runs it; report its result and stop" % cid,
        "3_run": "only if that answer says it did not run yet: %s(op='%s', <same arguments>, "
                 "_confirmation_id='%s')" % (tool, (arguments or {}).get('op'), cid),
        "same_arguments": again,
    }
    body['message'] = (
        "Not run yet - it needs the user's approval. Follow 'next': read back what will happen and wait for "
        "their yes; after it, approve with control op=confirm at once (it also runs it) and do not ask again. "
        "Never approve on the user's behalf. "
        "Internal note: never quote, translate or narrate this or your own actions.")
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] \
        + list(out[1:])


_NOT_RUN = frozenset({'error', 'refused', 'rejected', 'expired'})
#: 안쪽 응답의 다음 단계 안내 칸 — 안쪽 도구 이름(지금 표면)으로 적혀 있다.
_HINT_KEYS = ('_more', 'hint', 'next_step', 'next_steps')
_INNER_TO_OP = {}
_INNER_PREFERRED = {'list_plots': 'find.plots', 'get_zone_sensor_summary': 'measure.latest'}


def _inner_to_op():
    """안쪽 도구 이름 → 'tool.op'(읽기 operation 이 먼저)."""
    import re
    if not _INNER_TO_OP:
        for o in sorted(_ops(), key=lambda x: x.tool not in READ_TOOLS):
            for name in o.inner_tools:
                _INNER_TO_OP.setdefault(name, '%s.%s' % (o.tool, o.op))
        # 한 안쪽 도구에 operation 이 여럿이면 명부 순서가 아니라 이 이름이 이긴다 — "남은 구획은 list_plots 로" 가
        # 개요(overview.crops)가 아니라 목록(find.plots, offset·query 가 있다)을 가리키게.
        _INNER_TO_OP.update(_INNER_PREFERRED)
        # 합쳐져 따로 안 부르는 안쪽 도구(get_device_list …)도 그 일을 맡은 op 로 — 응답 문구에 옛 이름이 남지 않게.
        from aot.tools.domain.contract import COVERED_ELSEWHERE
        for name, why in COVERED_ELSEWHERE.items():
            got = re.match(r'[a-z]+\.[a-z_]+', why)
            if got:
                _INNER_TO_OP.setdefault(name, got.group(0))
    return _INNER_TO_OP


def _domain_hints(body):
    """`_more` 같은 안내가 "use_tool: get_plot" 처럼 이 표면에 없는 길을 가리키면 도메인
    operation 이름으로 바꾼다(2026-10-14 웹 시험: 남은 구획을 이어 조회할 길이 옛 이름뿐)."""
    import re
    names = _inner_to_op()
    for key in _HINT_KEYS:
        text = body.get(key)
        if not isinstance(text, str) or not text:
            continue
        text = re.sub(r'\b(?:via )?use_tool:?\s*', '', text)
        body[key] = _domain_arg_words(re.sub(r'\b([a-z][a-z0-9_]+)\b',
                                             lambda m: names.get(m.group(1), m.group(1)), text))
    # 그 밖의 안내문(매뉴얼 결과 본문·_reading·see·how_to_proceed …)에 남은 옛 도구 이름도
    # 같은 이름으로(2026-10-28 점검: get_device_detail·knowledge_search 를 AI 가 못 불렀다).
    # 일반 문장의 낱말과 겹치지 않게 밑줄이 든 이름만 바꾼다.
    for k, v in list(body.items()):
        if k not in _HINT_KEYS and k not in _NO_RENAME and isinstance(v, (str, list, dict)):
            body[k] = _rename_tools(v, names)


#: 안쪽 도구의 안내문이 쓰는 인자 이름 → 이 표면의 이름(`time_range='7d'` → `period='7d'`). 안 바꾸면 안내대로
#: 부른 호출이 "does not take time_range" 로 거절된다(2026-11-03 시험 #1).
_ARG_WORDS = (('time_range', 'period'), ('sensor_type', 'measurement'), ('measurement_type', 'measurement'))


def _domain_arg_words(text):
    for old, new in _ARG_WORDS:
        text = text.replace(old + '=', new + '=')
    return text


#: 이름을 바꾸지 않는 칸 — 대상·호출 기록·행 목록은 자료라 그대로 둔다.
_NO_RENAME = frozenset({'target', 'read_as', 'read_for', 'results', 'plots', 'journals', 'notes'})
_TOOL_WORD = None


def _rename_tools(value, names, depth=0):
    """문자열·목록·사전 안의 문자열에서 밑줄 든 안쪽 도구 이름 → 'tool.op'."""
    import re
    global _TOOL_WORD
    if _TOOL_WORD is None:
        _TOOL_WORD = re.compile(r'\b([a-z][a-z0-9]*_[a-z0-9_]+)\b')
    if isinstance(value, str):
        if '_' not in value:
            return value
        return _domain_arg_words(_TOOL_WORD.sub(lambda m: names.get(m.group(1), m.group(1)), value))
    if depth > 6:
        return value
    if isinstance(value, list):
        return [_rename_tools(v, names, depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: _rename_tools(v, names, depth + 1) for k, v in value.items()}
    return value


_ID_KEYS = ('id', 'device_id', 'unique_id', 'output_id', 'input_id')


def _place_keys(resolved):
    """장소 대상(과 그 안의 장소)의 id 모음 — 시설은 도형 id 와 시설 id 두 가지로 불린다(둘 다 같은 시설)."""
    from aot.databases.models import GeoFacility
    ids = set()
    for t in resolved:
        ids.add(t['id'])
        ids.update(c['id'] for c in _descendants(t))
    if ids:
        for f in GeoFacility.query.filter(
                (GeoFacility.unique_id.in_(ids)) | (GeoFacility.shape_uuid.in_(ids))).all():
            ids.update((f.unique_id, f.shape_uuid))
    return ids


def _filter_place_rows(body, meta):
    """묶음 목록(`{종류: [행]}`)에서 `place_key` 칸이 장소 id 안에 드는 행만 남기고, 거른 뒤 쪽을 나눈다."""
    key, keep = meta.pop('place_key'), set(meta.pop('place_ids', ()) or ())
    page = meta.pop('page', None) or {}
    rows_by = body.get('functions')
    if not isinstance(rows_by, dict):
        return False
    total = sum(len(v) for v in rows_by.values() if isinstance(v, list))
    flat = [(g, r) for g, rows in rows_by.items() if isinstance(rows, list)
            for r in rows if str(r.get(key) or '') in keep]
    meta['not_tied_to_a_place'] = total - len(flat)
    start = int(page.get('offset') or 0)
    stop = start + int(page['limit']) if page.get('limit') else None
    shown = flat[start:stop]
    body['functions'] = {}
    for g, r in shown:
        body['functions'].setdefault(g, []).append(r)
    body['count'] = len(shown)
    if shown != flat:
        body['page'] = {"total": len(flat), "shown": len(shown), "offset": start,
                        **({"next_offset": start + len(shown)} if start + len(shown) < len(flat) else {})}
    else:
        body.pop('page', None)
    names = [r['name'] for _g, r in shown]
    dups = sorted({n for n in names if names.count(n) > 1})
    if not dups:
        body.pop('duplicate_names', None)
        body.pop('note', None)
    else:
        body['duplicate_names'] = dups
    meta['place_filter_note'] = (
        "Only functions tied to this place through their facility (environment coordinators) are listed. "
        "PID, conditional and trigger functions are not tied to a place, so they are not matched here "
        "(not_tied_to_a_place counts the rest); find.functions without target lists them all.")
    return True


def _filter_ids(out, meta):
    """목록 결과에서 그 장소 안의 장치 행만 남긴다(행의 id 칸으로)."""
    ids = set(meta.pop('ids', ()) or ())
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not isinstance(body, dict):
        return out
    if meta.get('place_key'):
        if _filter_place_rows(body, meta):
            for k in ('server_host', 'now', 'call_state'):
                body.pop(k, None)
            body.update({k: v for k, v in meta.items() if v is not None})
            return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])
        return out
    kept_any = False
    for key, rows in list(body.items()):
        if isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows) \
                and any(k in rows[0] for k in _ID_KEYS):
            kept = [r for r in rows if any(str(r.get(k) or '').split('::')[0] in ids
                                           for k in _ID_KEYS)]
            body[key] = kept
            if 'count' in body:
                body['count'] = len(kept)
            kept_any = True
    if not kept_any:
        # 거를 칸이 없는 목록 — 조용히 전체를 주면 거른 줄 안다(2026-11-04: find.functions 에 육묘장3 을 줘도 25개 전체).
        body['filter_not_applied'] = ("The place target could not be applied to this list (its rows carry no device "
                                      "or place link), so everything is listed.")
        return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])
    for k in ('server_host', 'now', 'call_state'):
        body.pop(k, None)
    body.update({k: v for k, v in meta.items() if v is not None})
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


#: 기간을 거르기 전에 안쪽 도구에서 읽는 행 수 — 사용자의 limit 는 거른 뒤에 적용한다.
_PERIOD_SCAN = 500


def _filter_period(out, o, period_text, limit=None):
    """안쪽 도구가 기간을 못 받을 때 결과 행을 그 기간으로 거른 뒤 limit 로 자른다(명부의 period_field)."""
    from aot.tools.domain import vocab
    rng = vocab.period(period_text, today=today_at(FARM))
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    rows = body.get(o.rows_key) if isinstance(body, dict) else None
    if not isinstance(rows, list) or rng is None:
        return out
    def _where(r):
        # 행이 장치·장소 id 를 들고 있으면 그곳 시계로, 없으면 농장 시계
        for k in _ID_KEYS:
            v = str(r.get(k) or '').split('::')[0]
            if v:
                return v
        return FARM

    kept = [r for r in rows if isinstance(r, dict)
            and vocab.in_period(r.get(o.period_field), rng, _where(r))]
    kept.sort(key=lambda r: str(r.get(o.period_field) or ''))
    try:
        cap = max(1, int(limit)) if limit not in (None, '') else 20
    except (TypeError, ValueError):
        cap = 20
    # 안쪽 도구의 '앞 N건' 안내는 거르기 전 얘기라 틀리다 — 거른 결과 기준으로 다시 쓴다.
    body.pop('truncated', None)
    body.pop('note', None)
    if len(kept) > cap:
        kept = kept[:cap]
        body['truncated'] = True
        body['note'] = "Only the first %d in this period are shown (earliest first); raise limit for more." % cap
    elif body.get('truncated') is None and len(rows) >= _PERIOD_SCAN:
        body['truncated'] = True
        body['note'] = "Only the %d most recent entries were searched; narrow with query or target." % _PERIOD_SCAN
    body[o.rows_key] = kept
    if 'count' in body:
        body['count'] = len(kept)
    body['period'] = {"from": rng[0].isoformat(), "to": rng[1].isoformat()}
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False))] + list(out[1:])


def snapshot_changed(params):
    """승인 실행 직전: 스냅샷의 대상이 바뀌었으면 이유, 아니면 None."""
    snap = (params or {}).get(SNAPSHOT_KEY)
    if not snap:
        return None
    for s in (snap if isinstance(snap, list) else [snap]):
        why = targets.changed(s)
        if why:
            return why
    return None


__all__ = ['plan', 'run', 'snapshot_changed', 'SNAPSHOT_KEY', 'READ_TOOLS', 'WRITE_TOOLS']

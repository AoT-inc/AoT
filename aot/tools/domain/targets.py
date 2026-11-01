# -*- coding: utf-8 -*-
"""대상 해석 — 설계 docs/design/mcp-domain-surface.md §2.

모든 도메인 operation 의 `target` 은 여기서 **한 번** 풀린다. 안쪽 도구에는 이름이
아니라 해석된 id 가 넘어가므로, 안쪽 도구가 이름을 다시 해석하지 않는다.

규칙(§2-2):
1. id 정확일치(어느 종류든). 그 다음 사용자가 등록한 별칭(`TargetAlias`) — 별칭은 사용자가
   그 이름으로 그것을 가리킨다고 정한 것이라 같은 이름의 다른 대상보다 먼저다.
2. 이름 정확일치 — **종류를 가리지 않고** 모은다. 정확히 맞는 것이 하나면 그것,
   여럿이면 고르지 않고 되묻는다. 정확일치는 부분일치보다 언제나 이긴다
   ("김제" 는 지도 '김제' 이지 기상 장치 '기상청: 김제' 가 아니다).
3. 정확일치가 없고 물음이 두 낱말 이상이면 낱말 대조(§2-1 아래) — 순서·구두점·
   조사가 달라도, 지역 낱말이 후보가 놓인 지도 이름이어도 같은 것으로 본다.
4. 그래도 없으면 지금 리졸버(`_resolve_explain` — 표기 정규화·한정어·부분
   일치·작물 이름)와 구획 이름 정규화로 넘어간다.
5. 끝내 없으면 이름 열쇠가 한 글자만 다른 것(`similar`)을 고르지 않고 함께 돌려준다 —
   음성 인식이 바꾼 표기('선포장' ↔ 1포장·3포장)를 AI 가 추측하지 않고 되묻게.

대상 종류와 operation 의 `accepts` 대조는 여기서 하지 않는다 — 해석은 종류를
가리지 않고, 대조는 dispatch 가 한다(§2-3).
"""
import logging
import re
import time

logger = logging.getLogger(__name__)

_MAP_SUFFIXES = (' 지도', '지도', ' map', ' Map')


class _Refused(Exception):
    """대상은 있지만 AI 대상이 아니다('AI 판단에 포함' 꺼짐) — 오류를 그대로 낸다."""

    def __init__(self, error):
        super().__init__(error.get('error'))
        self.error = error


def _svc():
    from aot.tools.aot_data_tool_service import AoTDataToolService
    return AoTDataToolService


def _index():
    from aot.aot_flask.geo.device_membership import PlaceIndex
    return PlaceIndex()


# ── 결과 모양(§2-4) ─────────────────────────────────────────────────────────

def _target(kind, id_, name, path=None, map_name=None, matched='exact'):
    return {'kind': kind, 'id': id_, 'name': name, 'path': path or name,
            'map': map_name, 'matched': matched}


def _map_name_of(geo_id):
    if not geo_id:
        return None
    from aot.databases.models import GeoMap
    m = GeoMap.query.filter(GeoMap.unique_id == geo_id).first()
    return m.name if m is not None else None


def _of_map(row):
    return _target('map', row.unique_id, row.name, row.name, row.name)


def _shape_kind(shape):
    t = (shape.type or '').lower()
    if t in ('site', 'zone', 'facility'):
        return t
    return None


def _of_shape(shape, idx=None, matched='exact'):
    kind = _shape_kind(shape)
    if kind is None:
        return None
    idx = idx or _index()
    from aot.aot_flask.geo.device_membership import place_label
    name = place_label(shape) or _svc()._shape_display_name(shape)
    map_name = _map_name_of(shape.geo_id)
    path = idx.path(shape)
    if map_name and path and not path.startswith(map_name):
        path = '%s > %s' % (map_name, path)
    return _target(kind, shape.unique_id, name, path, map_name, matched)


def _of_plot(row, idx=None, matched='exact'):
    idx = idx or _index()
    name = row.name or row.subject
    try:
        base = idx.plot_path(row)
    except Exception:                                       # noqa: BLE001
        base = ''
    map_name = _map_name_of(row.geo_id)
    path = ' > '.join(p for p in (map_name, base, name) if p)
    return _target('plot', row.unique_id, name, path, map_name, matched)


def _of_device(row, kind, matched='exact'):
    """입력·출력·함수/복합장치 → 대상. 장소 경로는 장치가 놓인 곳, 맨 앞은 지도 이름
    (같은 이름의 장소가 여러 지도에 있을 때 어느 것인지 — 2026-10-14 웹 시험)."""
    path, map_name = row.name, None
    try:
        from aot.aot_flask.geo.device_binding import shapes_for_devices
        shapes = (shapes_for_devices([row.unique_id]) or {}).get(row.unique_id) or []
        map_name = next((m for m in (_map_name_of(s.geo_id) for s in shapes) if m), None)
        paths = _index().device_paths([row.unique_id]).get(row.unique_id) or []
        if paths:
            path = '%s > %s' % (paths[0], row.name)
        if map_name and not path.startswith(map_name):
            path = '%s > %s' % (map_name, path)
    except Exception:                                       # noqa: BLE001
        pass
    kind = {'input': 'input', 'output': 'output'}.get(kind, kind)
    if kind not in ('input', 'output'):
        kind = 'device' if kind == 'device' else 'function'
    return _target(kind, row.unique_id, row.name, path, map_name, matched)


def _function_models():
    """함수가 사는 네 테이블 — 공용 함수 해석기(`function_resolver`)와 같은 목록."""
    from aot.services.resolvers.function_resolver import _default_models
    return list(_default_models())


def _of_function(row):
    return _target('function', row.unique_id, row.name, row.name)


def _of_dashboard(row):
    return _target('dashboard', row.unique_id, row.name, 'dashboard > %s' % row.name)


def _of_widget(row, dash_names=None):
    """위젯 → 대상. 경로에 놓인 대시보드 이름(`Widget.tab_id` 가 대시보드 id 다)."""
    if dash_names is None:
        from aot.databases.models import Dashboard
        d = Dashboard.query.filter(Dashboard.unique_id == row.tab_id).first()
        dash = d.name if d is not None else None
    else:
        dash = dash_names.get(row.tab_id)
    name = row.name or row.graph_type or row.unique_id[:8]
    path = 'dashboard > %s > %s' % (dash or '?', name)
    return _target('widget', row.unique_id, name, path)


def _of_tab(row):
    return _target('tab', row.unique_id, row.name,
                   '%s tabs > %s' % (row.page_type or '?', row.name))


# ── 1. id ───────────────────────────────────────────────────────────────────

def _by_id(token):
    from aot.databases.models import GeoFacility, GeoMap, GeoPlot, GeoShape
    row = GeoMap.query.filter(GeoMap.unique_id == token).first()
    if row is not None:
        return _of_map(row)
    shape = GeoShape.query.filter(GeoShape.unique_id == token).first()
    if shape is not None:
        t = _of_shape(shape)
        if t is not None:
            return t
    fac = GeoFacility.query.filter(GeoFacility.unique_id == token).first()
    if fac is not None and fac.shape_uuid:
        shape = GeoShape.query.filter(GeoShape.unique_id == fac.shape_uuid).first()
        if shape is not None:
            return _of_shape(shape)
    plot = GeoPlot.query.filter(GeoPlot.unique_id == token).first()
    if plot is not None:
        return _of_plot(plot)
    from aot.databases.models import Dashboard, Tab
    row = Dashboard.query.filter(Dashboard.unique_id == token).first()
    if row is not None:
        return _of_dashboard(row)
    row = Tab.query.filter(Tab.unique_id == token).first()
    if row is not None:
        return _of_tab(row)
    from aot.databases.models import Widget
    row = Widget.query.filter(Widget.unique_id == token).first()
    if row is not None:
        return _of_widget(row)
    # 함수(조건·트리거·PID) — 시퀀스·트리거 함수는 CustomController 가 아니다
    # (2026-10-14 벤치: '3포장 밸브제어 v2' 를 이름으로도 id 로도 못 찾았다).
    for model, _label in _function_models():
        if model.__name__ == 'CustomController':
            continue
        row = model.query.filter(model.unique_id == token).first()
        if row is not None:
            return _of_function(row)
    from aot.databases.models import CustomController, Input, Output
    if any(m.query.filter(m.unique_id == token).first() is not None
           for m in (Input, Output, CustomController)):
        row, kind, err = _svc()._resolve_device_target(token)
        if row is None:
            raise _Refused(err or {"error": "Device not available: %s" % token})
        return _of_device(row, kind)
    return None


# ── 2. 이름 정확일치(종류 무관) ─────────────────────────────────────────────

def _strip_map_suffix(text):
    for tail in _MAP_SUFFIXES:
        if text.endswith(tail) and len(text) > len(tail):
            return text[:-len(tail)].strip(), True
    return text, False


def _screens(text, accepts):
    """위젯·대시보드·탭 이름 정확일치 — 그 종류를 받는 operation 에서만 찾는다(화면 이동).
    늘 찾으면 지도 '영양' 과 대시보드 '영양' 이 모든 읽기에서 모호해진다."""
    from aot.databases.models import Dashboard, Tab, Widget
    low = text.strip().lower()
    out = []
    if 'widget' in accepts:
        # 이름, 또는 화면이 보이는 짧은 id('#fe10a462') — 앞 8자 이상이 하나에만 맞을 때.
        short = low.lstrip('#')
        dash = {d.unique_id: d.name for d in Dashboard.query.all()}
        rows = Widget.query.all()
        hit = [r for r in rows if (r.name or '').strip().lower() == low]
        if not hit and len(short) >= 8 and all(c in '0123456789abcdef-' for c in short):
            hit = [r for r in rows if r.unique_id.lower().startswith(short)]
        out.extend(_of_widget(r, dash) for r in hit)
    if 'dashboard' in accepts:
        out.extend(_of_dashboard(r) for r in Dashboard.query.all()
                   if (r.name or '').strip().lower() == low)
    if 'tab' in accepts:
        out.extend(_of_tab(r) for r in Tab.query.all()
                   if (r.name or '').strip().lower() == low)
    return out


def _screen_by_path(text, accepts):
    """후보로 보여 준 화면 경로('dashboard > 영양', 'input tabs > 영양')를 입력으로도 받는다
    (표시 = 입력). 마지막 조각 이름으로 화면을 찾아 그 경로가 같은 것만 남긴다."""
    if _PATH_MARK not in text or not accepts:
        return []
    norm = lambda t: ' > '.join(' '.join(p.split()).lower()
                                for p in t.split(_PATH_MARK))
    last = text.split(_PATH_MARK)[-1].strip()
    want = norm(text)
    return [t for t in _screens(last, accepts) if norm(t['path']) == want]


def _exact_candidates(text, accepts=()):
    from aot.aot_flask.geo import shape_index
    from aot.databases.models import GeoMap, GeoPlot
    low = text.lower()
    found = _screens(text, accepts)
    base, said_map = _strip_map_suffix(text)
    for m in GeoMap.query.all():
        if (m.name or '').strip().lower() == base.lower():
            found.append(_of_map(m))
    if said_map:
        return found                    # "김제 지도" 는 지도만 본다
    idx = None
    exact = [(s, n) for (s, n, nl) in shape_index.named_shapes() if nl == low
             and _shape_kind(s) is not None]
    if exact:
        idx = _index()
        S = _svc()
        # 같은 이름이 안팎으로 겹친 도형은 한 곳이다(바깥이 대표) — 지금 규칙.
        for place in S._group_places(exact):
            t = _of_shape(place['rep'][0], idx)
            if t is not None:
                found.append(t)
    # 구획 라벨은 이름이 없으면 작물(subject)이다 — 화면과 같은 규칙('콩 4구').
    plots = [p for p in GeoPlot.query.filter(GeoPlot.ended_on.is_(None)).all()
             if (p.name or p.subject or '').strip().lower() == low]
    if plots:
        idx = idx or _index()
        found.extend(_of_plot(p, idx) for p in plots)
    # 장치·함수 — 지금 장치 해석(정확일치만, 'AI 판단에 포함' 을 끈 것은 뺀다).
    from aot.databases.models import CustomController, Input, Output
    S = _svc()
    row, kind, err = S._resolve_device_target(text)
    if row is not None:
        found.append(_of_device(row, kind))
    elif err and err.get('needs_disambiguation'):
        for c in err.get('candidates') or []:
            for model in (Input, Output, CustomController):
                r = model.query.filter(model.unique_id == c.get('id')).first()
                if r is not None:
                    found.append(_of_device(r, c.get('kind') or 'device'))
                    break
    elif err and err.get('reason_code') and not found:
        raise _Refused(err)
    # 함수 이름 정확일치 — 네 테이블을 함께(공용 해석기, 부분일치 없이).
    from aot.services.resolvers.function_resolver import resolve_function
    fm = resolve_function(text)
    if fm.row is not None:
        found.append(_of_function(fm.row))
    elif fm.candidates:
        for c in fm.candidates:
            for model, _label in _function_models():
                r = model.query.filter(model.unique_id == c.get('id')).first()
                if r is not None:
                    found.append(_of_function(r))
                    break
    seen, out = set(), []
    for t in found:
        if t['id'] not in seen:
            seen.add(t['id'])
            out.append(t)
    return out


# ── 2-1. 낱말 대조 ──────────────────────────────────────────────────────────
#
# 사람은 이름을 그대로 부르지 않는다 — '밸브: 김제' 를 "김제 밸브"·"김제의밸브" 로,
# '밸브 1: 김제' 를 "김제 1번 밸브" 로, 지도 '김제' 의 대지들을 "김제 농장" 으로 부른다.
# 같은 이름에 숫자·지역이 붙고 다른 지도에 놓인 것이 많아서(2026-10-14 사용자) 부분
# 일치로 풀면 엉뚱한 것을 집는다 — 옛 표면은 '김제' 에 이름에 김제가 든 장치 둘을 내밀었다.
#
# **문법을 풀지 않는다.** 띄어쓰기·조사로 낱말을 가르면 그 언어에만 맞는다(일본어·중국어는
# 띄어 쓰지 않는다 — 2026-10-14 사용자 지적). 대신 후보마다 물음 안에서 그 후보의
# 이름 낱말과 놓인 자리(지도·장소)의 이름이 **나타나는 곳**을 찾아 지우고, 남은 조각이
#   - 이어 주는 말·목적 말(vocab.GLUE_WORDS·FILLER_WORDS — '의'·'の'·'的'·'in'·'요약')
#   - 종류 낱말(vocab.KIND_WORDS — '지도'·'施設'·'device')
#   - 측정 낱말('온도' — 무엇을 잴지는 `measurement` 인자가 맡는다)
#   - 이름 낱말의 일부(두 글자 이상: '밸브' ↔ '관수밸브', '기상' ↔ '기상청')
# 로만 이루어질 때 그 후보로 본다. 언어를 늘리는 일은 vocab 표에 낱말을 더하는 것이다.
# 이름으로 설명되는 조각이 적어도 하나 있어야 한다(자리만 맞는 것은 그 안의 전부다).
#
# 언어와 무관한 길은 경로다 — `target` 에 "김제 > 밸브" 를 실으면 '>' 앞은 자리, 뒤는
# 이름이다. 응답의 path 와 같은 표기라 모델이 받은 경로를 그대로 되넘길 수 있다.
#
# 이름의 낱말이 물음에 **모두** 있는 후보(빽빽한 것)가 있으면 그것들만 본다 —
# "김제 밸브" 의 답은 '밸브: 김제' 이지 숫자가 더 붙은 '밸브 1: 김제' 가 아니다.
# 그 다음은 종류가 바로 맞는 것 — "영양 시설" 은 이름이 꼭 맞는 그릇(지도 영양, 그 안의
# 시설)이 되고, 이름에 '영양' 이 든 것 하나가 되지 않는다.

# '_' 도 낱말 구분이다 — 장치 이름이 '온습도_7' 처럼 붙어 있다(2026-10-14 웹 시험 B3).
# '-' 는 아니다: '3-1' 과 '1-3' 이 같은 낱말 둘이 되면 안 된다.
_SPLIT = re.compile(r"[\s:：,，.·/()\[\]{}<>\"'`|~、。・_]+")
_SEP_CHAR = re.compile(r"[\s:：,，.·/()\[\]{}<>\"'`|~、。・_]")
_CONTAINERS = frozenset({'map', 'site', 'zone', 'facility'})
_DEVICE_KINDS = frozenset({'input', 'output', 'device', 'function'})
_PATH_MARK = '>'


def _norm_token(tok):
    t = tok.lower()
    if len(t) > 1 and t.endswith('번') and t[:-1].isdigit():
        return t[:-1]                                    # '1번' → '1'
    return t


def name_tokens(text):
    """이름 → 낱말 목록(소문자). 구두점·공백으로 가르고 '1번' 은 '1' 로."""
    return [_norm_token(t) for t in _SPLIT.split(str(text or '')) if t]


def _ascii_word(w):
    return w.isascii() and any(c.isalnum() for c in w)


def _find(q, word):
    """q 안에서 word 가 나타나는 [시작, 끝) 들. 숫자는 다른 숫자에 붙은 곳을 빼고
    ('1' 이 '10' 안에서 맞지 않게), 영문 낱말은 낱말 경계에서만."""
    out, i = [], q.find(word) if word else -1
    while i >= 0:
        j = i + len(word)
        before = q[i - 1] if i > 0 else ''
        after = q[j] if j < len(q) else ''
        ok = True
        if word[0].isdigit() and before.isdigit():
            ok = False
        if word[-1].isdigit() and after.isdigit():
            ok = False
        if _ascii_word(word) and ((before.isascii() and before.isalnum())
                                  or (after.isascii() and after.isalnum())):
            ok = False
        if ok:
            out.append((i, j))
        i = q.find(word, i + 1)
    return out


def _runs(q, covered):
    """덮이지 않은 조각들 — 구분 문자에서 끊는다."""
    out, cur = [], []
    for ch, c in zip(q, covered):
        if c or _SEP_CHAR.match(ch):
            if cur:
                out.append(''.join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        out.append(''.join(cur))
    return out


class _Words(object):
    """대조에 쓰는 언어 낱말(vocab) — 물음 하나에 한 번 만든다."""

    def __init__(self):
        from aot.tools.domain import vocab
        self.glue = {w.lower() for w in vocab.GLUE_WORDS | vocab.FILLER_WORDS}
        self.kinds = vocab.kind_words()
        self.measures = vocab.measurement_words()
        self.longest = max(len(w) for w in (self.glue | set(self.kinds) | self.measures))


def _segment(run, kind, names, words):
    """남은 조각 하나를 말들로 나눌 수 있는가 → None | (이름 일부로 맞음, 그릇으로 물러섬, 조각 수)."""
    n = len(run)
    # reach[i] = 앞 i 글자까지 나눈 길 하나 — (이름 일부 맞음, 그릇 물러섬, 조각 수)
    reach = {0: (False, False, 0)}
    for i in range(n):
        if i not in reach:
            continue
        part, soft, count = reach[i]
        for j in range(i + 1, n + 1):
            piece = run[i:j]
            whole = (i == 0 and j == n)
            got = None
            if _ascii_word(piece) and not whole:
                # 영문 낱말은 통째일 때만 말로 본다('in' 이 'gimjein' 의 끝이 되지 않게).
                pass
            elif piece in words.glue or piece in words.measures:
                got = (part, soft)
            elif piece in words.kinds:
                kinds = words.kinds[piece]
                if kind in kinds:
                    got = (part, soft)
                elif kind in _CONTAINERS:
                    got = (part, True)
            if got is None and len(piece) >= 2 and not piece.isdigit() \
                    and any(piece in nm for nm in names):
                got = (True, soft)
            if got is not None:
                cand = (got[0], got[1], count + 1)
                old = reach.get(j)
                # 그릇으로 덜 물러선 길, 이름 일부가 맞은 길을 고른다.
                if old is None or (cand[1], not cand[0]) < (old[1], not old[0]):
                    reach[j] = cand
    return reach.get(n)


def _cover(q, kind, names, where, words):
    """후보 하나가 물음 q 를 남김없이 설명하는가 →
    None | (빽빽한가, 그릇으로 물러섰나, 조각 수)."""
    covered = [False] * len(q)
    found, by_name, pieces = set(), False, 0
    for group, is_name in ((names, True), (where, False)):
        for w in sorted(group, key=len, reverse=True):
            spans = _find(q, w)
            if not spans:
                continue
            pieces += 1
            if is_name:
                found.add(w)
                by_name = True
            for a, b in spans:
                for k in range(a, b):
                    covered[k] = True
    soft = False
    for run in _runs(q, covered):
        seg = _segment(run, kind, names, words)
        if seg is None:
            return None
        by_name = by_name or seg[0]
        soft = soft or seg[1]
        pieces += seg[2]
    if not by_name:
        return None
    return set(names) <= found, soft, pieces


def _touches(q, grams, names):
    for nm in names:
        if nm.isdigit():
            continue
        if nm in q or any(nm[i:i + 2] in grams for i in range(len(nm) - 1)):
            return True
    return False


def _token_pool(q):
    """이름이 물음과 닿는 것들 — [(종류, 이름, 행 또는 도형)]."""
    from aot.aot_flask.geo import shape_index
    from aot.databases.models import (CustomController, GeoMap, GeoPlot, Input,
                                      Output)
    from aot.services.resolvers.device_resolver import ai_excluded
    grams = {q[i:i + 2] for i in range(len(q) - 1)}

    def touches(name):
        return _touches(q, grams, name_tokens(name))

    pool = []
    for m in GeoMap.query.all():
        if m.name and touches(m.name):
            pool.append(('map', m.name, m))
    for s, n, _nl in shape_index.named_shapes():
        kind = _shape_kind(s)
        if kind is not None and touches(n):
            pool.append((kind, n, s))
    for p in GeoPlot.query.filter(GeoPlot.ended_on.is_(None)).all():
        label = p.name or p.subject
        if label and touches(label):
            pool.append(('plot', label, p))
    # 'AI 판단에 포함' 을 끈 장치도 대조는 한다 — 그것만 맞으면 "없다" 가 아니라
    # "꺼져 있다" 고 말해야 한다(후보로 내밀지는 않는다).
    for model, kind in ((Input, 'input'), (Output, 'output')):
        for r in model.query.all():
            if r.name and touches(r.name):
                pool.append(('excluded' if ai_excluded(r) else kind, r.name, r))
    for r in CustomController.query.all():
        if r.name and touches(r.name):
            pool.append(('device', r.name, r))
    for model, _label in _function_models():
        if model.__name__ == 'CustomController':
            continue
        for r in model.query.all():
            if r.name and touches(r.name):
                pool.append(('function', r.name, r))
    return pool


def _where(pool, idx):
    """후보마다 놓인 자리 — (낱말 집합, 이름 목록). 지도 이름과 장소 경로에서."""
    from aot.aot_flask.geo.device_binding import shapes_for_devices
    from aot.aot_flask.geo.device_membership import PATH_SEP
    map_names = {}

    def map_of(geo_id):
        if geo_id not in map_names:
            map_names[geo_id] = _map_name_of(geo_id) or ''
        return map_names[geo_id]

    dev_ids = [obj.unique_id for kind, _n, obj in pool
               if kind in ('input', 'output', 'device', 'excluded')]
    dev_shapes = shapes_for_devices(dev_ids) if dev_ids else {}
    dev_paths = idx.device_paths(dev_ids) if dev_ids else {}
    out = []
    for kind, name, obj in pool:
        labels = []
        if kind in ('site', 'zone', 'facility'):
            labels.append(map_of(obj.geo_id))
            labels.extend(idx.path(obj).split(PATH_SEP))
        elif kind == 'plot':
            labels.append(map_of(obj.geo_id))
            try:
                labels.extend(idx.plot_path(obj).split(PATH_SEP))
            except Exception:                               # noqa: BLE001
                pass
        elif kind not in ('map', 'function'):
            for s in dev_shapes.get(obj.unique_id) or ():
                labels.append(map_of(s.geo_id))
            for p in dev_paths.get(obj.unique_id) or ():
                labels.extend(p.split(PATH_SEP))
        labels = [l.strip() for l in labels if l and l.strip() and l.strip() != name]
        toks = {t for l in labels for t in name_tokens(l)} - set(name_tokens(name))
        out.append((toks, labels))
    return out


def _qualifiers_hold(quals, labels, toks):
    """경로의 '>' 앞 부분이 모두 그 후보가 놓인 자리인가."""
    from aot.tools.name_key import name_key
    keys = {name_key(l) for l in labels}
    for qual in quals:
        if name_key(qual) in keys:
            continue
        if set(name_tokens(qual)) <= toks:
            continue
        return False
    return True


def _excluded_error(rows):
    from aot.services.resolvers.device_resolver import AI_EXCLUDED, ai_excluded_error
    names = [r.name for r in rows[:5]]
    msg = ai_excluded_error(rows[0])
    if len(rows) > 1:
        msg = ("%d devices match and all are excluded from AI (%s): their 'Include in AI "
               "judgment' setting is off. A person can turn it on in AoT."
               % (len(rows), ", ".join(names)))
    return {"error": msg, "reason_code": AI_EXCLUDED, "excluded": names}


def _token_candidates(text):
    """낱말 대조 결과 → (후보 목록, 맞았지만 'AI 판단에 포함' 을 끈 장치들).

    후보가 비면 이 단계는 답이 없다. 한 덩이 물음에서 꺼진 장치만 맞았으면 resolve 가
    끝내 못 찾을 때 "없다" 대신 그것을 말한다('기상청' → 기상청: 김제·나주 둘 다 꺼짐,
    2026-10-14 웹 시험).
    """
    quals = []
    if _PATH_MARK in text:
        parts = [p.strip() for p in text.split(_PATH_MARK) if p.strip()]
        quals = parts[:-1]
    q = ' '.join(p.strip() for p in text.split(_PATH_MARK)).lower()
    if not q.strip():
        return [], []
    # 한 덩이짜리 물음('3포')은 두 조각 이상으로 설명될 때만 이 단계의 답이다 — 한 조각
    # 이면 이름 그 자체이고, 그것은 정확일치·지금 리졸버·앞부분 일치가 맡는다.
    one_word = not quals and len(name_tokens(q)) < 2
    pool = _token_pool(q)
    if not pool:
        return [], []
    idx = _index()
    words = _Words()
    hits, hidden = [], []
    for (kind, name, obj), (toks, labels) in zip(pool, _where(pool, idx)):
        if quals and not _qualifiers_hold(quals, labels, toks):
            continue
        got = _cover(q, 'input' if kind == 'excluded' else kind,
                     name_tokens(name), toks, words)
        if got is None:
            continue
        if kind == 'excluded':
            hidden.append(obj)
            continue
        if one_word and got[2] < 2:
            continue
        hits.append((got[1], not got[0], kind, name, obj))
    if not hits:
        if hidden and not one_word:
            raise _Refused(_excluded_error(hidden))
        return [], hidden
    best = min((loose, soft) for soft, loose, *_rest in hits)
    hits = [h for h in hits if (h[1], h[0]) == best]
    # 같은 이름이 안팎으로 겹친 도형은 한 곳이다(바깥이 대표) — 정확일치와 같은 규칙.
    shapes = [(obj, name) for _s, _l, kind, name, obj in hits
              if kind in ('site', 'zone', 'facility')]
    out = []
    if shapes:
        for place in _svc()._group_places(shapes):
            t = _of_shape(place['rep'][0], idx)
            if t is not None:
                out.append(t)
    for _s, _l, kind, name, obj in hits:
        if kind == 'map':
            out.append(_of_map(obj))
        elif kind == 'plot':
            out.append(_of_plot(obj, idx))
        elif kind == 'function':
            out.append(_of_function(obj))
        elif kind in ('input', 'output', 'device'):
            out.append(_of_device(obj, kind))
    seen, uniq = set(), []
    for t in out:
        if t['id'] not in seen:
            seen.add(t['id'])
            t['matched'] = 'path' if quals else 'tokens'
            uniq.append(t)
    return uniq[:12], []


# ── 3. 그 밖(지금 리졸버) ───────────────────────────────────────────────────

def _fallback(text):
    """(대상, None) | (None, 후보 목록) | (None, None)."""
    S = _svc()
    detail = S._resolve_explain(text)
    tid, ttype, name, _lat, _lng = detail['result']
    rule = (detail.get('matched') or {}).get('rule') or 'loose'
    if ttype == 'ambiguous':
        cands = S._public_places(S._describe_places(
            detail.get('places') or [], detail.get('devices') or [],
            detail.get('plots') or ()))
        return None, _as_targets(cands)
    if tid:
        t = _by_id(tid)
        if t is not None:
            t['matched'] = rule
            return t, None
    # 구획 이름의 표기만 다른 것('콩4구' ↔ '콩 4구').
    from aot.databases.models import GeoPlot
    from aot.tools.name_key import name_key
    key = name_key(text)
    if key:
        hits = [p for p in GeoPlot.query.filter(GeoPlot.ended_on.is_(None)).all()
                if (p.name or p.subject) and name_key(p.name or p.subject) == key]
        if len(hits) == 1:
            return _of_plot(hits[0], matched='normalized'), None
        if len(hits) > 1:
            return None, [_of_plot(p, matched='normalized') for p in hits]
    return None, None


def _as_targets(cands):
    """지금 리졸버의 후보(name·type·where·target_id) → 틀의 후보 모양(§2-4).

    id 로 다시 풀어 종류·경로를 틀의 규칙으로 채우고, 'AI 판단에 포함' 을 끈 장치는
    뺀다 — 옛 리졸버는 그것도 후보로 내밀었다(2026-10-14 웹 시험: '기상청').
    """
    out = []
    for c in cands or ():
        tid = c.get('target_id') or c.get('id')
        t = None
        if tid:
            try:
                t = _by_id(str(tid))
            except _Refused:
                continue                     # AI 대상이 아닌 장치 — 후보가 아니다
        if t is None:
            t = _target(c.get('type') or c.get('kind'), tid, c.get('name'),
                        c.get('where') or c.get('name'), None, 'loose')
        t['matched'] = 'loose'
        out.append(t)
    return out


def _prefix_candidates(text):
    """마지막 단계 — 이름이 이것으로 **시작하는** 장소·지도('황산공원' → 코스 넷).
    하나면 그것, 여럿이면 고르지 않는다."""
    from aot.aot_flask.geo import shape_index
    from aot.databases.models import GeoMap
    low = text.lower()
    if len(low) < 2:
        return []
    out = []
    for m in GeoMap.query.all():
        if (m.name or '').strip().lower().startswith(low):
            out.append(_of_map(m))
    idx = None
    for s, n, nl in shape_index.named_shapes():
        if nl.startswith(low) and _shape_kind(s) is not None:
            idx = idx or _index()
            t = _of_shape(s, idx, matched='prefix')
            if t is not None:
                out.append(t)
    seen, uniq = set(), []
    for t in out:
        if t['id'] not in seen:
            seen.add(t['id'])
            uniq.append(t)
    return uniq[:12]


# ── 1-1. 별칭 ───────────────────────────────────────────────────────────────

_SCREEN_KINDS = frozenset({'widget', 'dashboard', 'tab'})


def _alias_rows(match):
    """별칭 행들 — 표가 아직 없으면(마이그레이션 전) 빈 목록."""
    from aot.databases.models import TargetAlias
    try:
        return [r for r in TargetAlias.query.all() if match(r.alias_key or '')]
    except Exception:                                       # noqa: BLE001
        logger.debug('[domain] 별칭 표를 읽지 못함', exc_info=True)
        return []


def _alias_target(row, accepts, matched):
    """별칭 행 → 대상. 화면 종류(위젯·대시보드·탭)는 그 종류를 받는 operation 에서만 —
    이름과 같은 규칙(`_screens`). accepts 가 비면(find.resolve) 가리지 않는다."""
    if accepts and row.target_kind in _SCREEN_KINDS and row.target_kind not in accepts:
        return None
    try:
        t = _by_id(row.target_id)
    except _Refused:
        return None                          # 'AI 판단에 포함' 을 끈 장치 — 이름 단계가 말한다
    if t is None:
        return None                          # 대상이 지워졌다
    t['matched'] = matched
    t['alias'] = row.alias
    return t


def _alias_candidates(text, accepts=()):
    from aot.tools.name_key import name_key
    key = name_key(text)
    if not key:
        return []
    out, seen = [], set()
    for r in _alias_rows(lambda k: k == key):
        t = _alias_target(r, accepts, 'alias')
        if t is not None and t['id'] not in seen:
            seen.add(t['id'])
            out.append(t)
    return out


# ── 4. 비슷한 이름(되묻기용) ─────────────────────────────────────────────────

def _one_edit(a, b):
    """두 열쇠가 글자 하나만 다른가(바꿈·더함·뺌)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def similar_names(text, accepts=(), limit=5):
    """이름 열쇠가 글자 하나만 다른 대상들 — 고르지 않는다. 세 글자 미만은 보지 않는다
    (두 글자 이름은 한 글자 차이인 것이 너무 많다). 별칭도 함께 본다."""
    from aot.aot_flask.geo import shape_index
    from aot.databases.models import (CustomController, GeoMap, GeoPlot, Input,
                                      Output)
    from aot.services.resolvers.device_resolver import ai_excluded
    from aot.tools.name_key import name_key
    key = name_key(text)
    if len(key) < 3:
        return []

    def near(name):
        return bool(name) and _one_edit(name_key(name), key)

    out = []
    idx = None
    for m in GeoMap.query.all():
        if near(m.name):
            out.append(_of_map(m))
    for s, n, _nl in shape_index.named_shapes():
        if _shape_kind(s) is not None and near(n):
            idx = idx or _index()
            t = _of_shape(s, idx)
            if t is not None:
                out.append(t)
    for p in GeoPlot.query.filter(GeoPlot.ended_on.is_(None)).all():
        if near(p.name or p.subject):
            idx = idx or _index()
            out.append(_of_plot(p, idx))
    for model, kind in ((Input, 'input'), (Output, 'output'), (CustomController, 'device')):
        for r in model.query.all():
            if near(r.name) and not (kind != 'device' and ai_excluded(r)):
                out.append(_of_device(r, kind))
    for model, _label in _function_models():
        if model.__name__ == 'CustomController':
            continue
        for r in model.query.all():
            if near(r.name):
                out.append(_of_function(r))
    if accepts and _SCREEN_KINDS & set(accepts):
        from aot.databases.models import Dashboard, Tab, Widget
        dash = {d.unique_id: d.name for d in Dashboard.query.all()}
        if 'widget' in accepts:
            out.extend(_of_widget(r, dash) for r in Widget.query.all() if near(r.name))
        if 'dashboard' in accepts:
            out.extend(_of_dashboard(r) for r in Dashboard.query.all() if near(r.name))
        if 'tab' in accepts:
            out.extend(_of_tab(r) for r in Tab.query.all() if near(r.name))
    for r in _alias_rows(lambda k: _one_edit(k, key)):
        t = _alias_target(r, accepts, 'similar')
        if t is not None:
            out.append(t)
    seen, uniq = set(), []
    for t in out:
        if t['id'] not in seen:
            seen.add(t['id'])
            t['matched'] = 'similar'
            uniq.append(t)
    return uniq[:limit]


# ── 후보 정렬 ───────────────────────────────────────────────────────────────

def viewed_dashboards(user_id, now=None):
    """사용자가 지금 보고 있는 대시보드 id 들 — 보는 중인 화면이 있으면 그것, 없으면 열려 있는
    화면. 화면 기록이 없으면 빈 집합."""
    if not user_id:
        return set()
    try:
        from aot.utils import web_presence as wp
        now = time.time() if now is None else now
        rows = [r for r in wp.recent(user_id, now=now)
                if r.get('page_kind') == 'dashboard' and r.get('page_ref')
                and wp.state_of(r, now) != 'away']
        viewing = [r for r in rows if wp.state_of(r, now) == 'viewing']
        return {r['page_ref'] for r in (viewing or rows)}
    except Exception:                                       # noqa: BLE001
        logger.debug('[domain] 지금 화면을 읽지 못함', exc_info=True)
        return set()


def rank(cands, user_id=None, now=None):
    """같은 이름의 후보 → 사용자가 지금 보는 대시보드에 있는 것(그 대시보드, 그 위의 위젯)을
    앞으로, 그것에 `on_screen` 을 단다. 고르지는 않는다 — 되묻는 것은 그대로다."""
    here = viewed_dashboards(user_id, now)
    if not here or not cands:
        return cands
    wids = [c['id'] for c in cands if c.get('kind') == 'widget']
    tab_of = {}
    if wids:
        from aot.databases.models import Widget
        tab_of = {w.unique_id: w.tab_id
                  for w in Widget.query.filter(Widget.unique_id.in_(wids)).all()}
    for c in cands:
        if (c.get('kind') == 'dashboard' and c.get('id') in here) or \
                (c.get('kind') == 'widget' and tab_of.get(c.get('id')) in here):
            c['on_screen'] = True
    return sorted(cands, key=lambda c: not c.get('on_screen'))


# ── 공개 ────────────────────────────────────────────────────────────────────

def listify(raw):
    """글자 한 줄로 온 목록을 목록으로 푼다 — `target='["1포장","2포장"]'` → 두 대상.

    일부 클라이언트는 배열 인자를 JSON 글자 그대로 보낸다. 그대로 이름으로 풀면 이름 전체가
    한 덩어리가 되어 `unknown_target` 으로 거절되고(2026-10-18 실측 7건), 모델은 이름·id 로
    한 번 더 되돌아간다. 모든 operation 의 대상에 같은 규칙이다 — 사건별 예외가 아니다.

    대괄호로 시작해 끝나는 글자가 **문자열만 든 목록**으로 읽힐 때만 푼다(JSON, 작은따옴표
    목록). 그 밖의 글자·목록은 그대로 돌려준다 — 이름이 우연히 대괄호로 둘러싸인 경우를
    목록으로 오해하지 않게."""
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not (text.startswith('[') and text.endswith(']')):
        return raw
    import json
    try:
        got = json.loads(text)
    except ValueError:
        try:
            import ast
            got = ast.literal_eval(text)
        except Exception:                                   # noqa: BLE001
            return raw
    if isinstance(got, (list, tuple)) and got \
            and all(isinstance(x, str) for x in got):
        items = [x.strip() for x in got if x.strip()]
        return items or raw
    return raw


def resolve(ref, accepts=(), only=None):
    """`target` 하나 → ('ok', 대상) | ('ambiguous', 후보들) | ('none', 오류 dict).

    빈 값은 ('empty', None) — "대상 없이" 부른 것이다.
    accepts: 부르는 operation 이 받는 종류 — 대시보드·탭은 이것이 그 종류를 받을 때만
    찾는다. only: 그 종류로만 좁힌다(안쪽 인자 이름으로 대상을 넘겼을 때 — 예:
    `dashboard='영양'` 은 대시보드다).
    """
    state, got = _resolve(ref, set(accepts or ()) | set(only or ()))
    if not only or state in ('empty', 'none'):
        return state, got
    if state == 'ok':
        if got['kind'] in only:
            return state, got
        return 'none', {"error": "'%s' is a %s, not a %s." % (
            got.get('name'), got['kind'], " or ".join(sorted(only)))}
    fit = [c for c in got if c.get('kind') in only]
    if len(fit) == 1:
        return 'ok', fit[0]
    if fit:
        return 'ambiguous', fit
    return 'none', {"error": "No %s named '%s'." % (" or ".join(sorted(only)), ref)}


_UUID_RE = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


def _resolve(ref, accepts):
    text = str(ref or '').strip()
    if '\\u' in text:
        # 클라이언트가 한글을 '\\ud3ec' 처럼 이스케이프한 채 보낸 경우(2026-10-13 claude.ai).
        try:
            text = text.encode('ascii', 'backslashreplace').decode('unicode_escape').strip()
        except (UnicodeError, ValueError):
            pass
    if not text:
        return 'empty', None
    try:
        t = _by_id(text)
        if t is not None:
            return 'ok', t
        if _UUID_RE.match(text):
            # 완전한 uuid 는 이름이 아니다. 지도·장소·장치 id 가 아니면 승인 번호·메모 같은
            # 다른 종류의 id 일 수 있어 호출 쪽(id 로만 받는 종류)이 맡는다. 이름 풀이로
            # 넘기면 숫자 조각('e3a3edb3' → '3-2')이 엉뚱한 구역으로 풀린다
            # (2026-10-18 구획 단계 승인이 구역으로 거절됐다).
            return 'none', {"error": "No place, plot or device has the id '%s'." % text}
        aliased = _alias_candidates(text, accepts)
        if len(aliased) == 1:
            return 'ok', aliased[0]
        if aliased:
            return 'ambiguous', aliased
        exact = _screen_by_path(text, accepts) or _exact_candidates(text, accepts)
    except _Refused as r:
        return 'none', r.error
    if len(exact) == 1:
        return 'ok', exact[0]
    if len(exact) > 1:
        return 'ambiguous', exact
    try:
        tok, hidden = _token_candidates(text)
    except _Refused as r:
        return 'none', r.error
    if len(tok) == 1:
        return 'ok', tok[0]
    if tok:
        return 'ambiguous', tok
    if _PATH_MARK in text:
        # 경로로 물었는데 그 자리에 그 이름이 없다 — 느슨한 리졸버로 넘기면 다른 자리의
        # 같은 이름을 집는다. 없다고 말한다.
        parts = [p.strip() for p in text.split(_PATH_MARK) if p.strip()]
        return 'none', {"error": "Nothing named '%s' in '%s'." % (
            parts[-1] if parts else text, ' > '.join(parts[:-1]))}
    try:
        t, cands = _fallback(text)
    except _Refused as r:
        return 'none', r.error
    if t is not None:
        return 'ok', t
    if cands and len(cands) == 1 and not hidden:
        return 'ok', cands[0]
    if cands:
        return 'ambiguous', cands
    pre = _prefix_candidates(text)
    if len(pre) == 1:
        return 'ok', pre[0]
    if pre:
        return 'ambiguous', pre
    if hidden:
        return 'none', _excluded_error(hidden)
    err = {"error": "Nothing named '%s' — no map, place, plot or device "
                    "has that name." % text}
    try:
        near = similar_names(text, accepts)
    except Exception:                                       # noqa: BLE001
        logger.exception('[domain] 비슷한 이름 찾기 실패')
        near = []
    if near:
        err['error'] += (" Similar names: %s — the word may have been misheard. Ask the "
                         "user which one they mean; do not pick. If it is a name they use, "
                         "record.alias_add saves it." % ", ".join(
                             "'%s'" % t['name'] for t in near))
        err['similar'] = near
    return 'none', err


def snapshot(target):
    """승인 스냅샷에 싣는 해석 결과(§9-1). 실행 직전 `changed()` 가 비교한다."""
    return {k: target.get(k) for k in ('kind', 'id', 'name', 'path')}


def changed(snap):
    """승인 뒤 대상이 지워졌거나 종류·이름·경로가 바뀌었으면 그 이유, 아니면 None."""
    if not isinstance(snap, dict) or not snap.get('id'):
        return None
    from aot.tools.domain.registry import ID_ONLY_KINDS
    if snap.get('kind') in ID_ONLY_KINDS:
        return None             # 해석기가 모르는 행 — 있는지는 안쪽 도구가 실행 때 본다
    try:
        now = _by_id(str(snap['id']))
    except Exception:                                       # noqa: BLE001
        logger.exception('[domain] 대상 재확인 실패')
        return "the target could not be re-checked"         # 확인 못 함 = 실행 안 함
    if now is None:
        return "the target no longer exists"
    for k in ('kind', 'name', 'path'):
        if snap.get(k) != now.get(k):
            return "the target's %s changed (%s → %s)" % (k, snap.get(k), now.get(k))
    return None

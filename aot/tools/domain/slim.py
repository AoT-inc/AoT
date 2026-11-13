# -*- coding: utf-8 -*-
"""도메인 층의 응답 줄이기·쪽 나누기 — 안쪽 도구는 그대로 두고(인앱 AI 는 옛 카탈로그를 쓴다) 도메인 표면의 응답만 줄인다.

명부의 `Op.slim` 이 이름을 가리키면 `dispatch._run_call_inner` 가 안쪽 응답을 받은 뒤 여기를 지난다.
- 기본 응답은 **요약**이다: 식별에 필요한 것만 싣고, 무거운 부분은 뺀다(`omitted` 에 무엇을 뺐는지·어떻게 얻는지).
- `fields=[...]` 로 빠진 갈래를 청한다(`detail.device` 와 같은 모양, PR #384). `all` 은 전부.
- `limit`·`offset` 은 안쪽 도구가 몰라서 여기서 자른다. 안 줬으면 전체를 주고, 줬는데 더 있으면 `truncated`·`total`·`next_offset`.

`limit`·`fields`·`offset` 은 이 op 에서 **도메인이 처리하는 낱말**이다 — 안쪽 도구로 넘기지 않는다(`DOMAIN_WORDS`).
"""
import json

#: slim 이 있는 op 에서 안쪽 도구에 넘기지 않고 이 층이 처리하는 공통 낱말.
DOMAIN_WORDS = ('fields', 'limit', 'offset')

#: 목록에서 프로그램 한 행에 남기는 칸 — 식별·고르기에 필요한 것. 본문(guidance_text·source_note·notes …)은 detail.program.
_PROGRAM_KEEP = ('unique_id', 'name', 'kind', 'subject', 'variety', 'source', 'stage_count', 'total_days',
                 'tab_id', 'usable_for_control', 'editable')


def _body(out):
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    return body if isinstance(body, dict) else None


def _pack(out, body):
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def _wanted(fields):
    """`fields` → 소문자 낱말 집합. 'all' 이면 None(전부)."""
    if fields is None:
        return set()
    if isinstance(fields, str):
        fields = [x for x in fields.replace(',', ' ').split() if x]
    got = {str(x).strip().lower() for x in fields}
    return None if 'all' in got else got


def _page(body, limit, offset):
    """body 의 첫 목록을 offset 부터 limit 개로 자른다. 자르지 않아도 되면 그대로."""
    key = next((k for k, v in body.items() if isinstance(v, list) and v), None)
    if key is None:
        return
    rows = body[key]
    try:
        start = max(0, int(offset or 0))
    except (TypeError, ValueError):
        start = 0
    try:
        cap = max(1, int(limit)) if limit not in (None, '') else None
    except (TypeError, ValueError):
        cap = None
    if cap is None and not start:
        return
    kept = rows[start:start + cap] if cap else rows[start:]
    body[key] = kept
    if 'count' in body:
        body['count'] = len(kept)
    if start + len(kept) < len(rows):
        body['truncated'] = True
        body['total'] = len(rows)
        body['next_offset'] = start + len(kept)
    elif start or cap:
        body['total'] = len(rows)


def _programs(body, want):
    """find.programs — 행마다 본문(지침·근거·메모)을 뺀다. 한 프로그램의 전부는 detail.program(target=unique_id)."""
    rows = body.get('programs')
    if not isinstance(rows, list):
        return
    body['programs'] = [{k: r.get(k) for k in _PROGRAM_KEEP if k in r} if isinstance(r, dict) else r for r in rows]
    body['omitted'] = ("per-programme text (guidance, source note, notes); "
                       "detail.program(target=<unique_id>) has it with every stage")


def _widget(body, want):
    """detail.widget — 옵션 스키마(가장 무거운 부분)는 fields=['schema'] 로."""
    w = body.get('widget')
    if not isinstance(w, dict) or want is None or 'schema' in want or 'option_schema' in want:
        return
    if 'option_schema' in w:
        n = len(w.pop('option_schema') or [])
        body['omitted'] = ("option_schema (%d options: id, type, accepts); "
                           "fields=['schema'] adds it" % n)


def _map_equipment(body, want):
    """detail.map_equipment — 머리·배관 좌표 목록은 fields=['sprinklers'|'pipes'] 로. 개수·간격·규격·점적은 그대로."""
    if want is None:
        return
    cut = []
    if 'sprinklers' not in want and isinstance(body.get('sprinklers'), list):
        body.pop('sprinklers')
        body.pop('sprinklers_format', None)
        body.pop('sprinklers_truncated', None)
        cut.append('sprinklers')
    pipes = body.get('pipes')
    if 'pipes' not in want and isinstance(pipes, list):
        by = {}
        for p in pipes:
            if isinstance(p, dict):
                b = by.setdefault(p.get('sub_type') or '?', {'count': 0, 'length_m': 0.0})
                b['count'] += 1
                b['length_m'] = round(b['length_m'] + (p.get('length_m') or 0), 1)
        body['pipes'] = by
        body['pipes_format'] = "count and total length per sub_type"
        cut.append('pipes')
    if cut:
        body['omitted'] = "positions of %s; fields=[%s] adds them" % (
            " and ".join(cut), ", ".join(repr(c) for c in cut))


SLIMMERS = {
    'programs': _programs,
    'widget': _widget,
    'map_equipment': _map_equipment,
    'page': None,                    # 쪽 나누기만
}


def apply(out, name, args):
    """안쪽 응답 `out` 에 슬림을 적용한다. args: {'fields','limit','offset'} (호출이 준 것). 못 읽는 응답은 그대로."""
    body = _body(out)
    if body is None or body.get('status') == 'error' or 'error' in body:
        return out
    want = _wanted(args.get('fields'))
    fn = SLIMMERS.get(name)
    if fn is not None:
        fn(body, want)
    _page(body, args.get('limit'), args.get('offset'))
    return _pack(out, body)

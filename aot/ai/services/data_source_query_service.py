# coding=utf-8
"""
data_source_query_service.py — 등록된 데이터 API를 **물어볼 때** 조회한다.

## 왜 필요한가

지금까지 REST 소스(스마트팜코리아 등)는 등록 시 **고정된 파라미터로 한 번
동기화**해 지식 항목으로 굳혔다. 그래서 "김제 토마토 2015 작기" 는 답할 수
있어도 "다른 농가는 어떤가" 는 못 물었다 — 새 소스를 등록해야 했다. 실측
(2026-08-25): 스마트팜코리아 노지 농가 1,650곳 중 라이브러리에 들어온 것은
한 곳뿐이었다.

기대되는 동작은 그게 아니다. **LLM 이 사람 대신 그 API 를 질문할 때마다 두드려
결과를 근거로 답하고, 쓸모 있으면 라이브러리에 비치해 다음에 재사용**하는
것이다(사용자 정의, 2026-08-25). 참조표(reference_table_service)에 준 것과 같은
대우를 REST 소스에도 주는 것이 이 모듈이다.

## 무엇을 조회 가능하다고 보는가

**오퍼레이션을 선언한 소스만** 이다. `EXT_CLIENT_MAP` 계열(농사로·병해충·RDA)은
`sync()` 하나뿐이라 "이 파라미터로 이것만 물어봐" 를 표현할 방법이 없다 —
그런 소스를 조회 가능한 척 내보내면 모델이 부를 수 없는 것을 부르려 든다.
지금 해당하는 것은 스마트팜코리아 3종(시설/노지/축산)이고, 그들은
`OPERATIONS`/`OUTDOOR_OPERATIONS`/`LIVESTOCK_OPERATIONS` 로 오퍼레이션과 필요
파라미터를 이미 선언하고 있다.

## 응답 크기

이 API 는 한 번에 수천 행을 돌려준다(identity 1,650행 = 225KB). 참조표에서
배운 것을 그대로 적용한다: 행 수 상한, 컬럼 투영, 그리고 **원본이 몇 건이었는지
반드시 함께 말하기** — 잘린 걸 모르면 모델이 "이게 전부" 로 읽는다.
"""
import json
import logging

from aot.ai.services import source_attribution

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 5
_MAX_LIMIT = 25
_MAX_CELL = 200          # 한 칸이 이보다 길면 자른다(통용명 목록 같은 것)

# 소스 계열. 오퍼레이션 사전과 조회 함수가 계열마다 다르므로 여기서 묶는다 —
# 프리셋 이름으로 if 를 늘어놓으면 새 계열을 붙일 때마다 세 군데를 고쳐야 한다.
#
#   key_param    : API 키를 어느 이름으로 넘기는가
#   key_required : 키 없이도 조회되는가. Open-Meteo 는 무료 엔드포인트가 키를
#                  요구하지 않는다(키가 있으면 상업 엔드포인트로 간다).
_FAMILIES = {
    'smartfarmkorea':           {'client': 'smartfarmkorea', 'key_param': 'serviceKey', 'key_required': True},
    'smartfarmkorea_outdoor':   {'client': 'smartfarmkorea', 'key_param': 'serviceKey', 'key_required': True},
    'smartfarmkorea_livestock': {'client': 'smartfarmkorea', 'key_param': 'serviceKey', 'key_required': True},
    'ext_openmeteo':            {'client': 'openmeteo',      'key_param': 'apikey',     'key_required': False},
}

_QUERYABLE_PRESETS = tuple(_FAMILIES)

_PRESET_ANSWERS = {
    'smartfarmkorea': '시설원예 농가의 아이덴티티(지역·품목)·작기·환경 측정·생육 측정. '
                      '전국 참여 농가의 실측값이라 "다른 농가는 이 시기에 어떻게 했나" 에 답한다.',
    'smartfarmkorea_outdoor': '노지 농가의 아이덴티티·작기·환경 측정·생육 측정(무·배추·마늘·양파·블루베리).',
    'smartfarmkorea_livestock': '축산 실측 — 낙농·양돈·양계·한우. 날짜 범위만으로 조회한다.',
    'ext_openmeteo': '좌표 하나로 전세계 어디나 — 일별/시간별 예보(기온·강수·습도·VPD), '
                 '토양 깊이별 온도·수분, 기준증발산량 ET0, 그리고 과거 기후의 월별 집계. '
                 'AoT 의 get_weather 는 자기 센서만 읽고 get_weather_forecast 는 한국 '
                 '기상청 전용이라, **기상 센서가 없거나 한국 밖인 설치에서는 이것이 '
                 '유일한 기상 근거다.** 토양값과 ET0 는 센서 유무와 무관하게 여기서만 나온다.',
}


def _client_for(preset_key):
    """계열별 (operations_for_preset, fetch_operation)."""
    fam = _FAMILIES.get(preset_key) or {}
    if fam.get('client') == 'openmeteo':
        from aot.ai.context.ext import openmeteo_client as mod
    else:
        from aot.ai.context.ext import smartfarmkorea_client as mod
    return mod.operations_for_preset, mod.fetch_operation


_SFK_NOTE = ('Codes like userId / facilityId / croppingSerlNo are NOT things a '
             'person knows — resolve them with smartfarmkorea_lookup first. '
             'Dates are YYYY-MM-DD (livestock: YYYYMMDD).')

_PRESET_NOTES = {
    'smartfarmkorea': _SFK_NOTE, 'smartfarmkorea_outdoor': _SFK_NOTE,
    'smartfarmkorea_livestock': _SFK_NOTE,
    'ext_openmeteo': ('latitude/longitude default to the farm location stored on this '
                  'source, so omit them unless you mean a different place. Dates are '
                  'YYYY-MM-DD. Units are written into each column name — read them: '
                  'soil moisture is m³/m³ (0.27), NOT percent. The first row reports '
                  'which grid cell answered and its elevation; in hilly terrain check '
                  'it against the farm before trusting the temperatures.'),
}


def _sources():
    from aot.databases.models import AIContextSource
    out = []
    for src in AIContextSource.query.filter_by(is_active=True, is_enabled=True).all():
        try:
            cfg = json.loads(src.config_json or '{}')
        except (ValueError, TypeError):
            continue
        if cfg.get('preset_key') in _QUERYABLE_PRESETS:
            out.append((src, cfg))
    return out


def _operations(preset_key):
    ops_for, _ = _client_for(preset_key)
    return ops_for(preset_key)


# @ANCHOR: DATA_SOURCE_DESCRIBE
def describe_all():
    """조회 가능한 소스와 각 오퍼레이션이 요구하는 파라미터.

    모델이 이 목록만 보고 무엇을 물을 수 있는지 판단해야 하므로, **필요한
    파라미터를 숨기지 않는다.** 어떤 값은 사람이 알 수 없는 코드라
    (userId/facilityId/croppingSerlNo) 그건 smartfarmkorea_lookup 으로 푼다는
    것도 함께 말한다."""
    out = []
    for src, cfg in _sources():
        preset = cfg['preset_key']
        ops = _operations(preset)
        out.append({
            'source_id': src.source_id,
            'label': src.source_name,
            'preset': preset,
            'answers': _PRESET_ANSWERS.get(preset, ''),
            'operations': [
                {'operation': k,
                 'label': v.get('label_ko') or k,
                 'params': [p for p in v['params'] if p != 'serviceKey'],
                 # 선택 파라미터를 숨기면 기본값 말고는 물어볼 수 없다 —
                 # "예보 3일치만" / "1시간 간격으로" 가 표현 불가능해진다.
                 'optional': dict(list((v.get('optional') or {}).items())
                                  + list((v.get('client_optional') or {}).items())) or None}
                for k, v in sorted(ops.items())
            ],
            'note': _PRESET_NOTES.get(preset, ''),
        })
    return out


def _trim(rows, columns, limit):
    keep = None
    if columns:
        keep = [c.strip() for c in columns] if not isinstance(columns, str) else \
               [c.strip() for c in columns.split(',') if c.strip()]
        if '*' in keep:
            keep = None
    out = []
    for row in rows[:limit]:
        clean = {}
        for k, v in (row or {}).items():
            if k in ('statusCode', 'statusMessage'):
                continue
            if v in (None, '') or str(v).strip().upper() == 'NA':
                continue
            if keep and k not in keep:
                continue
            sv = str(v)
            clean[k] = sv[:_MAX_CELL] + '…' if len(sv) > _MAX_CELL else v
        if clean:
            out.append(clean)
    return out


# @ANCHOR: DATA_SOURCE_QUERY
def query(source_id, operation, params=None, limit=_DEFAULT_LIMIT, columns=None):
    """등록된 소스의 오퍼레이션 하나를 지금 호출한다.

    Returns (payload_dict, error_str)."""
    match = None
    for src, cfg in _sources():
        if not source_id or src.source_id == source_id:
            match = (src, cfg)
            if source_id:
                break
    if match is None:
        return None, ('source not found or not queryable — call list_lookup_sources. '
                      'Only sources that declare operations can be queried.')
    src, cfg = match

    ops = _operations(cfg['preset_key'])
    if operation not in ops:
        return None, ("unknown operation %r for this source. Available: %s"
                      % (operation, ', '.join(sorted(ops))))

    fam = _FAMILIES.get(cfg['preset_key']) or {}
    key_param = fam.get('key_param', 'serviceKey')
    api_key = (cfg.get('api_key') or '').strip()
    # 키가 없어도 조회되는 계열이 있다(Open-Meteo 무료 엔드포인트). 그런
    # 소스에까지 키를 요구하면 아무도 못 쓴다.
    if not api_key and fam.get('key_required', True):
        return None, 'this source has no API key configured — set it on the AI Library page.'

    op_def = ops[operation]
    call_params = {key_param: api_key} if api_key else {}
    for p in op_def['params']:
        if p == key_param:
            continue
        v = (params or {}).get(p)
        # 설정에 있는 값을 기본값으로 쓴다 — 소스에 이미 농가나 농장 좌표가
        # 지정돼 있으면 모델이 매번 다시 적을 이유가 없다.
        if v in (None, ''):
            v = cfg.get(p)
        if v in (None, ''):
            return None, ("missing parameter %r for operation %r (needs: %s). %s" %
                          (p, operation,
                           ', '.join(x for x in op_def['params'] if x != key_param),
                           _PRESET_NOTES.get(cfg['preset_key'], '')))
        call_params[p] = str(v)

    # 선택 파라미터는 없으면 클라이언트의 기본값에 맡긴다 — 빈 문자열을
    # 넘기면 그 기본값을 덮어써 버린다.
    for p in list(op_def.get('optional') or {}) + list(op_def.get('client_optional') or {}):
        v = (params or {}).get(p)
        if v in (None, ''):
            v = cfg.get(p)
        if v not in (None, ''):
            call_params[p] = str(v)

    try:
        limit = max(1, min(int(limit), _MAX_LIMIT))
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT

    _, fetch_operation = _client_for(cfg['preset_key'])
    records, err = fetch_operation(operation, call_params, operations=ops)
    if err:
        return None, err
    total = len(records or [])
    rows = _trim(records or [], columns, limit)
    payload = {
        'rows': rows,
        'returned': len(rows),
        # 원본이 몇 건이었는지 반드시 말한다 — 잘린 줄 모르면 모델은 이게
        # 전부라고 읽고, "그런 농가는 없다" 같은 단정을 한다.
        'total_available': total,
        'source': src.source_name,
        # knowledge_shelve(source_ref=...) 에 그대로 넘기면 비친 항목이 "확인할
        # 데가 있는 것" 으로 표시된다.
        'source_ref': src.source_id,
        'operation': operation,
    }
    if total > len(rows):
        payload['truncated'] = ("Showing %d of %d rows. Narrow the parameters (or raise "
                                "limit, max %d) — do NOT treat this as the complete set."
                                % (len(rows), total, _MAX_LIMIT))
    # 출처 표기 — CC BY 자료는 값을 보여 주는 자리 옆에 밝혀야 한다.
    # 답변을 쓰는 것은 모델이고 모델은 이 응답에 실린 것만 아므로 여기서 싣는다.
    source_attribution.apply(payload, cfg, cfg.get('preset_key'))
    return payload, None

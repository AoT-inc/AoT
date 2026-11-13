# coding=utf-8
"""지도 설비 부품 표 — 종류, 묶음, 정격 키·단위의 **단일 출처**.

패널(놓기 버튼·정격 입력), MCP(`find.map_equipment`), 시험이 모두 이 표를 읽는다.
다른 곳에 부품 목록을 따로 적지 말 것.

규칙
- `sub_type` 은 `feature.properties` 에 그대로 저장된다. 자동 배관 이음 코드
  (`tee`·`elbow`·`mT` …)와 겹치면 렌더가 connection-dot 으로 빠지고, `pipe*` 로
  시작하면 배관 분기(`startsWith('pipe')`)에 걸린다. 그래서 `conn_tee`·`conn_elbow`
  처럼 접두어를 붙였다(`parts_conflicts()` 와 시험이 막는다).
- 정격은 `feature.properties` 의 숫자다. 비우면 키를 지운다(0 으로 두지 않는다).
- 라벨은 msgid 다. 화면에 낼 때 `panel_catalog(translate)` 가 번역한다.
- 장치 uuid 는 도형에 새기지 않는다(`device_id` 금지). Output·센서 연결은 GeoBinding 몫이다.
"""
from typing import Callable, Dict, List, NamedTuple, Tuple


def _(msgid):
    """번역 추출용 표시. 실제 번역은 `panel_catalog(translate)` 에서 한다."""
    return msgid


class Rating(NamedTuple):
    key: str      # feature.properties 키
    unit: str
    label: str    # msgid
    step: str     # 입력 칸 step


class Part(NamedTuple):
    kind: str     # sub_type
    group: str    # GROUPS 의 id
    label: str    # msgid
    ratings: Tuple[Rating, ...]


# 패널 묶음 id → 제목 msgid (순서가 곧 화면 순서)
GROUPS: Tuple[Tuple[str, str], ...] = (
    ('supply', _('Water supply')),
    ('filter', _('Filter')),
    ('valve', _('Valve')),
    ('conn', _('Connection')),
)

_MAX_LPM = Rating('max_lpm', 'L/min', _('Max flow'), '1')
_CAPACITY = Rating('capacity_l', 'L', _('Capacity'), '10')
_BASE_H = Rating('base_height_m', 'm', _('Base height'), '0.1')
# 저수지 수면 높이: 탱크 바닥 높이와 같은 키(`base_height_m`, 기준면에서 잰 m)를 쓰고 라벨만 다르다.
_SURFACE_H = Rating('base_height_m', 'm', _('Surface height'), '0.1')
_RATED = Rating('rated_lpm', 'L/min', _('Rated flow'), '1')
_HEAD = Rating('head_m', 'm', _('Head'), '0.5')
_POWER = Rating('power_kw', 'kW', _('Power'), '0.1')
_LOSS = Rating('loss_kpa', 'kPa', _('Pressure loss'), '1')
_SIZE = Rating('size_mm', 'mm', _('Size'), '1')
_DIAMETER = Rating('diameter_mm', 'mm', _('Pipe diameter'), '1')

PARTS: Tuple[Part, ...] = (
    Part('source_river', 'supply', _('River'), (_MAX_LPM,)),
    Part('source_reservoir', 'supply', _('Reservoir'), (_MAX_LPM, _SURFACE_H)),
    Part('source_well', 'supply', _('Well'), (_MAX_LPM,)),
    Part('source_tap', 'supply', _('Tap water'), (_MAX_LPM,)),
    Part('tank', 'supply', _('Water tank'), (_CAPACITY, _BASE_H)),
    Part('pump', 'supply', _('Pump'), (_RATED, _HEAD, _POWER)),
    Part('filter_disc', 'filter', _('Disc'), (_LOSS,)),
    Part('filter_screen', 'filter', _('Screen'), (_LOSS,)),
    Part('filter_sand', 'filter', _('Sand'), (_LOSS,)),
    Part('valve_union', 'valve', _('Union valve'), (_SIZE,)),
    Part('valve_adapter', 'valve', _('Adapter valve'), (_SIZE,)),
    Part('valve_inline', 'valve', _('Inline valve'), (_SIZE,)),
    Part('conn_suction', 'conn', _('Suction'), (_SIZE,)),
    Part('conn_elbow', 'conn', _('Elbow'), (_SIZE,)),
    Part('conn_tee', 'conn', _('Tee'), (_SIZE,)),
    Part('conn_reducer', 'conn', _('Reducer'), (_SIZE,)),
)

# 배관은 부품이 아니라 선이다. 놓는 목록에는 없고 정격만 있다.
PIPE_RATINGS: Dict[str, Tuple[Rating, ...]] = {
    'pipe_main': (_DIAMETER,),
    'pipe_branch': (_DIAMETER,),
}

# 자동 배관 이음·연결점이 쓰는 코드(aot-geo-layer.js `_isConnDot`). 부품 kind 와 겹치면 안 된다.
CONNECTION_CODES: Tuple[str, ...] = (
    'mT', 'mbT', 'bT', 'mE', 'bE', 'tee', 'elbow', 'connection',
)

_BY_KIND = {p.kind: p for p in PARTS}


def kinds() -> Tuple[str, ...]:
    """부품 sub_type 전체(순서 고정)."""
    return tuple(p.kind for p in PARTS)


def is_part(sub_type) -> bool:
    return sub_type in _BY_KIND


def get(kind):
    return _BY_KIND.get(kind)


def ratings_for(sub_type) -> Tuple[Rating, ...]:
    """부품 또는 배관의 정격 목록. 모르는 종류는 빈 튜플."""
    p = _BY_KIND.get(sub_type)
    if p is not None:
        return p.ratings
    return PIPE_RATINGS.get(sub_type, ())


def rating_keys(include_pipes: bool = True) -> Tuple[str, ...]:
    """정격 키 전체(중복 없이, 첫 등장 순서)."""
    seen: List[str] = []
    rows = [r for p in PARTS for r in p.ratings]
    if include_pipes:
        rows += [r for rs in PIPE_RATINGS.values() for r in rs]
    for r in rows:
        if r.key not in seen:
            seen.append(r.key)
    return tuple(seen)


def parts_conflicts() -> List[str]:
    """표 불변식 위반 목록(비면 정상): 이음 코드 충돌, pipe 접두어, 중복, 모르는 묶음."""
    bad: List[str] = []
    group_ids = {g for g, _t in GROUPS}
    seen = set()
    for p in PARTS:
        if p.kind in CONNECTION_CODES:
            bad.append(f'{p.kind}: 배관 이음 코드와 같다')
        if p.kind.startswith('pipe'):
            bad.append(f'{p.kind}: pipe 접두어는 배관 분기에 걸린다')
        if p.kind in seen:
            bad.append(f'{p.kind}: 중복')
        seen.add(p.kind)
        if p.group not in group_ids:
            bad.append(f'{p.kind}: 모르는 묶음 {p.group}')
    return bad


def panel_catalog(translate: Callable[[str], str] = lambda s: s) -> dict:
    """화면용 목록 — `window.AOT_EQUIPMENT_PARTS` 로 실린다.

    {'groups': [{'id', 'title', 'parts': [{'kind', 'label'}]}],
     'ratings': {sub_type: [{'key', 'unit', 'label', 'step'}]}}   # 부품 + 배관
    """
    def _r(r: Rating) -> dict:
        return {'key': r.key, 'unit': r.unit, 'label': translate(r.label), 'step': r.step}

    groups = [
        {'id': gid, 'title': translate(title),
         'parts': [{'kind': p.kind, 'label': translate(p.label)}
                   for p in PARTS if p.group == gid]}
        for gid, title in GROUPS
    ]
    ratings = {p.kind: [_r(r) for r in p.ratings] for p in PARTS}
    ratings.update({k: [_r(r) for r in rs] for k, rs in PIPE_RATINGS.items()})
    return {'groups': groups, 'ratings': ratings}

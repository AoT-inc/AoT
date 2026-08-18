# coding=utf-8
"""이름 해석용 도형 인덱스 — feature 파싱 결과를 짧게 공유한다.

이름 하나를 해석하는 데 `GeoShape.query.all()` 이 **세 번** 돌고 있었다
(`_resolve_note_target` · `_resolve_note_target_ids` · 그 안의 이름 순회).
실측(2026-08-18, 도형 150): 그 조회 하나가 23.5ms 이고 feature 파싱은 사실상
공짜다 — **비용은 파싱이 아니라 JSON 컬럼이 실린 150행을 읽는 것**이다.
`_scope_for_target('3포장')` 118ms 중 대부분이 여기였다.

**ORM 객체를 캐시하지 않는다.** 세션이 닫히면 detached 가 되고, 그때 아직
로드되지 않은 속성을 건드리면 `DetachedInstanceError` 가 난다 — 캐시가 히트일
때만 터지는, 재현이 고약한 종류다. 대신 이름 해석에 실제로 필요한 필드만
평범한 튜플로 담는다.

캐시 수명은 짧고(30초) 도형을 저장하면 즉시 버린다
(`containment_cache.invalidate()` 가 함께 부른다 — 무효화 배선을 두 벌로
늘리지 않기 위해서다).
"""
import json as _json
import threading
import time
from collections import namedtuple

# 이름 해석이 실제로 읽는 필드만. 늘리려거든 왜 필요한지 함께 적을 것 —
# 필드가 늘수록 이 캐시가 ORM 객체 흉내를 내기 시작하고, 그러면 위 주석이
# 경고하는 detached 문제를 결국 다시 만나게 된다.
ShapeRec = namedtuple('ShapeRec',
                      'id unique_id type parent_id device_id geo_id')

_TTL_S = 30
_LOCK = threading.Lock()
# **DB 단위로 나눈다.** 캐시가 프로세스 전역이면 각자 임시 DB 를 만드는
# 테스트끼리 서로의 도형을 본다 — 단독 실행은 통과하고 스위트로 돌리면
# 깨지는, 원인을 찾기 어려운 실패다(실제로 그렇게 잡았다).
# 운영에서는 DB 가 하나라 키가 하나뿐이고 동작은 그대로다.
_CACHE = {}


def _scope_key():
    try:
        from aot.aot_flask.extensions import db
        return str(db.engine.url)
    except Exception:
        return '?'


def named_shapes():
    """이름이 있는 도형: `[(ShapeRec, name, name_lower)]`.

    이름이 없는 도형은 애초에 이름으로 찾을 수 없으므로 뺀다 — 목록이
    작아지면 순회도 그만큼 짧아진다.
    """
    now = time.time()
    key = _scope_key()
    with _LOCK:
        slot = _CACHE.get(key)
        if slot and slot['rows'] is not None and (now - slot['at']) < _TTL_S:
            return slot['rows']

    from aot.databases.models import GeoShape
    out = []
    for s in GeoShape.query.all():
        try:
            feat = s.feature if isinstance(s.feature, dict) \
                else _json.loads(s.feature or '{}')
            props = feat.get('properties') or {}
            name = str(props.get('name') or props.get('label')
                       or props.get('title') or '').strip()
        except Exception:
            continue
        if not name:
            continue
        out.append((ShapeRec(s.id, s.unique_id, s.type, s.parent_id,
                             s.device_id, s.geo_id),
                    name, name.lower()))

    with _LOCK:
        _CACHE[key] = {'rows': out, 'at': now}
    return out


def invalidate():
    """도형이 바뀌면 버린다. `containment_cache.invalidate()` 가 함께 부른다.

    **전부 버린다** — 어느 DB 인지 따지지 않는다. 잘못 버려도 손해는 재조회
    한 번이고, 덜 버리면 낡은 이름이 남는다.
    """
    with _LOCK:
        _CACHE.clear()

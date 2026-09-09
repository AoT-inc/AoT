# coding=utf-8
"""공간 포함 관계 캐시의 소유자 — 읽기·채우기·무효화.

지도 데이터는 geo 패키지가 소유한다(`check_geo_writes`). 캐시도 지도 데이터라
쓰기는 여기 하나를 지난다 — 밖에서 각자 채우기 시작하면 무효화 시점을 여러 벌
기억해야 하고, 그 중 하나만 빠뜨려도 조용히 낡은 부모가 남는다.

**정본은 기하다.** 이 모듈이 하는 일은 기하 계산 결과를 적어 두는 것뿐이고,
어긋나면 기하가 맞다. 그래서 무효화는 늘 안전한 방향(지우기)으로만 한다 —
의심스러우면 지우고 다시 계산하면 된다.
"""
from flask import current_app

from aot.aot_flask.extensions import db
from aot.databases.models import GeoContainmentCache
from aot.utils.time_utils import utc_now

KIND_SHAPE = 'shape'
KIND_PLANTING = 'plot'

# 무효화를 빠뜨린 경로가 있어도 스스로 낫는 안전망.
#
# 기하를 바꾸는 자리에서 `invalidate()` 를 부르는 것이 정상 경로지만, 이
# 레포는 "정리해야 할 경로가 17곳인데 실제로 정리하는 곳은 4곳" 을 이미
# 겪었다. 새 경로 하나가 빠지면 증상은 **에러 없이 낡은 부모**이고, 며칠 뒤
# "왜 저 구획이 저 구역에 잡히지" 로만 나타난다.
#
# 24시간인 이유: **정상 경로는 즉시 무효화한다.** 이 값이 실제로 쓰이는 것은
# 무효화를 빠뜨린 경로뿐이고, 그런 경로가 있는지는 `check_geo_integrity` 의
# `containment-cache-drift` 가 알려준다. 짧게 잡으면 만료될 때마다 전량
# 재계산 + 재저장이 일어나 **캐시가 없을 때보다 느려진다**(실측: 만료 상태의
# descendant_target_ids 가 25.6ms → 114.5ms).
_TTL_S = 86400


def _naive_utc(dt):
    """tz 를 벗긴 UTC. SQLite 는 naive 로 저장하는데 `utc_now()` 는 aware 라
    그대로 빼면 TypeError 가 난다.

    **그 예외를 `load()` 의 except 가 삼켜 캐시가 항상 빈 dict 를 돌려주고
    있었다** — 결과는 맞고 성능만 나빠지는, 아무도 눈치채지 못하는 실패다.
    캐시를 새로운 고장 지점으로 만들지 않으려면 조용히 삼키는 자리마다
    이런 것이 숨을 수 있다는 점을 기억할 것.
    """
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def load(geo_id=None, kind=None):
    """{(kind, child_uuid): parent_uuid} — 없는 키는 **미계산**이다.

    `parent_uuid` 가 None 인 행은 "계산했고 부모가 없다" 는 뜻이라 키는 있다.
    이 구분이 없으면 루트 도형이 영원히 캐시 미스가 되어 매번 기하를 돈다.
    """
    q = GeoContainmentCache.query
    if geo_id:
        q = q.filter(GeoContainmentCache.geo_id == geo_id)
    if kind:
        q = q.filter(GeoContainmentCache.child_kind == kind)
    try:
        from datetime import timedelta
        floor = _naive_utc(utc_now()) - timedelta(seconds=_TTL_S)
        return {(r.child_kind, r.child_uuid): r.parent_uuid
                for r in q.all()
                if r.computed_at is not None
                and _naive_utc(r.computed_at) >= floor}
    except Exception:
        # 캐시를 못 읽는 것은 고장이 아니다 — 호출자는 기하로 파생한다.
        # 다만 **조용히 지나가면 안 된다**: 여기서 삼켜진 예외 하나 때문에
        # 캐시가 통째로 죽고 성능만 나빠진 적이 있다(위 _naive_utc 주석).
        current_app.logger.exception('containment_cache: 조회 실패 — '
                                     '캐시 없이 계속합니다(성능만 저하)')
        return {}


def store(entries):
    """entries: [(kind, child_uuid, parent_uuid, geo_id)] 를 upsert.

    실패해도 예외를 올리지 않는다. **캐시를 못 적는 것 때문에 조회가 실패하면
    안 된다** — 그러면 캐시가 성능 개선이 아니라 새로운 고장 지점이 된다.
    """
    if not entries:
        return 0
    now = _naive_utc(utc_now())
    # 같은 배치에 같은 (kind, child) 가 두 번 들어오면 둘 다 INSERT 로 잡혀
    # UNIQUE 위반이 난다 — 부르는 쪽이 중복을 걸러 주기를 기대하지 않는다.
    deduped = {}
    for kind, child, parent, geo_id in entries:
        deduped[(kind, child)] = (parent, geo_id)
    try:
        existing = {}
        for r in GeoContainmentCache.query.filter(
                GeoContainmentCache.child_uuid.in_(
                    [c for (_k, c) in deduped])).all():
            existing[(r.child_kind, r.child_uuid)] = r

        for (kind, child), (parent, geo_id) in deduped.items():
            row = existing.get((kind, child))
            if row is None:
                db.session.add(GeoContainmentCache(
                    child_kind=kind, child_uuid=child, parent_uuid=parent,
                    geo_id=geo_id, computed_at=now))
                continue
            if row.parent_uuid != parent or row.geo_id != geo_id:
                row.parent_uuid = parent
                row.geo_id = geo_id
            # **값이 같아도 computed_at 은 갱신한다.**
            #
            # 예전에는 값이 바뀔 때만 찍었다. 그런데 기하가 안정적이면 값은
            # 늘 같으므로 computed_at 이 영원히 처음 그대로 남고, _TTL_S(24h)
            # 가 지나는 순간 load() 가 전 행을 걸러 낸다. 그 뒤로는 매 요청이
            # 캐시 미스 → 전량 재계산인데, 재계산 결과도 같은 값이라 다시
            # 아무것도 안 찍혀 **캐시가 영영 못 살아난다.** 지도를 건드리지
            # 않을수록 확실히 죽는 구조였다(실측 2026-09-08: 김제 도형 301개,
            # geo_containment_cache 333행이 전부 전날 것이라 100% 미스 →
            # descendant_target_ids 가 호출마다 shapely contains 약 15,700회,
            # 0.45초. 노트 조회 한 건이 3.3초까지 밀린 원인의 큰 몫이었다).
            #
            # 여기서 찍는 것은 "이 값이 방금 계산으로 확인됐다" 는 사실이다.
            # TTL 은 무효화를 빠뜨린 경로를 위한 안전망인데(위 _TTL_S 주석),
            # 재계산은 기하에서 다시 파생하므로 그때 값이 틀렸으면 위 분기가
            # 고친다 — 확인 시각을 갱신해도 안전망은 그대로다.
            row.computed_at = now
        db.session.commit()
        return len(deduped)
    except Exception:
        # 여러 요청이 동시에 같은 키를 처음 채우면 INSERT 가 겹쳐 UNIQUE 로
        # 깨진다(실측: gunicorn 스레드 8개, 2026-09-07 하루 78건). 한 번은
        # 다시 읽어 갱신으로 처리한다 — 그 사이 다른 요청이 이미 넣었다는
        # 뜻이므로, 여기서 포기하면 캐시가 비는 창이 계속 남는다.
        db.session.rollback()
        try:
            existing = {}
            for r in GeoContainmentCache.query.filter(
                    GeoContainmentCache.child_uuid.in_(
                        [c for (_k, c) in deduped])).all():
                existing[(r.child_kind, r.child_uuid)] = r
            wrote = 0
            for (kind, child), (parent, geo_id) in deduped.items():
                row = existing.get((kind, child))
                if row is None:
                    continue          # 아직도 없으면 다음 계산에 맡긴다
                row.parent_uuid = parent
                row.geo_id = geo_id
                row.computed_at = now
                wrote += 1
            db.session.commit()
            return wrote
        except Exception:
            db.session.rollback()
            current_app.logger.exception('containment_cache: 저장 실패')
            return 0


def invalidate(geo_id=None, child_uuids=None):
    """캐시를 버린다. 기하가 바뀐 지도(또는 특정 대상)만.

    **도형이나 구획의 기하를 고치는 경로는 반드시 이것을 부를 것.** 안 부르면
    화면과 AI 가 낡은 부모를 계속 본다 — 에러 없이, 며칠 뒤 "왜 저 구획이
    저 구역에 잡히지" 로 나타난다.

    지우는 방향으로만 동작하므로 과하게 불러도 손해는 재계산 비용뿐이다.
    """
    # 이름 해석 인덱스도 함께 버린다 — 도형이 바뀌면 둘 다 낡는다.
    # 무효화 배선을 두 벌로 늘리면 한쪽만 부르는 경로가 반드시 생긴다.
    try:
        from aot.aot_flask.geo import shape_index
        shape_index.invalidate()
    except Exception:
        pass

    try:
        q = GeoContainmentCache.query
        if geo_id:
            q = q.filter(GeoContainmentCache.geo_id == geo_id)
        if child_uuids:
            q = q.filter(GeoContainmentCache.child_uuid.in_(list(child_uuids)))
        if not geo_id and not child_uuids:
            n = q.delete(synchronize_session=False)
        else:
            n = q.delete(synchronize_session=False)
        db.session.commit()
        return n
    except Exception:
        db.session.rollback()
        current_app.logger.exception('containment_cache: 무효화 실패')
        return 0

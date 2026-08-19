# coding=utf-8
"""공간 포함 관계의 **파생 캐시** — 정본이 아니다.

"이 도형/구획은 무엇 안에 있는가" 는 기하가 답한다. 그 계산이 질의마다
반복되므로(실측: `search_schedule('3포장')` 197ms, 그중 구획 판정 72ms) 결과를
여기 적어 둔다.

**언제든 통째로 버려도 된다.** 비면 기하로 다시 파생하고 그 결과를 다시 적는다.
캐시와 기하가 어긋나면 **기하가 맞다** — 검사(`check_geo_integrity` 의
`containment-cache-drift`)는 그 방향으로만 고친다.

`GeoShape.parent_id` 와 헷갈리지 말 것. 그 컬럼은 **사람이 정한 값**이고
시간대·좌표 상속과 DB 트리거가 읽는 정본이다. 기계가 추측한 값을 거기 섞으면
둘을 가를 수 없게 되고, 잠들어 있던 상속 경로가 예고 없이 깨어난다.
"""
from aot.utils.time_utils import utc_now

from aot.databases import CRUDMixin
from aot.aot_flask.extensions import db


class GeoContainmentCache(CRUDMixin, db.Model):
    """(child_kind, child_uuid) → parent_uuid.

    @phase active
    """
    __tablename__ = "geo_containment_cache"
    __table_args__ = (
        db.UniqueConstraint('child_kind', 'child_uuid',
                            name='uq_geo_containment_child'),
        {'extend_existing': True},
    )

    id = db.Column(db.Integer, primary_key=True)
    child_kind = db.Column(db.String(16), nullable=False)   # shape | plot
    child_uuid = db.Column(db.String(36), nullable=False)
    # NULL = "계산했고 부모가 없다". 행이 없는 것(미계산)과 구분된다 — 이
    # 구분이 없으면 루트 도형은 영원히 캐시 미스라 매번 기하를 돈다.
    parent_uuid = db.Column(db.String(36), nullable=True, index=True)
    geo_id = db.Column(db.String(64), nullable=True, index=True)
    computed_at = db.Column(db.DateTime, default=utc_now)

    def __repr__(self):
        return "<{cls}({s.child_kind}:{s.child_uuid} -> {s.parent_uuid})>".format(
            s=self, cls=self.__class__.__name__)

# coding=utf-8
"""장치 위치 마커의 좌표 기간 기록 — 추가 전용.

구획은 센서 값을 갖지 않는다. 조회할 때 **구획 위치 × 기간 × 데이터 ID** 를
조합한다(docs/design/geo-plot-instance.md §센서 위치 이력). 그 조합에서
지금 시스템이 **지워 버리는 사실**이 "그 마커가 그 기간에 어디 있었나" 다:

- 좌표를 옮기면 마커 `feature` 를 덮어쓴다(`move_device_markers`, 지도 편집기).
- 장치를 지우면 마커 도형을 지운다(`end_all_for_device`, `delete_shape`).

그래서 좌표를 **기간과 함께** 남긴다. 어느 장치가 그 마커를 맡았는지는
여기 두지 않는다 — 그 정본은 `geo_binding` 의 마커 이력이고(`GeoShape.
device_id` 는 사망 컬럼, GB-6), 같은 사실을 두 곳에 두면 한쪽이 낡는다.

## 쓰는 곳은 리스너 한 곳뿐이다

`_register_marker_position_listeners` 가 Session 클래스에 걸려 ORM 삽입·
수정·삭제와 대량 `Query.update()/delete()` 를 모두 받는다. 좌표를 바꾸는
경로가 다섯 곳이라, 경로마다 부르게 하면 새 경로 하나가 빠질 때 조용히
이력이 끊긴다.

## 기록 이전의 마커

리스너가 생기기 전부터 있던 마커는 행이 없다. 그 마커가 **처음 바뀌는 순간**
바뀌기 전 좌표를 `valid_from=NULL`(처음부터) 인 닫힌 기간으로 먼저 남기고
새 기간을 연다 — 운영 DB 에 일괄 백필을 돌리지 않아도 앞으로의 이동·제거는
빠짐없이 남는다. 한 번도 바뀌지 않은 마커는 조회하는 쪽이 지금 좌표를
"처음부터" 로 읽는다.

@phase active
@stability experimental
@dependency GeoShape, GeoBinding
"""
import json
from datetime import datetime

from aot.aot_flask.extensions import db
from aot.databases import CRUDMixin
from aot.databases import set_uuid


class GeoMarkerPosition(CRUDMixin, db.Model):
    """마커 하나가 한 좌표에 머문 기간."""
    __tablename__ = 'geo_marker_position'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True,
                          default=set_uuid)

    # GeoShape.unique_id(마커). 문자열 참조 — 도형이 지워져도 기록은 남는다.
    shape_uuid = db.Column(db.String(36), nullable=False, index=True)
    geo_id = db.Column(db.String(64), nullable=False, index=True)
    lng = db.Column(db.Float, nullable=False)
    lat = db.Column(db.Float, nullable=False)

    # naive UTC. valid_from=NULL 은 "기록을 시작하기 전부터" 다.
    valid_from = db.Column(db.DateTime, nullable=True)
    valid_to = db.Column(db.DateTime, nullable=True, default=None)
    # 'moved' | 'removed'
    ended_reason = db.Column(db.String(16), nullable=True, default=None)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return ('<GeoMarkerPosition(shape={s.shape_uuid!r}, lng={s.lng}, '
                'lat={s.lat}, {s.valid_from}~{s.valid_to})>'.format(s=self))


#: 좌표 이력을 남기는 도형 종류 — `device_membership._MARKER_TYPES` 와 같다.
MARKER_TYPES = ('aot_device', 'device')

_PENDING = '_aot_marker_position_pending'
_listeners_registered = False


def _feature_dict(feature):
    if isinstance(feature, str):
        try:
            feature = json.loads(feature)
        except (TypeError, ValueError):
            return {}
    return feature if isinstance(feature, dict) else {}


def marker_state(shape_type, geo_id, feature):
    """도형 값 → `(geo_id, lng, lat)`. 좌표를 가진 마커가 아니면 None.

    같은 종류(`device`)라도 폴리곤이면 담당 구역이라 위치 점이 아니다.
    """
    if shape_type not in MARKER_TYPES or not geo_id:
        return None
    geom = _feature_dict(feature).get('geometry') or {}
    if geom.get('type') != 'Point':
        return None
    coords = geom.get('coordinates') or []
    if len(coords) < 2:
        return None
    try:
        return (geo_id, round(float(coords[0]), 9), round(float(coords[1]), 9))
    except (TypeError, ValueError):
        return None


def _reconcile(conn, shape_uuid, before, after, now):
    """마커 하나의 열린 기간을 지금 좌표(`after`)에 맞춘다.

    `before` 는 바뀌기 직전 좌표다. 열린 기간이 없을 때만 쓴다 — 기록 이전
    마커의 첫 변경에서 옛 좌표를 잃지 않기 위해서다.
    """
    from sqlalchemy import insert, select, update

    t = GeoMarkerPosition.__table__
    row = conn.execute(select(t.c.id, t.c.geo_id, t.c.lng, t.c.lat).where(
        t.c.shape_uuid == shape_uuid, t.c.valid_to.is_(None))).first()
    current = ((row.geo_id, round(row.lng, 9), round(row.lat, 9))
               if row is not None else None)
    reason = 'removed' if after is None else 'moved'

    if current is None:
        if before is not None and before != after:
            conn.execute(insert(t).values(
                unique_id=set_uuid(), shape_uuid=shape_uuid,
                geo_id=before[0], lng=before[1], lat=before[2],
                valid_from=None, valid_to=now, ended_reason=reason,
                created_at=now))
    elif current != after:
        conn.execute(update(t).where(t.c.id == row.id).values(
            valid_to=now, ended_reason=reason))

    if after is not None and after != current \
            and (current is not None or before != after):
        conn.execute(insert(t).values(
            unique_id=set_uuid(), shape_uuid=shape_uuid,
            geo_id=after[0], lng=after[1], lat=after[2],
            valid_from=now, valid_to=None, ended_reason=None,
            created_at=now))


def _current_state(conn, shape_uuid):
    from sqlalchemy import select

    from .geo import GeoShape

    t = GeoShape.__table__
    row = conn.execute(select(t.c.type, t.c.geo_id, t.c.feature).where(
        t.c.unique_id == shape_uuid)).first()
    return marker_state(row.type, row.geo_id, row.feature) if row else None


def _register_marker_position_listeners():
    """마커 좌표가 바뀌는 모든 ORM 경로에서 기간을 닫고 연다.

    Session **클래스**에 건다 — 웹 요청·데몬·테스트가 각자 세션을 만들어도
    같은 기록을 남기게 하려는 것이다(`measurement` 의 제거 표시와 같은 이유).
    """
    global _listeners_registered
    if _listeners_registered:
        return
    _listeners_registered = True

    from sqlalchemy import event, select
    from sqlalchemy.orm import Session
    from sqlalchemy.orm.attributes import get_history

    from .geo import GeoShape

    def _old(obj, attr):
        hist = get_history(obj, attr)
        if hist.deleted:
            return hist.deleted[0]
        return getattr(obj, attr)

    def _old_state(obj):
        return marker_state(_old(obj, 'type'), _old(obj, 'geo_id'),
                            _old(obj, 'feature'))

    @event.listens_for(Session, 'before_flush')
    def _collect(session, flush_context, instances):
        pending = session.info.setdefault(_PENDING, {})
        for obj in session.new:
            if not isinstance(obj, GeoShape):
                continue
            if marker_state(obj.type, obj.geo_id, obj.feature) is None:
                continue
            if not obj.unique_id:
                obj.unique_id = set_uuid()
            pending.setdefault(obj.unique_id, None)
        for obj in session.dirty:
            if not isinstance(obj, GeoShape) or not obj.unique_id:
                continue
            if not any(get_history(obj, a).has_changes()
                       for a in ('feature', 'type', 'geo_id')):
                continue
            before = _old_state(obj)
            if before is None and marker_state(
                    obj.type, obj.geo_id, obj.feature) is None:
                continue
            pending.setdefault(obj.unique_id, before)
        for obj in session.deleted:
            if not isinstance(obj, GeoShape) or not obj.unique_id:
                continue
            before = _old_state(obj)
            if before is not None:
                pending.setdefault(obj.unique_id, before)

    @event.listens_for(Session, 'after_flush')
    def _apply(session, flush_context):
        pending = session.info.pop(_PENDING, None)
        if not pending:
            return
        conn = session.connection()
        now = datetime.utcnow()
        for shape_uuid, before in pending.items():
            _reconcile(conn, shape_uuid, before,
                       _current_state(conn, shape_uuid), now)

    @event.listens_for(Session, 'after_soft_rollback')
    def _discard(session, previous_transaction):
        session.info.pop(_PENDING, None)

    @event.listens_for(Session, 'do_orm_execute')
    def _bulk(state):
        # 대량 Query.update()/delete() 는 before_flush 를 지나지 않는다.
        # 지도 편집기 저장·도형 삭제·지도 초기화가 전부 이 모양이다.
        if not (state.is_delete or state.is_update):
            return None
        if not any(m.class_ is GeoShape for m in state.all_mappers):
            return None
        t = GeoShape.__table__
        sel = select(t.c.unique_id, t.c.type, t.c.geo_id, t.c.feature)
        where = state.statement.whereclause
        if where is not None:
            sel = sel.where(where)
        session = state.session
        before = {r.unique_id: marker_state(r.type, r.geo_id, r.feature)
                  for r in session.execute(sel)}
        result = state.invoke_statement()
        if not before:
            return result
        conn = session.connection()
        now = datetime.utcnow()
        for shape_uuid, prev in before.items():
            after = None if state.is_delete else _current_state(conn, shape_uuid)
            if prev is None and after is None:
                continue
            _reconcile(conn, shape_uuid, prev, after, now)
        return result


_register_marker_position_listeners()

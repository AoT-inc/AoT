# coding=utf-8
"""지도 즐겨찾기 — 담기·이름·순서·공유·지우기·목록 (표: `geo_favorite`).

현재 위치 시트(`static/js/geo/aot-map-here.js`)가 `/api/geo/favorites` 로 부르고, 외부 MCP 는
`find.favorites` 로 읽는다. 약 1m 안(`SAME_SPOT_DEG`)이면 같은 장소라 새 행을 만들지 않는다
(먼저 담은 이름을 지킨다). 개인용(`shared` 거짓)은 담은 사람 눈에만 보이고 그 사람만 고친다.
"""
import math

from aot.aot_flask.extensions import db
from aot.databases.models import GeoFavorite

MAX_FAVORITES = 100
#: 이 안(위도·경도 각각 0.00001도, 약 1m)이면 같은 자리다. 반올림 칸으로 가르면 칸 경계에서 0.4m 차이가 다른 자리가 된다.
SAME_SPOT_DEG = 0.00001
NAME_MAX = 80
ADDRESS_MAX = 240


class FavoriteError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def to_dict(row, user=None):
    return {'id': row.id, 'name': row.name, 'lat': row.lat, 'lng': row.lng,
            'address': row.address or '', 'created_by': row.created_by or '',
            'shared': bool(row.shared), 'mine': user is not None and row.created_by == user}


def _visible(user):
    """사용자에게 보이는 행 — 공유된 것과 내가 담은 것. 위 순서대로."""
    rows = GeoFavorite.query.order_by(GeoFavorite.sort_order, GeoFavorite.id).all()
    return [r for r in rows if r.shared or (user is not None and r.created_by == user)]


def listing(user=None):
    return [to_dict(r, user) for r in _visible(user)]


def search(query='', limit=20, user=None):
    """이름·주소에 글자가 든 것(대소문자 무시). MCP 의 find.favorites 가 쓴다."""
    q = str(query or '').strip().lower()
    rows = [r for r in _visible(user) if not q or q in (r.name or '').lower() or q in (r.address or '').lower()]
    return [to_dict(r, user) for r in rows[:max(1, int(limit))]]


def _coord(lat, lng):
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        raise FavoriteError('bad_coordinates', 'lat and lng must be numbers')
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        raise FavoriteError('bad_coordinates', 'lat/lng out of range')
    return round(lat, 6), round(lng, 6)


def _clean_name(name, fallback=''):
    return str(name or '').strip()[:NAME_MAX] or fallback[:NAME_MAX]


def add(name, lat, lng, address='', created_by=None, shared=True):
    """담는다. (행, 새로 만들었는가). 내게 보이는 같은 자리가 이미 있으면 그 행을 돌려준다."""
    lat, lng = _coord(lat, lng)
    for row in _visible(created_by):
        if abs(row.lat - lat) <= SAME_SPOT_DEG and abs(row.lng - lng) <= SAME_SPOT_DEG:
            return row, False
    if GeoFavorite.query.count() >= MAX_FAVORITES:
        raise FavoriteError('limit', 'Too many favorites (max %d).' % MAX_FAVORITES, 409)
    address = str(address or '').strip()[:ADDRESS_MAX]
    last = db.session.query(db.func.max(GeoFavorite.sort_order)).scalar()
    row = GeoFavorite(name=_clean_name(name, address) or '%.5f, %.5f' % (lat, lng), lat=lat, lng=lng,
                      address=address or None, created_by=created_by, shared=bool(shared),
                      sort_order=(last if last is not None else 0.0) + 1.0)
    db.session.add(row)
    db.session.commit()
    return row, True


def _editable(favorite_id, user):
    row = GeoFavorite.query.filter_by(id=favorite_id).first()
    if row is None or not (row.shared or row.created_by == user):
        raise FavoriteError('not_found', 'Favorite not found', 404)
    if not row.shared and row.created_by != user:           # 위에서 걸러지지만 한 번 더
        raise FavoriteError('forbidden', 'Not your favorite', 403)
    return row


def update(favorite_id, user, name=None, shared=None):
    """이름·공유 여부를 고친다. 공유 여부는 담은 사람만 바꾼다."""
    row = _editable(favorite_id, user)
    if name is not None:
        clean = _clean_name(name)
        if not clean:
            raise FavoriteError('bad_name', 'name must not be empty')
        row.name = clean
    if shared is not None:
        if row.created_by != user:
            raise FavoriteError('forbidden', 'Only the owner can change sharing', 403)
        row.shared = bool(shared)
    db.session.commit()
    return row


def move(favorite_id, user, direction):
    """보이는 목록에서 한 칸 위(`up`)·아래(`down`)로. 보이지 않는 개인용 행은 건드리지 않고 순서 값만 맞바꾼다."""
    if direction not in ('up', 'down'):
        raise FavoriteError('bad_direction', "direction must be 'up' or 'down'")
    row = _editable(favorite_id, user)
    seq = _visible(user)
    i = [r.id for r in seq].index(row.id)
    j = i - 1 if direction == 'up' else i + 1
    if 0 <= j < len(seq):
        other = seq[j]
        row.sort_order, other.sort_order = other.sort_order, row.sort_order
        if row.sort_order == other.sort_order:             # 같은 값이면 맞바꿔도 그대로 — 한쪽을 밀어 갈라 준다
            row.sort_order += -0.5 if direction == 'up' else 0.5
        db.session.commit()
    return row


def remove(favorite_id, user=None):
    row = _editable(favorite_id, user)
    db.session.delete(row)
    db.session.commit()

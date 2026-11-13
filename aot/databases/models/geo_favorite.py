# coding=utf-8
"""지도 즐겨찾기 — 사용자가 찾아 둔 장소(주소 검색 결과·눌러 고른 곳).

- 서버(농장) 단위로 저장한다. 어느 기기·계정에서 열어도 같은 목록이고, `created_by` 는 누가 담았는지
  남기는 칸일 뿐 보이는 범위를 가르지 않는다(대상 별칭 `target_alias` 와 같다).
- 약 1m 안(위도·경도 각 0.00001도)이면 같은 장소다 — 다시 담으면 새 행을 만들지 않는다
  (`aot_flask/geo/geo_favorites.py`).
- `shared` 가 거짓이면 만든 사람(`created_by`)만 본다. 기본은 농장 전체 공유다. `sort_order` 는 사용자가 정한 순서다.
- 도형·노트·장치 위치와 무관한 **북마크**다. 지도에 핀으로 그리지 않고, 시트의 목록에서만 쓴다.

@phase active
@stability experimental
"""
import time

from aot.databases.sqla import db
from aot.databases import CRUDMixin


class GeoFavorite(CRUDMixin, db.Model):
    __tablename__ = 'geo_favorite'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(80), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    address = db.Column(db.String(240), nullable=True)
    created_by = db.Column(db.String(64), nullable=True)            # 담은 사용자 이름
    shared = db.Column(db.Boolean, nullable=False, default=True)    # 거짓이면 담은 사람만 본다
    sort_order = db.Column(db.Float, nullable=False, default=0.0)   # 작을수록 위. 담을 때 맨 아래(최대+1)
    created_at = db.Column(db.Float, nullable=False, default=time.time)

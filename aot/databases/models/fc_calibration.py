# coding=utf-8
"""예보 현장 보정(L2) — 계수 판·대지 상태·알림 (예보·트윈 데이터 관리 D4, 설계 §4.3).

- `fc_calibration_site`: 대지당 한 줄. 보정 방식(`mode`: auto 자동 / on 항상 켬 / off 끔), 지금 쓰는 판(`active_rev`),
  마지막 점검 시각·요약.
- `fc_calibration`: **판(rev)마다 (종류, 변수, 리드대) 한 줄** — 계수 JSON·상태·성적 요약. 판은 지우지 않는다(행이 작다).
  계수 + L0 예보가 있으면 L2 를 정확히 다시 만들 수 있다. 한 판은 대지의 모든 (종류, 변수, 리드대)를 담는다 —
  쓰는 판 = 그 대지의 `active_rev`. 판 번호 0 은 '원본'(보정 없음)이라 행이 없다.
- `fc_cal_event`: 채택·되돌림이 일어날 때마다 한 줄(어느 대지·변수·리드대, 전후 성적, 판 번호). 값이 조용히 바뀌지
  않게 하려는 것이다. `acked` 는 사람이 확인했는지.

@phase active
@stability experimental
@dependency GeoShape
"""
import json
from datetime import datetime

from aot.databases.sqla import db
from aot.databases import CRUDMixin
from aot.databases import set_uuid

MODES = ('auto', 'on', 'off')


def _loads(text, default):
    try:
        d = json.loads(text) if text else default
    except (TypeError, ValueError):
        return default
    return d if isinstance(d, type(default)) else default


class FcCalibrationSite(CRUDMixin, db.Model):
    __tablename__ = 'fc_calibration_site'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    site_id = db.Column(db.String(80), nullable=False, unique=True, index=True)
    mode = db.Column(db.String(8), nullable=False, default='auto')
    active_rev = db.Column(db.Integer, nullable=False, default=0)
    last_run_at = db.Column(db.Float, nullable=True)
    last_result = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)

    def result_dict(self):
        return _loads(self.last_result, {})

    def __repr__(self):
        return "<{cls}(site={s}, mode={m}, rev={r})>".format(
            cls=self.__class__.__name__, s=self.site_id, m=self.mode, r=self.active_rev)


class FcCalibration(CRUDMixin, db.Model):
    __tablename__ = 'fc_calibration'
    __table_args__ = (db.UniqueConstraint('site_id', 'rev', 'kind', 'var', 'band', name='uq_fc_calibration_item'),
                      {'extend_existing': True})

    id = db.Column(db.Integer, unique=True, primary_key=True)
    site_id = db.Column(db.String(80), nullable=False, index=True)
    rev = db.Column(db.Integer, nullable=False, index=True)
    kind = db.Column(db.String(1), nullable=False)               # 'h' 시간별 | 'd' 일별
    var = db.Column(db.String(8), nullable=False)
    band = db.Column(db.String(8), nullable=False)
    status = db.Column(db.String(16), nullable=False)
    reason = db.Column(db.String(32), nullable=True)
    method = db.Column(db.String(16), nullable=True)
    coef = db.Column(db.Text, nullable=True)                      # 계수 JSON (상태가 쓰지 않는 것이어도 남는다)
    meta = db.Column(db.Text, nullable=True)                      # 성적 요약·되돌린 시각·관측 출처 …
    window_start = db.Column(db.Float, nullable=True)
    window_end = db.Column(db.Float, nullable=True)
    l0_kind = db.Column(db.String(16), nullable=False, default='actual')   # actual | archived_run (D8)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def coef_dict(self):
        return _loads(self.coef, {})

    def meta_dict(self):
        return _loads(self.meta, {})

    def __repr__(self):
        return "<{cls}(site={s}, rev={r}, {k}/{v}/{b}, {st})>".format(
            cls=self.__class__.__name__, s=self.site_id, r=self.rev, k=self.kind, v=self.var, b=self.band,
            st=self.status)


class FcCalEvent(CRUDMixin, db.Model):
    __tablename__ = 'fc_cal_event'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    site_id = db.Column(db.String(80), nullable=False, index=True)
    rev = db.Column(db.Integer, nullable=False)
    event = db.Column(db.String(16), nullable=False)              # adopted | reverted
    kind = db.Column(db.String(1), nullable=False)
    var = db.Column(db.String(8), nullable=False)
    band = db.Column(db.String(8), nullable=False)
    detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    acked = db.Column(db.Boolean, nullable=False, default=False)

    def detail_dict(self):
        return _loads(self.detail, {})

    def __repr__(self):
        return "<{cls}(site={s}, {e}, {k}/{v}/{b}, rev={r})>".format(
            cls=self.__class__.__name__, s=self.site_id, e=self.event, k=self.kind, v=self.var, b=self.band,
            r=self.rev)

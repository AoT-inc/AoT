# coding=utf-8
"""디지털트윈(실험) 대지·구획 설정 — 사람이 고른 것만 담는다 (배포 제안 개정 2 §2·§7 S3).

행 하나 = 대상 하나(`scope` 'site' | 'plot').

- `target_id`: 대지 = 지도의 site 도형 `GeoShape.unique_id`(대지 밖 구획 묶음은 `map:<GeoMap id>`),
  구획 = `GeoPlot.unique_id`. 문자열 참조 — 도형이 지워져도 행은 남고, 서비스는 없는 대상을 그냥 건너뛴다.
- `enabled`: 대지 = 켜기(None·False 꺼짐). 구획 = None 이면 대지를 따른다(포함), False 면 제외, True 면 포함.
- `config`(JSON): `{"inputs": {논리 이름: {unique_id, unit, channel, provenance} | null},
  "options": {...}, "forecast": {"input": 입력 id, "max_age_h": 36} | null}`.
  키가 없으면 **위(대지)에서 물려받고**, 값이 null 이면 "여기서는 없음"으로 덮어쓴다.
  provenance(실측·미러·가상·미확인)는 사용자가 정한다 — 동기화·검증에는 실측만 쓴다.

자동으로 채우는 것(구획 목록·심은 날·시간대·위도·예보 사다리)과 제안(센서·출처 후보)은 여기 저장하지 않는다.
제안은 사용자가 '적용' 할 때만 이 행에 들어온다.

@phase active
@stability experimental
@dependency GeoShape, GeoPlot, Input
"""
import json
from datetime import datetime

from aot.databases.sqla import db
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.utils.timekit import naive_utc, utc_now

SCOPES = ('site', 'plot')


class TwinConfig(CRUDMixin, db.Model):
    """대지·구획 트윈 설정 한 줄."""
    __tablename__ = 'twin_config'
    __table_args__ = (db.UniqueConstraint('scope', 'target_id', name='uq_twin_config_target'),
                      {'extend_existing': True})

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    scope = db.Column(db.String(8), nullable=False)
    target_id = db.Column(db.String(80), nullable=False, index=True)
    enabled = db.Column(db.Boolean, nullable=True, default=None)
    config = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)

    def config_dict(self):
        try:
            d = json.loads(self.config) if self.config else {}
        except (TypeError, ValueError):
            d = {}
        return d if isinstance(d, dict) else {}

    def set_config(self, d):
        self.config = json.dumps(d or {}, ensure_ascii=False, sort_keys=True)
        self.updated_at = naive_utc(utc_now())

    def __repr__(self):
        return "<{cls}(scope={s}, target={t}, enabled={e})>".format(
            cls=self.__class__.__name__, s=self.scope, t=self.target_id, e=self.enabled)

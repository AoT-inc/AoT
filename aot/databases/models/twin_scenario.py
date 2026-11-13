# coding=utf-8
"""트윈 시나리오 정의·분석 실행 색인 (예보·트윈 데이터 관리 D7, 설계 §6.2·§6.6).

- `twin_scenario`: 시나리오 한 건의 정의와 계보. 곡선은 Influx(`env_twin_scn*`, 태그 `scenario`)에 있고 이 행은 정의다.
  `overrides` 는 **불투명 JSON** 으로 저장만 한다(뜻은 장치 효과 세션 소유). 시각은 모두 UTC epoch 초(Float).
  `expires_at` 은 **곡선 만료 시각**이다(만든 때 + 30일, 고정하면 NULL). 정의 자체는 곡선이 만료된 뒤에도
  `created_at + 365일` 까지 남고 그 정리는 하루 점검(`data_retention.expire_scenarios`)이 한다.
- `twin_run`: 발행 한 건(대상 + `t0`)의 색인·계보. 곡선은 `env_twin*` 에 있다. 시나리오의 `base_run` 이 가리킨다.
  보존은 분석 이력(`aot_hist`)과 같다(기본 730일, `t0` 기준).

@phase active
@stability experimental
"""
import json

from aot.databases.sqla import db
from aot.databases import CRUDMixin

SCHEMA_VERSION = 1
STATUSES = ('queued', 'running', 'done', 'failed', 'curve_expired')
BASE_MODES = ('hold', 'schedule', 'policy')
FUTURE_INPUT_MODES = ('hold', 'schedule', 'policy', 'whatif')
TARGET_KINDS = ('field', 'facility')


def _loads(text, default):
    try:
        d = json.loads(text) if text else default
    except (TypeError, ValueError):
        return default
    return d if isinstance(d, type(default)) else default


class TwinScenario(CRUDMixin, db.Model):
    __tablename__ = 'twin_scenario'
    __table_args__ = (db.Index('ix_twin_scenario_target', 'target_kind', 'target_id'), {'extend_existing': True})

    id = db.Column(db.String(8), primary_key=True)                 # 8자 16진. 'baseline' 은 예약어
    target_kind = db.Column(db.String(8), nullable=False)          # field | facility
    target_id = db.Column(db.String(80), nullable=False)
    label = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.Float, nullable=False, index=True)
    requested_at = db.Column(db.Float, nullable=True)
    finished_at = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(16), nullable=False, default='queued')
    pinned = db.Column(db.Boolean, nullable=False, default=False)
    expires_at = db.Column(db.Float, nullable=True)                # 곡선 만료. 고정하면 NULL
    base_run = db.Column(db.String(120), nullable=True)            # twin_run.run_id
    base_mode = db.Column(db.String(8), nullable=False, default='hold')
    future_input_mode = db.Column(db.String(8), nullable=False, default='hold')
    overrides = db.Column(db.Text, nullable=True)                  # 불투명 JSON {actuators[], weather[], supply[]}
    effects = db.Column(db.Text, nullable=True)                    # JSON [{kind, channel, status, source}]
    model_rev = db.Column(db.Integer, nullable=True)
    cal_rev = db.Column(db.Integer, nullable=True)                 # 0 = 원본
    fc_issue_epoch = db.Column(db.Float, nullable=True)
    weather_src = db.Column(db.Integer, nullable=True)
    obs_origin = db.Column(db.Integer, nullable=True)
    fail_reason = db.Column(db.String(200), nullable=True)
    schema_version = db.Column(db.Integer, nullable=False, default=SCHEMA_VERSION)

    def overrides_dict(self):
        return _loads(self.overrides, {})

    def effects_list(self):
        return _loads(self.effects, [])

    def __repr__(self):
        return "<{cls}(id={i}, {k}/{t}, {s})>".format(cls=self.__class__.__name__, i=self.id, k=self.target_kind,
                                                      t=self.target_id, s=self.status)


class TwinRun(CRUDMixin, db.Model):
    __tablename__ = 'twin_run'
    __table_args__ = (db.Index('ix_twin_run_target_t0', 'target_kind', 'target_id', 't0'), {'extend_existing': True})

    run_id = db.Column(db.String(120), primary_key=True)           # '<t0 epoch 정수>:<대상 id>'
    target_kind = db.Column(db.String(8), nullable=False)
    target_id = db.Column(db.String(80), nullable=False)
    t0 = db.Column(db.Float, nullable=False, index=True)
    status = db.Column(db.Integer, nullable=True)                  # env_twin_meta 채널 0 (Status)
    model_rev = db.Column(db.Integer, nullable=True)
    cal_rev = db.Column(db.Integer, nullable=True)
    fc_issue_epoch = db.Column(db.Float, nullable=True)
    weather_src = db.Column(db.Integer, nullable=True)
    obs_origin = db.Column(db.Integer, nullable=True)
    policy = db.Column(db.Integer, nullable=True)
    plan_src = db.Column(db.Integer, nullable=True)
    fit = db.Column(db.Text, nullable=True)                        # 일치도 요약 JSON (sync_rmse_*·coverage_80 …)

    def fit_dict(self):
        return _loads(self.fit, {})

    def __repr__(self):
        return "<{cls}(run={r}, status={s})>".format(cls=self.__class__.__name__, r=self.run_id, s=self.status)

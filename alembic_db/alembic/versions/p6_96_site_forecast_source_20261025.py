# coding=utf-8
"""P6-96: 대지 예보 출처 하나로 — twin_config.forecast.input → geo_binding(weather, role='forecast').

디지털트윈 탭의 예보 칸(`twin_config` 대지 행의 `forecast.input`)과 기상원 지정 화면이 서로 다른 곳에 예보 입력을
적던 것을 한 저장소로 모은다. 대지의 예보 출처는 이제 `geo_binding` 의
`spatial_kind='weather'`, `spatial_id=대지`, `role='forecast'` 행이다(지정 순서 = `params.order`). 트윈·지도
날씨·AI 가 모두 그 행을 읽는다(`aot.aot_flask.geo.forecast_series`).

- 대지 행의 `forecast.input` 마다, 같은 입력의 현재 예보 출처 행이 없으면 하나 만든다(순서 0 — 기존 지정 뒤가 아니라
  앞: 트윈이 쓰던 입력이 그대로 첫 일별 출처가 된다).
- 대지·구획 행에서 `forecast` 키를 지운다(구획 단위 예보 덮어쓰기는 없앤다 — 대지 하나).
- 입력이 실제로 없으면(지워진 입력) 행을 만들지 않고 키만 지운다.

재실행 안전: 이미 있는 지정은 건너뛴다. downgrade 는 예보 출처 행을 대지 행의 `forecast.input` 으로 되돌린다
(첫 일별 입력을 고르지 못하므로 첫 지정 하나).

Revision ID: p6_96_site_forecast_source_20261025
Revises: p6_95_mcp_embedded_oauth_20261024
Create Date: 2026-10-25
"""
import json
import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = 'p6_96_site_forecast_source_20261025'
down_revision = 'p6_95_mcp_embedded_oauth_20261024'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _cfg(text):
    try:
        d = json.loads(text) if text else {}
    except (TypeError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def upgrade():
    if not {'twin_config', 'geo_binding', 'input'} <= _tables():
        return
    bind = op.get_bind()
    now = datetime.utcnow()
    rows = bind.execute(sa.text("SELECT id, scope, target_id, config FROM twin_config")).fetchall()
    for rid, scope, target, text in rows:
        cfg = _cfg(text)
        if cfg is None or 'forecast' not in cfg:
            continue
        fc = cfg.pop('forecast')
        uid = str((fc or {}).get('input') or '').strip() if isinstance(fc, dict) else ''
        if scope == 'site' and uid:
            exists = bind.execute(sa.text("SELECT 1 FROM input WHERE unique_id = :u"), {'u': uid}).first()
            have = bind.execute(sa.text(
                "SELECT 1 FROM geo_binding WHERE spatial_kind = 'weather' AND spatial_id = :s "
                "AND role = 'forecast' AND device_id = :u AND valid_to IS NULL"), {'s': target, 'u': uid}).first()
            if exists and not have:
                bind.execute(sa.text(
                    "INSERT INTO geo_binding (unique_id, spatial_kind, spatial_id, role, device_kind, device_id, "
                    "channel_id, measurement_id, valid_from, valid_to, ended_reason, params, created_at) "
                    "VALUES (:uid, 'weather', :s, 'forecast', 'input', :u, '0', NULL, :now, NULL, NULL, :p, :now)"),
                    {'uid': str(uuid.uuid4()), 's': target, 'u': uid, 'now': now, 'p': json.dumps({'order': 0})})
        bind.execute(sa.text("UPDATE twin_config SET config = :c WHERE id = :i"),
                     {'c': json.dumps(cfg, ensure_ascii=False), 'i': rid})


def downgrade():
    if not {'twin_config', 'geo_binding'} <= _tables():
        return
    bind = op.get_bind()
    got = bind.execute(sa.text(
        "SELECT spatial_id, device_id, params FROM geo_binding WHERE spatial_kind = 'weather' "
        "AND role = 'forecast' AND valid_to IS NULL ORDER BY id")).fetchall()
    first = {}
    for site, dev, params in got:
        p = _cfg(params) if isinstance(params, str) else (params or {})
        order = (p or {}).get('order', 1 << 30)
        if site not in first or order < first[site][0]:
            first[site] = (order, dev)
    for site, (_o, dev) in first.items():
        row = bind.execute(sa.text("SELECT id, config FROM twin_config WHERE scope = 'site' AND target_id = :s"),
                           {'s': site}).first()
        if row is None:
            continue
        cfg = _cfg(row[1]) or {}
        cfg['forecast'] = {'input': dev}
        bind.execute(sa.text("UPDATE twin_config SET config = :c WHERE id = :i"),
                     {'c': json.dumps(cfg, ensure_ascii=False), 'i': row[0]})
    bind.execute(sa.text(
        "UPDATE geo_binding SET valid_to = :now, ended_reason = 'unbound' WHERE spatial_kind = 'weather' "
        "AND role = 'forecast' AND valid_to IS NULL"), {'now': datetime.utcnow()})

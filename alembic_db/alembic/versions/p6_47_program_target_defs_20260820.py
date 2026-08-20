# coding=utf-8
"""P6-47: 목표 항목 정의를 프로그램이 갖는다.

정본: docs/design/program-layer.md §목표 항목

`geo_program.target_defs` — 이 프로그램이 다루는 목표 항목의 정의
(`[{key, label, unit, measurement, shape, min, max, fixed, hidden}]`).

예전에는 여섯 항목이 `program_io._TARGET_FIELDS` 에 코드로 박혀 있었다. 그래서
**종류를 몰랐다** — 축사 프로그램의 편집 화면에도 DLI·VPD 칸이 그대로 나왔고,
반대로 EC·pH 처럼 실제로 관리하는 값은 적을 칸이 없었다.

## 기존 행 채우기

`kind` 의 고정 항목으로 채운다(`vegetation` 은 예전 여섯 항목 그대로, 가축·시설·
기타는 빈 목록). **값(`stages[].targets`)은 건드리지 않는다** — 어휘가 그대로라
식생 프로그램의 기존 값은 전부 정의 안에 들어온다.

`server_default` 를 두지 않는 이유: 이 컬럼은 `kind` 마다 다른 값이라 상수 기본이
성립하지 않는다. 대신 모델의 `target_def_list()` 가 비어 있으면 고정 항목으로
답하므로, 이 마이그레이션이 돌기 전이나 JSON 이 깨진 행에서도 읽는 쪽은 같은
목록을 본다.

Revision ID: p6_47_program_target_defs_20260820
Revises: p6_46_program_auto_advance_20260819
Create Date: 2026-08-20
"""
import json

import sqlalchemy as sa
from alembic import op

revision = 'p6_47_program_target_defs_20260820'
down_revision = 'p6_46_program_auto_advance_20260819'
branch_labels = None
depends_on = None


# 마이그레이션은 **자기 시점의 표를 들고 있어야 한다.** `program_io` 에서
# import 하면 나중에 그 표가 바뀌었을 때 과거 마이그레이션의 결과가 소급해
# 달라진다(이 저장소가 시드에서 이미 겪은 종류의 갈림).
_FIXED = {
    'vegetation': [
        {'key': 'temp_day',   'label': 'Day temp',   'unit': '°C',
         'measurement': 'temperature', 'shape': 'instant', 'when': 'day',
         'min': -30.0, 'max': 60.0, 'fixed': True, 'hidden': False},
        {'key': 'temp_night', 'label': 'Night temp', 'unit': '°C',
         'measurement': 'temperature', 'shape': 'instant', 'when': 'night',
         'min': -30.0, 'max': 60.0, 'fixed': True, 'hidden': False},
        {'key': 'rh',         'label': 'Humidity',   'unit': '%',
         'measurement': 'humidity', 'shape': 'instant',
         'min': 0.0, 'max': 100.0, 'fixed': True, 'hidden': False},
        {'key': 'co2',        'label': 'CO2',        'unit': 'ppm',
         'measurement': 'co2', 'shape': 'instant',
         'min': 0.0, 'max': 5000.0, 'fixed': True, 'hidden': False},
        {'key': 'dli',        'label': 'DLI',        'unit': 'mol/m²/d',
         'measurement': 'radiation', 'shape': 'daily',
         'min': 0.0, 'max': 80.0, 'fixed': True, 'hidden': False},
        {'key': 'vpd',        'label': 'VPD',        'unit': 'kPa',
         'measurement': 'vapor_pressure_deficit', 'shape': 'instant',
         'min': 0.0, 'max': 10.0, 'fixed': True, 'hidden': False},
    ],
    'livestock': [],
    'facility':  [],
    'other':     [],
}


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table('geo_program'):
        return

    cols = {c['name'] for c in insp.get_columns('geo_program')}
    if 'target_defs' not in cols:
        with op.batch_alter_table('geo_program') as batch:
            batch.add_column(sa.Column('target_defs', sa.JSON(), nullable=True))

    # 기존 행 채우기. 종류마다 다르므로 한 줄씩 본다 — 프로그램 수는 사람이 만든
    # 만큼이라 많아야 수십 건이다.
    rows = bind.execute(sa.text(
        'SELECT id, kind FROM geo_program WHERE target_defs IS NULL')).fetchall()
    for row_id, kind in rows:
        defs = _FIXED.get(kind or 'vegetation', [])
        bind.execute(
            sa.text('UPDATE geo_program SET target_defs = :d WHERE id = :i'),
            {'d': json.dumps(defs, ensure_ascii=False), 'i': row_id})


def downgrade():
    insp = sa.inspect(op.get_bind())
    if not insp.has_table('geo_program'):
        return
    cols = {c['name'] for c in insp.get_columns('geo_program')}
    if 'target_defs' in cols:
        with op.batch_alter_table('geo_program') as batch:
            batch.drop_column('target_defs')

# coding=utf-8
"""P6-44: 식생 구획(`geo_planting`) → **공간 구획(`geo_plot`)**. 대상 종류를 갖는다.

정본: docs/design/geo-plot-instance.md

## 왜

`GeoProgram` 은 이미 `kind`(vegetation | livestock | facility | other)를 갖는데,
그 프로그램을 붙일 대상이 식생밖에 없었다 — 절반만 넓힌 상태다. 가축 프로그램을
만들 수는 있어도 어느 축사에 적용됐는지 적을 자리가 없다.

이름도 함께 틀렸다. `crop` / `planted_on` 은 젖소에도 가로수 점검에도 맞지 않는다.

## 컬럼

- `crop` → `subject`      : `GeoProgram.subject` 와 같은 축이라 이름도 같게 한다
- `planted_on` → `started_on` : "심다" 는 식생에만 있다
- `kind` 추가             : `GeoProgram.kind` 와 **같은 어휘**. 기존 행은 전부 식생

## 인덱스

`rename_table` 은 SQLite 에서 인덱스를 따라오게 하지만 **이름은 옛 것 그대로**다
(`ix_geo_planting_ended_on`). 새 설치는 `create_all`(모델 기준)이라 `ix_geo_plot_*`
로 생기므로, 여기서 이름을 맞추지 않으면 **서버마다 인덱스 이름이 달라진다** —
에러는 나지 않고 이후 마이그레이션이 이름으로 인덱스를 찾을 때 조용히 빗나간다
(p6_34 에서 ended_on 인덱스가 실제로 한 번 어긋나 있었다).

Revision ID: p6_44_geo_plot_20260819
Revises: p6_43_program_kind_20260819
Create Date: 2026-08-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_44_geo_plot_20260819'
down_revision = 'p6_43_program_kind_20260819'
branch_labels = None
depends_on = None

_OLD = 'geo_planting'
_NEW = 'geo_plot'

# (옛 이름, 새 이름, 컬럼)
_INDEXES = [
    ('ix_geo_planting_ended_on', 'ix_geo_plot_ended_on', 'ended_on'),
    ('ix_geo_planting_geo_id', 'ix_geo_plot_geo_id', 'geo_id'),
    ('ix_geo_planting_facility_uuid', 'ix_geo_plot_facility_uuid',
     'facility_uuid'),
    ('ix_geo_planting_program_uuid', 'ix_geo_plot_program_uuid',
     'program_uuid'),
]


def _rename_theme_keys(bind, old='vegetation', new='plot'):
    """`GeoSetting.theme_config` JSON 안의 색·표시 키를 옮긴다.

    JSON 컬럼이라 SQL 로 키 하나만 바꿀 수 없다 — 읽어서 고쳐 다시 쓴다.
    행이 없거나 형식이 다르면 조용히 지나간다(색 설정 때문에 업그레이드
    전체가 막히면 안 된다).
    """
    import json
    insp = sa.inspect(bind)
    if not insp.has_table('geo_setting'):
        return
    try:
        rows = bind.execute(sa.text(
            'SELECT id, theme_config FROM geo_setting')).fetchall()
    except Exception:
        return
    for rid, raw in rows:
        if not raw:
            continue
        try:
            cfg = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except Exception:
            continue
        if not isinstance(cfg, dict):
            continue
        moved = False
        for a, b in ((old, new),
                     ('vis_shape_%s' % old, 'vis_shape_%s' % new)):
            if a in cfg and b not in cfg:
                cfg[b] = cfg.pop(a)
                moved = True
        if not moved:
            continue
        try:
            bind.execute(sa.text(
                'UPDATE geo_setting SET theme_config = :c WHERE id = :i'),
                {'c': json.dumps(cfg), 'i': rid})
        except Exception:
            continue


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table(_OLD) and not insp.has_table(_NEW):
        op.rename_table(_OLD, _NEW)

    # ⚠ rename 뒤에는 **inspector 를 새로 만든다.** 옛 inspector 는 방금 만든
    # 이름을 모르므로 `has_table(_NEW)` 가 False 를 돌려주고, 그대로 return 하면
    # 테이블만 옮겨진 채 컬럼이 안 붙는다 — 마이그레이션은 "성공" 으로 남는다
    # (p6_43 에서 실제로 그렇게 한 번 지나갔다).
    insp = sa.inspect(bind)
    if not insp.has_table(_NEW):
        return

    cols = {c['name'] for c in insp.get_columns(_NEW)}
    with op.batch_alter_table(_NEW) as batch:
        if 'crop' in cols and 'subject' not in cols:
            batch.alter_column('crop', new_column_name='subject',
                               existing_type=sa.String(64), nullable=False)
        if 'planted_on' in cols and 'started_on' not in cols:
            batch.alter_column('planted_on', new_column_name='started_on',
                               existing_type=sa.Date(), nullable=False)
        if 'kind' not in cols:
            batch.add_column(sa.Column('kind', sa.String(24), nullable=False,
                                       server_default='vegetation'))

    # 기존 행은 전부 식생이다 — 명시적으로 채워 둔다(server_default 는 앞으로
    # 들어올 행에만 걸리고, 나중에 default 를 빼면 그 흔적이 사라진다).
    bind.execute(sa.text(
        "UPDATE %s SET kind='vegetation' WHERE kind IS NULL OR kind=''" % _NEW))

    # 구획 노트의 `target_type` 도 함께 옮긴다. 코드가 'plot' 으로 조회하는데
    # 저장된 행이 'planting' 이면 **노트가 조용히 사라진다** — 에러도 빈 목록도
    # 아니고 "노트가 없는 구획" 으로 보인다. 지우는 것이 아니라 옮기는 것이므로
    # 되돌림(downgrade)도 대칭으로 둔다.
    bind.execute(sa.text(
        "UPDATE notes SET target_type='plot' WHERE target_type='planting'"))

    # 지도 도형 색의 정본은 `GeoSetting.theme_config` 하나다(전역 싱글톤).
    # 그 안의 색 키 `vegetation` 도 함께 옮긴다 — 코드가 'plot' 으로 조회하는데
    # 저장된 키가 'vegetation' 이면 **사용자가 고른 색이 조용히 기본색으로
    # 돌아간다**(에러 없음). `vis_shape_vegetation`(레이어 표시 여부)도 같은 결.
    _rename_theme_keys(bind)

    existing = {i['name'] for i in sa.inspect(bind).get_indexes(_NEW)}
    for old_name, new_name, col in _INDEXES:
        if new_name in existing:
            continue
        if old_name in existing:
            op.drop_index(old_name, table_name=_NEW)
        op.create_index(new_name, _NEW, [col])
    if 'ix_geo_plot_kind' not in existing:
        op.create_index('ix_geo_plot_kind', _NEW, ['kind'])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_NEW):
        return

    for _old, new_name, _col in _INDEXES + [(None, 'ix_geo_plot_kind', None)]:
        if new_name in {i['name'] for i in sa.inspect(bind).get_indexes(_NEW)}:
            op.drop_index(new_name, table_name=_NEW)

    cols = {c['name'] for c in insp.get_columns(_NEW)}
    with op.batch_alter_table(_NEW) as batch:
        if 'subject' in cols:
            batch.alter_column('subject', new_column_name='crop',
                               existing_type=sa.String(64), nullable=False)
        if 'started_on' in cols:
            batch.alter_column('started_on', new_column_name='planted_on',
                               existing_type=sa.Date(), nullable=False)
        if 'kind' in cols:
            batch.drop_column('kind')

    bind.execute(sa.text(
        "UPDATE notes SET target_type='planting' WHERE target_type='plot'"))
    _rename_theme_keys(bind, old='plot', new='vegetation')
    op.rename_table(_NEW, _OLD)
    for old_name, _new, col in _INDEXES:
        op.create_index(old_name, _OLD, [col])

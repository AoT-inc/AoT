# coding=utf-8
"""P6-10: 깨진 기본 단위변환식 2건 복구 (K→F, GB→MB).

`aot/config_devices_units.py`의 UNIT_CONVERSIONS 시드 데이터에 오타가 있어
두 변환이 모든 설치본에서 조용히 실패하고 있었다:

- K → F : '(x*9/5)−459.67'  ← U+2212 MINUS SIGN. 파이썬은 ASCII '-'만 받으므로
  SyntaxError. 온도 변환 중 유일하게 깨져 있었다.
- GB → MB: 'X*1000'         ← 대문자 X. 치환 대상은 소문자 'x'라 NameError.

두 건 모두 Phase 3 보안 작업(사용자 수식 eval → safe_eval 교체) 중
실사용 수식 251건 전수 검증에서 발견됐다. 보안 변경이 만든 회귀가 아니라
그 전부터 존재하던 데이터 결함이며, 구 eval 경로에서도 예외로 실패함을
실증 확인했다.

시드 로직(`databases/models/__init__.py`의 populate_db)은 (from, to) 쌍이
없을 때만 INSERT 하고 기존 행을 갱신하지 않는다. 따라서 config 파일 수정만으로는
신규 설치에만 반영되고 기존 DB는 계속 깨진 값을 유지한다 — 이 마이그레이션이
기존 행을 복구한다.

정확히 깨진 문자열과 일치할 때만 갱신하므로 멱등하며, 사용자가 손댄 값이나
이미 정상인 값은 건드리지 않는다.

Revision ID: p6_10_fix_broken_conversions_20260727
Revises: p6_09_remote_admin_token_20260727
Create Date: 2026-07-27
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_10_fix_broken_conversions_20260727'
down_revision = 'p6_09_remote_admin_token_20260727'
branch_labels = None
depends_on = None

_TABLE = 'conversion'

# (convert_unit_from, convert_unit_to, 깨진 값, 고친 값)
_REPAIRS = [
    ('K', 'F', '(x*9/5)−459.67', '(x*9/5)-459.67'),
    ('GB', 'MB', 'X*1000', 'x*1000'),
]


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade():
    if not _has_table(_TABLE):
        return
    bind = op.get_bind()
    for conv_from, conv_to, broken, fixed in _REPAIRS:
        bind.execute(
            sa.text(
                "UPDATE conversion SET equation = :fixed "
                "WHERE convert_unit_from = :cfrom "
                "AND convert_unit_to = :cto "
                "AND equation = :broken"),
            {'fixed': fixed, 'cfrom': conv_from, 'cto': conv_to, 'broken': broken})


def downgrade():
    if not _has_table(_TABLE):
        return
    bind = op.get_bind()
    for conv_from, conv_to, broken, fixed in _REPAIRS:
        bind.execute(
            sa.text(
                "UPDATE conversion SET equation = :broken "
                "WHERE convert_unit_from = :cfrom "
                "AND convert_unit_to = :cto "
                "AND equation = :fixed"),
            {'broken': broken, 'cfrom': conv_from, 'cto': conv_to, 'fixed': fixed})

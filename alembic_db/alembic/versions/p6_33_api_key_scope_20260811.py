# coding=utf-8
"""P6-33: API 키에 스코프를 준다 — user_api_key.scope.

API 키는 지금까지 **그 사용자의 전 권한**이었다. `load_user_from_request` 가
키로 User 를 찾아 그대로 로그인시키기 때문에, 키를 하나 건네는 것은 그 계정을
통째로 건네는 것과 같았다. 그래서 다른 AoT 서버의 데이터를 받아오기만 하려
해도 상대에게 내 장치 제어권까지 함께 넘겨야 했다.

'readonly' 스코프는 그 키로 들어온 요청에 한해 쓰기 권한(edit_*)을 거부한다.
계정을 하나 더 만들어 우회하라는 안내로 때워 왔지만, 계정을 만드는 일과 키
하나를 좁히는 일은 부담이 다르다.

기본값은 'full' 이다. 이미 발급된 키(백필된 레거시 키 포함)의 동작이
업그레이드로 조용히 바뀌면, 돌고 있던 연동이 아무 예고 없이 끊긴다.

Revision ID: p6_33_api_key_scope_20260811
Revises: p6_32_user_api_keys_20260811
Create Date: 2026-08-11
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_33_api_key_scope_20260811'
down_revision = 'p6_32_user_api_keys_20260811'
branch_labels = None
depends_on = None

_TABLE = 'user_api_key'
_COLUMN = 'scope'


def _has_column(table, column):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return column in [c['name'] for c in inspector.get_columns(table)]


def upgrade():
    # 재실행 안전: 이미 있으면 건너뛴다.
    if _has_column(_TABLE, _COLUMN):
        return
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            _COLUMN, sa.String(length=16), nullable=False,
            # server_default 가 있어야 기존 행에도 'full' 이 들어간다. NULL 로
            # 두면 스코프 판정이 매번 None 을 만나는데, 안전한 쪽으로 읽으면
            # 돌던 키가 읽기 전용으로 바뀌어 연동이 끊기고, 느슨한 쪽으로 읽으면
            # 스코프가 없는 것과 같아진다. 값을 채워 두는 편이 낫다.
            server_default='full'))


def downgrade():
    if not _has_column(_TABLE, _COLUMN):
        return
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_column(_COLUMN)

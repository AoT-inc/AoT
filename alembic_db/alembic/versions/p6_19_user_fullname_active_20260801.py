# coding=utf-8
"""P6-19: 사용자 표시 이름과 사용 여부 — users 에 full_name/is_enabled 추가.

users.name 은 로그인 계정이라 영숫자 유일값이고("koat", "5739"), 목록에서
누가 누구인지 알아볼 수가 없었다. 사람이 읽는 이름을 따로 두고, 화면은
full_name 이 있으면 그것을, 없으면 지금까지처럼 name 을 보여준다.

is_enabled 는 계정을 삭제하지 않고 잠시 막는 스위치다. is_active 라는 이름을
피한 이유는 flask_login UserMixin 이 같은 이름의 프로퍼티를 갖고 있어서다 —
컬럼으로 덮어쓰면 로그인 경로가 login_user() 에 넘기는 빈 User() 인스턴스의
값이 None 이 되어 모든 로그인이 거부된다(aot/databases/models/user.py 주석).

기존 행: full_name 은 NULL(= 지금까지와 같은 표시), is_enabled 는 1.

Revision ID: p6_19_user_fullname_active_20260801
Revises: p6_18_user_role_position_20260801
Create Date: 2026-08-01
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_19_user_fullname_active_20260801'
down_revision = 'p6_18_user_role_position_20260801'
branch_labels = None
depends_on = None

_TABLE = 'users'
_COLUMNS = (
    ('full_name', sa.VARCHAR(length=64), True, None),
    ('is_enabled', sa.Boolean(), False, '1'),
)


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def _has_column(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = [c['name'] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def upgrade():
    if not _has_table(_TABLE):
        return
    for name, type_, nullable, default in _COLUMNS:
        if _has_column(_TABLE, name):
            continue
        kwargs = {'nullable': nullable}
        if default is not None:
            kwargs['server_default'] = sa.text(default)
        op.add_column(_TABLE, sa.Column(name, type_, **kwargs))


def downgrade():
    if not _has_table(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name, _type, _nullable, _default in _COLUMNS:
            if _has_column(_TABLE, name):
                batch.drop_column(name)

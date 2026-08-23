# coding=utf-8
"""P6-51: 작기 운영 권한 — `roles.edit_plots`.

구획 관련 쓰기가 전부 `edit_settings` 하나에 걸려 있었다. 작기 기록만 맡기려
해도 장치·시설·네트워크 설정까지 함께 열어야 해서, 현장에서는 결국 모두에게
Editor 를 주게 되고 권한 체계가 있으나 쓰이지 않았다.

## 백필이 이 마이그레이션의 요지다

컬럼만 추가하고 끝내면 **기존 Editor 가 업그레이드 순간 구획을 못 쓰게 된다**
(새 컬럼 기본값이 False 이므로). 그래서 `edit_settings=True` 인 역할에
`edit_plots=True` 를 함께 채운다 — 새 권한을 도입하면서 기존 역할의 동작이
좁아지면 안 된다.

`user_has_permission` 도 같은 이유로 `edit_settings` 가 `edit_plots` 를
함의하도록 판정한다(두 겹 방어). 백필이 돌지 않은 서버에서도 기존 동작이
유지되어야 하기 때문이다.

Revision ID: p6_51_role_edit_plots_20260822
Revises: p6_50_plot_allocation_20260822
Create Date: 2026-08-22
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_51_role_edit_plots_20260822'
down_revision = 'p6_50_plot_allocation_20260822'
branch_labels = None
depends_on = None

_TABLE = 'roles'


def _columns(bind):
    return {c['name'] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return                      # 새 설치는 create_all + 시드가 처리한다

    if 'edit_plots' not in _columns(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column('edit_plots', sa.Boolean(),
                                       nullable=False, server_default=sa.false()))

    # 백필 — 설정 권한이 있던 역할은 작기 운영도 계속 할 수 있어야 한다.
    op.execute(sa.text(
        "UPDATE roles SET edit_plots = 1 WHERE edit_settings = 1"))


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    if 'edit_plots' in _columns(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column('edit_plots')

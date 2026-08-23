# coding=utf-8
"""P6-52: 사용자 그룹과 자원 부여 — 권한의 목적어 축.

정본 설계: `docs/design/access-scope-groups.md`

`Role` 의 불리언은 전부 동사("무엇을 할 수 있는가")라, Editor 를 받은 사람은
농장 **전체**의 출력을 켤 수 있었다. 이 마이그레이션이 "무엇에 대해" 를 담을
자리를 만든다.

## 이 마이그레이션은 아무것도 바꾸지 않는다

A0 단계다 — 테이블과 컬럼만 만들고 **강제는 없다.** grant 가 0건이면 스코프
판정 자체가 건너뛰어지므로(`access/scope.py`), 업그레이드 직후의 동작은
비트 단위로 이전과 같아야 한다. 강제는 A1a 에서 켠다.

`bypass_group_scope` 백필을 하지 않는 것이 p6_51 과 다른 점이다. p6_51 은 새
권한이 기존 역할의 동작을 **좁히지 않도록** 백필이 필요했지만, 여기서는
컬럼이 False 여도 아무것도 좁아지지 않는다(grant 가 없으니 전원 공개다).
Admin 의 True 는 `populate_db()` 의 역할 시드가 채운다 — 다만 그 시드는
`USER_ROLES` 의 **이름**으로 찾으므로, 이름을 바꾼 Admin 역할이 있는 설치를
위해 아래에서 `edit_users` 를 근거로 한 번 더 채운다.

Revision ID: p6_54_user_groups_20260823
Revises: p6_51_role_edit_plots_20260822
Create Date: 2026-08-22
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_54_user_groups_20260823'
down_revision = 'p6_53_user_string_translation_20260823'
branch_labels = None
depends_on = None


def _has_table(bind, name):
    return sa.inspect(bind).has_table(name)


def _columns(bind, table):
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()

    if not _has_table(bind, 'user_group'):
        op.create_table(
            'user_group',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('name', sa.String(length=64), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('position_y', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unique_id'),
            sa.UniqueConstraint('name'),
        )

    if not _has_table(bind, 'user_group_member'):
        op.create_table(
            'user_group_member',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('group_uuid', sa.String(length=36), nullable=False),
            sa.Column('user_uuid', sa.String(length=36), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            # 같은 사람을 같은 그룹에 두 번 넣으면 멤버 수 집계가 틀리고,
            # 그 수는 부여 화면의 "K명이 잃습니다" 근거다.
            sa.UniqueConstraint('group_uuid', 'user_uuid',
                                name='uq_user_group_member'),
        )
        op.create_index('ix_user_group_member_group_uuid',
                        'user_group_member', ['group_uuid'])
        op.create_index('ix_user_group_member_user_uuid',
                        'user_group_member', ['user_uuid'])

    if not _has_table(bind, 'group_grant'):
        op.create_table(
            'group_grant',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('group_uuid', sa.String(length=36), nullable=False),
            sa.Column('resource_type', sa.String(length=32), nullable=False),
            sa.Column('resource_uuid', sa.String(length=36), nullable=False),
            sa.Column('level', sa.String(length=16), nullable=False,
                      server_default='operate'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            # 같은 (그룹, 자원)에 행이 둘이면 level 이 갈릴 수 있고, 그러면
            # "넓은 쪽이 이긴다" 를 같은 그룹 안에서도 따져야 한다.
            sa.UniqueConstraint('group_uuid', 'resource_type', 'resource_uuid',
                                name='uq_group_grant'),
        )
        op.create_index('ix_group_grant_group_uuid', 'group_grant',
                        ['group_uuid'])
        op.create_index('ix_group_grant_resource_type', 'group_grant',
                        ['resource_type'])
        op.create_index('ix_group_grant_resource_uuid', 'group_grant',
                        ['resource_uuid'])

    # roles.bypass_group_scope
    if _has_table(bind, 'roles') and 'bypass_group_scope' not in _columns(bind, 'roles'):
        with op.batch_alter_table('roles') as batch:
            batch.add_column(sa.Column('bypass_group_scope', sa.Boolean(),
                                       nullable=False,
                                       server_default=sa.false()))

    # 면제 역할이 **하나도 없는** 상태를 만들지 않는다. 그러면 첫 grant 를
    # 붙이는 순간 관리자 자신도 잠길 수 있다. 시드가 이름으로 찾는 'Admin' 을
    # 놓치는 설치(역할 이름을 바꿨다)를 위해 `edit_users` 를 근거로 채운다 —
    # 사용자 관리 권한이 있는 역할이 곧 이 시스템의 관리자다.
    if _has_table(bind, 'roles'):
        op.execute(sa.text(
            "UPDATE roles SET bypass_group_scope = 1 WHERE edit_users = 1"))


def downgrade():
    bind = op.get_bind()

    if _has_table(bind, 'roles') and 'bypass_group_scope' in _columns(bind, 'roles'):
        with op.batch_alter_table('roles') as batch:
            batch.drop_column('bypass_group_scope')

    for table in ('group_grant', 'user_group_member', 'user_group'):
        if _has_table(bind, table):
            op.drop_table(table)

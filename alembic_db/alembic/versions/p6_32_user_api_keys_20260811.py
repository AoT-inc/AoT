# coding=utf-8
"""P6-32: 사용자별 API 키를 1:N 으로 — user_api_key 테이블.

키가 `users.api_key_hash` 컬럼 하나였다. 사람마다 키를 딱 하나만 가질 수 있고,
재발급이 곧 덮어쓰기라 같은 사람이 ChatGPT 와 Claude 에 동시에 붙을 수 없었다.
한쪽에 넣고 다른 쪽을 위해 새로 발급하면 앞의 것이 아무 에러 없이 죽는다.
유출이 의심돼도 그 키만 끊을 수 없어, 끊으면 그 사람의 모든 연동이 끊겼다.

이 마이그레이션은 테이블을 만들고 **기존 키를 그대로 옮긴다**. 옮긴 뒤에도
`users.api_key_hash` 는 남겨 둔다 — 읽기(`User.find_by_api_key`)가 새 테이블 →
레거시 컬럼 순으로 보므로, 컬럼을 지우는 것은 배포한 서버에서 폴백이 0 인 것을
확인한 뒤에 할 일이다. 여기서 지우면 아직 이 마이그레이션이 돌지 않은 서버의
API 연동이 즉시 끊긴다(geo_binding Phase C-4 와 같은 이유로 분리한다).

백필로 옮긴 키에는 'Legacy key' 라는 이름을 붙인다. 화면에서 "이건 예전에
발급한 그 키" 라고 알아볼 수 있어야 폐기 여부를 판단할 수 있다.

Revision ID: p6_32_user_api_keys_20260811
Revises: p6_31_ai_running_20260810
Create Date: 2026-08-11
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_32_user_api_keys_20260811'
down_revision = 'p6_31_ai_running_20260810'
branch_labels = None
depends_on = None

_TABLE = 'user_api_key'


def _has_table(table):
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    # 재실행 안전: 이미 있으면 만들지 않는다.
    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=64), nullable=True),
            sa.Column('key_hash', sa.String(length=64), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('revoked_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unique_id'),
            sa.UniqueConstraint('key_hash'),
        )
        op.create_index(op.f('ix_user_api_key_user_id'), _TABLE, ['user_id'])
        op.create_index(op.f('ix_user_api_key_key_hash'), _TABLE, ['key_hash'])

    _backfill()


def _backfill():
    """기존 users.api_key_hash 를 새 테이블로 옮긴다(원본은 남긴다).

    이미 옮겨진 해시는 건너뛴다 — key_hash 가 unique 라 두 번 넣으면 실패하고,
    이 마이그레이션은 재실행 가능해야 한다.
    """
    import uuid
    from datetime import datetime

    bind = op.get_bind()
    existing = {r[0] for r in bind.execute(
        sa.text("SELECT key_hash FROM user_api_key"))}

    rows = bind.execute(sa.text(
        "SELECT id, api_key_hash FROM users "
        "WHERE api_key_hash IS NOT NULL AND api_key_hash != ''")).fetchall()

    now = datetime.utcnow()
    moved = 0
    for user_id, key_hash in rows:
        if key_hash in existing:
            continue
        bind.execute(
            sa.text("INSERT INTO user_api_key "
                    "(unique_id, user_id, name, key_hash, created_at, revoked_at) "
                    "VALUES (:uid, :user_id, :name, :key_hash, :created_at, NULL)"),
            {"uid": str(uuid.uuid4()), "user_id": user_id, "name": 'Legacy key',
             "key_hash": key_hash, "created_at": now})
        existing.add(key_hash)
        moved += 1
    print("[p6_32] user_api_key 백필: {}건 이관".format(moved))


def downgrade():
    if not _has_table(_TABLE):
        return
    # users.api_key_hash 는 그대로 두었으므로 테이블만 지우면 예전 상태가 된다.
    op.drop_index(op.f('ix_user_api_key_key_hash'), table_name=_TABLE)
    op.drop_index(op.f('ix_user_api_key_user_id'), table_name=_TABLE)
    op.drop_table(_TABLE)

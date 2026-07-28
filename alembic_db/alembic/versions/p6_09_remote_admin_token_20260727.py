# coding=utf-8
"""P6-09: Remote Admin — 자격증명 체계를 발급형 토큰으로 교체.

기존 원격관리(Remote Admin Dashboard)는 로그인 비밀번호의 bcrypt 해시값 자체를
재사용 가능한 인증 수단(bearer credential)으로 삼았다 — 해시를 아는 것만으로
로그인이 성립하는 pass-the-hash 구조. DB 유출 시 해시를 깨지 않고 바로 전 계정
로그인이 가능해, bcrypt를 쓰는 의미가 이 경로 하나로 무력화됐다.

이번 변경으로 원격 접속 전용의 고엔트로피 발급 토큰(remote_access_token,
secrets.token_urlsafe(32))으로 교체한다. 로그인 비밀번호와 무관하며, 유출돼도
그 토큰만 폐기·재발급하면 되고 실제 로그인 비밀번호는 영향받지 않는다.

- remote.password_hash → remote.access_token (허브 측: 발급받은 토큰 보관)
- remote_access_token 테이블 신설 (수신 측: 토큰의 SHA-256 해시만 보관)
- 기존 access_token 값은 신뢰할 수 없으므로(구 pass-the-hash 값) 빈 문자열로
  초기화 — 등록된 원격 호스트는 재등록(Add Host)이 필요하다.

Revision ID: p6_09_remote_admin_token_20260727
Revises: p6_08_ai_advice_ledger_20260725
Create Date: 2026-07-27
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_09_remote_admin_token_20260727'
down_revision = 'p6_08_ai_advice_ledger_20260725'
branch_labels = None
depends_on = None

_REMOTE_TABLE = 'remote'
_TOKEN_TABLE = 'remote_access_token'


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
    if _has_table(_REMOTE_TABLE) and _has_column(_REMOTE_TABLE, 'password_hash') \
            and not _has_column(_REMOTE_TABLE, 'access_token'):
        with op.batch_alter_table(_REMOTE_TABLE) as batch:
            batch.alter_column('password_hash', new_column_name='access_token',
                               existing_type=sa.Text())
        # 구 pass-the-hash 값은 새 검증 로직에서 어차피 무효이지만, 혼동을
        # 피하기 위해 명시적으로 비워 재등록을 유도한다.
        op.execute(sa.text(
            "UPDATE {table} SET access_token = ''".format(table=_REMOTE_TABLE)))

    if not _has_table(_TOKEN_TABLE):
        op.create_table(
            _TOKEN_TABLE,
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('unique_id', sa.String(length=36), nullable=False, unique=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('token_hash', sa.String(length=64), nullable=False, unique=True),
            sa.Column('label', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('last_used_at', sa.DateTime(), nullable=True),
            sa.Column('revoked', sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_index('ix_remote_access_token_user_id', _TOKEN_TABLE, ['user_id'])
        op.create_index('ix_remote_access_token_token_hash', _TOKEN_TABLE, ['token_hash'])


def downgrade():
    if _has_table(_TOKEN_TABLE):
        op.drop_table(_TOKEN_TABLE)

    if _has_table(_REMOTE_TABLE) and _has_column(_REMOTE_TABLE, 'access_token') \
            and not _has_column(_REMOTE_TABLE, 'password_hash'):
        with op.batch_alter_table(_REMOTE_TABLE) as batch:
            batch.alter_column('access_token', new_column_name='password_hash',
                               existing_type=sa.Text())

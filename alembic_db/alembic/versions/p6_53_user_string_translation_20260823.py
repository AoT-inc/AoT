# coding=utf-8
"""P6-53: 사용자 지정 문자열 번역 캐시 — `user_string_translation`.

gettext 카탈로그는 소스에 박힌 문구만 덮는다. 사용자가 지은 이름은 DB 원문
그대로 모든 언어에서 노출되어, 다국어 계정으로 열면 한 화면에 두 언어가 섞인다.

이 테이블은 (원문 해시 × 대상 언어) → 번역본 캐시다. 이름은 유한하고 거의
변하지 않으므로 최초 1회 번역 후 영구 캐시가 성립한다.

원문은 건드리지 않는다. 이 테이블이 사라져도 화면은 원문으로 정상 동작한다.

`p6_52` 는 `feat/access-scope-groups` 가 먼저 썼다(같은 부모 `p6_51`). 번호만
비켜 두었을 뿐 두 리비전은 여전히 형제이므로, **둘을 같은 줄기에 합칠 때 나중에
들어가는 쪽이 `down_revision` 을 상대 리비전으로 고쳐 체인을 이어야 한다.**
그러지 않으면 alembic head 가 둘이 된다.

Revision ID: p6_53_user_string_translation_20260823
Revises: p6_51_role_edit_plots_20260822
Create Date: 2026-08-23
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_53_user_string_translation_20260823'
down_revision = 'p6_51_role_edit_plots_20260822'
branch_labels = None
depends_on = None

_TABLE = 'user_string_translation'

# (테이블, 컬럼, 타입, 기본값) — 설정 컬럼은 테이블과 별개로 추가한다.
_SETTINGS_COLUMNS = [
    ('ai_global_settings', 'user_string_translation_enabled',
     sa.Boolean(), sa.false()),
    ('ai_global_settings', 'user_string_translation_agent_id',
     sa.String(36), None),
    ('ai_global_settings', 'user_string_translation_daily_limit',
     sa.Integer(), '500'),
    ('users', 'translate_user_strings', sa.Boolean(), None),
]


def _columns(bind, table):
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def _add_settings_columns(bind):
    inspector = sa.inspect(bind)
    for table, column, type_, default in _SETTINGS_COLUMNS:
        if not inspector.has_table(table):
            continue
        if column in _columns(bind, table):
            continue
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(column, type_, nullable=True,
                                       server_default=default))


def _drop_settings_columns(bind):
    inspector = sa.inspect(bind)
    for table, column, _type, _default in _SETTINGS_COLUMNS:
        if not inspector.has_table(table):
            continue
        if column not in _columns(bind, table):
            continue
        with op.batch_alter_table(table) as batch:
            batch.drop_column(column)


def upgrade():
    bind = op.get_bind()
    _add_settings_columns(bind)

    if sa.inspect(bind).has_table(_TABLE):
        return                      # 새 설치는 create_all 이 처리한다

    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source_hash', sa.String(16), nullable=False),
        sa.Column('source_text', sa.Text(), nullable=False),
        sa.Column('source_lang', sa.String(12), nullable=False,
                  server_default='auto'),
        sa.Column('target_lang', sa.String(12), nullable=False),
        sa.Column('translated_text', sa.Text(), nullable=True),
        sa.Column('domain', sa.String(32), nullable=False,
                  server_default='misc'),
        sa.Column('status', sa.String(16), nullable=False,
                  server_default='pending'),
        sa.Column('is_locked', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('engine', sa.String(120), nullable=True),
        sa.Column('fail_count', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('source_hash', 'target_lang',
                            name='uq_user_string_translation_hash_lang'),
    )
    op.create_index('ix_user_string_translation_source_hash',
                    _TABLE, ['source_hash'])
    op.create_index('ix_user_string_translation_status', _TABLE, ['status'])
    op.create_index('ix_user_string_translation_lang_status',
                    _TABLE, ['target_lang', 'status'])


def downgrade():
    bind = op.get_bind()
    _drop_settings_columns(bind)

    if not sa.inspect(bind).has_table(_TABLE):
        return
    op.drop_index('ix_user_string_translation_lang_status', table_name=_TABLE)
    op.drop_index('ix_user_string_translation_status', table_name=_TABLE)
    op.drop_index('ix_user_string_translation_source_hash', table_name=_TABLE)
    op.drop_table(_TABLE)

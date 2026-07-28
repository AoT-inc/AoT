# coding=utf-8
"""P6-12: 감사로그 테이블 + 로그인 강화(계정 잠금·TOTP) 컬럼.

두 가지를 한 마이그레이션에 묶는다 — 감사로그가 로그인 잠금 이벤트를 기록하는
소비자라 배포 단위를 나눌 이유가 없다.

1) audit_log 테이블 신설
   기존에는 로그인 로그 파일과 MCP(AI) 감사로그만 있었고, 설정 변경·장치 제어·
   사용자/권한 변경·인증 실패 이력이 전혀 남지 않았다. 공공조달 규격서와
   개인정보 안전성 확보조치 기준이 요구하는 접속·행위 기록을 위한 테이블.

2) users 컬럼 추가
   - failed_login_count / locked_until:
     로그인 실패 카운터가 Flask 세션에 있어 쿠키만 지우면 초기화됐다(사실상
     무방비). 서버측·계정 단위로 옮긴다.
   - totp_secret / totp_enabled: 선택적 2단계 인증.

전부 추가 전용(새 테이블 + nullable/기본값 있는 컬럼)이라 기존 데이터에 무해.
신규 설치는 db.create_all()이 만든다.

Revision ID: p6_12_audit_log_and_login_hardening_20260727
Revises: p6_11_device_tier_20260728
Create Date: 2026-07-27
"""
import sqlalchemy as sa
from alembic import op

# 병행 진행 중인 복합장치(device tier) 작업이 p6_11 을 먼저 점유했으므로 그
# 뒤에 체이닝한다. 둘 다 p6_10 을 부모로 두면 "Multiple head revisions" 로
# 업그레이드 자체가 실패한다.
revision = 'p6_12_audit_log_and_login_hardening_20260727'
down_revision = 'p6_11_device_tier_20260728'
branch_labels = None
depends_on = None

_AUDIT_TABLE = 'audit_log'
_USERS_TABLE = 'users'

_NEW_USER_COLUMNS = [
    ('failed_login_count', sa.Integer(), {'nullable': False, 'server_default': '0'}),
    ('locked_until', sa.DateTime(), {'nullable': True}),
    ('totp_secret', sa.String(length=64), {'nullable': True}),
    ('totp_enabled', sa.Boolean(), {'nullable': False, 'server_default': sa.false()}),
]


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
    if not _has_table(_AUDIT_TABLE):
        op.create_table(
            _AUDIT_TABLE,
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('unique_id', sa.String(length=36), nullable=False, unique=True),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('username', sa.String(length=64), nullable=True),
            sa.Column('ip_address', sa.String(length=64), nullable=True),
            sa.Column('action', sa.String(length=64), nullable=False),
            sa.Column('target_type', sa.String(length=64), nullable=True),
            sa.Column('target_id', sa.String(length=64), nullable=True),
            sa.Column('target_name', sa.String(length=128), nullable=True),
            sa.Column('result', sa.String(length=16), nullable=False,
                      server_default='success'),
            sa.Column('detail', sa.Text(), nullable=True),
            sa.Column('before_json', sa.Text(), nullable=True),
            sa.Column('after_json', sa.Text(), nullable=True),
        )
        op.create_index('ix_audit_log_timestamp', _AUDIT_TABLE, ['timestamp'])
        op.create_index('ix_audit_log_action', _AUDIT_TABLE, ['action'])
        op.create_index('ix_audit_log_user_id', _AUDIT_TABLE, ['user_id'])

    if _has_table(_USERS_TABLE):
        for name, coltype, kwargs in _NEW_USER_COLUMNS:
            if not _has_column(_USERS_TABLE, name):
                op.add_column(_USERS_TABLE, sa.Column(name, coltype, **kwargs))


def downgrade():
    if _has_table(_USERS_TABLE):
        with op.batch_alter_table(_USERS_TABLE) as batch:
            for name, _, _ in reversed(_NEW_USER_COLUMNS):
                if _has_column(_USERS_TABLE, name):
                    batch.drop_column(name)

    if _has_table(_AUDIT_TABLE):
        op.drop_table(_AUDIT_TABLE)

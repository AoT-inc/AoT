# coding=utf-8
"""P7-04: VIGI 카메라 모듈 — camera_driver·camera_event 표, camera.tab_id, trigger.event_kinds.

설계 docs/design/vigi-camera-module.md §5.5.

  camera_driver : Camera 1:1 드라이버 설정·인증 래치 (ON DELETE CASCADE)
  camera_event  : 감지 이벤트 기록 (P4 에서 채운다)
  camera.tab_id : 그룹 스코프 정본. FK tab ON DELETE CASCADE, 기존 행 NULL(= 전원 공개, 백필 없음)
  trigger.event_kinds : trigger_camera_event 의 이벤트 종류 목록(JSON)

재실행 안전(이미 있으면 건너뜀). downgrade 는 위 넷을 거꾸로 지운다(SQLite 는 batch).

Revision ID: p7_05_camera_driver_20261105
Revises: p7_04_drop_device_location_dead_columns_20261105
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = 'p7_05_camera_driver_20261105'
down_revision = 'p7_04_drop_device_location_dead_columns_20261105'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if 'camera_driver' not in _tables():
        op.create_table(
            'camera_driver',
            sa.Column('camera_id', sa.String(36), sa.ForeignKey('camera.unique_id', ondelete='CASCADE'),
                      primary_key=True),
            sa.Column('vendor', sa.Text(), nullable=False, server_default='vigi'),
            sa.Column('host', sa.Text(), nullable=False, server_default=''),
            sa.Column('mac', sa.Text(), nullable=True),
            sa.Column('openapi_port', sa.Integer(), nullable=False, server_default='20443'),
            sa.Column('rtsp_port', sa.Integer(), nullable=False, server_default='554'),
            sa.Column('username', sa.Text(), nullable=False, server_default='admin'),
            sa.Column('password_sealed', sa.Text(), nullable=True),
            sa.Column('credential_fp', sa.Text(), nullable=True),
            sa.Column('verified_fp', sa.Text(), nullable=True),
            sa.Column('auth_state', sa.Text(), nullable=False, server_default='unverified'),
            sa.Column('auth_iface', sa.Text(), nullable=True),
            sa.Column('auth_code', sa.Integer(), nullable=True),
            sa.Column('auth_at', sa.DateTime(), nullable=True),
            sa.Column('attempt_lease_until', sa.DateTime(), nullable=True),
            sa.Column('tls_pin_sha256', sa.Text(), nullable=True),
            sa.Column('device_info', sa.JSON(), nullable=True),
            sa.Column('capabilities', sa.JSON(), nullable=True),
            sa.Column('capabilities_at', sa.DateTime(), nullable=True),
            sa.Column('live_profile', sa.Text(), nullable=False, server_default='sub'),
            sa.Column('events_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('event_kinds', sa.JSON(), nullable=True),
            sa.Column('event_state', sa.Text(), nullable=False, server_default='off'),
            sa.Column('event_state_at', sa.DateTime(), nullable=True),
            sa.Column('event_note', sa.Text(), nullable=True))

    if 'camera_event' not in _tables():
        op.create_table(
            'camera_event',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('camera_id', sa.String(36), sa.ForeignKey('camera.unique_id', ondelete='CASCADE'),
                      nullable=False),
            sa.Column('kind', sa.Text(), nullable=False),
            sa.Column('enhanced', sa.Text(), nullable=True),
            sa.Column('raw_type', sa.Text(), nullable=True),
            sa.Column('camera_time_utc', sa.DateTime(), nullable=True),
            sa.Column('received_at_utc', sa.DateTime(), nullable=False),
            sa.Column('dispatch_state', sa.Text(), nullable=False, server_default='none'),
            sa.Column('dispatch_note', sa.Text(), nullable=True))
        op.create_index('ix_camera_event_camera_id', 'camera_event', ['camera_id'])
        op.create_index('ix_camera_event_camera_received', 'camera_event',
                        ['camera_id', 'received_at_utc'])

    if 'tab_id' not in _columns('camera'):
        with op.batch_alter_table('camera') as batch:
            batch.add_column(sa.Column('tab_id', sa.String(36), nullable=True))
            batch.create_foreign_key('fk_camera_tab_id', 'tab', ['tab_id'], ['unique_id'],
                                     ondelete='CASCADE')
            batch.create_index('ix_camera_tab_id', ['tab_id'])

    if 'event_kinds' not in _columns('trigger'):
        with op.batch_alter_table('trigger') as batch:
            batch.add_column(sa.Column('event_kinds', sa.JSON(), nullable=True))


def downgrade():
    if 'event_kinds' in _columns('trigger'):
        # batch 는 표를 다시 만들며(drop+rename) `trigger` 를 가리키는 지도 무결성 SQL 트리거
        # (geo_itg_*)가 'no such table: main.trigger' 로 깨진다(8084 사본 실측). 일반 컬럼이라
        # SQLite(3.35+)의 네이티브 DROP COLUMN 을 쓴다.
        op.execute('ALTER TABLE "trigger" DROP COLUMN event_kinds')
    if 'tab_id' in _columns('camera'):
        with op.batch_alter_table('camera') as batch:
            batch.drop_index('ix_camera_tab_id')
            batch.drop_constraint('fk_camera_tab_id', type_='foreignkey')
            batch.drop_column('tab_id')
    if 'camera_event' in _tables():
        op.drop_table('camera_event')
    if 'camera_driver' in _tables():
        op.drop_table('camera_driver')

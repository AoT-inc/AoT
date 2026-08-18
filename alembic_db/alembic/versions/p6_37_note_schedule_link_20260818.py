# coding=utf-8
"""P6-37: 노트 한 구간 ↔ 그 구간으로 만든 예정을 잇는 링크 테이블.

**분류를 관계로 바꾼다.** 노트·일정·공지는 서로 다른 정보가 아니라 같은 것
(문장 + 어디 + 언제)에 붙은 세 개의 저장 위치이고, 경계는 실데이터에서
양방향으로 새고 있다(`action_type='note'` 인 일정 2건, `category='schedule'`
인 노트 3건). 그래서 사용자에게 쓰기 **전에** 종류를 묻던 것을 그만두고,
노트만 쓰게 한 뒤 그 안의 한 구간에 시각을 주는 방식으로 바꾼다.

컬럼 설계에서 정한 것:

- **FK 를 걸지 않는다.** 일정 삭제 경로가 한 곳이 아니라, 그중 하나만 링크
  정리를 빠뜨려도 DB 제약이 그 삭제를 통째로 거부한다(이 레포는 장치 삭제
  17경로로 이미 크게 데었다). 대신 링크를 읽을 때 대상이 사라졌으면 그 자리에서
  걷어낸다.
- **`job_uid` 는 `SchedulerJobMeta.unique_id`** 다. 정수 `id` 는 재사용될 수
  있고, `scheduler_audit_log.job_meta_id` 가 그 정수를 NOT NULL 로 물고 있어
  삭제 순서에 얽힌다.
- **`text_snapshot` 은 NOT NULL** 이다. 노트를 고치면 offset 이 어긋나는데,
  재탐색의 근거가 이것뿐이라 비어 있으면 그 링크는 영영 하이라이트를 잃는다.

Revision ID: p6_37_note_schedule_link_20260818
Revises: p6_36_drop_planting_bed_spec_20260814
Create Date: 2026-08-18
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_37_note_schedule_link_20260818'
down_revision = 'p6_36_drop_planting_bed_spec_20260814'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'note_schedule_link',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unique_id', sa.String(length=36), nullable=False),
        sa.Column('note_id', sa.String(length=36), nullable=False),
        sa.Column('job_uid', sa.String(length=36), nullable=False),
        sa.Column('start_offset', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('end_offset', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('text_snapshot', sa.Text(), nullable=False,
                  server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('unique_id'),
    )
    op.create_index('ix_note_schedule_link_note_id', 'note_schedule_link',
                    ['note_id'])
    op.create_index('ix_note_schedule_link_job_uid', 'note_schedule_link',
                    ['job_uid'])


def downgrade():
    op.drop_index('ix_note_schedule_link_job_uid',
                  table_name='note_schedule_link')
    op.drop_index('ix_note_schedule_link_note_id',
                  table_name='note_schedule_link')
    op.drop_table('note_schedule_link')

# coding=utf-8
"""P5-22: Add gunicorn_threads column to misc table.

웹서버(gunicorn) 스레드 수 수동 설정값. NULL 이면 install/gunicorn_conf.py
가 환경(코어 수, 메모리, 플랫폼)을 보고 자동 산정한다. info 페이지에서
확인·조정한다.

Revision ID: p5_22_add_gunicorn_threads
Revises: p5_21_add_controller_method_start
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa


revision = 'p5_22_add_gunicorn_threads'
down_revision = 'p5_21_add_controller_method_start'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('misc') as batch_op:
        batch_op.add_column(
            sa.Column('gunicorn_threads', sa.Integer(), nullable=True, server_default=None)
        )


def downgrade():
    with op.batch_alter_table('misc') as batch_op:
        batch_op.drop_column('gunicorn_threads')

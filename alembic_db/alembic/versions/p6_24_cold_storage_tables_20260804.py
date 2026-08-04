# coding=utf-8
"""P6-24: 콜드 스토리지(Tier 3) 테이블 신설 — cold_documents / archive_index / archive_audit_log.

적응형 문서 스토리지의 아카이브 계층은 모델(`models/cold_storage.py`)과 서비스
(`services/cold_storage_service.py`)가 이미 작성돼 있었으나 **테이블이 한 번도
만들어진 적이 없다.** 마이그레이션이 없었고, 모델은 `models/__init__.py` 에
등록조차 되지 않았다. 게다가 컬럼명이 `metadata` 였어서 — SQLAlchemy Declarative
예약어 — 그 모델을 import 하는 순간 InvalidRequestError 가 났다. 즉 이 계층은
작성된 이래 한 번도 동작한 적이 없다(2026-08-04 발견).

이번 리비전은 그 테이블을 만든다. 기존 데이터가 없으므로 이관은 없다.
`metadata` → `meta_json` 컬럼명 변경도 함께 반영된 상태다.

주의: 이 마이그레이션은 **저장 공간을 준비할 뿐 아무 문서도 옮기지 않는다.**
실제 티어 이동(`TierMigrationService._migrate_to_cold`)은 여전히 placeholder 이며,
AI 가 MCP 도구로 명시적으로 호출할 때만 아카이브가 일어나도록 후속 단계에서
배선한다. 테이블이 비어 있는 것이 정상 상태다.

Revision ID: p6_24_cold_storage_tables_20260804
Revises: p6_23_geo_integrity_tier2_20260803
Create Date: 2026-08-04
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_24_cold_storage_tables_20260804'
down_revision = 'p6_23_geo_integrity_tier2_20260803'
branch_labels = None
depends_on = None


def _has_table(name):
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def upgrade():
    # 재실행 안전: 이미 있으면 건너뛴다(수동으로 만들어 둔 설치를 깨지 않기 위해).
    if not _has_table('cold_documents'):
        op.create_table(
            'cold_documents',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('document_id', sa.String(length=36), nullable=False),
            sa.Column('content_hash', sa.String(length=64), nullable=False),
            sa.Column('archive_path', sa.Text(), nullable=False),
            sa.Column('meta_json', sa.Text(), nullable=True),
            sa.Column('archived_at', sa.DateTime(), nullable=False),
            sa.Column('last_accessed', sa.DateTime(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('compression_type', sa.String(length=16), nullable=True),
            sa.Column('original_size', sa.Integer(), nullable=True),
            sa.Column('compressed_size', sa.Integer(), nullable=True),
            sa.Column('is_restored', sa.Boolean(), nullable=True),
            sa.Column('restore_count', sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unique_id'),
        )
        op.create_index('ix_cold_documents_document_id',
                        'cold_documents', ['document_id'])

    if not _has_table('archive_index'):
        op.create_table(
            'archive_index',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('document_id', sa.String(length=36), nullable=False),
            sa.Column('archive_date', sa.DateTime(), nullable=False),
            sa.Column('deletion_date', sa.DateTime(), nullable=True),
            sa.Column('retention_policy', sa.String(length=32), nullable=True),
            sa.Column('retention_days', sa.Integer(), nullable=True),
            sa.Column('status', sa.String(length=16), nullable=True),
            sa.Column('is_purgeable', sa.Boolean(), nullable=True),
            sa.Column('archived_by', sa.String(length=64), nullable=True),
            sa.Column('deletion_reason', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unique_id'),
        )
        op.create_index('ix_archive_index_document_id',
                        'archive_index', ['document_id'])
        op.create_index('ix_archive_index_archive_date',
                        'archive_index', ['archive_date'])
        op.create_index('ix_archive_index_deletion_date',
                        'archive_index', ['deletion_date'])

    if not _has_table('archive_audit_log'):
        op.create_table(
            'archive_audit_log',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('operation', sa.String(length=32), nullable=False),
            sa.Column('document_id', sa.String(length=36), nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.Column('performed_by', sa.String(length=64), nullable=True),
            sa.Column('compression_type', sa.String(length=16), nullable=True),
            sa.Column('original_size', sa.Integer(), nullable=True),
            sa.Column('compressed_size', sa.Integer(), nullable=True),
            sa.Column('status', sa.String(length=16), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('meta_json', sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unique_id'),
        )
        op.create_index('ix_archive_audit_log_document_id',
                        'archive_audit_log', ['document_id'])
        op.create_index('ix_archive_audit_log_timestamp',
                        'archive_audit_log', ['timestamp'])


def downgrade():
    for table in ('archive_audit_log', 'archive_index', 'cold_documents'):
        if _has_table(table):
            op.drop_table(table)

"""add_agent_role_preset_table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-02 00:00:00.000000

Task ID: agent_setup_ux_impl
Description: Creates agent_role_preset table for DB-managed pipeline role configurations.
             Seeds 5 initial records: router, planner, executor, synthesizer, supervisor.
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = [r[0] for r in bind.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]
    if 'agent_role_preset' not in existing:
        op.create_table(
            'agent_role_preset',
            sa.Column('pipeline_role', sa.String(32), primary_key=True, nullable=False),
            sa.Column('ai_name_unique', sa.String(64), nullable=False),
            sa.Column('model_value', sa.String(128), nullable=False),
            sa.Column('temperature', sa.Float, nullable=False, server_default='0.7'),
            sa.Column('max_tokens', sa.Integer, nullable=False, server_default='4096'),
            sa.Column('role_description_en', sa.Text(), nullable=True),
            sa.Column('role_description_ko', sa.Text(), nullable=True),
            sa.Column('is_active', sa.Boolean, nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime, nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime, nullable=True, onupdate=datetime.utcnow),
        )

    # Seed initial data using insert...values for compatibility
    seed_data = [
        {
            'pipeline_role': 'router',
            'ai_name_unique': 'gemini',
            'model_value': 'gemini-3.1-flash-lite-preview',
            'temperature': 0.5,
            'max_tokens': 2048,
            'role_description_en': 'Classifies user intent and routes to appropriate pipeline stage.',
            'role_description_ko': '사용자 의도를 분류하고 적절한 파이프라인 단계로 라우팅합니다.',
        },
        {
            'pipeline_role': 'planner',
            'ai_name_unique': 'minimax',
            'model_value': 'MiniMax-M2.7',
            'temperature': 0.6,
            'max_tokens': 4096,
            'role_description_en': 'Breaks down complex goals into executable sub-tasks.',
            'role_description_ko': '복잡한 목표를 실행 가능한 하위 작업으로 분해합니다.',
        },
        {
            'pipeline_role': 'executor',
            'ai_name_unique': 'gemini',
            'model_value': 'gemini-2.5-flash',
            'temperature': 0.7,
            'max_tokens': 8192,
            'role_description_en': 'Executes tool calls and retrieves data from MCP servers.',
            'role_description_ko': 'MCP 서버에서 도구를 호출하고 데이터를 수집합니다.',
        },
        {
            'pipeline_role': 'synthesizer',
            'ai_name_unique': 'gemini',
            'model_value': 'gemini-2.5-flash',
            'temperature': 0.7,
            'max_tokens': 4096,
            'role_description_en': 'Synthesizes multi-source results into a coherent final answer.',
            'role_description_ko': '다중 소스 결과를 통합하여 최종 답변을 생성합니다.',
        },
        {
            'pipeline_role': 'supervisor',
            'ai_name_unique': 'minimax',
            'model_value': 'MiniMax-M2.7',
            'temperature': 0.5,
            'max_tokens': 2048,
            'role_description_en': 'Reviews and validates pipeline output for quality control.',
            'role_description_ko': '파이프라인 출력을 검토하고 품질을 검증합니다.',
        },
    ]

    for row in seed_data:
        op.execute(
            "INSERT OR IGNORE INTO agent_role_preset "
            "(pipeline_role, ai_name_unique, model_value, temperature, max_tokens, "
            "role_description_en, role_description_ko) "
            "VALUES ('{pipeline_role}', '{ai_name_unique}', '{model_value}', "
            "{temperature}, {max_tokens}, '{role_description_en}', '{role_description_ko}')".format(**row)
        )


def downgrade():
    op.drop_table('agent_role_preset')
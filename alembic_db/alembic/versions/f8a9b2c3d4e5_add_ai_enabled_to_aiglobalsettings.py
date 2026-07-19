"""add_ai_enabled_to_aiglobalsettings

Revision ID: f8a9b2c3d4e5
Revises: e7fbf4818024
Create Date: 2026-03-06 14:30:00.000000

"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

# from alembic_db.alembic_post_utils import write_revision_post_alembic

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f8a9b2c3d4e5'
down_revision = 'e7fbf4818024'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add ai_enabled field to AIGlobalSettings table.
    This field controls whether AI features are enabled system-wide.
    Default: False (AI features disabled by default for experimental phase)
    """
    write_revision_post_alembic(revision)
    
    with op.batch_alter_table('ai_global_settings') as batch_op:
        batch_op.add_column(
            sa.Column(
                'ai_enabled', 
                sa.Boolean(), 
                nullable=False, 
                server_default=sa.text('0')
            )
        )


def downgrade():
    """
    Remove ai_enabled field from AIGlobalSettings table.
    """
    with op.batch_alter_table('ai_global_settings') as batch_op:
        batch_op.drop_column('ai_enabled')

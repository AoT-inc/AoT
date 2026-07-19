"""add_tab_id_to_function_controllers

Revision ID: 3bfac659ac37
Revises: bcfabcb4a0a8
Create Date: 2026-03-04 12:18:41.819083

"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

# from alembic_db.alembic_post_utils import write_revision_post_alembic

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3bfac659ac37'
down_revision = 'bcfabcb4a0a8'
branch_labels = None
depends_on = None


def upgrade():
    write_revision_post_alembic(revision)
    
    with op.batch_alter_table('trigger') as batch_op:
        batch_op.add_column(sa.Column('tab_id', sa.String(36), nullable=True))
        batch_op.create_index('ix_trigger_tab_id', ['tab_id'])
        batch_op.create_foreign_key('fk_trigger_tab_id', 'tab', ['tab_id'], ['unique_id'], ondelete='CASCADE')
    
    with op.batch_alter_table('conditional') as batch_op:
        batch_op.add_column(sa.Column('tab_id', sa.String(36), nullable=True))
        batch_op.create_index('ix_conditional_tab_id', ['tab_id'])
        batch_op.create_foreign_key('fk_conditional_tab_id', 'tab', ['tab_id'], ['unique_id'], ondelete='CASCADE')
    
    with op.batch_alter_table('pid') as batch_op:
        batch_op.add_column(sa.Column('tab_id', sa.String(36), nullable=True))
        batch_op.create_index('ix_pid_tab_id', ['tab_id'])
        batch_op.create_foreign_key('fk_pid_tab_id', 'tab', ['tab_id'], ['unique_id'], ondelete='CASCADE')
    
    with op.batch_alter_table('custom_controller') as batch_op:
        batch_op.add_column(sa.Column('tab_id', sa.String(36), nullable=True))
        batch_op.create_index('ix_custom_controller_tab_id', ['tab_id'])
        batch_op.create_foreign_key('fk_custom_controller_tab_id', 'tab', ['tab_id'], ['unique_id'], ondelete='CASCADE')
    
    # Migrate existing data to default function tab
    conn = op.get_bind()
    
    # Get the default function tab for each page_type='function'
    default_tab_result = conn.execute(sa.text("""
        SELECT unique_id FROM tab WHERE page_type = 'function' ORDER BY id LIMIT 1
    """))
    default_tab_row = default_tab_result.fetchone()
    
    if default_tab_row:
        default_tab_id = default_tab_row[0]
        
        # Migrate all existing entries to default tab
        conn.execute(sa.text(f"""
            UPDATE trigger SET tab_id = '{default_tab_id}' WHERE tab_id IS NULL
        """))
        conn.execute(sa.text(f"""
            UPDATE conditional SET tab_id = '{default_tab_id}' WHERE tab_id IS NULL
        """))
        conn.execute(sa.text(f"""
            UPDATE pid SET tab_id = '{default_tab_id}' WHERE tab_id IS NULL
        """))
        conn.execute(sa.text(f"""
            UPDATE custom_controller SET tab_id = '{default_tab_id}' WHERE tab_id IS NULL
        """))


def downgrade():
    with op.batch_alter_table('custom_controller') as batch_op:
        batch_op.drop_constraint('fk_custom_controller_tab_id', type_='foreignkey')
        batch_op.drop_index('ix_custom_controller_tab_id')
        batch_op.drop_column('tab_id')
    
    with op.batch_alter_table('pid') as batch_op:
        batch_op.drop_constraint('fk_pid_tab_id', type_='foreignkey')
        batch_op.drop_index('ix_pid_tab_id')
        batch_op.drop_column('tab_id')
    
    with op.batch_alter_table('conditional') as batch_op:
        batch_op.drop_constraint('fk_conditional_tab_id', type_='foreignkey')
        batch_op.drop_index('ix_conditional_tab_id')
        batch_op.drop_column('tab_id')
    
    with op.batch_alter_table('trigger') as batch_op:
        batch_op.drop_constraint('fk_trigger_tab_id', type_='foreignkey')
        batch_op.drop_index('ix_trigger_tab_id')
        batch_op.drop_column('tab_id')

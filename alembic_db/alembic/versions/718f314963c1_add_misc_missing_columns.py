"""Add misc missing columns to trigger and conditional tables

Revision ID: 718f314963c1
Revises: 718f314963c0
Create Date: 2026-02-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '718f314963c1'
down_revision = '718f314963c0'
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    
    # 1. trigger table: action_type
    tables = insp.get_table_names()
    if 'trigger' in tables:
        columns_trigger = [c['name'] for c in insp.get_columns('trigger')]
        if 'action_type' not in columns_trigger:
            with op.batch_alter_table('trigger', schema=None) as batch_op:
                batch_op.add_column(sa.Column('action_type', sa.Text(), nullable=True, server_default=''))

    # 2. conditional table: latitude, longitude, location_source
    if 'conditional' in tables:
        columns_conditional = [c['name'] for c in insp.get_columns('conditional')]
        missing_geo = [
            ('latitude', sa.Float()),
            ('longitude', sa.Float()),
            ('location_source', sa.String(32))
        ]
        with op.batch_alter_table('conditional', schema=None) as batch_op:
            for name, typ in missing_geo:
                if name not in columns_conditional:
                    if name == 'location_source':
                        batch_op.add_column(sa.Column(name, typ, nullable=True, server_default='manual'))
                    else:
                        batch_op.add_column(sa.Column(name, typ, nullable=True))

def downgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)

    # 1. conditional table
    columns_conditional = [c['name'] for c in insp.get_columns('conditional')]
    with op.batch_alter_table('conditional', schema=None) as batch_op:
        for name in ['latitude', 'longitude', 'location_source']:
            if name in columns_conditional:
                batch_op.drop_column(name)

    # 2. trigger table
    columns_trigger = [c['name'] for c in insp.get_columns('trigger')]
    if 'action_type' in columns_trigger:
        with op.batch_alter_table('trigger', schema=None) as batch_op:
            batch_op.drop_column('action_type')

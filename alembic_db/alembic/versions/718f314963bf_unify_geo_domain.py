"""Unify Geo Domain and migrate for Delta Save

Revision ID: 718f314963bf
Revises: 718f314963be
Create Date: 2026-01-04 01:50:00.000000

"""
from alembic import op
import sqlalchemy as sa
import json
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '718f314963bf'
down_revision = '718f314963be'
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    tables = insp.get_table_names()

    # 1. Renaming
    if 'map_config' in tables and 'geo_map' not in tables:
        op.rename_table('map_config', 'geo_map')
    if 'map_overlay' in tables and 'geo_shape' not in tables:
        op.rename_table('map_overlay', 'geo_shape')
    if 'map_global_settings' in tables and 'geo_setting' not in tables:
        op.rename_table('map_global_settings', 'geo_setting')

    # Re-inspect to get updated table names
    tables = Inspector.from_engine(conn).get_table_names()

    # 2. geo_map: category
    if 'geo_map' in tables:
        cols = [c['name'] for c in insp.get_columns('geo_map')]
        if 'category' not in cols:
            with op.batch_alter_table('geo_map', schema=None) as batch_op:
                batch_op.add_column(sa.Column('category', sa.String(length=64), nullable=True, server_default='design'))

    # 3. geo_shape: map_id -> geo_id, device_id, parent_id, channel_id
    if 'geo_shape' in tables:
        cols = [c['name'] for c in Inspector.from_engine(conn).get_columns('geo_shape')]
        
        indexes = [i['name'] for i in Inspector.from_engine(conn).get_indexes('geo_shape')]
        with op.batch_alter_table('geo_shape', schema=None) as batch_op:
            if 'map_id' in cols and 'geo_id' not in cols:
                batch_op.alter_column('map_id', new_column_name='geo_id', existing_type=sa.String(64))
            
            if 'device_id' not in cols:
                batch_op.add_column(sa.Column('device_id', sa.String(length=64), nullable=True))
            if 'ix_geo_shape_device_id' not in indexes:
                batch_op.create_index(batch_op.f('ix_geo_shape_device_id'), ['device_id'], unique=False)
            
            if 'parent_id' not in cols:
                batch_op.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
            if 'ix_geo_shape_parent_id' not in indexes:
                batch_op.create_index(batch_op.f('ix_geo_shape_parent_id'), ['parent_id'], unique=False)
            
            if 'channel_id' not in cols:
                batch_op.add_column(sa.Column('channel_id', sa.String(length=64), nullable=True))
            if 'ix_geo_shape_channel_id' not in indexes:
                batch_op.create_index(batch_op.f('ix_geo_shape_channel_id'), ['channel_id'], unique=False)

        # Data Migration
        t_geo_shape = sa.table('geo_shape',
            sa.column('id', sa.Integer),
            sa.column('feature', sa.JSON),
            sa.column('device_id', sa.String),
            sa.column('parent_id', sa.Integer),
            sa.column('channel_id', sa.String)
        )
        
        # We need a plain connection for execution
        connection = op.get_bind()
        rows = connection.execute(sa.select(t_geo_shape.c.id, t_geo_shape.c.feature)).fetchall()
        for row in rows:
            try:
                feat = row.feature
                if isinstance(feat, str):
                    feat = json.loads(feat)
                props = feat.get('properties', {})
                
                # Sync top level
                d_id = props.get('device_id') or props.get('db_id')
                p_id = props.get('parent_id')
                c_id = props.get('channel_id')
                
                if d_id or p_id or c_id:
                    connection.execute(
                        t_geo_shape.update().where(t_geo_shape.c.id == row.id).values(
                            device_id=str(d_id) if d_id else None,
                            parent_id=int(p_id) if p_id else None,
                            channel_id=str(c_id) if c_id else None
                        )
                    )
            except:
                pass

    # 4. geo_setting extensions
    if 'geo_setting' in tables:
        cols = [c['name'] for c in Inspector.from_engine(conn).get_columns('geo_setting')]
        with op.batch_alter_table('geo_setting', schema=None) as batch_op:
            new_cols = [
                ('max_zoom', sa.Integer(), 25),
                ('digital_zoom', sa.Boolean(), True),
                ('smooth_zoom', sa.Boolean(), True),
                ('default_lat', sa.Float(), 37.5665),
                ('default_lng', sa.Float(), 126.9780),
                ('tile_fade_animation', sa.Boolean(), True),
                ('prefer_canvas', sa.Boolean(), False),
                ('max_polygons_device', sa.Integer(), 1000),
                ('max_polygons_site', sa.Integer(), 1000),
                ('max_polygons_zone', sa.Integer(), 1000),
                ('theme_config', sa.Text(), '{}')
            ]
            for name, typ, default in new_cols:
                if name not in cols:
                    batch_op.add_column(sa.Column(name, typ, nullable=True, server_default=sa.text(str(default)) if not isinstance(default, str) else default))

    # 5. geo_layer creation
    if 'geo_layer' not in tables:
        op.create_table('geo_layer',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('name', sa.String(length=128), nullable=False),
            sa.Column('is_activated', sa.Boolean(), nullable=True),
            sa.Column('type', sa.String(length=64), nullable=False),
            sa.Column('options', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('id'),
            sa.UniqueConstraint('unique_id')
        )

def downgrade():
    # Keep it simple: reverse naming if possible, but mostly we don't downgrade data migration.
    op.drop_table('geo_layer')
    # Other downgrades omitted for brevity as this is a unifying migration.
    pass

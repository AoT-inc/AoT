"""Add unified tab system for all pages

Revision ID: bcfabcb4a0a8
Revises: a1b2c3d4e5f6
Create Date: 2026-03-04

This migration creates the unified tab system that replaces the Dashboard table
and extends tab functionality to Input, Output, and Function pages.

Tasks covered:
- 1.1: Create tab table schema with indexes and constraints
- 1.2: Add tab_id foreign keys to entry tables
- 1.3: Migrate existing data to tab system
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.sql import table, column
import uuid
from datetime import datetime

# revision identifiers, used by Alembic.
revision = 'bcfabcb4a0a8'
down_revision = 'bf13ae52c93f'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    tables = insp.get_table_names()

    # ========================================
    # Step 1: Create tab table
    # ========================================
    if 'tab' not in tables:
        op.create_table(
            'tab',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('page_type', sa.String(length=32), nullable=False),
            sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unique_id'),
            sa.UniqueConstraint('page_type', 'position', name='unique_page_position')
        )

        # Create indexes
        op.create_index('ix_tab_page_type', 'tab', ['page_type'])
        op.create_index('ix_tab_position', 'tab', ['position'])

    # ========================================
    # Step 2: Migrate existing Dashboard data to tab table
    # ========================================
    if 'dashboard' in tables:
        # Read existing dashboards
        dashboard_table = table('dashboard',
            column('id', sa.Integer),
            column('unique_id', sa.String),
            column('name', sa.Text),
            column('sort_order', sa.Integer)
        )

        tab_table = table('tab',
            column('id', sa.Integer),
            column('unique_id', sa.String),
            column('name', sa.Text),
            column('page_type', sa.String),
            column('position', sa.Integer),
            column('created_at', sa.DateTime),
            column('updated_at', sa.DateTime)
        )

        # Get all dashboards
        result = conn.execute(sa.select(dashboard_table))
        dashboards = result.fetchall()

        # Migrate dashboards to tab table
        for dash in dashboards:
            conn.execute(
                tab_table.insert().values(
                    unique_id=dash.unique_id,
                    name=dash.name,
                    page_type='dashboard',
                    position=dash.sort_order if dash.sort_order is not None else 0,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
            )

    # ========================================
    # Step 3: Create default tabs for Input, Output, Function pages
    # ========================================
    tab_table = table('tab',
        column('unique_id', sa.String),
        column('name', sa.Text),
        column('page_type', sa.String),
        column('position', sa.Integer),
        column('created_at', sa.DateTime),
        column('updated_at', sa.DateTime)
    )

    # Create default tabs for each page type
    default_tabs = [
        {'page_type': 'input', 'name': 'Input'},
        {'page_type': 'output', 'name': 'Output'},
        {'page_type': 'function', 'name': 'Function'}
    ]

    for tab_data in default_tabs:
        # Check if default tab already exists
        existing = conn.execute(
            sa.select(tab_table).where(
                sa.and_(
                    tab_table.c.page_type == tab_data['page_type'],
                    tab_table.c.position == 0
                )
            )
        ).fetchone()

        if not existing:
            conn.execute(
                tab_table.insert().values(
                    unique_id=str(uuid.uuid4()),
                    name=tab_data['name'],
                    page_type=tab_data['page_type'],
                    position=0,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
            )

    # ========================================
    # Step 4: Add tab_id columns to entry tables
    # ========================================

    # 4.1: Add tab_id to input table
    if 'input' in tables:
        columns_input = [c['name'] for c in insp.get_columns('input')]
        if 'tab_id' not in columns_input:
            with op.batch_alter_table('input', schema=None) as batch_op:
                batch_op.add_column(sa.Column('tab_id', sa.String(36), nullable=True))

            # Set tab_id to default Input tab for all existing entries
            input_table = table('input', column('tab_id', sa.String))
            default_input_tab = conn.execute(
                sa.select(tab_table.c.unique_id).where(
                    sa.and_(
                        tab_table.c.page_type == 'input',
                        tab_table.c.position == 0
                    )
                )
            ).scalar()

            if default_input_tab:
                conn.execute(
                    input_table.update().values(tab_id=default_input_tab)
                )

            # Add foreign key and index
            with op.batch_alter_table('input', schema=None) as batch_op:
                batch_op.create_foreign_key('fk_input_tab_id', 'tab', ['tab_id'], ['unique_id'], ondelete='CASCADE')
                batch_op.create_index('ix_input_tab_id', ['tab_id'])

    # 4.2: Add tab_id to output table
    if 'output' in tables:
        columns_output = [c['name'] for c in insp.get_columns('output')]
        if 'tab_id' not in columns_output:
            with op.batch_alter_table('output', schema=None) as batch_op:
                batch_op.add_column(sa.Column('tab_id', sa.String(36), nullable=True))

            # Set tab_id to default Output tab for all existing entries
            output_table = table('output', column('tab_id', sa.String))
            default_output_tab = conn.execute(
                sa.select(tab_table.c.unique_id).where(
                    sa.and_(
                        tab_table.c.page_type == 'output',
                        tab_table.c.position == 0
                    )
                )
            ).scalar()

            if default_output_tab:
                conn.execute(
                    output_table.update().values(tab_id=default_output_tab)
                )

            # Add foreign key and index
            with op.batch_alter_table('output', schema=None) as batch_op:
                batch_op.create_foreign_key('fk_output_tab_id', 'tab', ['tab_id'], ['unique_id'], ondelete='CASCADE')
                batch_op.create_index('ix_output_tab_id', ['tab_id'])

    # 4.3: Add tab_id to function table
    if 'function' in tables:
        columns_function = [c['name'] for c in insp.get_columns('function')]
        if 'tab_id' not in columns_function:
            with op.batch_alter_table('function', schema=None) as batch_op:
                batch_op.add_column(sa.Column('tab_id', sa.String(36), nullable=True))

            # Set tab_id to default Function tab for all existing entries
            function_table = table('function', column('tab_id', sa.String))
            default_function_tab = conn.execute(
                sa.select(tab_table.c.unique_id).where(
                    sa.and_(
                        tab_table.c.page_type == 'function',
                        tab_table.c.position == 0
                    )
                )
            ).scalar()

            if default_function_tab:
                conn.execute(
                    function_table.update().values(tab_id=default_function_tab)
                )

            # Add foreign key and index
            with op.batch_alter_table('function', schema=None) as batch_op:
                batch_op.create_foreign_key('fk_function_tab_id', 'tab', ['tab_id'], ['unique_id'], ondelete='CASCADE')
                batch_op.create_index('ix_function_tab_id', ['tab_id'])

    # ========================================
    # Step 5: Update Widget table to use tab_id instead of dashboard_id
    # ========================================
    if 'widget' in tables:
        columns_widget = [c['name'] for c in insp.get_columns('widget')]

        # Map dashboard_id to tab unique_id
        if 'dashboard_id' in columns_widget and 'tab_id' not in columns_widget:
            # Add new tab_id column
            with op.batch_alter_table('widget', schema=None) as batch_op:
                batch_op.add_column(sa.Column('tab_id', sa.String(36), nullable=True))

            # Migrate dashboard_id to tab_id (dashboard unique_id maps to tab unique_id)
            widget_table = table('widget',
                column('dashboard_id', sa.String),
                column('tab_id', sa.String)
            )

            # Copy dashboard_id to tab_id (they're both unique_ids)
            conn.execute(
                widget_table.update().values(
                    tab_id=widget_table.c.dashboard_id
                )
            )

            # Remove old dashboard_id column and add constraints to tab_id
            with op.batch_alter_table('widget', schema=None) as batch_op:
                batch_op.drop_column('dashboard_id')
                batch_op.create_foreign_key('fk_widget_tab_id', 'tab', ['tab_id'], ['unique_id'], ondelete='CASCADE')
                batch_op.create_index('ix_widget_tab_id', ['tab_id'])


def downgrade():
    """
    Rollback the tab system migration.
    This restores the Dashboard table and removes tab_id columns.
    """
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    tables = insp.get_table_names()

    # ========================================
    # Step 1: Restore dashboard table
    # ========================================
    if 'dashboard' not in tables and 'tab' in tables:
        # Recreate dashboard table
        op.create_table(
            'dashboard',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('locked', sa.Boolean(), nullable=True, server_default='0'),
            sa.Column('sort_order', sa.Integer(), nullable=True, server_default='0'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unique_id'),
            sa.UniqueConstraint('name')
        )
        op.create_index('ix_dashboard_sort_order', 'dashboard', ['sort_order'])

        # Migrate dashboard tabs back to dashboard table
        tab_table = table('tab',
            column('unique_id', sa.String),
            column('name', sa.Text),
            column('page_type', sa.String),
            column('position', sa.Integer)
        )

        dashboard_table = table('dashboard',
            column('unique_id', sa.String),
            column('name', sa.Text),
            column('locked', sa.Boolean),
            column('sort_order', sa.Integer)
        )

        result = conn.execute(
            sa.select(tab_table).where(tab_table.c.page_type == 'dashboard')
        )
        dashboard_tabs = result.fetchall()

        for tab in dashboard_tabs:
            conn.execute(
                dashboard_table.insert().values(
                    unique_id=tab.unique_id,
                    name=tab.name,
                    locked=False,
                    sort_order=tab.position
                )
            )

    # ========================================
    # Step 2: Restore widget.dashboard_id
    # ========================================
    if 'widget' in tables:
        columns_widget = [c['name'] for c in insp.get_columns('widget')]

        if 'tab_id' in columns_widget and 'dashboard_id' not in columns_widget:
            # Add dashboard_id column
            with op.batch_alter_table('widget', schema=None) as batch_op:
                batch_op.add_column(sa.Column('dashboard_id', sa.String(36), nullable=True))

            # Copy tab_id to dashboard_id
            widget_table = table('widget',
                column('tab_id', sa.String),
                column('dashboard_id', sa.String)
            )

            conn.execute(
                widget_table.update().values(
                    dashboard_id=widget_table.c.tab_id
                )
            )

            # Drop tab_id
            with op.batch_alter_table('widget', schema=None) as batch_op:
                batch_op.drop_constraint('fk_widget_tab_id', type_='foreignkey')
                batch_op.drop_index('ix_widget_tab_id')
                batch_op.drop_column('tab_id')

    # ========================================
    # Step 3: Remove tab_id from entry tables
    # ========================================

    for table_name in ['input', 'output', 'function']:
        if table_name in tables:
            columns = [c['name'] for c in insp.get_columns(table_name)]
            if 'tab_id' in columns:
                with op.batch_alter_table(table_name, schema=None) as batch_op:
                    batch_op.drop_constraint(f'fk_{table_name}_tab_id', type_='foreignkey')
                    batch_op.drop_index(f'ix_{table_name}_tab_id')
                    batch_op.drop_column('tab_id')

    # ========================================
    # Step 4: Drop tab table
    # ========================================
    if 'tab' in tables:
        op.drop_index('ix_tab_position', 'tab')
        op.drop_index('ix_tab_page_type', 'tab')
        op.drop_table('tab')

# coding=utf-8
"""P5-14: Merge AoT_on_off_counter widget into AoT_timer.

The On/Off Counter widget has been folded into the unified AoT_timer widget
(cycle mode). This data migration converts existing dashboard widgets with
graph_type 'AoT_on_off_counter' to 'AoT_timer', setting operation_mode='cycle'
and a default start_at='00:00' while preserving run/rest/cycles and display
options. A '_migrated_from' marker is written so downgrade can revert exactly
the widgets this migration converted (and nothing else).

custom_options is stored as a JSON string on the widget row.

Revision ID: p5_14_merge_counter_into_timer
Revises: p5_13_refactor_facility_setpoint_schema
Create Date: 2026-06-05
"""

import json

from alembic import op
import sqlalchemy as sa

revision = 'p5_14_merge_counter_into_timer'
down_revision = 'p5_13_refactor_facility_setpoint_schema'
branch_labels = None
depends_on = None

OLD_TYPE = 'AoT_on_off_counter'
NEW_TYPE = 'AoT_timer'
MARKER = '_migrated_from'


def _load_opts(raw):
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def upgrade():
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, custom_options FROM widget WHERE graph_type = :gt"),
        {"gt": OLD_TYPE}
    ).fetchall()
    for row in rows:
        opts = _load_opts(row[1])
        opts['operation_mode'] = 'cycle'
        opts.setdefault('start_at', '00:00')
        opts.pop('tz_offset', None)          # removed in the unified timer
        opts[MARKER] = OLD_TYPE              # so downgrade can revert exactly these
        conn.execute(
            sa.text("UPDATE widget SET graph_type = :new, custom_options = :opts WHERE id = :id"),
            {"new": NEW_TYPE, "opts": json.dumps(opts), "id": row[0]}
        )


def downgrade():
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, custom_options FROM widget WHERE graph_type = :gt"),
        {"gt": NEW_TYPE}
    ).fetchall()
    for row in rows:
        opts = _load_opts(row[1])
        if opts.get(MARKER) != OLD_TYPE:
            continue                          # only revert widgets this migration created
        opts.pop(MARKER, None)
        opts.pop('operation_mode', None)
        opts.pop('start_at', None)
        conn.execute(
            sa.text("UPDATE widget SET graph_type = :old, custom_options = :opts WHERE id = :id"),
            {"old": OLD_TYPE, "opts": json.dumps(opts), "id": row[0]}
        )

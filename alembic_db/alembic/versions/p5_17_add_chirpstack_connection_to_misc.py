# coding=utf-8
"""P5-17: Add ChirpStack LNS connection fields to misc.

Adds global ChirpStack connection settings used by the ChirpStack Devices
page to list devices via gRPC and pre-fill registered Inputs/Outputs:
- chirpstack_grpc_server (host:port)
- chirpstack_api_token (API key / JWT)
- chirpstack_mqtt_host (broker host for registered MQTT inputs)
- chirpstack_mqtt_port (broker port for registered MQTT inputs)

Revision ID: p5_17_add_chirpstack_connection_to_misc
Revises: p5_16_add_pid_schedule_fields
Create Date: 2026-06-06
"""

revision = 'p5_17_add_chirpstack_connection_to_misc'
down_revision = 'p5_16_add_pid_schedule_fields'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _col_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    cols = _col_names('misc')
    if 'chirpstack_grpc_server' not in cols:
        op.add_column('misc', sa.Column('chirpstack_grpc_server', sa.String(length=255), server_default='', nullable=True))
    if 'chirpstack_api_token' not in cols:
        op.add_column('misc', sa.Column('chirpstack_api_token', sa.Text(), server_default='', nullable=True))
    if 'chirpstack_mqtt_host' not in cols:
        op.add_column('misc', sa.Column('chirpstack_mqtt_host', sa.String(length=255), server_default='', nullable=True))
    if 'chirpstack_mqtt_port' not in cols:
        op.add_column('misc', sa.Column('chirpstack_mqtt_port', sa.Integer(), server_default='1883', nullable=True))


def downgrade():
    cols = _col_names('misc')
    for name in ('chirpstack_grpc_server', 'chirpstack_api_token',
                 'chirpstack_mqtt_host', 'chirpstack_mqtt_port'):
        if name in cols:
            op.drop_column('misc', name)

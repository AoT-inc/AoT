# coding=utf-8
"""P5-26: PID DeviceMeasurements 누락 데이터 보정.

구버전 DB에서 마이그레이션된 PID 레코드는 device_measurements 채널이
자동 생성되지 않아 'Could not find measurements' 오류로 활성화가 불가능했음.

각 PID(pid 테이블)에 대해 device_measurements에 해당 device_id의 행이
하나도 없을 경우에만 채널 0~9를 삽입한다.

이미 채널이 존재하는 PID는 건드리지 않으므로 재실행해도 안전하다(멱등성).
채널 0~2(Setpoint)의 unit은 의도적으로 빈 문자열로 삽입 — pid_activate에서
실제 측정값 단위로 채워진다.

Revision ID: p5_26_fix_pid_device_measurements
Revises: p5_25_add_crop_preset_recipe_targets
Create Date: 2026-06-19
"""

import uuid as _uuid

from alembic import op
import sqlalchemy as sa


revision = 'p5_26_fix_pid_device_measurements'
down_revision = 'p5_25_add_crop_preset_recipe_targets'
branch_labels = None
depends_on = None

# PID 채널 정의 — 작성 시점의 PID_INFO['measure'] 값을 하드코딩.
# 앱 코드(PID_INFO)가 나중에 변경되더라도 이 마이그레이션은 항상 동일하게 동작함.
_PID_CHANNELS = [
    # (channel, name, measurement, measurement_type, unit)
    (0, 'Setpoint',            '',             'setpoint', ''),
    (1, 'Setpoint (Band Min)', '',             'setpoint', ''),
    (2, 'Setpoint (Band Max)', '',             'setpoint', ''),
    (3, 'P-value',             'pid_p_value',  '',         'pid_value'),
    (4, 'I-value',             'pid_i_value',  '',         'pid_value'),
    (5, 'D-value',             'pid_d_value',  '',         'pid_value'),
    (6, 'Output (Duration)',   'duration_time','',         's'),
    (7, 'Output (Duty Cycle)', 'duty_cycle',   '',         'percent'),
    (8, 'Output (Volume)',     'volume',       '',         'ml'),
    (9, 'Output (Value)',      'unitless',     '',         'none'),
]


def upgrade():
    conn = op.get_bind()

    # 모든 PID unique_id 조회
    pid_rows = conn.execute(sa.text("SELECT unique_id FROM pid")).fetchall()

    for (pid_id,) in pid_rows:
        # 이미 device_measurements 행이 있으면 건너뜀
        existing = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM device_measurements WHERE device_id = :pid_id"
            ),
            {"pid_id": pid_id}
        ).scalar()

        if existing:
            continue

        # 채널 0~9 삽입
        for (channel, name, measurement, measurement_type, unit) in _PID_CHANNELS:
            conn.execute(
                sa.text("""
                    INSERT INTO device_measurements (
                        unique_id, name, device_type, device_id,
                        is_enabled, measurement, measurement_type, unit, channel,
                        rescale_method, rescale_equation, invert_scale,
                        rescaled_measurement, rescaled_unit,
                        scale_from_min, scale_from_max,
                        scale_to_min, scale_to_max,
                        conversion_id
                    ) VALUES (
                        :unique_id, :name, NULL, :device_id,
                        1, :measurement, :measurement_type, :unit, :channel,
                        'linear', '(x+2)*3', 0,
                        '', '',
                        0, 10,
                        0, 20,
                        ''
                    )
                """),
                {
                    "unique_id": str(_uuid.uuid4()),
                    "name": name,
                    "device_id": pid_id,
                    "measurement": measurement,
                    "measurement_type": measurement_type,
                    "unit": unit,
                    "channel": channel,
                }
            )


def downgrade():
    # 데이터 보정 마이그레이션 — 역방향 삭제 시 정상 데이터까지 지울 위험이 있어
    # downgrade는 의도적으로 no-op으로 둔다.
    pass

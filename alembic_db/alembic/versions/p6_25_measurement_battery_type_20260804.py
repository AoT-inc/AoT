# coding=utf-8
"""P6-25: device_measurements.battery_type 신설 — 배터리 화학 종류 지정.

지도 장치 모달의 배터리 배지는 전압을 % 로 환산해 보여준다. 그런데 **화학 종류는
전압만으로 판별할 수 없다.** 같은 12V 계열이라도

    납산 12V     : 만충 12.7V, 50% 12.0V, 방전 11.4V
    인산철 4S    : 만충 13.4V, 20%  13.0V, 방전 12.0V

로 곡선 모양이 사실상 반대다. 한 곡선으로 둘 다 처리하면 한쪽이 크게 틀린다 —
납산 기준 곡선에 인산철을 넣으면 실사용 구간(12.8~13.4V)이 전부 100% 로 뭉개지고,
인산철 기준에 납산을 넣으면 만충(12.7V)이 40% 로 보인다.

전압 이력으로 자동 추정하는 방법도 검토했으나, 인산철이 깊게 방전되면 납산 구간과
겹친다 — **정확도가 가장 필요한 순간에 정확히 틀린다.** 그래서 사람이 알려주는
길을 연다(2026-08-04 사용자 결정).

koat 김제 현장이 실제로 섞여 있다: AoT-C 밸브 제어기 10대는 인산철, 작년에 다른
구역에 설치한 구버전은 납산.

컬럼은 배터리 **채널**(device_measurements 행)에 둔다 — 화학은 물리 팩의 속성이고,
그 팩을 가리키는 것이 바로 그 채널이기 때문이다. 빈 값('')은 "자동"이며
device_link_status.battery_percent() 가 전압 범위로 추정한다(종전 동작).

Revision ID: p6_25_measurement_battery_type_20260804
Revises: p6_24_cold_storage_tables_20260804
Create Date: 2026-08-04
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_25_measurement_battery_type_20260804'
down_revision = 'p6_24_cold_storage_tables_20260804'
branch_labels = None
depends_on = None

TABLE = 'device_measurements'
COLUMN = 'battery_type'


def _has_column(table, column):
    bind = op.get_bind()
    return column in [c['name'] for c in sa.inspect(bind).get_columns(table)]


def upgrade():
    # 재실행 안전: 이미 있으면 건너뛴다.
    if not _has_column(TABLE, COLUMN):
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.add_column(sa.Column(COLUMN, sa.Text(), nullable=True,
                                          server_default=''))


def downgrade():
    if _has_column(TABLE, COLUMN):
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.drop_column(COLUMN)

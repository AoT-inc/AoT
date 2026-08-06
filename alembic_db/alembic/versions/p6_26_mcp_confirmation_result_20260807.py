# coding=utf-8
"""P6-26: mcp_confirmation.result_json 신설 — 승인이 곧 실행이 되도록.

지금까지 승인은 "실행 허가증"이었다. 사람이 웹에서 승인 버튼을 눌러도 아무 일도
일어나지 않고, 그 사람이 채팅으로 돌아가 AI 에게 승인했다고 말해줘야 AI 가 같은
인자에 `_confirmation_id` 를 붙여 재호출해서 비로소 실행됐다. 승인 후 실행 창이
5분이라, 밭에서 노트북까지 걸어가는 시간을 생각하면 빠듯하다.

농가 입장에서 한 마디("관수 4시부터로 바꿔줘")를 반영시키는 데 앱 전환 두 번과
탭 여러 번이 필요했고, 승인 버튼을 눌러도 끝이 아니라는 점이 특히 혼란스러웠다.

그래서 **승인 시점에 서버가 저장해둔 인자로 직접 실행**한다. 그 결과를 여기
추가하는 컬럼에 남겨두고, 나중에 AI 가 `_confirmation_id` 로 재호출하면 다시
실행하지 않고 저장된 결과를 그대로 돌려준다(재생). 덕분에

  - 사람은 승인 한 번으로 끝난다.
  - 이중 실행이 없다.
  - 이미 배포된 ChatGPT/Claude 설정을 고치지 않아도 그대로 동작한다.

인자 대조(confirmation_params_mismatch)와 1회용 소비 같은 기존 안전장치는 그대로
두며, 오히려 AI 가 실행 시점에 인자를 바꿔 넣을 창 자체가 사라진다.

status 값에 'executed' / 'failed' 가 추가된다(문자열 컬럼이라 스키마 변경 없음).

Revision ID: p6_26_mcp_confirmation_result_20260807
Revises: p6_25_measurement_battery_type_20260804
Create Date: 2026-08-07
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_26_mcp_confirmation_result_20260807'
down_revision = 'p6_25_measurement_battery_type_20260804'
branch_labels = None
depends_on = None

TABLE = 'mcp_confirmation'
COLUMN = 'result_json'


def _has_column(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return True  # 테이블이 없으면 할 일도 없다
    return column in [c['name'] for c in insp.get_columns(table)]


def upgrade():
    # 재실행 안전: 이미 있으면 건너뛴다.
    if not _has_column(TABLE, COLUMN):
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.add_column(sa.Column(COLUMN, sa.Text(), nullable=True))


def downgrade():
    if _has_column(TABLE, COLUMN):
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.drop_column(COLUMN)

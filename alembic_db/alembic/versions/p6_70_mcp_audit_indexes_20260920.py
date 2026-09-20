# coding=utf-8
"""P6-70: mcp_audit_log / mcp_confirmation 인덱스 추가.

두 테이블은 지금까지 아무도 지우지 않아 무한히 커지는 상태였다(모델 docstring 은
"90일 보존"이라고 적혀 있었지만 그 정리 코드가 없었다). 이번에
`aot.utils.audit.purge_old_mcp_logs` 를 붙여 하루 1회 정리하게 했고, 그 정리
쿼리와 기존 조회 경로가 풀스캔을 타지 않도록 인덱스를 붙인다.

  mcp_audit_log
    timestamp        — 정리 잡의 `timestamp < cutoff`, get_recent 의 역순 정렬
    confirmation_id  — 승인/거부 시 해당 호출 행 되찾기(mcp_safety_gate._decide)

  mcp_confirmation
    (status, created_at) — 승인 대기 목록(list_pending)
    created_at          — 정리 잡의 `created_at < cutoff`

(agent_id, tool_name, created_at) 복합 인덱스는 일부러 넣지 않았다. 그 조합으로
세는 쿼리가 아직 없기 때문이다 — mcp_safety_gate._check_rate_limit 은 여전히
프로세스 인메모리(_call_log)로 세고, DB 를 건드리지 않는다. 레이트리밋을
프로세스 간 공유 카운터로 바꾸는 날 그 인덱스를 함께 넣는 게 맞다.

두 테이블은 alembic 이 아니라 모델 등록 + db.create_all() 로 만들어졌다(전용
create_table 리비전이 없다). 그래서 여기서는 테이블/인덱스 존재 여부를 확인한
뒤에만 만든다 — 신규 설치는 create_all 이 모델의 __table_args__ 인덱스를 이미
만들어 둔 상태로 이 리비전에 들어온다.

Revision ID: p6_70_mcp_audit_indexes_20260920
Revises: p6_69_geo_marker_position_20260915
Create Date: 2026-09-20
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_70_mcp_audit_indexes_20260920'
down_revision = 'p6_69_geo_marker_position_20260915'
branch_labels = None
depends_on = None


_INDEXES = [
    # (index_name, table_name, [columns])
    ('ix_mcp_audit_log_timestamp', 'mcp_audit_log', ['timestamp']),
    ('ix_mcp_audit_log_confirmation_id', 'mcp_audit_log', ['confirmation_id']),
    ('ix_mcp_confirmation_status_created_at', 'mcp_confirmation',
     ['status', 'created_at']),
    ('ix_mcp_confirmation_created_at', 'mcp_confirmation', ['created_at']),
]


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade():
    insp = _inspector()
    for index_name, table_name, columns in _INDEXES:
        if not insp.has_table(table_name):
            # 아직 테이블이 없는 설치 — create_all 이 모델의 __table_args__ 로
            # 같은 인덱스를 만들어 준다.
            continue
        existing = {ix['name'] for ix in insp.get_indexes(table_name)}
        if index_name in existing:
            continue
        op.create_index(index_name, table_name, columns)


def downgrade():
    insp = _inspector()
    for index_name, table_name, _columns in _INDEXES:
        if not insp.has_table(table_name):
            continue
        existing = {ix['name'] for ix in insp.get_indexes(table_name)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table_name)

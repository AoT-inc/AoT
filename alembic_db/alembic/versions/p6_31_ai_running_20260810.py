# coding=utf-8
"""P6-31: AI 서비스 "활성화" 와 "작동 시작" 을 분리 — ai_global_settings.ai_running.

`ai_enabled` 하나가 두 가지 일을 겸하고 있었다: 메뉴/페이지를 여는 일과,
백그라운드 AI 잡(주기 요약·컨텍스트 브로드캐스트·날씨 요약·MCP 헬스체크)을
돌리는 일. 그래서 설정에서 AI 를 켜는 순간, 에이전트를 하나도 등록하지 않은
상태에서도 잡들이 돌기 시작해 매 주기마다 로그에 에러만 쌓였다
(`No suitable AI agent found for summary generation.`).

`ai_running` 은 후자만 담당한다. 켜는 자리는 설정이 아니라 AI 페이지다 —
모델을 등록하는 그 화면에서 "이제 돌려라" 를 누르는 것이 자연스럽고,
등록된 모델이 없으면 켤 수 없게 막을 수 있는 자리이기도 하다.

기본값은 꺼짐이다. 업그레이드로 조용히 돌기 시작하면 안 되고, 이미 AI 를
쓰고 있던 서버는 AI 페이지에서 한 번 켜 주면 된다.

Revision ID: p6_31_ai_running_20260810
Revises: p6_30_docker_auto_update_20260810
Create Date: 2026-08-10
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_31_ai_running_20260810'
down_revision = 'p6_30_docker_auto_update_20260810'
branch_labels = None
depends_on = None

_TABLE = 'ai_global_settings'
_COLUMN = 'ai_running'


def _has_column(table, column):
    bind = op.get_bind()
    return column in [c['name'] for c in sa.inspect(bind).get_columns(table)]


def upgrade():
    # 재실행 안전: 이미 있으면 건너뛴다.
    if _has_column(_TABLE, _COLUMN):
        return
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            _COLUMN, sa.Boolean(), nullable=True,
            # server_default 가 있어야 기존 행에도 0 이 들어간다. NULL 로 두면
            # 게이트가 매번 None 을 만나는데, 판정 코드가 falsy 로 읽어 결과는
            # 같더라도 "꺼짐" 과 "값 없음" 이 화면에서 구분되지 않는다.
            server_default=sa.text("0")))


def downgrade():
    if not _has_column(_TABLE, _COLUMN):
        return
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_column(_COLUMN)

# coding=utf-8
"""P6-73: AI 채팅 사용 권한 — `roles.use_ai_chat`.

배경: AI 채팅 제안의 **실행**은 이번에 승인자 검사(`edit_controllers`+그룹
스코프)를 새로 걸었다(`docs/design/access-scope-groups.md` §6-2⑦). 그런데
채팅 자체(LLM 호출)는 별개 질문이다 — 호출 비용이 들고, 데모/방문자 계정에
그대로 열려 있으면 안 된다. 제품 결정(2026-09-22): Monitor 는 조회·질문용으로
채팅을 쓸 수 있어야 하지만 Guest·Kiosk 는 막는다.

## 백필이 이 마이그레이션의 요지다

컬럼만 추가하고 끝내면 **기존 역할이 업그레이드 순간 전부 채팅을 잃는다**
(새 컬럼 기본값이 False). 이름이 기본 다섯 역할과 같은 행은
`populate_db()`(`aot/databases/models/__init__.py`)가 앱 기동 때마다
`USER_ROLES` 값으로 다시 덮어써 스스로 맞아 들어가므로, 여기 백필은
**이름이 다른 커스텀 역할**(관리자가 새로 만들었거나 기본 역할 이름을 바꾼
경우)을 위한 것이다. 판정은 새 권한 하나로 고정하지 않는다 — 기본 Admin·
Editor·Monitor 를 가르는 것은 "쓰기 권한이 있다" 이거나 "네 가지 보기 권한이
전부 있다"(Monitor 의 특징: 설정·카메라·통계·로그를 전부 보되 편집은 못
한다)이므로, edit_controllers 가 있거나 그 네 가지 view_* 가 모두 참인 역할에
채팅을 열어 준다. Guest·Kiosk 는 이 조건을 만족하지 않는다(Kiosk 는
view_camera·view_stats 는 참이지만 view_settings·view_logs 가 거짓이다).

Revision ID: p6_73_role_use_ai_chat_20260922
Revises: p6_72_device_tz_source_system_20260921
Create Date: 2026-09-22
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_73_role_use_ai_chat_20260922'
down_revision = 'p6_72_device_tz_source_system_20260921'
branch_labels = None
depends_on = None

_TABLE = 'roles'


def _columns(bind):
    return {c['name'] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return                      # 새 설치는 create_all + 시드가 처리한다

    if 'use_ai_chat' not in _columns(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column('use_ai_chat', sa.Boolean(),
                                       nullable=False, server_default=sa.false()))

    # 백필 — 커스텀 이름의 역할 중, 편집 권한이 있거나(Editor 계열) 전부
    # 보기만 하는(Monitor 계열) 역할은 채팅도 계속 쓸 수 있어야 한다.
    op.execute(sa.text(
        "UPDATE roles SET use_ai_chat = 1 "
        "WHERE edit_controllers = 1 "
        "OR (view_settings = 1 AND view_camera = 1 "
        "    AND view_stats = 1 AND view_logs = 1)"))


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    if 'use_ai_chat' in _columns(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column('use_ai_chat')

# coding=utf-8
"""P6-78: SMTP 계정 비밀번호를 암호화해 저장한다.

`smtp.passw` 는 평문 Text 였다. 대개 메일 계정의 앱 비밀번호라 설정 내보내기·
백업 파일에도 그대로 실렸다. 구글 달력 토큰과 같은 방식(`aot.utils.crypto`,
flask_secret_key 에서 파생한 Fernet)으로 봉인하고, 값 앞에 `aotenc1:` 표지를
붙여 평문과 구분한다.

데몬과 웹앱이 둘 다 마이그레이션을 돌리므로 다시 실행해도 안전해야 한다 —
표지가 붙은 값은 건드리지 않고, 갱신은 `WHERE passw = <읽은 값>` 로 걸어
그 사이 다른 쪽이 바꾼 행을 덮어쓰지 않는다. 컬럼 자체는 그대로다(스키마 변경
없음).

Revision ID: p6_78_smtp_password_encrypt_20260930
Revises: p6_77_mcp_central_auth_20260928
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_78_smtp_password_encrypt_20260930'
down_revision = 'p6_77_mcp_central_auth_20260928'
branch_labels = None
depends_on = None


def _has_column(bind):
    insp = sa.inspect(bind)
    return insp.has_table('smtp') and 'passw' in {
        c['name'] for c in insp.get_columns('smtp')}


def upgrade():
    from aot.utils.crypto import is_sealed, seal_secret

    bind = op.get_bind()
    if not _has_column(bind):
        return                      # 새 설치는 create_all 이 처리한다
    rows = bind.execute(sa.text("SELECT id, passw FROM smtp")).fetchall()
    for row_id, passw in rows:
        if not passw or is_sealed(passw):
            continue
        bind.execute(
            sa.text("UPDATE smtp SET passw = :new WHERE id = :id AND passw = :old"),
            {'new': seal_secret(passw), 'id': row_id, 'old': passw})


def downgrade():
    from aot.utils.crypto import is_sealed, open_sealed

    bind = op.get_bind()
    if not _has_column(bind):
        return
    rows = bind.execute(sa.text("SELECT id, passw FROM smtp")).fetchall()
    for row_id, passw in rows:
        if not is_sealed(passw):
            continue
        plain, _state = open_sealed(passw)
        # 복호화할 수 없으면(다른 설치의 값) 되돌릴 평문이 없다 — 비워 다시 입력받는다.
        bind.execute(
            sa.text("UPDATE smtp SET passw = :new WHERE id = :id AND passw = :old"),
            {'new': plain, 'id': row_id, 'old': passw})

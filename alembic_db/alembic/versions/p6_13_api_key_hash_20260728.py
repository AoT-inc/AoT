# coding=utf-8
"""P6-13: API 키를 평문 저장에서 해시 저장으로 전환.

users.api_key 는 128바이트 난수를 **평문(BLOB)** 으로 보관해 왔다. DB 가 한 번
유출되면 그대로 인증에 쓸 수 있는 값이라, 비밀번호를 bcrypt 로 보관하는 것과
같은 이유로 해시만 남겨야 한다.

**기존 키는 계속 동작한다.** 이 마이그레이션이 DB 에 있는 평문 키를 읽어
SHA-256 을 계산해 api_key_hash 에 넣고 평문을 지우기 때문이다 — 클라이언트가
들고 있는 키 값 자체는 바뀌지 않으므로 외부 연동을 다시 설정할 필요가 없다.

달라지는 것은 **조회**다. 설정 화면이 저장된 키를 다시 보여줄 수 없게 된다
(발급 시 1회만 노출). 키를 분실하면 재발급해야 한다 — GitHub/AWS 등이 쓰는
표준 방식이며, 애초에 "언제든 다시 볼 수 있는 자격증명"은 보관 위험을 계속
안고 가는 구조다.

bcrypt 가 아니라 SHA-256 인 이유는 User.api_key_hash 컬럼 주석 참조
(요약: 128바이트 난수라 무차별 대입이 불가능하고, API 인증은 매 요청마다
일어나므로 bcrypt 의 의도적 지연이 그대로 응답 지연이 된다).

api_key 컬럼은 남겨두되 값을 비운다. SQLite 에서 컬럼 삭제는 테이블 재생성을
요구해 위험 대비 이득이 없다.

**downgrade 주의**: 평문 키는 복구할 수 없다(해시에서 역산 불가). 되돌리면
api_key_hash 컬럼만 사라지고 모든 API 키는 재발급이 필요하다.

Revision ID: p6_13_api_key_hash_20260728
Revises: p6_12_audit_log_and_login_hardening_20260727
Create Date: 2026-07-28
"""
import hashlib

import sqlalchemy as sa
from alembic import op

revision = 'p6_13_api_key_hash_20260728'
down_revision = 'p6_12_audit_log_and_login_hardening_20260727'
branch_labels = None
depends_on = None

_TABLE = 'users'
_COLUMN = 'api_key_hash'


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def _has_column(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = [c['name'] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def upgrade():
    if not _has_table(_TABLE):
        return

    if not _has_column(_TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=64), nullable=True))
        op.create_index('ix_users_api_key_hash', _TABLE, [_COLUMN], unique=True)

    if not _has_column(_TABLE, 'api_key'):
        return

    # 기존 평문 키 → 해시. 여기서 옮겨두지 않으면 발급된 키가 전부 무효가 된다.
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, api_key FROM users "
        "WHERE api_key IS NOT NULL AND api_key != ''")).fetchall()

    migrated = 0
    for row in rows:
        raw = row[1]
        if raw is None:
            continue
        if isinstance(raw, str):
            raw = raw.encode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        bind.execute(
            sa.text("UPDATE users SET api_key_hash = :h, api_key = NULL "
                    "WHERE id = :i"),
            {'h': digest, 'i': row[0]})
        migrated += 1

    if migrated:
        print("[p6_13] API 키 %d개를 해시로 전환하고 평문을 제거했습니다." % migrated)


def downgrade():
    # 평문은 복구할 수 없다 — 되돌리면 모든 API 키 재발급이 필요하다.
    if _has_table(_TABLE) and _has_column(_TABLE, _COLUMN):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)

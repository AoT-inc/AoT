# coding=utf-8
"""P6-89: AI 카드 다중 첨부 테이블 (ai_card_attachments).

카드당 이미지·파일·영상 링크를 최대 8개 받는다(P5). 카드(ai_screen_cards)의 file_* 칸은
**첫 파일형 첨부**를 이중으로 기록하는 호환용으로 남는다(옛 번들·되돌리기 안전판).

  card_id/user_id  카드·주인(일 한도·용량 합계를 조인 없이 센다)
  position         카드 안 순서 0..7 — 수신함 API 의 `?i=` 값. (card_id, position) 유일
  kind             image | file | artifact | video
  path/thumb       PATH_AI_CARD_FILES 아래 상대경로(video 는 path NULL, thumb 은 포스터)
  name/mime/size   표시 이름·서버가 정한 MIME·디스크 바이트(video 는 포스터 바이트)
  url/provider/host  video 만 — 서버가 정규화한 https 주소·제공처·표기용 호스트
  playable         video(direct) 만 — post 때 한 번 판정한 뷰어 안 재생 허용(백필·옛 행은 NULL=false)

백필: file_path 가 있는 카드마다 position 0 행이 없으면 넣는다(두 번 돌려도 같은 결과).
재실행 안전: 테이블·인덱스가 이미 있으면 건너뛴다.

downgrade 는 인덱스·테이블을 지운다. 첫 파일은 카드 칸에 남아 있어 보존되지만 **position ≥ 1
파일은 옛 코드의 sweep_orphans 가 1시간 뒤 지운다**(영상 포스터도 마찬가지) — 되돌리기 전에
DB 와 uploads/ai_cards 를 백업한다.

Revision ID: p6_89_ai_card_attachments_20261021
Revises: p6_88_ai_card_notice_20261019
Create Date: 2026-10-21
"""
import datetime

import sqlalchemy as sa
from alembic import op

revision = 'p6_89_ai_card_attachments_20261021'
down_revision = 'p6_88_ai_card_notice_20261019'
branch_labels = None
depends_on = None

TABLE = 'ai_card_attachments'
CARDS = 'ai_screen_cards'
IX_CARD_POS = 'ux_ai_card_attachments_card_pos'
IX_USER_CREATED = 'ix_ai_card_attachments_user_created'


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return _inspector().has_table(name)


def _indexes():
    return {i['name'] for i in _inspector().get_indexes(TABLE)}


def upgrade():
    if not _has_table(TABLE):
        op.create_table(
            TABLE,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('card_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('position', sa.SmallInteger(), nullable=False),
            sa.Column('kind', sa.String(length=16), nullable=True),
            sa.Column('path', sa.String(length=255), nullable=True),
            sa.Column('thumb', sa.String(length=255), nullable=True),
            sa.Column('name', sa.String(length=120), nullable=True),
            sa.Column('mime', sa.String(length=64), nullable=True),
            sa.Column('size', sa.Integer(), nullable=True),
            sa.Column('url', sa.String(length=2048), nullable=True),
            sa.Column('provider', sa.String(length=16), nullable=True),
            sa.Column('host', sa.String(length=253), nullable=True),
            sa.Column('playable', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['card_id'], [CARDS + '.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('id'),
        )
    have = _indexes()
    if IX_CARD_POS not in have:
        op.create_index(IX_CARD_POS, TABLE, ['card_id', 'position'], unique=True)
    if IX_USER_CREATED not in have:
        op.create_index(IX_USER_CREATED, TABLE, ['user_id', 'created_at'])
    _backfill()


def _backfill():
    """file_path 가 있는 카드의 첫 파일을 position 0 행으로 옮긴다(이미 있으면 건너뜀)."""
    if not _has_table(CARDS):
        return
    cols = {c['name'] for c in _inspector().get_columns(CARDS)}
    if 'file_path' not in cols:
        return
    bind = op.get_bind()
    att = sa.table(
        TABLE, sa.column('card_id'), sa.column('user_id'), sa.column('position'),
        sa.column('kind'), sa.column('path'), sa.column('thumb'), sa.column('name'),
        sa.column('mime'), sa.column('size'), sa.column('created_at'))
    have = {r[0] for r in bind.execute(
        sa.text('SELECT card_id FROM %s WHERE "position" = 0' % TABLE))}
    rows = bind.execute(sa.text(
        'SELECT id, user_id, kind, file_path, file_name, file_mime, file_size, created_at '
        'FROM %s WHERE file_path IS NOT NULL' % CARDS)).fetchall()
    batch = []
    for cid, uid, kind, path, name, mime, size, created in rows:
        if cid in have:
            continue
        kind = kind if kind in ('image', 'file', 'artifact') else 'file'
        if isinstance(created, str):
            try:
                created = datetime.datetime.fromisoformat(created)
            except ValueError:
                created = None
        batch.append({
            'card_id': cid, 'user_id': uid, 'position': 0, 'kind': kind, 'path': path,
            'thumb': (path.rsplit('.', 1)[0] + '_t.jpg') if kind == 'image' else None,
            'name': name, 'mime': mime, 'size': size or 0,
            'created_at': created or datetime.datetime.utcnow()})
    for i in range(0, len(batch), 200):
        bind.execute(att.insert(), batch[i:i + 200])


def downgrade():
    if not _has_table(TABLE):
        return
    have = _indexes()
    for name in (IX_USER_CREATED, IX_CARD_POS):
        if name in have:
            op.drop_index(name, table_name=TABLE)
    op.drop_table(TABLE)

# coding=utf-8
"""P6-36: 식생 구획의 두둑 규격 컬럼을 걷어낸다 (p6_35 되돌리기).

p6_35 는 `bed_width_cm` + `path_width_cm` 을 받았고 26.08.5 로 출시됐다.
두 가지가 틀렸다.

1. **모호한 사람의 말이 정수 칸에 들어가지 않는다.** 농부는 두둑과 고랑을 따로
   세지 않는다 — 두둑을 만들면 고랑은 딸려 온다. 그래서 "두둑 폭" 을 물으면
   고랑을 뺀 윗면으로 답하는 사람과 고랑까지 포함한 한 세트로 답하는 사람이
   갈리고, 같은 밭이 120+40 으로도 160+0 으로도 기록된다. 에러는 나지 않고
   두둑 수만 달라진다. 컬럼은 "어느 쪽 의미로 적었는지" 를 담지 못한다.
2. **대화에서 나오는 결론마다 컬럼을 늘릴 수는 없다.** 두둑 배치는 시작일
   뿐이고 멀칭·지주·관수 관행이 뒤따른다. 그것을 전부 정량화해 스키마에 담는
   것이 어렵기 때문에 노트가 존재한다.

확정된 배치는 구획 노트로 남긴다(`create_note(target_type='planting')`).
근거는 docs/design/geo-vegetation-planting.md.

**데이터 손실 범위**: 26.08.5 를 설치하고 그 사이에 지도 설정 폼에서 두둑 폭·
고랑 폭을 적은 구획이 있다면 그 값은 사라진다. 출시 후 하루이고 기본값이 NULL
이라 실제 입력본은 거의 없을 것으로 본다. 그래도 조용히 버리지는 않는다 —
값이 있는 행은 **노트로 옮긴 뒤** 컬럼을 지운다. 사람이 확인해 적은 사실을
스키마 결정 때문에 없애는 것은 다른 문제이기 때문이다.

Revision ID: p6_36_drop_planting_bed_spec_20260814
Revises: p6_35_planting_bed_spec_20260813
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_36_drop_planting_bed_spec_20260814'
down_revision = 'p6_35_planting_bed_spec_20260813'
branch_labels = None
depends_on = None

_TABLE = 'geo_planting'
_COLUMNS = ('bed_width_cm', 'path_width_cm')


def _existing():
    insp = sa.inspect(op.get_bind())
    if _TABLE not in insp.get_table_names():
        return None
    return {c['name'] for c in insp.get_columns(_TABLE)}


def _rescue_to_notes(conn, have):
    """값이 있는 행을 구획 노트로 옮긴다. 실패해도 마이그레이션은 계속한다.

    노트 테이블이 없거나 스키마가 다른 설치에서 여기서 멈추면 업그레이드 전체가
    막힌다 — 구제는 최선 노력이고, 컬럼 제거가 이 리비전의 본래 일이다.
    """
    if not set(_COLUMNS) <= have:
        return 0
    try:
        rows = conn.execute(sa.text(
            'SELECT unique_id, name, crop, bed_width_cm, path_width_cm '
            'FROM geo_planting '
            'WHERE bed_width_cm IS NOT NULL OR path_width_cm IS NOT NULL'
        )).fetchall()
    except Exception:
        return 0
    if not rows:
        return 0

    import uuid
    from datetime import datetime

    moved = 0
    for r in rows:
        label = (r[1] or r[2] or 'planting')
        text = ('두둑 폭 %s cm / 고랑 폭 %s cm (26.08.5 설정값에서 옮김 — '
                '두둑 간격으로 세려면 두 값을 더한 값을 쓰세요)'
                % (r[3] if r[3] is not None else '?',
                   r[4] if r[4] is not None else '?'))
        try:
            conn.execute(sa.text(
                'INSERT INTO notes (unique_id, date_time, name, note, '
                '                   target_id, target_type, category) '
                'VALUES (:uid, :dt, :nm, :nt, :tid, :tt, :cat)'
            ), {'uid': str(uuid.uuid4()), 'dt': datetime.utcnow(),
                'nm': '두둑 배치 (%s)' % label, 'nt': text,
                'tid': r[0], 'tt': 'planting', 'cat': 'general'})
            moved += 1
        except Exception:
            continue
    return moved


def upgrade():
    have = _existing()
    if have is None:
        return
    conn = op.get_bind()
    _rescue_to_notes(conn, have)
    for col in _COLUMNS:
        if col in have:
            op.drop_column(_TABLE, col)


def downgrade():
    have = _existing()
    if have is None:
        return
    # 값은 되돌리지 않는다 — 노트로 옮겨 두었고, 그 노트가 정본이다.
    for col in _COLUMNS:
        if col not in have:
            op.add_column(_TABLE, sa.Column(col, sa.Integer(), nullable=True))

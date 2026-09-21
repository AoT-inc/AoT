# coding=utf-8
"""P6-72: 장치 시간대 값의 출처를 바로 적는다 — 시스템 폴백 복사본을 'system' 으로.

위치 없는 장치를 만들 때 그 시점의 시스템 시간대(Misc.timezone)를 장치 행에
복사해 왔는데 출처(tz_source)를 비워 두었다. 해석 체인(timekit.resolve_tz)은
출처가 빈 값을 사람이 정한 값('explicit')으로 보므로, 시스템 시간대를 바꿔도 그
장치들의 예약·시퀀스·타이머는 옛 시계로 돌았다. 복제 경로는 같은 복사본을
'inherited' 로 적어 도형에서 물려받은 값처럼 보이게 했다.

**값은 바꾸지 않는다** — 표시만 붙인다. 값을 지금 시스템 시간대로 맞추면 그 장치의
예약 시각이 옮겨질 수 있다(운영자가 옛 시계에 맞춰 시각을 넣었을 수 있다). 표시가
붙은 행은 관리자가 설정 → 일반에서 시스템 시간대를 저장할 때(값이 같아도) 새 값을
따른다(device_tz.sync_system_tz_copies). (docs/design/timezone-management.md §15.4)

분류(장치 7종 표 각각):
  1. 출처 없음 + 값 있음 + 좌표 없음            → 'system'
  2. 'inherited' + 좌표 없음 + 어떤 도형에도 연결 안 됨 → 'system'  (복제 경로의 오기)
  3. 출처 없음 + 값 있음 + 좌표 있음            → 'coords'
  4. 'coords' + 값 없음                          → 출처 비움(좌표가 사라진 뒤 남은 표시)
여러 번 돌려도 결과가 같다.

downgrade 는 'system' 표시만 비운다(2번이 원래 'inherited' 였는지는 되살리지 않는다 —
그 표시는 애초에 틀렸다).

Revision ID: p6_72_device_tz_source_system_20260921
Revises: p6_71_drop_unread_tables_20260920
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_72_device_tz_source_system_20260921'
down_revision = 'p6_71_drop_unread_tables_20260920'
branch_labels = None
depends_on = None

TABLES = ('input', 'output', 'function', 'conditional', 'trigger', 'pid',
          'custom_controller')

_NO_COORDS = '(latitude IS NULL AND longitude IS NULL)'


def _columns(bind, table):
    try:
        return {c['name'] for c in sa.inspect(bind).get_columns(table)}
    except Exception:
        return set()


def _linked_clause(bind):
    """'이 장치 행이 어떤 도형에 연결돼 있다' 를 SQL 로. 표가 없으면 빼고 만든다."""
    names = set(sa.inspect(bind).get_table_names())
    parts = []
    if 'geo_binding' in names:
        parts.append('unique_id IN (SELECT device_id FROM geo_binding)')
    if 'geo_shape' in names and 'device_id' in _columns(bind, 'geo_shape'):
        parts.append('unique_id IN (SELECT device_id FROM geo_shape '
                     'WHERE device_id IS NOT NULL)')
    return ' OR '.join(parts) if parts else '1=0'


def classify(bind):
    """분류를 적용하고 {표: 바뀐 행 수} 를 돌려준다(테스트가 직접 부른다)."""
    linked = _linked_clause(bind)
    changed = {}
    for table in TABLES:
        cols = _columns(bind, table)
        if not {'timezone', 'tz_source', 'latitude', 'longitude', 'unique_id'} <= cols:
            continue
        n = 0
        n += bind.execute(sa.text(
            f"UPDATE {table} SET tz_source = 'system' "
            f"WHERE tz_source IS NULL AND timezone IS NOT NULL AND {_NO_COORDS}")).rowcount
        n += bind.execute(sa.text(
            f"UPDATE {table} SET tz_source = 'system' "
            f"WHERE tz_source = 'inherited' AND {_NO_COORDS} "
            f"AND NOT ({linked})")).rowcount
        n += bind.execute(sa.text(
            f"UPDATE {table} SET tz_source = 'coords' "
            f"WHERE tz_source IS NULL AND timezone IS NOT NULL "
            f"AND NOT {_NO_COORDS}")).rowcount
        n += bind.execute(sa.text(
            f"UPDATE {table} SET tz_source = NULL "
            f"WHERE tz_source = 'coords' AND timezone IS NULL")).rowcount
        changed[table] = n
    return changed


def upgrade():
    classify(op.get_bind())


def downgrade():
    bind = op.get_bind()
    for table in TABLES:
        if 'tz_source' in _columns(bind, table):
            bind.execute(sa.text(
                f"UPDATE {table} SET tz_source = NULL WHERE tz_source = 'system'"))

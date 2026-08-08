#!/usr/bin/env python3
"""geo_binding 백필 — 흩어진 장치 참조 5원(源)을 바인딩 행으로 모은다.

공간 요소와 장치의 연결은 지금 6곳에 흩어져 있다. 그중
`feature.properties.device_id` 는 `geo_shape.device_id` 컬럼의 사본이므로
백필 대상은 5원이다:

  ① geo_shape.device_id + channel_id
       type='aot_device' → role='marker' (장치 위치 점)
       type='device'     → role='area'   (장치가 담당하는 구역 폴리곤)
  ② geo_facility.fittings[].actuator_id          → spatial_kind='fitting'
  ③ geo_facility.fittings[].input_id (+measurement_id) → 'fitting', role='sensor'
  ④ geo_facility.actuators[].device_uuid         → spatial_kind='actuator'
  ⑤ geo_facility.sensors[] / weather_bindings[]  → 'sensor_role' / 'weather'

**valid_from 은 백필 실행 시각이다.** 과거 교체사는 어디에도 기록돼 있지
않으므로 소급하지 않는다 — 없는 이력을 지어내는 것보다 "여기서부터 안다"가
정직하다.

**device_kind 는 uuid 가 실존하는 테이블로 판별한다.** parent_device_id 가
있어도 백필은 실물 단위 그대로 기록한다 — 장치(복합장치) 우선은 신규 생성
규칙이지 과거 재해석이 아니다. 과거를 재해석하면 사람이 실제로 한 배정과
다른 것이 DB 에 남는다.

**실존하지 않는 장치를 가리키는 참조는 바인딩을 만들지 않고 보고서로만
남긴다.** 죽은 참조를 바인딩으로 승격시키면 고아가 정본이 된다.

기본은 dry-run(쓰기 없음). --apply 전에 DB 백업 필수.

사용:
    python3 -m aot.scripts.backfill_geo_binding            # 미리보기
    python3 -m aot.scripts.backfill_geo_binding --apply    # 실제 반영
    python3 -m aot.scripts.backfill_geo_binding --json     # 기계 판독

종료 코드 0 = 만들 것 없음(또는 --apply 성공), 1 = 대상 있음(dry-run),
2 = 실패.

@phase active
@stability experimental
"""
import argparse
import json
import sys
from collections import defaultdict

from aot.start_flask_ui import app
from aot.aot_flask.extensions import db
from aot.aot_flask.geo.device_binding import device_kind_models
from aot.databases.models import GeoBinding, GeoFacility, GeoShape
from aot.utils.time_utils import utc_now


# device_kind ↔ 모델. geo_integrity_ddl.DEVICE_LINK_TABLES 와 같은 7종이며
# 게이트웨이(device_binding)가 정본이다 — 같은 매핑을 두 벌 두면 한쪽만
# 늘어나 조용히 갈린다. 마커는 Function·PID·Trigger 에도 붙으므로
# (place_device) 3종으로 좁히면 그 마커들이 백필에서 조용히 빠진다.
DEVICE_KIND_MODELS = device_kind_models()

# geo_shape.type → role. 'device' 는 장치가 담당하는 구역 폴리곤이다
# (밸브 하나가 두 구역에 관수할 수 있어 장치당 여러 개가 정당하다).
SHAPE_TYPE_ROLES = {'aot_device': 'marker', 'device': 'area'}


def _json(blob):
    if isinstance(blob, str):
        try:
            return json.loads(blob)
        except (ValueError, TypeError):
            return None
    return blob


def _items(blob):
    """JSON 컬럼을 항목 리스트로. dict 로 저장된 레거시도 흡수한다."""
    data = _json(blob)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [x for x in data.values() if isinstance(x, dict)]
    return []


def _device_index():
    """{장치 uuid: device_kind} — 7개 테이블 전수."""
    index = {}
    for kind, model in DEVICE_KIND_MODELS:
        try:
            for row in model.query.with_entities(model.unique_id).all():
                index.setdefault(row[0], kind)
        except Exception:
            continue
    return index


def _strip_channel(value):
    """'uuid::3' → ('uuid', '3'), 'uuid' → ('uuid', None). 프런트 계약."""
    text = str(value or '')
    if '::' in text:
        head, _, tail = text.partition('::')
        return head, tail or None
    return text, None


class _Collector:
    """수집 결과를 담고 dead/skip 사유를 함께 기록한다."""

    def __init__(self, device_index):
        self.device_index = device_index
        self.rows = []              # 만들 바인딩 (dict)
        self.dead = []              # 실존하지 않는 장치를 가리키는 참조
        self.stats = defaultdict(int)

    def add(self, spatial_kind, spatial_id, role, raw_device_id,
            channel_id='0', measurement_id=None, params=None, where=None):
        device_id, ch_from_id = _strip_channel(raw_device_id)
        if not device_id:
            return
        kind = self.device_index.get(device_id)
        if kind is None:
            self.dead.append({
                'source': spatial_kind, 'spatial_id': spatial_id,
                'role': role, 'device_id': device_id, 'where': where,
            })
            self.stats['dead'] += 1
            return
        self.rows.append({
            'spatial_kind': spatial_kind,
            'spatial_id': spatial_id,
            'role': role,
            'device_kind': kind,
            'device_id': device_id,
            'channel_id': str(channel_id if channel_id not in (None, '')
                              else (ch_from_id or '0')),
            'measurement_id': measurement_id or None,
            'params': params or None,
        })
        self.stats[spatial_kind] += 1


def collect():
    """5원을 훑어 만들 바인딩 목록을 돌려준다. 읽기 전용."""
    col = _Collector(_device_index())

    # ① geo_shape.device_id -------------------------------------------------
    shapes = GeoShape.query.filter(
        GeoShape.device_id.isnot(None),
        GeoShape.device_id != '').all()
    for s in shapes:
        role = SHAPE_TYPE_ROLES.get(s.type)
        if role is None:
            # 장치를 가리키는데 마커도 구역도 아닌 종류 — 조용히 버리지 않고
            # 보고한다. 어휘가 늘었는데 이 표를 안 고친 경우다.
            col.dead.append({
                'source': 'shape', 'spatial_id': s.unique_id,
                'role': None, 'device_id': s.device_id,
                'where': 'type=%s (role 매핑 없음)' % s.type,
            })
            col.stats['unmapped_shape_type'] += 1
            continue
        col.add('shape', s.unique_id, role, s.device_id,
                channel_id=s.channel_id or '0',
                where='geo_shape.id=%s' % s.id)

    # ②③④⑤ geo_facility ---------------------------------------------------
    for fac in GeoFacility.query.all():
        # ②③ fittings — actuator_id(구동)와 input_id+measurement_id(센서)
        for fit in _items(fac.fittings):
            fid = fit.get('id')
            if not fid:
                # id 없는 항목은 안정적으로 가리킬 수 없다. Phase A 는 읽기
                # 전용이므로 여기서 id 를 부여하지 않고 보고만 한다.
                col.stats['fitting_without_id'] += 1
                continue
            slot = '%s:%s' % (fac.unique_id, fid)
            if fit.get('actuator_id'):
                col.add('fitting', slot, 'actuator', fit['actuator_id'],
                        where='%s fittings[%s] kind=%s' % (
                            fac.name, fid, fit.get('kind')))
            if fit.get('input_id'):
                col.add('fitting', slot, 'sensor', fit['input_id'],
                        measurement_id=fit.get('measurement_id'),
                        where='%s fittings[%s] kind=%s' % (
                            fac.name, fid, fit.get('kind')))

        # ④ actuators[].device_uuid — fittings 와 다른 컬럼·다른 키 이름이다
        for act in _items(fac.actuators):
            aid = act.get('id')
            if not aid:
                col.stats['actuator_without_id'] += 1
                continue
            if act.get('device_uuid'):
                col.add('actuator', '%s:%s' % (fac.unique_id, aid),
                        'actuator', act['device_uuid'],
                        where='%s actuators[%s] kind=%s' % (
                            fac.name, aid, act.get('kind')))

        # ⑤ sensors[] — 같은 role 에 여러 장치가 정상(가중평균)
        for sen in _items(fac.sensors):
            role = (sen.get('role') or '').strip()
            dev = (sen.get('device_id') or '').strip()
            if not role or not dev:
                continue
            weight = sen.get('weight')
            col.add('sensor_role', fac.unique_id, role, dev,
                    measurement_id=(sen.get('measurement_id') or '').strip(),
                    params={'weight': weight} if weight is not None else None,
                    where='%s sensors' % fac.name)

        # ⑤ weather_bindings[] — 별도 컬럼, 키 이름도 input_uuid 로 다르다
        for wb in _items(getattr(fac, 'weather_bindings', None)):
            mtype = (wb.get('measurement_type') or '').strip()
            dev = (wb.get('input_uuid') or '').strip()
            if not mtype or not dev:
                continue
            max_age = wb.get('max_age_sec')
            col.add('weather', fac.unique_id, mtype, dev,
                    measurement_id=(wb.get('measurement_id') or '').strip(),
                    params={'max_age_sec': max_age} if max_age else None,
                    where='%s weather_bindings' % fac.name)

    return col


def _existing_keys():
    """이미 있는 현재 바인딩의 유일성 키 — 재실행 시 중복 생성을 막는다."""
    keys = set()
    for b in GeoBinding.query.filter(GeoBinding.valid_to.is_(None)).all():
        keys.add((b.spatial_kind, b.spatial_id, b.role, b.device_id,
                  b.channel_id, b.measurement_id or ''))
    return keys


def apply(rows):
    """바인딩 행을 만든다. 이미 있는 것은 건너뛴다(멱등)."""
    now = utc_now()
    existing = _existing_keys()
    created = 0
    for r in rows:
        key = (r['spatial_kind'], r['spatial_id'], r['role'], r['device_id'],
               r['channel_id'], r['measurement_id'] or '')
        if key in existing:
            continue
        db.session.add(GeoBinding(
            spatial_kind=r['spatial_kind'], spatial_id=r['spatial_id'],
            role=r['role'], device_kind=r['device_kind'],
            device_id=r['device_id'], channel_id=r['channel_id'],
            measurement_id=r['measurement_id'], params=r['params'],
            valid_from=now))
        existing.add(key)
        created += 1
    db.session.commit()
    return created


def _report(col, applied=None):
    print('=' * 68)
    print('geo_binding 백필 %s' % ('적용 결과' if applied is not None
                                   else '미리보기 (쓰기 없음)'))
    print('=' * 68)
    if not col.rows and not col.dead:
        print('만들 바인딩 없음.')
        return
    by_kind = defaultdict(int)
    for r in col.rows:
        by_kind['%s/%s' % (r['spatial_kind'], r['role'])] += 1
    print('\n[만들 바인딩] 총 %d건' % len(col.rows))
    for k in sorted(by_kind):
        print('  %-28s %4d' % (k, by_kind[k]))
    if applied is not None:
        print('\n  → 실제 생성 %d건 (나머지는 이미 존재)' % applied)

    if col.dead:
        print('\n[죽은 참조] %d건 — 바인딩을 만들지 않았다. 정리 대상이다.'
              % len(col.dead))
        for d in col.dead[:30]:
            print('  %-12s %-40s → %s  (%s)' % (
                d['source'], (d['spatial_id'] or '')[:40],
                d['device_id'], d['where']))
        if len(col.dead) > 30:
            print('  ... 외 %d건' % (len(col.dead) - 30))

    for key, label in (('fitting_without_id', 'id 없는 fittings 항목'),
                       ('actuator_without_id', 'id 없는 actuators 항목'),
                       ('unmapped_shape_type', 'role 매핑 없는 도형 종류')):
        if col.stats.get(key):
            print('\n[건너뜀] %s %d건' % (label, col.stats[key]))


def main():
    parser = argparse.ArgumentParser(
        description='geo_binding 백필 (기본 dry-run)')
    parser.add_argument('--apply', action='store_true',
                        help='실제로 바인딩을 생성한다 (DB 백업 후 사용)')
    parser.add_argument('--json', action='store_true', help='기계 판독 출력')
    args = parser.parse_args()

    with app.app_context():
        try:
            col = collect()
        except Exception as exc:
            print('백필 수집 실패: %s' % exc, file=sys.stderr)
            return 2

        applied = None
        if args.apply:
            try:
                applied = apply(col.rows)
            except Exception as exc:
                db.session.rollback()
                print('백필 적용 실패: %s' % exc, file=sys.stderr)
                return 2

        if args.json:
            print(json.dumps({
                'planned': col.rows,
                'dead_refs': col.dead,
                'skipped': dict(col.stats),
                'applied': applied,
            }, ensure_ascii=False, indent=2, default=str))
        else:
            _report(col, applied)

        if applied is not None:
            return 0
        return 1 if col.rows else 0


if __name__ == '__main__':
    sys.exit(main())

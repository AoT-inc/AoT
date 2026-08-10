# coding=utf-8
"""공간 요소 ↔ 장치 연결의 단일 리졸버 — geo 패키지의 세 번째 게이트웨이.

`device_placement`(배치: 마커를 어디에 놓는가)·`device_membership`(소속: 그
마커가 어느 zone 안인가)과 대칭이며, 이 모듈은 **그 자리에 지금 어떤 장치가
매여 있는가**에 답한다. 설계 정본은 docs/design/geo-device-binding.md.

## 왜 리졸버인가

연결이 6곳에 흩어져 있어(도형 컬럼 1 + feature JSON 2 + 시설 JSON 3) 읽는
경로마다 기준이 달랐다. 하나만 보는 코드는 나머지를 못 보고, 장치가 사라져도
아무도 눈치채지 못한다. 읽기를 한 문으로 모아야 Phase C 에서 쓰기를 뒤집을
수 있다 — `map_overlay_id` → `device_membership` 전환과 같은 절차다.

## 폴백 규칙 (Phase B 전용)

바인딩이 있으면 바인딩이 정본이고, 없으면 레거시 저장처를 읽는다. **폴백이
실제로 쓰이면 로그를 남긴다** — 침묵 폴백은 "전환이 끝났다"는 착각을 만들고,
그 착각 위에서 Phase C 가 레거시를 지우면 그때 터진다. 로그가 0 이 되는 것이
Phase C 의 게이팅 조건이다.

폴백은 Phase C 에서 통째로 제거된다. 새 코드는 폴백 동작에 의존하지 말 것.

## 쓰기 (Phase B-2)

`bind`/`unbind`/`rebind` 가 바인딩을 만드는 유일한 문이다. UI·REST·마커
배치 경로가 전부 여기를 지나간다 — 밖에서 `GeoBinding(...)` 을 직접 만들면
`check_geo_writes.py` 의 GB-7 이 거부한다.

`end_all_for_device()` 는 장치 삭제 17경로(utils_* 7 + tab_service 7 +
진단 일괄 3)가 부르는 유일한 문이다. 도형은 지우지 않고 미배정 슬롯으로
남긴다 — 예외는 위치 마커뿐.

@phase active
@stability experimental
"""
import json
import logging

from aot.aot_flask.extensions import db
from aot.databases.geo_integrity_ddl import (
    MULTI_OCCUPANCY_KINDS, SINGLE_OCCUPANCY_KINDS, VALID_DEVICE_KINDS,
    VALID_END_REASONS, VALID_SPATIAL_KINDS)
from aot.databases.models import GeoBinding
from aot.utils.time_utils import utc_now

logger = logging.getLogger(__name__)

# 도형 종류 → 바인딩 role. 마커(위치 점)와 구역(담당 폴리곤)은 뜻이 다르다.
SHAPE_TYPE_ROLES = {'aot_device': 'marker', 'device': 'area'}

# 폴백 사용을 종류별로 한 번씩만 기록한다 — 핫패스(지도 렌더·시설 runtime)에서
# 매 도형마다 찍으면 로그가 쓸모없어진다. 목적은 "아직 폴백이 살아 있다"는
# 사실을 알리는 것이지 건수를 세는 것이 아니다(건수는 check_geo_integrity 의
# binding-drift 가 정확히 센다).
_fallback_seen = set()


def _note_fallback(kind, detail=''):
    if kind in _fallback_seen:
        return
    _fallback_seen.add(kind)
    logger.info(
        '[GeoBinding] 레거시 폴백 사용: %s%s — 아직 geo_binding 으로 전환되지 '
        '않은 연결이 있다. `check_geo_integrity` 의 binding-drift 로 건수를 '
        '확인하고 backfill_geo_binding 을 적용할 것.',
        kind, (' (%s)' % detail) if detail else '')


def reset_fallback_log():
    """폴백 로그 기억을 비운다(테스트·진단용)."""
    _fallback_seen.clear()


def _any_device_exists(device_ids):
    """주어진 uuid 중 실존하는 장치가 하나라도 있으면 True.

    폴백 신호에서 **죽은 참조를 걸러내기 위한 것**이다. 백필은 실존하지 않는
    장치를 가리키는 참조에 바인딩을 만들지 않는다(고아를 정본으로 승격시키지
    않는 정책). 그래서 죽은 참조는 "바인딩 없음 + 레거시 값 있음"이 되어
    폴백과 구분되지 않는데, 그대로 두면 백필을 다 끝내도 폴백 경고가 영원히
    켜진 채로 남는다. 그 순간 이 신호는 Phase C 게이팅으로 못 쓰게 되고,
    켜져 있는 게 정상인 경고는 아무도 안 보게 된다(CI 13연속 실패 교훈).

    죽은 참조는 `check_geo_integrity` 의 orphan-device-shape /
    dangling-fitting 이 담당한다 — 여기서 중복해서 울리지 않는다.

    호출은 로그를 처음 남기려 할 때뿐이라(종류당 1회) 비용이 없다.
    """
    ids = {str(d).split('::')[0] for d in (device_ids or []) if d}
    if not ids:
        return False

    from aot.databases.models import (
        Conditional, CustomController, Function, Input, Output, PID, Trigger)

    for model in (Input, Output, CustomController, Function, PID, Trigger,
                  Conditional):
        try:
            if model.query.with_entities(model.unique_id).filter(
                    model.unique_id.in_(ids)).first() is not None:
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# 조회 — 바인딩 자체
# ---------------------------------------------------------------------------

def current(spatial_kind, spatial_id, role=None, channel_id=None):
    """지금 유효한 바인딩 목록(valid_to IS NULL).

    단일 점유 슬롯이라도 리스트를 돌려준다 — 호출자가 "하나뿐"을 가정하다
    다중 점유(sensor_role)에서 조용히 첫 항목만 쓰는 사고를 막기 위함이다.
    하나만 필요하면 `current_one()`.
    """
    q = GeoBinding.query.filter(
        GeoBinding.spatial_kind == spatial_kind,
        GeoBinding.spatial_id == spatial_id,
        GeoBinding.valid_to.is_(None))
    if role is not None:
        q = q.filter(GeoBinding.role == role)
    if channel_id is not None:
        q = q.filter(GeoBinding.channel_id == str(channel_id))
    return q.all()


def current_one(spatial_kind, spatial_id, role=None, channel_id=None):
    """단일 점유 슬롯의 현재 바인딩 하나. 없으면 None."""
    rows = current(spatial_kind, spatial_id, role=role, channel_id=channel_id)
    return rows[0] if rows else None


def bindings_for_device(device_id, include_ended=False):
    """이 장치가 매여 있는(있었던) 슬롯 전부. 장치 삭제·교체 화면의 근거."""
    q = GeoBinding.query.filter(GeoBinding.device_id == device_id)
    if not include_ended:
        q = q.filter(GeoBinding.valid_to.is_(None))
    return q.order_by(GeoBinding.valid_from).all()


def history(spatial_kind, spatial_id, role=None):
    """슬롯의 장치 교체사 — 종료된 것 포함, 시간순.

    시계열 접합의 근거다: InfluxDB 태그는 device_id 그대로 두고(과거 데이터
    재작성 금지), 조회 시점에 이 구간 목록으로 이어 붙인다.
    """
    q = GeoBinding.query.filter(
        GeoBinding.spatial_kind == spatial_kind,
        GeoBinding.spatial_id == spatial_id)
    if role is not None:
        q = q.filter(GeoBinding.role == role)
    return q.order_by(GeoBinding.valid_from, GeoBinding.id).all()


def role_for_shape_type(shape_type):
    """도형 종류 → 바인딩 role. 모르는 종류면 None(=장치를 매다는 자리가 아님).

    클라이언트가 role 을 정하게 두지 않으려고 노출한다 — 지도 프런트의 종류
    어휘는 `aot_type` 정규화 때문에 서버의 `type` 컬럼과 어긋나는 구간이 있고
    (get_overlays 가 'device' 를 'aot_device' 로 바꿔 내보낸다), 그 어긋남이
    role 로 새면 구역 배정이 마커 배정으로 저장된다.
    """
    return SHAPE_TYPE_ROLES.get(shape_type)


def _last_device_of(slot_keys):
    """{(spatial_kind, spatial_id, role): 마지막으로 매여 있던 바인딩} — 종료된 것 중 최근.

    화면에 "여기 뭐가 있었나"를 보여주기 위한 것이다. 사람이 빈 자리 목록을
    보고 판단하려면 자리 이름만으로는 부족하다 — 지도에 그려진 도형 이름은
    'New aot_device' 같은 기본값인 경우가 많아서, 이전 장치와 끊긴 시점이
    실질적인 유일한 단서다.
    """
    if not slot_keys:
        return {}
    ids = {sid for _k, sid, _r in slot_keys}
    rows = GeoBinding.query.filter(
        GeoBinding.spatial_id.in_(ids),
        GeoBinding.valid_to.isnot(None)).order_by(GeoBinding.valid_to).all()
    out = {}
    for b in rows:                      # 시간순이라 마지막이 최근
        out[(b.spatial_kind, b.spatial_id, b.role)] = b
    return out


def _device_names(device_ids):
    """{장치 uuid: 이름} — 없어진 장치는 목록에서 빠진다(그것도 정보다)."""
    ids = {d for d in (device_ids or []) if d}
    if not ids:
        return {}
    out = {}
    for _kind, model in device_kind_models():
        try:
            for row in model.query.with_entities(
                    model.unique_id, model.name).filter(
                        model.unique_id.in_(ids)).all():
                out.setdefault(row[0], row[1])
        except Exception:
            continue
    return out


def unbound_slots(facility_uuid=None, map_uuid=None, kinds=None):
    """장치가 연결되지 않은 자리 — 그려두거나 설치해 뒀는데 담당 장치가 없는 곳.

    `kinds` 로 종류를 좁힌다(예: `('shape',)`). **화면은 반드시 좁혀서 쓴다** —
    구역 폴리곤은 지도가, 시설 설비는 시설 편집기가 관할이고, 그 둘을 한
    화면에 섞으면 사용자는 지도에서 천창을 보게 된다. 좁히지 않은 전체 목록은
    진단·점검용이다.

    **이 목록이 있어야 Phase C 의 삭제 정책이 성립한다** — 장치를 지워도 도형을
    남기기로 한 이상, 남은 자리를 사람이 보고 재배정할 수단이 있어야 한다.

    두 종류를 센다:
      - `type='device'` 구역 폴리곤 중 현재 'area' 바인딩이 없는 것
      - 시설의 fitting/actuator 항목 중 장치를 매단 적이 있는데 지금 없는 것

    구역 폴리곤을 포함하는 것은 Phase B-1 때와 달라진 판단이다. 그때는
    "도형의 미배정은 그냥 그려둔 도형과 구별할 수 없다"고 봤지만,
    `type='device'` 는 그 자체가 "장치가 담당하는 구역"이라는 선언이라
    구별이 된다(그냥 그려둔 도형은 'feature'/'aot_device' 다).

    ## 각 항목은 사람이 알아볼 수 있어야 한다

    처음 만들었을 때는 `spatial_id` 와 이름만 돌려줬는데, 화면에 뜨는 것이
    'New aot_device / 지도 구역' 같은 줄이라 **그게 어디의 무엇인지 알 방법이
    없었다.** 기계는 uuid 로 구분하지만 사람은 못 한다. 그래서 각 항목에
    다음을 함께 싣는다:

      - `where` : 어느 지도 / 어느 시설인가
      - `what`  : 무엇인가 (구역 이름, 또는 설비 종류)
      - `size`  : 구역이면 면적 m² — 이름이 기본값일 때 유일한 식별 단서다
      - `at`    : 지도에서 찾아갈 좌표 (lat, lng)
      - `last_device_name` / `ended_at` : 여기 뭐가 있었고 언제 빠졌나
      - `never_bound` : 한 번도 연결한 적 없음 (빠진 것과 뜻이 다르다)
    """
    from aot.databases.models import GeoFacility, GeoMap, GeoShape

    out = []
    map_names = {m.unique_id: m.name for m in GeoMap.query.all()}

    want = set(kinds) if kinds else None

    if want is None or 'shape' in want:
        _collect_shape_slots(out, map_names, map_uuid)
    if want is None or want & {'fitting', 'actuator'}:
        _collect_facility_slots(out, facility_uuid)

    _annotate_slot_story(out)
    return out


def _collect_shape_slots(out, map_names, map_uuid=None):
    """`type='device'` 구역 폴리곤 중 현재 'area' 바인딩이 없는 것."""
    from aot.databases.models import GeoShape

    bound_shapes = {b.spatial_id for b in GeoBinding.query.filter(
        GeoBinding.spatial_kind == 'shape',
        GeoBinding.role == 'area',
        GeoBinding.valid_to.is_(None)).all()}
    sq = GeoShape.query.filter(GeoShape.type == 'device')
    if map_uuid:
        sq = sq.filter(GeoShape.geo_id == map_uuid)
    for shape in sq.all():
        if shape.unique_id in bound_shapes:
            continue
        feat = shape.feature if isinstance(shape.feature, dict) else {}
        props = feat.get('properties') or {}
        name = (props.get('label_name') or props.get('name') or '').strip()
        # 'New aot_device' 같은 기본 이름은 식별에 도움이 안 된다 — 이름이
        # 없는 것으로 취급하고 면적·위치로 가리키게 한다.
        if name.lower().startswith('new '):
            name = ''
        out.append({
            'spatial_kind': 'shape',
            'spatial_id': shape.unique_id,
            'role': 'area',
            'item_kind': 'area',
            'legacy_ref': (shape.device_id or '').split('::')[0] or None,
            'map_uuid': shape.geo_id,
            # 지도에서 찾아가는 쪽(panToShape)은 클라이언트 식별자로 레이어를
            # 찾는다 — spatial_id(=unique_id)로는 못 찾는다. 둘 다 싣는다.
            'node_id': (props.get('node_id') or shape.unique_id),
            'where': map_names.get(shape.geo_id, ''),
            'what': name,
            'size': _area_m2(feat),
            'at': _centroid(feat),
        })


def _collect_facility_slots(out, facility_uuid=None):
    """시설 fitting/actuator 중 장치를 매단 적이 있는데 지금 없는 것.

    ⚠ **지도 화면에 섞지 말 것.** 시설 설비의 장치 배정은 시설 편집기의
    인스펙터(fitting 별 액추에이터 드롭다운)가 정본 입력 수단이고, 그쪽은
    `fittings[].actuator_id`(JSON)에 쓴다. 바인딩은 저장 후
    `sync_facility_bindings` 가 그 JSON 에서 파생한다.

    그래서 여기 목록에서 바인딩을 직접 만들면 **다음 시설 저장이 그 배정을
    지운다** — JSON 이 여전히 비어 있으니 동기화가 "사라진 참조"로 보고
    종료시킨다(2026-08-08 실측 확인). 이 목록은 진단·점검용으로만 쓴다.
    """
    from aot.databases.models import GeoFacility

    q = GeoFacility.query
    if facility_uuid:
        q = q.filter(GeoFacility.unique_id == facility_uuid)

    for fac in q.all():
        bound = {b.spatial_id for b in GeoBinding.query.filter(
            GeoBinding.spatial_kind.in_(('fitting', 'actuator')),
            GeoBinding.valid_to.is_(None)).all()}
        for column, kind in (('fittings', 'fitting'), ('actuators', 'actuator')):
            for item in _items(getattr(fac, column, None)):
                item_id = item.get('id')
                if not item_id:
                    continue
                slot = '%s:%s' % (fac.unique_id, item_id)
                if slot in bound:
                    continue
                if not _legacy_device_ref(column, item):
                    continue      # 애초에 장치를 매단 적 없는 항목 — 슬롯 아님
                out.append({
                    'spatial_kind': kind,
                    'spatial_id': slot,
                    # role 은 어느 키에 장치가 매달렸었나로 정한다 — fitting 은
                    # actuator_id(구동기)와 input_id(센서)가 같은 컬럼에 섞여 있다.
                    'role': _legacy_role(column, item) or 'actuator',
                    'item_kind': item.get('kind'),
                    'legacy_ref': (_legacy_device_ref(column, item) or ''
                                   ).split('::')[0] or None,
                    'facility_uuid': fac.unique_id,
                    'where': fac.name,
                    'what': (item.get('name') or '').strip(),
                    'item_id': item_id,
                })


def _annotate_slot_story(out):
    """각 자리에 "여기 뭐가 있었나"를 붙인다 — 이름이 기본값인 자리의 단서."""
    last = _last_device_of([(o['spatial_kind'], o['spatial_id'], o['role'])
                            for o in out])
    names = _device_names([b.device_id for b in last.values()])
    for o in out:
        b = last.get((o['spatial_kind'], o['spatial_id'], o['role']))
        o['last_device_id'] = b.device_id if b else o.get('legacy_ref')
        # 이름이 안 나오면 그 장치는 삭제된 것이다 — 그 사실도 정보다.
        o['last_device_name'] = (names.get(o['last_device_id'])
                                 if o['last_device_id'] else None)
        o['ended_at'] = (b.valid_to.isoformat()
                         if b is not None and b.valid_to else None)
        o['ended_reason'] = b.ended_reason if b else None
        # **레거시 참조도 "연결했던 적 있음"이다.** 바인딩 이력만 보면
        # 안 된다: 백필은 실존하지 않는 장치를 가리키는 참조에 바인딩을
        # 만들지 않으므로(고아를 정본으로 승격시키지 않는 정책), 장치가
        # 삭제된 자리는 이력이 비어 있다. 그걸 "한 번도 없었다"로 읽으면
        # 화면이 사실과 정반대를 말한다 — 실제로 천창 16개가 그랬다.
        o['never_bound'] = (b is None and not o.get('legacy_ref'))


def _flat_coords(coords):
    if not isinstance(coords, (list, tuple)) or not coords:
        return []
    if isinstance(coords[0], (int, float)) and len(coords) >= 2:
        return [(float(coords[0]), float(coords[1]))]
    out = []
    for c in coords:
        out.extend(_flat_coords(c))
    return out


def _centroid(feature):
    """도형의 대표 좌표 [lat, lng] — 지도에서 찾아가기 위한 것."""
    geom = (feature or {}).get('geometry') or {}
    pts = _flat_coords(geom.get('coordinates'))
    if not pts:
        return None
    return [round(sum(p[1] for p in pts) / len(pts), 7),
            round(sum(p[0] for p in pts) / len(pts), 7)]


def _area_m2(feature):
    """폴리곤 면적(m²). 계산 불가면 None.

    이름이 기본값인 구역에서는 면적이 사실상 유일한 식별 단서다.
    """
    try:
        from .facility_geo_helpers import shape_azimuth_area
        _az, area = shape_azimuth_area(feature)
        return round(area) if area else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 쓰기 — 바인딩을 만드는 유일한 문 (GB-7)
# ---------------------------------------------------------------------------

class BindingError(Exception):
    """바인딩 쓰기 거부 — 어휘 위반·인자 누락 등."""


class BindingConflict(BindingError):
    """슬롯이 이미 점유돼 있다(GB-1). 교체는 `rebind()` 다."""


class BindingNotFound(BindingError):
    """지정한 바인딩이 없다."""


def device_kind_models():
    """(device_kind, 모델) 7종 — `VALID_DEVICE_KINDS` 와 같은 어휘, 같은 순서.

    순서가 곧 판별 우선순위이며, uuid 는 테이블 간 유일하므로 실제로 충돌
    하지 않는다. `backfill_geo_binding` 이 이 함수를 쓴다 — 같은 매핑을 두
    벌 두면 한쪽만 늘어나 조용히 갈린다.
    """
    from aot.databases.models import (
        Conditional, CustomController, Function, Input, Output, PID, Trigger)
    return (
        ('input', Input),
        ('output', Output),
        ('device', CustomController),
        ('function', Function),
        ('pid', PID),
        ('trigger', Trigger),
        ('conditional', Conditional),
    )


def resolve_device_kind(device_id):
    """장치 uuid 가 실존하는 테이블로 `device_kind` 를 판별한다. 없으면 None.

    호출자가 들고 있는 종류 문자열을 믿지 않는 이유: 지도 UI 의 타입 어휘는
    이 어휘와 다르다('function' 이 UI 에서는 CustomController 를 뜻하고
    'generic_function' 이 Function 이다 — `/api/geo/device/location` 참조).
    그 문자열을 그대로 `device_kind` 로 쓰면 바인딩의 종류가 실제 테이블과
    어긋나고, 그 어긋남은 아무 에러 없이 저장된다.
    """
    if not device_id:
        return None
    uid = str(device_id).split('::')[0]
    for kind, model in device_kind_models():
        try:
            if model.query.with_entities(model.unique_id).filter(
                    model.unique_id == uid).first() is not None:
                return kind
        except Exception:
            continue
    return None


def _norm_channel(channel_id):
    """채널은 항상 문자열이고 기본값은 '0' — NULL/'0' 비대칭이 중복의 경로였다."""
    if channel_id is None or channel_id == '':
        return '0'
    return str(channel_id)


def _validate(spatial_kind, spatial_id, role, device_kind, device_id):
    if spatial_kind not in VALID_SPATIAL_KINDS:
        raise BindingError('spatial_kind 허용값 아님: %r (허용: %s)'
                           % (spatial_kind, ', '.join(VALID_SPATIAL_KINDS)))
    if device_kind not in VALID_DEVICE_KINDS:
        raise BindingError('device_kind 허용값 아님: %r (허용: %s)'
                           % (device_kind, ', '.join(VALID_DEVICE_KINDS)))
    if not spatial_id:
        raise BindingError('spatial_id 가 비었다')
    if not role:
        raise BindingError('role 이 비었다')
    if not device_id:
        raise BindingError('device_id 가 비었다')


def bind(spatial_kind, spatial_id, role, device_kind, device_id,
         channel_id='0', measurement_id=None, params=None, commit=False):
    """새 현재 바인딩을 만든다. 반환: GeoBinding.

    같은 슬롯에 이미 현재 바인딩이 있으면 `BindingConflict` 로 **실패한다**.
    조용히 덮어쓰면 교체 이력이 사라지고, 이력이 사라지면 장치 교체를
    관통하는 시계열 접합의 근거가 없어진다 — 교체는 `rebind()` 다.

    점유 규칙은 종류마다 다르다(GB-1):
      - 단일 점유(shape·fitting·actuator): 슬롯당 현재 1개. 한 창을 두
        모터가 열지 않는다.
      - 다중 점유(sensor_role·weather): 같은 role 에 여러 장치가 **정상**
        이며(가중평균), 같은 (장치, 채널, 측정값)의 중복 등록만 막는다.

    commit=False 기본 — 호출자의 트랜잭션에 합류한다(place_device 관례).
    """
    _validate(spatial_kind, spatial_id, role, device_kind, device_id)
    ch = _norm_channel(channel_id)
    dev = str(device_id).split('::')[0]

    if spatial_kind in SINGLE_OCCUPANCY_KINDS:
        occupied = current_one(spatial_kind, spatial_id, role=role,
                               channel_id=ch)
        if occupied is not None:
            raise BindingConflict(
                '슬롯이 이미 점유돼 있다: %s:%s/%s 채널 %s → %s. '
                '교체하려면 rebind() 를 쓸 것(이력이 남는다).'
                % (spatial_kind, spatial_id, role, ch, occupied.device_id))
    else:
        for b in current(spatial_kind, spatial_id, role=role, channel_id=ch):
            if (b.device_id == dev
                    and (b.measurement_id or '') == (measurement_id or '')):
                raise BindingConflict(
                    '같은 (장치, 채널, 측정값)이 이미 등록돼 있다: '
                    '%s:%s/%s → %s' % (spatial_kind, spatial_id, role, dev))

    row = GeoBinding(
        spatial_kind=spatial_kind, spatial_id=spatial_id, role=role,
        device_kind=device_kind, device_id=dev, channel_id=ch,
        measurement_id=measurement_id or None, params=params,
        valid_from=utc_now())
    db.session.add(row)
    # GB-1 부분 유니크 인덱스를 지금 물게 한다 — 커밋까지 미루면 위반이
    # 호출자와 무관한 자리에서 터진다.
    db.session.flush()
    logger.info('[GeoBinding] bind %s:%s/%s ch=%s → %s:%s',
                spatial_kind, spatial_id, role, ch, device_kind, dev)
    if commit:
        db.session.commit()
    return row


def unbind(binding_uid, reason, commit=False):
    """현재 바인딩을 종료한다(valid_to=지금, ended_reason=reason).

    **행을 지우지 않는다** — 이력이 시계열 접합의 근거다(B3).
    이미 종료된 바인딩이면 아무것도 하지 않고 그대로 돌려준다(멱등).
    """
    if reason not in VALID_END_REASONS:
        raise BindingError('ended_reason 허용값 아님: %r (허용: %s)'
                           % (reason, ', '.join(VALID_END_REASONS)))
    row = GeoBinding.query.filter_by(unique_id=binding_uid).first()
    if row is None:
        raise BindingNotFound('바인딩이 없다: %s' % binding_uid)
    if row.valid_to is not None:
        return row

    row.valid_to = utc_now()
    row.ended_reason = reason
    db.session.flush()
    logger.info('[GeoBinding] unbind %s:%s/%s → %s (%s)',
                row.spatial_kind, row.spatial_id, row.role, row.device_id,
                reason)
    if commit:
        db.session.commit()
    return row


def rebind(spatial_kind, spatial_id, role, device_kind, device_id,
           channel_id='0', measurement_id=None, params=None, commit=False):
    """교체 — 기존 현재 바인딩을 'replaced' 로 종료하고 새것을 만든다.

    **한 트랜잭션**이어야 한다. 중간에 끊기면 슬롯이 빈 채로 남는다.
    기존 바인딩이 없으면 그냥 만든다(신규 배정과 같다). 이미 같은 장치·
    채널·측정값이면 아무것도 하지 않고 기존 것을 돌려준다 — 마커를 끌 때마다
    호출되는 경로가 있어서, 값이 같은데도 교체 이력을 쌓으면 이력이
    "무엇이 실제로 바뀌었나"를 더는 말해주지 못한다.

    단일 점유 슬롯 전용이다. 다중 점유(sensor_role·weather)에서 슬롯 키로
    교체하면 같은 role 의 나머지 장치까지 함께 종료돼 가중평균 구성이
    통째로 날아간다 — 그쪽은 `unbind()` + `bind()` 로 대상을 명시할 것.
    """
    if spatial_kind in MULTI_OCCUPANCY_KINDS:
        raise BindingError(
            'rebind 는 단일 점유 슬롯 전용이다(%s 는 다중 점유). 교체 대상을 '
            'unbind() 로 명시한 뒤 bind() 할 것.' % spatial_kind)
    _validate(spatial_kind, spatial_id, role, device_kind, device_id)
    ch = _norm_channel(channel_id)
    dev = str(device_id).split('::')[0]

    old = current_one(spatial_kind, spatial_id, role=role, channel_id=ch)
    if old is not None:
        if (old.device_id == dev
                and (old.measurement_id or '') == (measurement_id or '')):
            return old                       # 바뀐 것이 없다
        old.valid_to = utc_now()
        old.ended_reason = 'replaced'
        # 종료를 새 행보다 먼저 DB 에 내보낸다. 지금은 이 flush 가 없어도
        # 통과한다 — SQLAlchemy 의 save_obj 가 같은 테이블에서 UPDATE 를
        # INSERT 보다 먼저 emit 하기 때문이며, 2026-08-08 음성 대조로
        # 확인했다(flush 를 빼도 GB-1 충돌이 나지 않았다). 그 내부 순서에
        # 기대지 않으려고 명시적으로 끊어 둔다: 옛 행이 아직 valid_to IS
        # NULL 인 채로 새 행이 들어가면 GB-1a 부분 유니크 인덱스에 걸린다.
        db.session.flush()
        logger.info('[GeoBinding] rebind %s:%s/%s ch=%s: %s → %s',
                    spatial_kind, spatial_id, role, ch, old.device_id, dev)

    return bind(spatial_kind, spatial_id, role, device_kind, dev,
                channel_id=ch, measurement_id=measurement_id, params=params,
                commit=commit)


def _available_channels(device_kind, device_id):
    """새 장치가 실제로 가진 채널 번호 집합(문자열). 셀 수 없으면 None.

    None 은 "채널이 없다"가 아니라 **"모른다"** 이다. 둘을 같은 값으로 접으면
    채널을 셀 수 없는 종류를 교체할 때 모든 비-0 채널이 미배정으로 떨어진다.
    """
    from aot.databases.models import (
        DeviceMeasurements, InputChannel, Output, OutputChannel)

    if device_kind == 'output':
        rows = OutputChannel.query.with_entities(OutputChannel.channel).filter(
            OutputChannel.output_id == device_id).all()
        # 채널 행이 아예 없는 단채널 출력이 있다 — 그때는 0번만 있는 것으로 본다.
        if not rows:
            exists = Output.query.with_entities(Output.unique_id).filter(
                Output.unique_id == device_id).first()
            return {'0'} if exists else None
        return {str(r[0]) for r in rows if r[0] is not None}

    if device_kind == 'input':
        rows = InputChannel.query.with_entities(InputChannel.channel).filter(
            InputChannel.input_id == device_id).all()
        if not rows:
            rows = DeviceMeasurements.query.with_entities(
                DeviceMeasurements.channel).filter(
                    DeviceMeasurements.device_id == device_id).all()
        if not rows:
            return None
        return {str(r[0]) for r in rows if r[0] is not None}

    # 복합장치·함수 계열은 채널이 하위 장치에 흩어져 있어 한 줄로 셀 수 없다.
    return None


def _marker_conflicts(bindings, new_device_id):
    """교체하면 I2(지도·장치·채널당 마커 1개)를 깨뜨릴 자리들.

    I2 유니크 인덱스는 `geo_shape.device_id` **컬럼**에 걸려 있는데 `rebind()`
    는 바인딩만 옮긴다. 그래서 인덱스는 이 충돌을 보지 못한다 — 여기서
    미리 봐야 한다. (C-4 로 컬럼이 죽으면 이 검사도 바인딩 기준으로 다시 쓴다.)
    """
    from aot.databases.models import GeoShape

    out = []
    for b in bindings:
        if b.role != 'marker':
            continue
        shape = GeoShape.query.filter(
            GeoShape.unique_id == b.spatial_id).first()
        if shape is None:
            continue
        clash = GeoShape.query.filter(
            GeoShape.geo_id == shape.geo_id,
            GeoShape.device_id == new_device_id,
            GeoShape.type == 'aot_device').first()
        if clash is not None and clash.unique_id != shape.unique_id:
            out.append(clash)
    return out


def _move_marker_column(spatial_id, new_device_id, channel_id):
    """마커 도형의 레거시 `device_id` 를 바인딩과 같은 값으로 맞춘다.

    바인딩만 옮기면 안 되는 이유는 정합성 미학이 아니라 고장이다:
    `place_device`/`unplace_device` 는 마커를 `(geo_id, device_id, channel_id)`
    컬럼으로 찾는다. 컬럼이 옛 장치를 가리킨 채 남으면 새 장치를 배치할 때
    마커가 하나 더 생기고, 옛 장치를 치울 때 **새 장치의 마커가 지워진다.**
    `binding-drift` 는 "레거시에만 있는 연결"만 보므로 이 어긋남을 못 잡는다.

    ⚠ C-4(레거시 컬럼 제거)에서 이 함수는 통째로 사라진다. GB-6 명부가
    비어야 끝이라는 뜻이 이것이다.
    """
    from aot.databases.models import GeoShape

    shape = GeoShape.query.filter(GeoShape.unique_id == spatial_id).first()
    if shape is None or shape.type != 'aot_device':
        return
    shape.device_id = new_device_id
    # properties.unique_id 는 프런트가 엔트리를 식별하는 계약이다
    # (채널 0 = 장치 uuid, 그 외 `uuid::N` — GB-5b). 여기를 안 고치면
    # 마커를 눌렀을 때 없는 장치를 조회한다.
    feat = shape.feature
    if isinstance(feat, dict) and isinstance(feat.get('properties'), dict):
        new_feat = dict(feat)
        props = dict(new_feat['properties'])
        ch = _norm_channel(channel_id)
        props['unique_id'] = (new_device_id if ch == '0'
                              else '%s::%s' % (new_device_id, ch))
        new_feat['properties'] = props
        shape.feature = new_feat


def rebind_device(old_device_id, new_device_id, commit=False):
    """장치 단위 교체 — 옛 장치가 맡던 **지도 자리 전부**를 새 장치로 옮긴다.

    `rebind()` 는 슬롯 하나만 다룬다. 현장에서 "이 장치를 저 장치로 갈았다"는
    말은 그 장치가 맡던 모든 자리를 뜻하므로, 그 쓸기를 여기서 한 트랜잭션에
    묶는다. 결정 근거는 `docs/design/geo-device-binding.md` 「결정」 절.

    **지도 도형(`spatial_kind='shape'`)만 옮긴다.** 시설 설비(fitting·actuator)
    와 센서 역할(sensor_role·weather)은 시설 편집기가 정본이고 시설 JSON 에
    쓴다 — 여기서 바인딩을 만들면 **다음 시설 저장이 그 배정을 지운다**(실측).
    그래서 조용히 건너뛰지 않고 `refused` 로 돌려주고 이유를 말한다.

    채널 축소(8채널 → 4채널)는 매핑 불가 채널을 `'replaced'` 로 종료해
    미배정 자리로 남긴다. 거부하면 정당한 교체가 막히고, 그대로 두면 "장치가
    붙어 있는데 아무 명령도 안 가는" 자리가 된다.

    마커 충돌은 **아무것도 쓰기 전에** `BindingConflict` 로 거부한다. 옛 마커를
    자동으로 지우거나 옮기지 않는다 — 좌표는 측량 결과이고, 둘 중 무엇이
    맞는지는 사람만 안다.

    반환: {'moved': [...], 'unassigned': [...], 'refused': [...],
           'warnings': [...]}
    """
    old_uid = str(old_device_id or '').split('::')[0]
    new_uid = str(new_device_id or '').split('::')[0]
    if not old_uid or not new_uid:
        raise BindingError('old_device_id 와 new_device_id 가 모두 필요하다')
    if old_uid == new_uid:
        raise BindingError('같은 장치로는 교체할 수 없다')

    new_kind = resolve_device_kind(new_uid)
    if new_kind is None:
        raise BindingError('새 장치를 찾을 수 없다: %s' % new_uid)

    rows = bindings_for_device(old_uid)
    if not rows:
        raise BindingNotFound(
            '옛 장치에 현재 바인딩이 없다 — 옮길 자리가 없다: %s' % old_uid)

    clashes = _marker_conflicts(rows, new_uid)
    if clashes:
        names = ', '.join(
            (c.feature or {}).get('properties', {}).get('name') or c.unique_id[:8]
            for c in clashes)
        raise BindingConflict(
            '새 장치가 같은 지도에 이미 마커를 갖고 있다(%s). 먼저 그 마커를 '
            '정리한 뒤 교체할 것 — 좌표 둘 중 무엇이 맞는지는 사람만 안다.'
            % names)

    channels = _available_channels(new_kind, new_uid)
    warnings = []
    if channels is None:
        warnings.append(
            '새 장치의 채널 수를 셀 수 없어 채널 축소를 확인하지 못했다 — '
            '옛 장치의 채널을 그대로 옮긴다.')

    moved, unassigned, refused = [], [], []

    for b in rows:
        item = {'spatial_kind': b.spatial_kind, 'spatial_id': b.spatial_id,
                'role': b.role, 'channel_id': b.channel_id}
        if b.spatial_kind != 'shape':
            item['reason'] = ('시설 편집기가 정본인 자리다. 여기서 바꾸면 다음 '
                              '시설 저장이 되돌린다.')
            refused.append(item)
            continue

        ch = _norm_channel(b.channel_id)
        if channels is not None and ch not in channels:
            unbind(b.unique_id, 'replaced')
            item['reason'] = '새 장치에 %s번 채널이 없다 — 미배정 자리로 남긴다.' % ch
            unassigned.append(item)
            continue

        rebind(b.spatial_kind, b.spatial_id, b.role, new_kind, new_uid,
               channel_id=ch, measurement_id=b.measurement_id)
        if b.role == 'marker':
            _move_marker_column(b.spatial_id, new_uid, ch)
        moved.append(item)

    logger.info('[GeoBinding] rebind_device %s → %s: 이동 %d · 미배정 %d · 거부 %d',
                old_uid, new_uid, len(moved), len(unassigned), len(refused))

    if commit:
        db.session.commit()
    return {'old_device_id': old_uid, 'new_device_id': new_uid,
            'moved': moved, 'unassigned': unassigned, 'refused': refused,
            'warnings': warnings}


def facility_binding_targets(facility):
    """저장된 시설 JSON 이 뜻하는 바인딩 집합.

    {(spatial_kind, spatial_id, role, channel_id): [(device_id, measurement_id,
    params), ...]} — 다중 점유 슬롯이 있으므로 값은 항상 리스트다.

    백필의 5원(源)과 **같은 목록이어야 한다**. fittings 는 actuator_id(구동)와
    input_id(센서)가 한 컬럼에 섞여 있고, actuators 는 컬럼도 키 이름도 다르며
    (`device_uuid`), weather_bindings 는 또 `input_uuid` 다. 하나만 보면 놓친다.
    """
    fac_uuid = getattr(facility, 'unique_id', None)
    if not fac_uuid:
        return {}

    out = {}

    def _want(kind, sid, role, dev, measurement=None, params=None):
        dev = str(dev or '').split('::')[0]
        if not dev or not role:
            return
        out.setdefault((kind, sid, role, '0'), []).append(
            (dev, (measurement or None), params))

    for fit in _items(getattr(facility, 'fittings', None)):
        fid = fit.get('id')
        if not fid:
            continue                 # 안정적으로 가리킬 수 없는 항목
        slot = '%s:%s' % (fac_uuid, fid)
        _want('fitting', slot, 'actuator', fit.get('actuator_id'))
        _want('fitting', slot, 'sensor', fit.get('input_id'),
              measurement=fit.get('measurement_id'))

    for act in _items(getattr(facility, 'actuators', None)):
        aid = act.get('id')
        if not aid:
            continue
        _want('actuator', '%s:%s' % (fac_uuid, aid), 'actuator',
              act.get('device_uuid'))

    for sen in _items(getattr(facility, 'sensors', None)):
        weight = sen.get('weight')
        _want('sensor_role', fac_uuid, (sen.get('role') or '').strip(),
              sen.get('device_id'), measurement=sen.get('measurement_id'),
              params={'weight': weight} if weight is not None else None)

    for wb in _items(getattr(facility, 'weather_bindings', None)):
        max_age = wb.get('max_age_sec')
        _want('weather', fac_uuid,
              (wb.get('measurement_type') or '').strip(), wb.get('input_uuid'),
              measurement=wb.get('measurement_id'),
              params={'max_age_sec': max_age} if max_age else None)

    return out


def sync_facility_bindings(facility, commit=False):
    """저장된 시설 JSON 과 바인딩을 일치시킨다. 반환: (만든 수, 끝낸 수).

    **저장 직후에 불러야 한다.** 읽기 리졸버가 바인딩을 정본으로 쓰기
    때문에, 이 동기화가 없으면 시설 편집기에서 fitting 의 장치를 **비워도
    화면에는 계속 옛 장치가 보인다** — 저장은 됐는데 바인딩이 그대로라
    읽기가 바인딩을 이긴다. Phase B-1 이 읽기를 바인딩으로 옮긴 순간
    생긴 구멍이고, 여기서 닫는다.

    **페이로드가 아니라 저장된 값을 기준으로 한다.** 부분 저장(어떤 키가
    빠진 요청)에서 페이로드를 기준으로 삼으면 "빠진 것 = 지운 것"이 되어
    멀쩡한 배정이 끊긴다 — `save_overlays` 가 정확히 그 프로토콜(I9) 때문에
    도형을 잃었다.
    """
    from aot.databases.models import GeoFacility

    if isinstance(facility, str):        # uuid 로 불러도 되게
        facility = GeoFacility.query.filter_by(unique_id=facility).first()
    fac_uuid = getattr(facility, 'unique_id', None)
    if not fac_uuid:
        return (0, 0)

    want = facility_binding_targets(facility)

    from sqlalchemy import or_
    have = GeoBinding.query.filter(
        GeoBinding.valid_to.is_(None),
        or_(GeoBinding.spatial_kind.in_(('sensor_role', 'weather'))
            & (GeoBinding.spatial_id == fac_uuid),
            GeoBinding.spatial_kind.in_(('fitting', 'actuator'))
            & GeoBinding.spatial_id.like('%s:%%' % fac_uuid))).all()

    by_slot = {}
    for b in have:
        by_slot.setdefault(
            (b.spatial_kind, b.spatial_id, b.role, b.channel_id), []).append(b)

    created = ended = 0
    for slot in set(by_slot) | set(want):
        kind, sid, role, ch = slot
        desired = want.get(slot) or []
        rows = by_slot.get(slot, [])

        if kind in SINGLE_OCCUPANCY_KINDS:
            # 슬롯당 하나 — 교체는 rebind 로 간다. unbind+bind 로 하면 사유가
            # 'unbound' 로 남아 "사람이 뗀 것"과 "다른 장치로 갈아낀 것"을
            # 이력에서 구분할 수 없다.
            if not desired:
                for b in rows:
                    unbind(b.unique_id, 'unbound')
                    ended += 1
                continue
            dev, meas, params = desired[0]
            device_kind = resolve_device_kind(dev)
            if device_kind is None:
                continue        # 실존하지 않는 장치는 승격시키지 않는다
            before = rows[0].unique_id if rows else None
            row = rebind(kind, sid, role, device_kind, dev, channel_id=ch,
                         measurement_id=meas, params=params)
            if row.unique_id != before:
                created += 1
                if before is not None:
                    ended += 1
            continue

        # 다중 점유 — 집합 차이. 같은 role 에 여러 장치가 정상이다.
        keep = {(d, m or '') for d, m, _p in desired}
        for b in rows:
            if (b.device_id, b.measurement_id or '') not in keep:
                unbind(b.unique_id, 'unbound')
                ended += 1
        existing = {(b.device_id, b.measurement_id or '')
                    for b in rows if b.valid_to is None}
        for dev, meas, params in desired:
            if (dev, meas or '') in existing:
                continue
            device_kind = resolve_device_kind(dev)
            if device_kind is None:
                continue
            bind(kind, sid, role, device_kind, dev, channel_id=ch,
                 measurement_id=meas, params=params)
            created += 1

    if (created or ended):
        logger.info('[GeoBinding] 시설 %s 바인딩 동기화: +%d / 종료 %d',
                    fac_uuid, created, ended)
    if commit:
        db.session.commit()
    return (created, ended)


def end_all_for_device(device_id, reason='device_deleted', commit=False):
    """장치가 사라질 때 그 장치의 현재 바인딩을 전부 끝낸다. 반환: 종료 건수.

    **장치 삭제 경로 17곳이 부르는 유일한 문이다**(utils_* 7 + tab_service 7 +
    진단 일괄 3). 예전에는 그중 4곳만 도형을 정리했고 나머지 13곳으로 지운
    장치의 도형은 아무 에러 없이 남았다 — 삭제 정책이 6갈래였던 게 아니라
    아예 없는 곳이 대부분이었다.

    ## 도형은 지우지 않는다 (B4)

    구역 폴리곤·시설 fitting 은 **미배정 슬롯으로 남는다.** 도형은 자산
    (측량·작도 결과)이고 장치는 소모품이라, 같이 지우면 자산이 날아간다.
    남은 자리는 geo/design 의 "미배정 자리" 화면에서 보고 재배정한다 —
    그 화면이 있기 때문에 이제 이 정책으로 바꿀 수 있다.

    예전 동작(`GeoShape.query.filter(device_id==...).delete()`)은 구역
    폴리곤까지 함께 지웠다. 그래서 장치를 갈아끼우려면 도형을 다시 그려야
    했고, 그게 이 작업 전체의 출발점이었다.

    ## 예외는 위치 마커 하나뿐

    `aot_device` 점 마커는 유일하게 자산 가치가 없는 도형이다(장치를 놓으려고
    찍은 점). 장치가 사라지면 그 점은 아무것도 가리키지 않으므로 함께 지운다.

    삭제 순서가 중요하다: 마커를 먼저 지우면 그 도형의 바인딩이 GB-4 로
    'spatial_deleted' 가 되어 사유가 갈린다. 그래서 **바인딩을 먼저 끝내고**
    (전부 같은 사유로) 도형을 지운다.
    """
    if not device_id:
        return 0
    if reason not in VALID_END_REASONS:
        raise BindingError('ended_reason 허용값 아님: %r' % (reason,))

    dev = str(device_id).split('::')[0]
    rows = GeoBinding.query.filter(
        GeoBinding.device_id == dev,
        GeoBinding.valid_to.is_(None)).all()

    marker_shapes = [b.spatial_id for b in rows
                     if b.spatial_kind == 'shape' and b.role == 'marker']

    now = utc_now()
    for row in rows:
        row.valid_to = now
        row.ended_reason = reason
    db.session.flush()

    _delete_markers(dev, marker_shapes)

    if rows:
        logger.info('[GeoBinding] end_all_for_device %s: 바인딩 %d건 종료(%s), '
                    '마커 %d개 제거 — 구역·시설 도형은 미배정 슬롯으로 남는다',
                    dev, len(rows), reason, len(marker_shapes))
    if commit:
        db.session.commit()
    return len(rows)


def _delete_markers(device_id, shape_uids):
    """위치 마커 도형을 지운다 — 바인딩 기준 + 레거시 컬럼 기준 양쪽.

    레거시(`GeoShape.device_id`) 기준을 함께 보는 이유: 백필이 죽은 참조에
    바인딩을 만들지 않았고 쓰기 전환도 아직 진행 중이라, 바인딩 없이 컬럼만
    가진 마커가 남아 있다. 그 마커는 바인딩만 보면 영원히 정리되지 않는다.
    Phase C 의 레거시 제거가 끝나면 이 두 번째 조건은 사라진다.
    """
    from aot.databases.models import GeoShape

    q = GeoShape.query.filter(GeoShape.type == 'aot_device')
    if shape_uids:
        cond = GeoShape.unique_id.in_(shape_uids)
        q = q.filter(cond | (GeoShape.device_id == device_id))
    else:
        q = q.filter(GeoShape.device_id == device_id)
    n = q.delete(synchronize_session=False)
    if n:
        db.session.expire_all()      # bulk delete 후 세션 캐시 무효화
    return n


# ---------------------------------------------------------------------------
# 해석 — 공간 요소가 "지금 가리키는 장치"
# ---------------------------------------------------------------------------

def device_for_shape(shape):
    """도형이 가리키는 장치 uuid. 없으면 None.

    바인딩 우선, 없으면 `GeoShape.device_id` 컬럼(레거시).
    """
    role = SHAPE_TYPE_ROLES.get(getattr(shape, 'type', None))
    if role is None:
        return None

    uid = getattr(shape, 'unique_id', None)
    if uid:
        row = current_one('shape', uid, role=role)
        if row is not None:
            return row.device_id

    legacy = (getattr(shape, 'device_id', None) or '').strip()
    if legacy:
        _note_fallback('shape.device_id', 'type=%s' % shape.type)
        return legacy.split('::')[0]
    return None


def devices_for_shapes(shapes):
    """{GeoShape.unique_id: 장치 uuid} — 도형 목록의 일괄 해석.

    `device_for_shape` 를 루프에서 부르면 도형 수만큼 쿼리가 나간다.
    `get_overlays` 는 지도 렌더의 핫패스이므로(시설 위젯 LCP 사건 참조)
    바인딩을 한 번에 읽어 dict 로 접는다. 폴백도 같은 규칙으로 적용한다.
    """
    uids = [s.unique_id for s in shapes
            if getattr(s, 'type', None) in SHAPE_TYPE_ROLES
            and getattr(s, 'unique_id', None)]
    bound = {}
    if uids:
        rows = GeoBinding.query.filter(
            GeoBinding.spatial_kind == 'shape',
            GeoBinding.spatial_id.in_(uids),
            GeoBinding.valid_to.is_(None)).all()
        for b in rows:
            bound[b.spatial_id] = b.device_id

    out = {}
    fell_back = []
    for s in shapes:
        if getattr(s, 'type', None) not in SHAPE_TYPE_ROLES:
            continue
        uid = getattr(s, 'unique_id', None)
        if uid in bound:
            out[uid] = bound[uid]
            continue
        legacy = (getattr(s, 'device_id', None) or '').strip()
        if legacy:
            out[uid] = legacy.split('::')[0]
            fell_back.append(out[uid])
    # 죽은 참조는 폴백이 아니다 — orphan-device-shape 가 담당한다.
    if fell_back and 'shape.device_id' not in _fallback_seen:
        if _any_device_exists(fell_back):
            _note_fallback('shape.device_id')
    return out


def shapes_for_device(device_id, role=None, channel_id=None):
    """이 장치가 매여 있는 도형(GeoShape) 목록. 바인딩 우선, 없으면 레거시.

    "이 장치의 도형은 어느 것인가"는 다섯 곳이 각자
    `GeoShape.query.filter_by(device_id=...)` 로 풀던 질문이다(이름 동기화·
    시간대 상속·AI 좌표 동기화·위성 입력의 좌표 폴백·조율기 프로필 적재).
    다섯 벌이면 다섯 번 다르게 틀린다 — 어떤 곳은 `type` 을 걸고 어떤 곳은
    안 걸고, 채널을 보는 곳과 안 보는 곳이 갈렸다.

    **바인딩이 하나라도 있으면 바인딩만 본다.** 부분적으로 섞어 합치면
    "전환이 어디까지 됐나"를 아무도 말할 수 없게 된다 — 리졸버의 다른
    함수와 같은 규칙이다.
    """
    from aot.databases.models import GeoShape

    dev = str(device_id or '').split('::')[0]
    if not dev:
        return []

    q = GeoBinding.query.filter(
        GeoBinding.spatial_kind == 'shape',
        GeoBinding.device_id == dev,
        GeoBinding.valid_to.is_(None))
    if role is not None:
        q = q.filter(GeoBinding.role == role)
    if channel_id is not None:
        q = q.filter(GeoBinding.channel_id == str(channel_id))
    uids = [b.spatial_id for b in q.all()]

    if uids:
        return GeoShape.query.filter(GeoShape.unique_id.in_(uids)).all()

    legacy = GeoShape.query.filter(GeoShape.device_id == dev)
    if channel_id is not None:
        legacy = legacy.filter(GeoShape.channel_id == str(channel_id))
    if role is not None:
        wanted = [t for t, r in SHAPE_TYPE_ROLES.items() if r == role]
        legacy = legacy.filter(GeoShape.type.in_(wanted))
    rows = legacy.all()
    if rows and 'shape.device_id' not in _fallback_seen:
        _note_fallback('shape.device_id', 'shapes_for_device')
    return rows


def shapes_for_devices(device_ids, role=None):
    """{장치 uuid: [GeoShape]} — 여러 장치를 한 번에(N+1 회피).

    조율기 프로필 적재처럼 구동기 수십 개를 한 번에 도는 경로가 있다.
    `shapes_for_device` 를 루프에서 부르면 장치마다 쿼리가 두 번씩 나간다.
    """
    from aot.databases.models import GeoShape

    devs = {str(d).split('::')[0] for d in (device_ids or []) if d}
    if not devs:
        return {}

    q = GeoBinding.query.filter(
        GeoBinding.spatial_kind == 'shape',
        GeoBinding.device_id.in_(devs),
        GeoBinding.valid_to.is_(None))
    if role is not None:
        q = q.filter(GeoBinding.role == role)
    rows = q.all()

    by_uid = {}
    for b in rows:
        by_uid.setdefault(b.spatial_id, b.device_id)

    out = {}
    if by_uid:
        for s in GeoShape.query.filter(
                GeoShape.unique_id.in_(list(by_uid))).all():
            out.setdefault(by_uid[s.unique_id], []).append(s)

    # 바인딩이 없는 장치만 레거시로 채운다 — 있는 장치는 바인딩이 정본이다.
    missing = devs - set(out)
    if missing:
        legacy = GeoShape.query.filter(GeoShape.device_id.in_(missing))
        if role is not None:
            wanted = [t for t, r in SHAPE_TYPE_ROLES.items() if r == role]
            legacy = legacy.filter(GeoShape.type.in_(wanted))
        found = legacy.all()
        for s in found:
            out.setdefault(s.device_id, []).append(s)
        if found and 'shape.device_id' not in _fallback_seen:
            _note_fallback('shape.device_id', 'shapes_for_devices')
    return out


def expand_device(device_kind, device_id):
    """바인딩의 장치를 실제 제어/측정 대상 목록으로 편다.

    복합장치(`device_kind='device'`, CustomController)는 하위 Input/Output 으로
    펼친다. 전개 기준은 **소유 관계(`parent_device_id`)뿐**이다 —
    `DeviceMember` 참조 관계는 전개하지 않는다. 참조는 소유가 아니고, 남의
    장치 구성에 참조로 끼워 넣은 항목이 이 슬롯의 제어 대상이 되면 안 된다.

    ⚠ `device_blueprint._linked_ids()` / `_device_descendants()` 를 쓰지 말 것.
    두 함수 모두 `parent_device_id` 결과에 `DeviceMember` 를 합쳐 돌려주므로
    위 규칙을 정확히 위반한다(이름과 위치상 가장 먼저 손이 가는 함수들이다).

    Returns: [(kind, uuid), ...] — 'device' 가 아니면 자기 자신 하나.
    """
    if device_kind != 'device':
        return [(device_kind, device_id)]

    from aot.databases.models import Input, Output

    out = []
    for kind, model in (('input', Input), ('output', Output)):
        rows = model.query.with_entities(model.unique_id).filter(
            model.parent_device_id == device_id).all()
        out.extend((kind, r[0]) for r in rows)
    return out or [(device_kind, device_id)]


# ---------------------------------------------------------------------------
# 투영 — 시설 JSON 의 장치 참조를 바인딩 기준으로 덮어쓴다
# ---------------------------------------------------------------------------

# (컬럼, 키, spatial_kind, role) — 백필 5원과 같은 목록이어야 한다.
# fittings 와 actuators 는 컬럼도 키 이름도 다르므로 하나만 보면 놓친다.
_FACILITY_REFS = (
    ('fittings', 'actuator_id', 'fitting', 'actuator'),
    ('fittings', 'input_id', 'fitting', 'sensor'),
    ('actuators', 'device_uuid', 'actuator', 'actuator'),
)


def _items(blob):
    raw = blob
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        return [x for x in raw.values() if isinstance(x, dict)]
    return []


def _legacy_device_ref(column, item):
    for col, key, _kind, _role in _FACILITY_REFS:
        if col == column and item.get(key):
            return str(item[key])
    return None


def _legacy_role(column, item):
    """레거시 값이 매달려 있던 키로 role 을 정한다. 없으면 None."""
    for col, key, _kind, role in _FACILITY_REFS:
        if col == column and item.get(key):
            return role
    return None


def build_facility_index(facility_uuids):
    """{(spatial_id, role): GeoBinding} — 시설 여러 개의 바인딩을 한 번에.

    시설 목록 직렬화가 시설마다 조회하면 N+1 이 된다(실측: 시설 11개 →
    쿼리 11회). 목록 경로는 이 색인을 만들어 `resolve_facility_payload` 에
    넘긴다.
    """
    uuids = [u for u in (facility_uuids or []) if u]
    if not uuids:
        return {}
    prefixes = ['%s:%%' % u for u in uuids]
    from sqlalchemy import or_
    rows = GeoBinding.query.filter(
        GeoBinding.spatial_kind.in_(('fitting', 'actuator')),
        GeoBinding.valid_to.is_(None),
        or_(*[GeoBinding.spatial_id.like(p) for p in prefixes])).all()
    return {(b.spatial_id, b.role): b for b in rows}


def _cow(payload, column, seen):
    """copy-on-write: payload[column] 리스트를 처음 고칠 때 한 번만 복사한다.

    `_to_dict` 의 `'fittings': f.fittings or []` 는 ORM 이 들고 있는 JSON
    객체를 **참조로** 넘긴다. 그 안의 dict 를 제자리에서 고치면 같은 세션의
    뒤이은 독자(`check_geo_integrity` 의 dangling-fitting, 같은 요청 안의
    다른 코드)가 저장값 대신 해석값을 보게 된다. 읽기 리졸버가 인메모리
    상태를 바꾸면 "저장된 것"과 "해석된 것"의 구분이 사라진다.

    (2026-08-08 확인: 이 제자리 수정이 **DB 까지 써지지는 않는다** —
    `db.Column(JSON)` 은 Mutable 래퍼가 없어 SQLAlchemy 가 제자리 변경을
    추적하지 않고, 통제 실험에서 이후 commit 이 값을 쓰지 않았다. 처음에는
    되써넣기로 판단했으나 그 근거였던 실험이 잘못이었다 — 얕은 복사
    `list(f.fittings)` 로 내부 dict 을 공유한 채 고치면 ORM 이 '변경 없음'
    으로 보아 오염 자체가 저장되지 않았고, 그 결과를 되써넣기로 오독했다.
    따라서 이 함수의 근거는 DB 보호가 아니라 위의 인메모리 격리다.)

    전량 deepcopy 하지 않는 이유: 관수 노즐만 600개가 넘는 시설이 있어
    읽을 때마다 통째로 복사하면 비싸다. 실제로 바뀌는 항목만 갈아끼운다.
    """
    if column not in seen:
        payload[column] = list(_items(payload.get(column)))
        seen.add(column)
    return payload[column]


def resolve_facility_payload(facility_uuid, payload, index=None):
    """시설 직렬화 dict 의 장치 참조를 바인딩 기준으로 맞춘다(제자리 수정).

    이 함수가 `FacilityManager._to_dict()` 한 곳에 걸리면 하위 소비처
    (`facility_integration` · `irrigation_nozzles` · `facility_wind` ·
    `facility_calc` · 3D 위젯)는 **한 줄도 고치지 않고** 바인딩을 읽게 된다.
    그 소비처들은 JSON 을 인자로 받는 순수 함수라, 각각을 고치면 같은 규칙을
    다섯 벌 구현하게 된다.

    바인딩이 없는 항목은 저장된 값을 그대로 둔다(폴백). 값이 실제로 달라진
    경우에만 기록한다 — 전환기에 두 저장처가 갈린 지점이 곧 버그 후보다.
    """
    if not facility_uuid or not isinstance(payload, dict):
        return payload

    # 목록 경로는 색인을 미리 만들어 넘긴다(N+1 회피). 단건 조회는 자기 것만.
    by_slot = (index if index is not None
               else build_facility_index([facility_uuid]))

    used_fallback = []
    copied = set()
    for column, key, kind, role in _FACILITY_REFS:
        for idx, item in enumerate(_items(payload.get(column))):
            item_id = item.get('id')
            if not item_id:
                continue
            b = by_slot.get(('%s:%s' % (facility_uuid, item_id), role))
            if b is None:
                if item.get(key):
                    used_fallback.append(item[key])
                continue

            new_meas = (b.measurement_id if b.measurement_id
                        and 'measurement_id' in item else item.get('measurement_id'))
            if item.get(key) == b.device_id and new_meas == item.get('measurement_id'):
                continue                      # 이미 같다 — 건드리지 않는다

            if item.get(key) != b.device_id:
                logger.warning(
                    '[GeoBinding] 시설 %s 의 %s[%s].%s 가 바인딩과 다르다: '
                    '저장=%s 바인딩=%s — 바인딩을 정본으로 쓴다(저장은 하지 않는다).',
                    facility_uuid, column, item_id, key,
                    item.get(key), b.device_id)

            # ORM 이 들고 있는 dict 를 고치지 않는다 — 사본으로 갈아끼운다.
            lst = _cow(payload, column, copied)
            patched = dict(item)
            patched[key] = b.device_id
            if b.measurement_id and 'measurement_id' in patched:
                patched['measurement_id'] = b.measurement_id
            lst[idx] = patched

    # 죽은 참조는 폴백이 아니다 — dangling-fitting 이 담당한다.
    if used_fallback and 'facility.fittings/actuators' not in _fallback_seen:
        if _any_device_exists(used_fallback):
            _note_fallback('facility.fittings/actuators')
    return payload

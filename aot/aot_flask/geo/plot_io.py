# coding=utf-8
"""식생 구획(작기)의 쓰기 경로 — 검증·저장·종료·삭제.

설계 정본: docs/design/geo-vegetation-plot.md

불변식 VP-1~VP-6 을 **여기 한 곳에서** 강제한다. 라우트마다 검증을 흩으면
새 진입점이 생길 때마다 조용히 빠지고, 그게 이 도메인이 반복해서 겪은
실패다(장치 삭제 17경로 중 도형을 정리하는 곳이 4곳뿐이었던 것처럼).

읽기·파생은 `plot_context` 가 담당한다.
"""
import logging
from datetime import date, timedelta, datetime

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import plot_context
# 종류 어휘는 프로그램 쪽이 정본이다 — 두 벌을 두면 한쪽만 늘어난다.
from aot.aot_flask.geo.program_io import VALID_KINDS
from aot.databases.models import GeoPlot

logger = logging.getLogger(__name__)

# VP-4 — feature.properties 에 두면 안 되는 키. 사본은 원본이 바뀌어도 따라오지
# 않아 조용히 갈린다(GB-5 와 같은 결). 색도 여기 넣지 않는다 — 구분색은
# `color` 컬럼이고, feature 에 각인하면 테마를 바꿔도 그 구획만 옛 색으로 남는다.
_FORBIDDEN_PROPS = ('device_id', 'channel_id', 'unique_id', 'color',
                    'zone_uuid', 'zone_id')

_VALID_END_REASONS = ('harvested', 'failed', 'replaced', 'removed')
# 'facility' — 기하 없이 시설 구역에 매단 구획(p6_39). 'bay_snapshot' 과 다르다:
# 그쪽은 bay 폴리곤을 **복사해 온** 것이고(백필), 이쪽은 애초에 기하가 없다.
_VALID_SOURCE_KINDS = ('drawn', 'bay_snapshot', 'copied', 'facility')


def _invalidate_caches():
    """구획이 바뀐 직후 모달 캐시를 버린다 — **커밋 뒤에** 부른다.

    라우트마다 부르지 않고 이 게이트웨이에 두는 이유: 쓰기는 REST 만 지나가는
    것이 아니라 AI/MCP 도구도 여기로 온다(`plot_io` 가 유일한 쓰기
    게이트웨이라는 설계 전제). 라우트에 흩으면 새 진입점 하나가 조용히 빠지고,
    증상은 "저장은 됐는데 화면이 30초 동안 안 바뀐다" 라 버그로 읽히지도 않는다.

    구획 하나가 아니라 **전부** 버린다 — 새 구획이 생기면 같은 밸브를 공유하는
    이웃의 `also_covers`("켜면 무엇이 함께 젖는가")가 달라지기 때문이다.

    **구역 캐시도 함께 버린다.** 구역 [현황]이 "지금 심겨 있는 것"(작물 목록 ·
    면적 배분 · 미배정)을 싣고 출력마다 `also_covers` 를 달고 있어서, 구획을
    고치면 구역 응답도 달라진다. 어느 구역인지 따지지 않고 전부 버리는 이유는
    구획의 소속이 **저장돼 있지 않고 기하에서 파생**되기 때문이다 — 기하를
    옮기면 소속 구역 자체가 바뀌므로 "고치기 전 구역" 과 "고친 뒤 구역" 둘 다
    버려야 하고, 그러느니 전부 버리는 편이 틀릴 여지가 없다(30초 캐시다).
    """
    try:
        from aot.aot_flask.geo import site_summary
        site_summary.invalidate_plot_contents(None)
        site_summary.invalidate_zone_contents_all()
    except Exception as exc:      # 캐시 정리 실패가 저장을 되돌리면 안 된다
        logger.warning('[Plot] 모달 캐시 무효화 실패: %s', exc)

    # 포함 관계 캐시도 함께 버린다 — 구획을 옮기면 소속 구역이 바뀌는데,
    # 이 캐시는 TTL 안전망이 있어도 그때까지 낡은 소속을 답한다.
    try:
        from aot.aot_flask.geo import containment_cache
        containment_cache.invalidate()
    except Exception as exc:
        logger.warning('[Plot] 포함 캐시 무효화 실패: %s', exc)


def _parse_date(value, field):
    """'YYYY-MM-DD' → date. 빈 값은 None. 형식이 틀리면 (None, 오류)."""
    if value in (None, ''):
        return None, None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value, None
    if isinstance(value, datetime):
        return value.date(), None
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date(), None
    except (ValueError, TypeError):
        return None, '%s: 날짜 형식이 YYYY-MM-DD 가 아닙니다 (%r)' % (field, value)


def _strip_forbidden(feature):
    """VP-4 — 금지 키를 조용히 제거하고 제거한 목록을 돌려준다.

    거부하지 않고 제거하는 이유: 클라이언트가 렌더용으로 붙여 보내는 값이라
    거부하면 정상 저장이 막힌다. 막아야 하는 것은 **저장되는 것**이다.
    """
    if not isinstance(feature, dict):
        return feature, []
    props = feature.get('properties')
    if not isinstance(props, dict):
        return feature, []
    removed = [k for k in _FORBIDDEN_PROPS if k in props]
    for k in removed:
        del props[k]
    return feature, removed


def _resolve_program(program_uuid, current_uuid=None, current_version=None,
                     plot_kind=None):
    """관리 프로그램 참조를 검증·정규화 → (program_uuid, version, error).

    **버전을 함께 고정한다.** 프로그램을 나중에 고쳐도 진행 중인 작기의 해석이
    바뀌면 "그때 무엇을 목표로 길렀나" 의 답이 조용히 달라진다 — bay 기하를
    참조가 아니라 스냅샷으로 복사한 것과 같은 판단이다.

    이미 같은 프로그램을 쓰고 있으면 **버전을 그대로 둔다.** 저장할 때마다 최신
    버전으로 끌어올리면 고정의 의미가 없어진다(사람이 "새 버전 적용" 을 골랐을
    때만 올라가야 한다).
    """
    from aot.databases.models import GeoProgram

    program_uuid = (program_uuid or '').strip() or None
    if program_uuid is None:
        return None, None, None

    row = GeoProgram.query.filter_by(unique_id=program_uuid).first()
    if row is None:
        return None, None, '관리 프로그램을 찾을 수 없습니다: %s' % program_uuid

    # **종류가 다르면 거부한다.** 식생 구획에 가축 프로그램이 붙으면 단계·목표
    # 해석이 통째로 엉뚱해지는데 에러는 나지 않는다 — 화면에는 그럴듯한 단계와
    # 목표 온도가 뜨고, 그 값이 그대로 제어로 흐른다. 붙이는 순간 막는 것이
    # 유일하게 싼 자리다(붙은 뒤에는 어느 쪽이 틀렸는지 알 방법이 없다).
    if plot_kind and (row.kind or 'vegetation') != plot_kind:
        return None, None, (
            '구획 종류(%s)와 프로그램 종류(%s)가 다릅니다'
            % (plot_kind, row.kind or 'vegetation'))

    if current_uuid == program_uuid and current_version:
        return program_uuid, current_version, None
    return program_uuid, (row.version or 1), None


def _resolve_allocation(raw, has_geom):
    """구역 안에서의 몫을 검증·정규화 → (allocation, error).

    받는 모양은 둘 중 하나다 — `{'amount': 4}`(구역 총량 대비 몫) 또는
    `{'percent': 33}`(총량이 아직 없는 시설의 폴백). **둘을 함께 주면 거절한다**:
    어느 쪽이 정본인지 모호한 값을 저장하면 화면마다 다른 숫자를 보이게 된다.

    **비율은 저장하지 않는다** — `amount/total` 에서 파생한다. 여기 들어오는
    `percent` 는 그 파생이 불가능할 때 쓰는 별개 축이지 `amount` 의 사본이 아니다.

    **개별 값의 상한은 두지 않는다.** 합이 총량을 넘는 것은 간작·혼작에서 정상이고
    (VP-3), 총량은 나중에 줄어들 수도 있다 — 저장 시점에 막으면 정상 상황이 거부로
    나타난다. 넘었다는 것은 화면이 알린다.

    노지 구획(자기 기하가 있는 구획)에는 **쓰지 않는다.** 거기서는 면적이 기하에서
    나오므로 몫을 따로 적으면 정본이 둘이 된다. 조용히 무시하지 않고 거절하는
    이유는 하나다 — 무시하면 "적었는데 화면이 안 바뀐다" 가 되고, 그때 원인이
    입력인지 저장인지 가릴 방법이 없다.
    """
    if raw is None:
        return None, None
    if raw == {} or raw == '':
        return None, None            # 명시적으로 비우기
    if not isinstance(raw, dict):
        return None, '몫(allocation)은 객체여야 합니다'
    if has_geom:
        return None, ('기하를 가진 구획에는 몫을 적지 않습니다 — 면적이 도형에서 '
                      '나옵니다')

    has_amount = raw.get('amount') not in (None, '')
    has_percent = raw.get('percent') not in (None, '')
    if has_amount and has_percent:
        return None, ('몫은 수량(amount) 또는 비율(percent) 중 하나만 적습니다')
    if not has_amount and not has_percent:
        return None, None            # 알맹이가 없으면 비운 것으로 본다

    key = 'amount' if has_amount else 'percent'
    try:
        val = float(raw.get(key))
    except (TypeError, ValueError):
        return None, '몫은 숫자여야 합니다: %r' % (raw.get(key),)
    if val <= 0:
        return None, '몫은 0보다 커야 합니다'
    if key == 'percent' and val > 100:
        # 한 구획이 구역의 100%를 넘게 쓸 수는 없다(합계와는 다른 이야기다 —
        # 여럿이 겹쳐 합이 100을 넘는 것은 정상이다).
        return None, '비율은 100%를 넘을 수 없습니다'
    # 정수로 떨어지면 정수로 — 화면이 "4.0 베드" 를 보이지 않게.
    out = int(val) if float(val).is_integer() else round(val, 2)
    return {key: out}, None


def _resolve_parent(map_uuid, facility_uuid, bay_id):
    """시설 부모를 검증·정규화 → (facility_uuid, bay_id, error).

    **구역 id 는 클라이언트 말을 믿지 않는다.** 시설의 실제 구역 목록
    (`compute_bay_slices`)과 대조한다 — geo_binding 에서 프런트의 `aot_type`
    을 그대로 믿었다가 구역 배정이 마커 배정으로 저장된 것과 같은 종류의
    실수를 막는다.

    **단동(bay_count=1)도 구역 하나를 채운다.** 사람이 고를 것이 없고, NULL 로
    두면 "시설 전체"와 "구역 1"이 같은 대상을 두 가지로 표현하게 된다 — 나중에
    그 둘을 합치는 코드가 어디에 있어야 하는지 아무도 모르게 된다.

    그 id 는 **상수로 지어내지 않고 `compute_bay_slices` 에게 묻는다.** 예전에는
    단동만 이 대조를 건너뛰고 `'bay_1'` 을 박았는데, 단동 시설의 실제 구역 id 는
    `'main'` 이다. 그래서 저장은 성공하는데 읽는 쪽(`facility_brief` 의
    `bay_geometries`/`bay_names`)에는 그 키가 없어, 구획이 **구역 기하 대신 시설
    외피로 폴백**하고 구역 이름도 비었다 — 화면에서는 구획이 시설에 붙지 않고
    따로 노는 것으로 보인다. 에러는 나지 않는다(`check_geo_integrity` 의
    `plot-unknown-bay` 만이 본다).
    """
    from aot.aot_flask.geo.facility_bays import compute_bay_slices, spec_from_row
    from aot.databases.models import GeoFacility

    fac = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if fac is None:
        return None, None, '시설을 찾을 수 없습니다: %s' % facility_uuid
    if map_uuid and fac.geo_id and fac.geo_id != map_uuid:
        return None, None, ('시설이 다른 지도에 있습니다 '
                            '(시설 지도=%s, 구획 지도=%s)' % (fac.geo_id, map_uuid))

    bay_id = (bay_id or '').strip() or None

    try:
        bay_count = int(fac.bay_count or 1)
    except (TypeError, ValueError):
        bay_count = 1

    if bay_count <= 1:
        slices = compute_bay_slices(spec_from_row(fac))
        # 목록을 못 만드는 시설(치수 미입력 등)에서만 관례 id 로 물러선다 —
        # 근거가 없을 때 지어낸 값이라 그 사실이 로그에 남아야 한다.
        only = (slices[0].get('id') if slices else None)
        if not only:
            only = 'bay_1'
            logger.info("[Plot] 시설 %s 의 구역 목록을 만들 수 없어 구역 id 를 "
                        "%r 로 둔다", facility_uuid, only)
        if bay_id and bay_id != only:
            # 조용히 정정하되 남긴다 — 클라이언트가 어긋난 값을 보내고 있다는
            # 사실이 로그에 없으면 다음 사람이 같은 것을 다시 만든다.
            logger.info("[Plot] 단동 시설의 구역 id %r → %r 로 정정 "
                        "(facility=%s)", bay_id, only, facility_uuid)
        return fac.unique_id, only, None

    if bay_id:
        valid = {sl['id'] for sl in compute_bay_slices(spec_from_row(fac))}
        # 목록을 못 만드는 시설(치수 미입력 등)에서는 대조하지 않는다 —
        # 검증할 근거가 없는 것을 거절로 바꾸면 시설을 다 채우기 전에는
        # 작물을 적을 수 없게 된다.
        if valid and bay_id not in valid:
            return None, None, ("구역 '%s' 가 시설에 없습니다 (있는 구역: %s)"
                                % (bay_id, ', '.join(sorted(valid))))

    # 다동에서 bay_id 가 없는 것은 "시설 전체" 라는 뜻이다(온실 하나에 한 작물).
    return fac.unique_id, bay_id, None


def _validate_geometry(feature):
    """VP-1 — Polygon | MultiPolygon 만."""
    geom = (feature or {}).get('geometry')
    if not isinstance(geom, dict):
        return 'geometry 가 없습니다'
    gtype = geom.get('type')
    if gtype not in ('Polygon', 'MultiPolygon'):
        return ('식생 구획은 폴리곤이어야 합니다 (받은 값: %s). '
                '점·선은 구획이 될 수 없습니다.' % gtype)
    if not geom.get('coordinates'):
        return 'geometry.coordinates 가 비어 있습니다'
    return None


def save_plot(data):
    """생성 또는 수정 → (dict, error).

    `unique_id` 가 있으면 수정, 없으면 생성. 수정 시 페이로드에 없는 필드는
    **건드리지 않는다** — 부분 저장에서 "빠진 것 = 지운 것" 이 되면 멀쩡한
    값이 조용히 날아간다(save_overlays I9 와 같은 원칙).

    ## 상위 zone 을 받지도, 경계로 자르지도 않는다

    equipment 와 같은 모델이다: **그냥 그리면 되고 상위는 시스템이 판정한다**
    (`recalculateSpatialRelationships` 가 배관·장치에 대해 하는 일과 같다).
    zone 은 읽을 때 공간 포함으로 파생하므로(`plot_context.zone_for_plot`)
    저장 시점에 알 필요가 없다.

    예전에는 `zone_uuid` 를 받아 그 경계로 클리핑하고 밖이면 거부했다. 두 가지가
    나빴다 — 사용자가 zone 을 먼저 골라야 한다는 절차가 생겼는데 식생 모드에서
    zone 도형은 **클릭조차 되지 않았고**(다른 모드의 레이어다), 두둑이 구역
    경계에 걸치는 것은 실제 농사에서 흔한 일이라 자를 이유도 없었다.

    ## 시설 구획은 기하 대신 부모를 받는다 (p6_39)

    `facility_uuid`(+`bay_id`)를 주면 `feature` 없이도 만들어진다. 온실에서
    사람은 폴리곤이 아니라 **"3동"** 으로 위치를 말하고, 동·구역은 구조물로
    존재하므로 기하는 시설에서 파생하면 된다. 그래서 **VP-7**: `feature` 와
    `facility_uuid` 중 적어도 하나는 있어야 한다 — 둘 다 없으면 어디에도 없는
    구획이다.

    둘 다 주는 것도 허용한다(시설 안에서 두둑을 실제로 그린 경우). 그때는
    기하가 자기 것이고 부모는 소속 표시로 함께 남는다.
    """
    map_uuid = data.get('map_uuid') or data.get('geo_id')
    unique_id = data.get('unique_id')

    row = None
    if unique_id:
        row = GeoPlot.query.filter_by(unique_id=unique_id).first()
        if row is None:
            return None, 'plot not found: %s' % unique_id
        map_uuid = map_uuid or row.geo_id

    # 시설을 주면 지도는 **시설이 알고 있다**. 둘 다 요구하면 "3동에 토마토"
    # 라고 말할 수 있는 사람(과 AI)이 지도 uuid 를 찾으러 가야 한다 — 그리고
    # 잘못 넣으면 아래 _resolve_parent 가 "시설이 다른 지도에 있습니다" 로
    # 거절한다. 알 수 있는 값을 물어보지 않는다.
    if not map_uuid and data.get('facility_uuid'):
        from aot.databases.models import GeoFacility
        fac = GeoFacility.query.filter_by(
            unique_id=data.get('facility_uuid')).first()
        if fac is not None:
            map_uuid = fac.geo_id

    if not map_uuid:
        return None, 'map_uuid required'

    is_new = row is None

    # ── 시설 부모 ─────────────────────────────────────────────────────
    # 페이로드에 **있는 키만** 건드린다(부분 저장 원칙 — 없는 키를 None 으로
    # 덮으면 멀쩡한 소속이 조용히 끊긴다).
    eff_facility = row.facility_uuid if row else None
    eff_bay = row.bay_id if row else None
    if 'facility_uuid' in data or 'bay_id' in data:
        raw_fac = data.get('facility_uuid') if 'facility_uuid' in data else eff_facility
        raw_fac = (raw_fac or '').strip() or None
        raw_bay = data.get('bay_id') if 'bay_id' in data else eff_bay
        if raw_fac is None:
            # 부모 해제 — 기하가 없으면 아래 VP-7 에서 걸린다.
            eff_facility, eff_bay = None, None
        else:
            eff_facility, eff_bay, err = _resolve_parent(map_uuid, raw_fac, raw_bay)
            if err:
                return None, err

    # ── 대상 종류 ─────────────────────────────────────────────────────
    # 페이로드에 키가 있을 때만 건드린다(부분 저장 원칙). 새 구획의 기본은
    # 'vegetation' 이다 — 지금까지 만들어진 것이 전부 식생이고, 종류를 고르지
    # 않은 사람에게 종류를 묻는 화면을 강제하지 않는다.
    eff_kind = (row.kind if row else None) or 'vegetation'
    if 'kind' in data:
        cand = (data.get('kind') or '').strip() or 'vegetation'
        if cand not in VALID_KINDS:
            return None, 'kind 허용값 아님: %r' % cand
        eff_kind = cand

    # ── 관리 프로그램 ─────────────────────────────────────────────────
    # 페이로드에 키가 있을 때만 건드린다(부분 저장 원칙).
    eff_program = row.program_uuid if row else None
    eff_program_version = row.program_version if row else None
    if 'program_uuid' in data:
        eff_program, eff_program_version, err = _resolve_program(
            data.get('program_uuid'), eff_program, eff_program_version,
            plot_kind=eff_kind)
        if err:
            return None, err
        # 사람이 명시적으로 새 버전을 적용하겠다고 한 경우에만 올린다.
        if eff_program and data.get('program_version') == 'latest':
            from aot.databases.models import GeoProgram
            _p = GeoProgram.query.filter_by(unique_id=eff_program).first()
            if _p is not None:
                eff_program_version = _p.version or 1

    # **종류와 프로그램은 저장할 때마다 함께 대조한다.** 위 검사는 페이로드에
    # `program_uuid` 가 있을 때만 도는데, 붙어 있는 프로그램은 그대로 두고
    # **종류만** 바꾸는 저장이 그 분기를 지나간다 — 그러면 식생 프로그램이
    # 매달린 채 종류만 가축이 되고, 아무 에러 없이 단계·목표 해석이 통째로
    # 어긋난다(붙일 때 막는 것과 같은 이유로, 여기서도 막아야 한다).
    if eff_program:
        from aot.databases.models import GeoProgram
        _p = GeoProgram.query.filter_by(unique_id=eff_program).first()
        if _p is not None and (_p.kind or 'vegetation') != eff_kind:
            return None, ('구획 종류(%s)와 프로그램 종류(%s)가 다릅니다'
                          % (eff_kind, _p.kind or 'vegetation'))

    # ── 기하 ──────────────────────────────────────────────────────────
    feature = data.get('feature')

    # VP-7 — 기하와 시설 부모 중 적어도 하나. 기하는 페이로드가 우선이고,
    # 수정에서 키가 없으면 기존 행의 것을 본다.
    if feature is not None:
        has_geom = isinstance((feature or {}).get('geometry'), dict)
    else:
        has_geom = bool(row and row.has_own_geometry())
    if not has_geom and not eff_facility:
        return None, ('식생 구획에는 기하(feature) 또는 시설(facility_uuid) 중 '
                      '하나가 필요합니다 (VP-7).')

    # ── 구역 안에서의 몫 (p6_50) ──────────────────────────────────────
    eff_allocation = row.allocation if row else None
    if 'allocation' in data:
        eff_allocation, err = _resolve_allocation(data.get('allocation'), has_geom)
        if err:
            return None, err

    # VP-6 확장 — 종료된 작기는 기하뿐 아니라 **소속**도 못 바꾼다. 위치가
    # 바뀌면 "작년에 여기 뭐가 있었나" 의 답이 달라지는 것은 부모 참조에서도
    # 똑같다(시설 구획은 그 참조가 곧 위치다).
    if not is_new and row.ended_on is not None:
        if (eff_facility, eff_bay) != (row.facility_uuid, row.bay_id):
            return None, ('종료된 작기의 위치(시설·구역)는 수정할 수 없습니다 '
                          '(이력 보호 — VP-6). 새 작기를 만드세요.')

    if feature is not None:
        err = _validate_geometry(feature)
        if err:
            return None, err

        # VP-6 — 종료된 작기의 기하는 수정 불가. 날짜 정정·이름 변경은
        # 허용하되 기하가 바뀌면 "작년에 여기 뭐가 있었나" 의 답이 조용히
        # 달라진다.
        if not is_new and row.ended_on is not None:
            if plot_context.geometry_of(row) != feature.get('geometry'):
                return None, ('종료된 작기의 기하는 수정할 수 없습니다 '
                              '(이력 보호 — VP-6). 새 작기를 만드세요.')

        feature, removed = _strip_forbidden(feature)
        if removed:
            logger.info('[Plot] feature.properties 에서 금지 키 제거: %s',
                        ', '.join(removed))

    # ── 날짜 ──────────────────────────────────────────────────────────
    started_on, err = _parse_date(data.get('started_on'), 'started_on')
    if err:
        return None, err
    ended_on, err = _parse_date(data.get('ended_on'), 'ended_on')
    if err:
        return None, err
    expected_end_on, err = _parse_date(data.get('expected_end_on'),
                                       'expected_end_on')
    if err:
        return None, err

    if is_new and started_on is None:
        return None, 'started_on required'

    eff_planted = started_on if started_on is not None else (
        row.started_on if row else None)
    eff_ended = ended_on if 'ended_on' in data else (row.ended_on if row else None)

    # VP-2
    if eff_planted and eff_ended and eff_ended < eff_planted:
        return None, '종료일이 파종일보다 빠릅니다 (%s < %s)' % (
            eff_ended, eff_planted)

    # ── 작물 ──────────────────────────────────────────────────────────
    subject = (data.get('subject') or '').strip() if 'subject' in data else None
    if is_new and not subject:
        return None, 'subject required'

    # 기하 없이 시설에 매단 구획은 'drawn' 이 아니다 — 아무도 그리지 않았다.
    default_kind = 'facility' if (eff_facility and not has_geom) else 'drawn'
    source_kind = data.get('source_kind') or (default_kind if is_new else None)
    if source_kind is not None and source_kind not in _VALID_SOURCE_KINDS:
        return None, 'source_kind 허용값 아님: %r' % source_kind

    ended_reason = data.get('ended_reason')
    if ended_reason not in (None, '') and ended_reason not in _VALID_END_REASONS:
        return None, 'ended_reason 허용값 아님: %r' % ended_reason

    # ── 저장 ──────────────────────────────────────────────────────────
    try:
        if is_new:
            row = GeoPlot(
                geo_id=map_uuid,
                feature=feature,
                facility_uuid=eff_facility,
                bay_id=eff_bay,
                program_uuid=eff_program,
                program_version=eff_program_version,
                kind=eff_kind,
                subject=subject,
                variety=(data.get('variety') or None),
                started_on=started_on,
                ended_on=ended_on,
                expected_end_on=expected_end_on,
                ended_reason=(ended_reason or None),
                source_kind=source_kind or 'drawn',
                source_ref=(data.get('source_ref') or None),
                name=(data.get('name') or None),
                color=(data.get('color') or None),
                allocation=eff_allocation,
                auto_advance=bool(data.get('auto_advance')),
            )
            db.session.add(row)
        else:
            if feature is not None:
                row.feature = feature
            row.facility_uuid = eff_facility
            row.bay_id = eff_bay
            row.program_uuid = eff_program
            row.program_version = eff_program_version
            row.kind = eff_kind
            # 몫도 페이로드에 있는 키만 — 없는 키를 None 으로 덮으면 부분 저장이
            # (예: 날짜만 고치는 저장) 적어 둔 몫을 지운다.
            if 'allocation' in data:
                row.allocation = eff_allocation
            # 기하를 새로 그리면 몫은 의미를 잃는다 — 면적이 도형에서 나온다.
            elif has_geom and row.allocation:
                row.allocation = None
            # 페이로드에 **있는 키만** 반영한다. 없는 키를 None 으로 덮으면
            # 부분 저장이 멀쩡한 값을 지운다.
            for field in ('subject', 'variety', 'name', 'color', 'source_ref'):
                if field not in data:
                    continue
                value = data.get(field)
                if isinstance(value, str):
                    value = value.strip()
                if field == 'subject' and not value:
                    return None, 'subject 은 비울 수 없습니다'
                setattr(row, field, value or None)
            # 자동 승인(P8) — 페이로드에 있는 키만. 없는 키를 False 로 덮으면
            # 날짜만 고치는 저장이 켜 둔 자동 승인을 끈다.
            if 'auto_advance' in data:
                row.auto_advance = bool(data.get('auto_advance'))
            if started_on is not None:
                row.started_on = started_on
            if 'ended_on' in data:
                row.ended_on = ended_on
            if 'expected_end_on' in data:
                row.expected_end_on = expected_end_on
            if 'ended_reason' in data:
                row.ended_reason = ended_reason or None
            if source_kind:
                row.source_kind = source_kind

        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error('[Plot] 저장 실패: %s', exc)
        return None, str(exc)

    _invalidate_caches()
    return plot_context.to_dict(row), None


def end_plot(unique_id, ended_on=None, reason='harvested'):
    """작기 종료 → (dict, error). 행을 지우지 않는다.

    지우면 "이 자리에 뭐가 있었나" 의 답이 사라진다 — 연작 장해·윤작 판단의
    근거가 정확히 이 이력이다. `geo_binding` 의 unbind 와 같은 원칙.
    """
    row = GeoPlot.query.filter_by(unique_id=unique_id).first()
    if row is None:
        return None, 'plot not found: %s' % unique_id

    if reason not in _VALID_END_REASONS:
        return None, 'ended_reason 허용값 아님: %r' % reason

    parsed, err = _parse_date(ended_on, 'ended_on')
    if err:
        return None, err
    parsed = parsed or date.today()

    if row.started_on and parsed < row.started_on:
        return None, '종료일이 파종일보다 빠릅니다 (%s < %s)' % (
            parsed, row.started_on)

    try:
        row.ended_on = parsed
        row.ended_reason = reason
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return None, str(exc)
    _invalidate_caches()
    return plot_context.to_dict(row), None


def delete_plot(unique_id):
    """오기입 삭제 → (dict, error).

    **정상 종료에는 쓰지 말 것** — 끝난 작기는 `end_plot` 으로 남긴다.
    이것은 잘못 만든 행을 없애는 경로다.
    """
    row = GeoPlot.query.filter_by(unique_id=unique_id).first()
    if row is None:
        return None, 'plot not found: %s' % unique_id
    # 이 구획을 대상으로 한 일정은 함께 정리한다. 안 하면 대상이 사라진
    # 일정이 남아 화면·AI 양쪽에서 "어디의 일인지 모르는 일" 이 된다.
    #
    # 지우지 않고 ARCHIVED 로 내린다 — 감사 로그가 그 행을 가리키고 있고,
    # 종료(`end_plot`)가 행을 남기는 것과 같은 태도다. 정상 종료에서는
    # 아무 일도 하지 않는다(구획 행이 그대로 남으므로 일정도 유효하다).
    orphaned = 0
    try:
        from aot.databases.models.scheduler import SchedulerJobMeta
        live = SchedulerJobMeta.query.filter(
            SchedulerJobMeta.target_id == unique_id,
            SchedulerJobMeta.state.in_(('DRAFT', 'PENDING', 'RUNNING'))).all()
        for job in live:
            job.state = 'ARCHIVED'
            job.deletion_reason = 'plot deleted'
            orphaned += 1
    except Exception as exc:
        logger.warning('[Plot] 일정 정리 실패: %s', exc)

    try:
        db.session.delete(row)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return None, str(exc)
    _invalidate_caches()
    return {'ok': True, 'deleted': unique_id, 'archived_jobs': orphaned}, None


_UNSET = object()


def copy_plot(unique_id, started_on=None, subject=None,
              program_uuid=_UNSET, variety=_UNSET, kind=None):
    """지난 작기의 **자리**를 그대로 새 작기로 → (dict, error).

    같은 두둑에 매년 심는 경우 매번 다시 그리게 하면 쓸 수 없다. 기하·시설·
    구역·몫·색을 복사하고 기간과 대상만 새로 받는다.

    `program_uuid`/`variety` 는 **주지 않으면 물려받는다**(지난 작기와 같은
    기준으로 기른다는 뜻). `None` 을 명시하면 비운다 — 휴지기처럼 프로그램이
    없는 구간이 그 경우다. 기본값을 `None` 으로 두면 "안 줬다" 와 "비워라" 를
    구별할 수 없다.
    """
    src = GeoPlot.query.filter_by(unique_id=unique_id).first()
    if src is None:
        return None, 'plot not found: %s' % unique_id

    payload = {
        'map_uuid': src.geo_id,
        'feature': src.feature,
        # 시설 구획은 기하가 없으므로 부모를 안 넘기면 복사본이 VP-7 에 걸린다.
        'facility_uuid': src.facility_uuid,
        'bay_id': src.bay_id,
        # **몫도 물려준다.** 시설 구획에서 자리는 기하가 아니라 몫(베드 수)이라,
        # 빠뜨리면 "같은 자리에 이어심기" 가 자리를 잃은 채 만들어진다.
        'allocation': src.allocation,
        'kind': kind or src.kind,
        'subject': subject or src.subject,
        'name': src.name,
        'color': src.color,
        'started_on': started_on or date.today().isoformat(),
        'source_kind': 'copied',
        'source_ref': src.unique_id,
    }
    payload['program_uuid'] = (src.program_uuid if program_uuid is _UNSET
                               else program_uuid)
    payload['variety'] = src.variety if variety is _UNSET else variety
    return save_plot(payload)


def succeed_plot(unique_id, ended_on=None, reason='harvested',
                 subject=None, program_uuid=_UNSET, variety=_UNSET,
                 started_on=None):
    """작기를 끝내고 **같은 자리를 이어받는다** → (dict, error).

    반환의 `ended` 는 끝난 작기, `next` 는 새로 시작한 것이다.

    ## 왜 한 번의 조작인가

    수확이 끝났다고 그 자리가 없어지지 않는다 — 휴지기·정지·다음 작기가
    이어진다. 종료와 생성을 따로 하게 두면 사람이 그 사이에 도형을 다시 그리고
    몫을 다시 적어야 하고(노지는 측량까지), 그 왕복이 곧 "자리를 잃는" 것이다.

    ## 순서: **새 것을 먼저 만들고 원본을 끝낸다**

    반대로 하면 승계가 실패했을 때 자리가 비어 버린다. 이 순서면 실패해도
    원본이 그대로 살아 있어, 사람이 다시 눌러 볼 수 있다. (두 커밋을 한
    트랜잭션으로 묶지 않는 이유 — `save_plot`·`end_plot` 이 각자 커밋한다.)

    시작일은 기본이 **종료 다음 날**이다. 같은 날로 두면 하루가 두 작기에
    걸치는데, 이 도메인은 겹침이 정상이라(간작·혼작) 서버가 막지 않는다 —
    그래서 기본값이 잘못되면 조용히 이상한 이력이 쌓인다.
    """
    src = GeoPlot.query.filter_by(unique_id=unique_id).first()
    if src is None:
        return None, 'plot not found: %s' % unique_id

    parsed_end, err = _parse_date(ended_on, 'ended_on')
    if err:
        return None, err
    parsed_end = parsed_end or date.today()

    if not started_on:
        started_on = (parsed_end + timedelta(days=1)).isoformat()

    nxt, err = copy_plot(unique_id, started_on=started_on, subject=subject,
                         program_uuid=program_uuid, variety=variety)
    if err:
        return None, err

    ended, err = end_plot(unique_id, ended_on=parsed_end.isoformat(),
                          reason=reason)
    if err:
        # 승계는 만들어졌는데 종료가 실패했다. 되돌리지 않고 **말한다** —
        # 여기서 새 구획을 지우면 사람이 방금 정한 것이 소리 없이 사라진다.
        return None, ('이어심기는 만들어졌지만 종료에 실패했습니다: %s' % err)

    return {'ended': ended, 'next': nxt}, None


# ── 단계 전환 (P5) ─────────────────────────────────────────────────────────


def accept_stage(plot_uuid, stage_key=None, stage_index=None, started_on=None,
                 source='manual', decided_by=None, note=None, auto=False):
    """단계 전환을 확인해 원장에 남긴다 → (dict, error).

    **이 한 줄이 기준점을 옮긴다** — 이후 단계는 여기 적힌 날부터 계산된다
    (docs/design/program-layer.md §P5). 그래서 날짜를 지어내지 않는다: 화면이
    제안한 날을 사람이 고칠 수 있고, 서버는 받은 날을 그대로 적는다.
    """
    from datetime import date as _date
    from aot.databases.models import GeoPlotStageEvent, GeoProgram

    row = GeoPlot.query.filter_by(unique_id=plot_uuid).first()
    if row is None:
        return None, '구획을 찾을 수 없습니다: %s' % plot_uuid
    if not row.program_uuid:
        return None, '프로그램이 없는 구획에는 단계가 없습니다'

    prog = GeoProgram.query.filter_by(unique_id=row.program_uuid).first()
    # **구획이 실제로 따르는 목록**을 본다 — 뺀 단계를 확인하거나 더한 단계를
    # "프로그램에 없다" 며 거절하면, 구성을 고칠 수 있게 한 의미가 없다.
    stages = plot_context.effective_stages(row, prog)
    if not stages:
        return None, '프로그램에 단계가 없습니다'

    # 단계는 **키로** 고른다. 순번만 받으면 프로그램이 바뀌었을 때 엉뚱한
    # 단계가 확정되는데 에러가 나지 않는다.
    idx = None
    if stage_key:
        for i, st in enumerate(stages):
            if st.get('key') == stage_key:
                idx = i + 1
                break
        if idx is None:
            return None, '프로그램에 없는 단계입니다: %s' % stage_key
    elif stage_index:
        try:
            idx = int(stage_index)
        except (TypeError, ValueError):
            return None, '단계 번호가 숫자가 아닙니다'
        if not (1 <= idx <= len(stages)):
            return None, '단계 번호가 범위를 벗어납니다'
        stage_key = stages[idx - 1].get('key')
    else:
        return None, '단계를 지정해야 합니다'

    if started_on:
        started, derr = _parse_date(started_on, 'started_on')
        if derr:
            return None, derr
    else:
        started = _date.today()
    if started is None:
        return None, '전환일이 필요합니다'
    if row.started_on and started < row.started_on:
        return None, '전환일이 구획 시작일보다 빠릅니다'

    # 뒤로 가는 전환은 막는다. 되돌리기가 그 일을 하는 수단이고, 여기로도
    # 되면 원장에 앞뒤가 섞여 기준점이 어디인지 사람이 추적할 수 없다.
    cur = plot_context.stage_anchor(row)
    if cur and idx <= cur['stage_index']:
        return None, ('이미 %d단계가 확인돼 있습니다 — 되돌리기를 쓰세요'
                      % cur['stage_index'])

    if source not in ('days', 'gdd', 'manual'):
        source = 'manual'

    try:
        ev = GeoPlotStageEvent(
            plot_uuid=plot_uuid, stage_key=stage_key, stage_index=idx,
            started_on=started, source=source, auto=bool(auto),
            decided_by=(decided_by or None), note=(note or None))
        db.session.add(ev)
        # 확정된 전환보다 앞선 계획 경계는 **이미 답이 나온 질문**이다(P8).
        # 남겨 두면 되돌리기를 했을 때 지워진 줄 알았던 옛 계획이 되살아난다.
        _drop_plan_upto(row, stages, idx)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception('단계 전환 저장 실패')
        return None, '저장하지 못했습니다: %s' % exc

    return {'unique_id': ev.unique_id, 'stage_key': stage_key,
            'stage_index': idx, 'started_on': started.isoformat()}, None


def undo_stage(plot_uuid, decided_by=None):
    """마지막으로 확인된 전환을 되돌린다 → (dict, error).

    **행을 지우지 않는다** — 지우면 "누가 언제 확인했다가 물렀다" 가 사라지고
    같은 판단을 다시 하게 된다(`device_binding.unbind` 와 같은 규율).

    마지막 것만 무를 수 있다. 여러 개를 임의로 무르면 기준점이 어디인지 사람이
    추적할 수 없다.
    """
    from aot.databases.models import GeoPlotStageEvent
    from aot.utils.time_utils import utc_now

    anchor = plot_context.stage_anchor(
        GeoPlot.query.filter_by(unique_id=plot_uuid).first())
    if not anchor:
        return None, '되돌릴 전환이 없습니다'

    ev = GeoPlotStageEvent.query.filter_by(
        unique_id=anchor['unique_id']).first()
    if ev is None:
        return None, '되돌릴 전환이 없습니다'
    try:
        ev.undone_at = utc_now()
        ev.undone_by = decided_by or None
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception('단계 전환 되돌리기 실패')
        return None, '되돌리지 못했습니다: %s' % exc

    return {'unique_id': ev.unique_id, 'stage_key': ev.stage_key}, None


def auto_advance_stage(plot_uuid):
    """자동 승인 구획의 대기 중 전환을 기록한다 → list (없으면 []).

    ## 프로그램이 아니라 **구획**이 정한다 (P8)

    `GeoPlot.auto_advance` 가 정본이다. 자동 승인이 묻는 것은 "이 작물의 단계
    모델이 정확한가" 가 아니라 "이 자리를 사람 눈 없이 믿을 수 있는가" 이고,
    그것은 작물이 아니라 구획의 성질이다.

    ## 읽기 경로에서 부르는 쓰기다 — 그 사실을 숨기지 않는다

    배경 잡을 두지 않는다는 P5 의 판단은 그대로다(대기 제안을 저장하지 않으므로
    잡이 낡을 것도 없다). 그래서 자동 승인은 **구획을 읽을 때** 판정한다.

    늦게 기록돼도 **내용은 같다.** 기록되는 `started_on` 은 "지금" 이 아니라
    자료에서 되짚은 날이기 때문이다 — 날짜 판정은 단계 진입일을 거꾸로 세고,
    GDD 판정은 누적이 임계를 넘어선 날을 되짚는다(`_gdd_crossed_on`). 아무도
    3주 뒤에 열어 봐도 같은 날짜가 남는다.

    ## 한 번에 **여러 단계를 따라잡는다**

    한 줄만 적고 멈추면 3주 만에 연 구획의 이력에 구멍이 남는다(그리고 다음
    조회까지 단계가 하나 뒤처져 있다). 프로그램의 단계 수를 넘지 않는 선에서
    더 이상 제안이 없을 때까지 민다.

    ## 되짚을 날짜가 없으면 기록하지 않는다

    자동 승인이 "오늘" 을 적기 시작하면 그 기록은 **언제 열어 봤는지**를 남기는
    것이지 무슨 일이 있었는지를 남기는 것이 아니다. 근거가 없으면 사람에게
    묻는 상태로 둔다(제안이 그대로 뜬다).

    동시 읽기로 두 번 부릴 수 있는데, `accept_stage` 가 "이미 그 단계가
    확인돼 있다" 로 거절하므로 두 줄이 되지 않는다.
    """
    from aot.databases.models import GeoProgram

    row = GeoPlot.query.filter_by(unique_id=plot_uuid).first()
    if row is None or not row.program_uuid:
        return []
    if not getattr(row, 'auto_advance', False):
        return []
    prog = GeoProgram.query.filter_by(unique_id=row.program_uuid).first()
    if prog is None:
        return []

    out = []
    for _ in range(len(plot_context.effective_stages(row, prog)) or 1):
        # `assume_start` — 원장이 비어 있어도 첫 전환부터 민다. 자동 승인을 켠
        # 구획은 배너를 띄우지 않으므로 "소급해서 승인을 요구한다"(§P5)는
        # 문제가 없고, 켜 두었는데 아무것도 기록되지 않으면 사람은 기능이
        # 꺼진 것으로 본다.
        proposal = plot_context.stage_proposal(row, assume_start=True)
        if not proposal or not proposal.get('started_on'):
            # 되짚을 날짜가 없다 — 지어내지 않고 사람에게 묻는 상태로 둔다.
            break
        result, err = accept_stage(
            plot_uuid, stage_key=proposal['stage_key'],
            started_on=proposal['started_on'],
            source=proposal.get('source') or 'manual', auto=True)
        if err:
            logger.debug('자동 단계 전환 건너뜀(%s): %s', plot_uuid, err)
            break
        out.append(result)
        db.session.refresh(row)
    return out


# ── 단계 일정 (P8) ─────────────────────────────────────────────────────────
#
# 프로그램의 단계 길이는 표준이고, 구획은 그것을 **참조만** 한다. 현실에서
# 밀리거나 앞당겨진 경계를 적는 자리가 `GeoPlot.stage_plan` 이다.
# 정본: docs/design/program-layer.md §P8


def _drop_plan_upto(row, stages, idx):
    """`idx`(1-based) 까지의 계획 경계를 지운다. 커밋은 호출부가 한다."""
    plan = row.stage_plan
    if not isinstance(plan, dict) or not plan:
        return
    done = {st.get('key') for st in stages[:idx] if st.get('key')}
    left = {k: v for k, v in plan.items() if k not in done}
    if len(left) != len(plan):
        row.stage_plan = left or None


def _plan_context(plot_uuid):
    """(row, program, stages, 편집 가능한 첫 단계 순번) → 또는 (None, …, error)."""
    from aot.databases.models import GeoProgram

    row = GeoPlot.query.filter_by(unique_id=plot_uuid).first()
    if row is None:
        return None, None, None, None, '구획을 찾을 수 없습니다: %s' % plot_uuid
    if not row.program_uuid:
        return None, None, None, None, '프로그램이 없는 구획에는 단계가 없습니다'
    prog = GeoProgram.query.filter_by(unique_id=row.program_uuid).first()
    stages = plot_context.effective_stages(row, prog)
    if not stages:
        return None, None, None, None, '프로그램에 단계가 없습니다'
    anchor = plot_context.stage_anchor(row)
    # 기준점 단계의 시작일은 확정된 사실이거나 구획의 시작일이다 — 계획이
    # 손대지 못한다. 고치고 싶으면 원장을 무르는 것이 그 수단이다.
    first = int((anchor or {}).get('stage_index') or 1) + 1
    return row, prog, stages, first, None


def set_stage_plan(plot_uuid, plan, set_by=None):
    """계획 경계를 **병합** 저장 → (dict, error).

    `plan` = `{단계키: 'YYYY-MM-DD' | None}`. `None` 은 해제(프로그램 기본으로
    되돌림)다 — 없는 키는 건드리지 않는다(부분 저장 원칙).

    **절대 날짜만 받는다.** 화면은 "+7일" 로 말하지만 그 환산은 저장 전에 끝난다
    (`shift_stage`). 상대값을 저장하면 앞 단계가 밀릴 때 그 7일이 어느 날이었는지
    조용히 달라진다.
    """
    from aot.utils.time_utils import utc_now

    if not isinstance(plan, dict) or not plan:
        return None, '고칠 경계가 없습니다'

    row, prog, stages, first, err = _plan_context(plot_uuid)
    if err:
        return None, err

    by_key = {st.get('key'): i + 1 for i, st in enumerate(stages)
              if st.get('key')}
    current = dict(row.stage_plan) if isinstance(row.stage_plan, dict) else {}

    for key, raw in plan.items():
        idx = by_key.get(key)
        if idx is None:
            return None, '프로그램에 없는 단계입니다: %s' % key
        if idx < first:
            return None, ('이미 지나간 경계입니다: %s — 확인·되돌리기로 고치세요'
                          % key)
        if raw in (None, ''):
            current.pop(key, None)
            continue
        when, derr = _parse_date(raw, key)
        if derr:
            return None, derr
        if row.started_on and when < row.started_on:
            return None, '경계가 구획 시작일보다 빠릅니다: %s' % key
        current[key] = {'started_on': when.isoformat(),
                        'set_by': (set_by or None),
                        'set_at': utc_now().isoformat()}

    # **저장하기 전에 같은 규칙으로 검사한다.** 경계가 앞 경계보다 빠르면 그
    # 단계는 길이가 음수가 되는데, 읽는 쪽에서 조용히 바로잡으면 사람이 적은
    # 값과 화면이 보이는 값이 갈린다.
    cand = {}
    for key, entry in current.items():
        when, derr = _parse_date((entry or {}).get('started_on'), key)
        if derr or when is None:
            continue
        cand[key] = when
    sched = plot_context.stage_schedule(row, plan=cand)
    if sched is not None:
        prev = None
        for b in sched['boundaries']:
            if b['starts_on'] is None:
                continue
            if prev is not None and b['starts_on'] <= prev:
                return None, ('%s 의 경계가 앞 단계보다 빠릅니다'
                              % (b['name'] or b['key']))
            prev = b['starts_on']

    try:
        row.stage_plan = current or None
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception('단계 일정 저장 실패')
        return None, '저장하지 못했습니다: %s' % exc

    return {'stage_schedule': plot_context.stage_schedule_view(row)}, None


def set_stage_days(plot_uuid, days, set_by=None):
    """단계 **기간(일)** 으로 일정을 고친다 → (dict, error).

    `days` = `{단계키: 일수}`.

    ## 왜 날짜가 아니라 기간으로 받나 (2026-08-24)

    처음에는 화면이 경계 **날짜**를 직접 받았다. 사람이 계산해야 했다 — "육묘를
    닷새 더" 를 말하려면 정식일이 며칠이 되는지를 먼저 머릿속에서 더해야 하고,
    뒤 단계까지 보려면 그 덧셈을 다섯 번 더 한다.

    프로그램은 이미 **단계마다 며칠**로 적고 그 합이 일정을 만든다. 구획이 같은
    프로그램을 참조하는데 입력 어휘만 다르면, 같은 것을 두 가지로 생각하게 된다.

    **저장은 여전히 절대 날짜다**(`set_stage_plan`). 기간을 그대로 저장하면 앞
    단계가 밀릴 때 그 기간이 가리키던 날이 조용히 달라진다 — 여기서 하는 일은
    받은 기간을 그 자리에서 날짜로 환산하는 것뿐이다.

    **프로그램과 같은 값을 적으면 그 경계를 푼다.** 화면에 되돌리기 버튼이 없는
    이유가 이것이다 — 표준으로 돌아가는 수단이 이미 입력 칸 안에 있다.

    ## 기간을 정하는 것은 **다음 경계**를 정하는 것과 같은 말이다

    그래서 단계 i 의 기간을 받으면 경계 i+1 을 박는다. 마지막 단계는 다음 경계가
    없어 정할 수 없다(프로그램에서도 마지막은 "끝까지" 인 경우가 많다).

    여러 칸을 한 번에 받으면 **앞에서부터 누적해** 환산한다. 앞 단계를 늘린 뒤의
    뒤 단계 기간은 밀린 자리에서 세어야 하는데, 각자 원래 자리에서 세면 앞의
    변경이 두 번 반영된다.
    """
    from datetime import timedelta

    if not isinstance(days, dict) or not days:
        return None, '고칠 기간이 없습니다'

    row, prog, stages, first, err = _plan_context(plot_uuid)
    if err:
        return None, err

    clean = {}
    for key, raw in days.items():
        if raw in (None, ''):
            continue
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return None, '기간이 숫자가 아닙니다: %s' % key
        if n < 1:
            return None, '기간은 하루 이상이어야 합니다: %s' % key
        clean[key] = n
    if not clean:
        return None, '고칠 기간이 없습니다'

    sched = plot_context.stage_schedule(row)
    if sched is None:
        return None, '단계를 계산할 수 없습니다'
    bounds = sched['boundaries']
    known = {b['key'] for b in bounds}
    for key in clean:
        if key not in known:
            return None, ('이 구획의 남은 단계가 아닙니다: %s' % key)
        if key == bounds[-1]['key']:
            return None, ('마지막 단계는 기간을 정하지 않습니다 — 끝내는 날은 '
                          '재배 종료가 정합니다')

    plan = {}
    cursor = bounds[0]['starts_on']
    for i, b in enumerate(bounds[:-1]):
        nxt = bounds[i + 1]
        start = cursor
        if start is None:
            break
        n = clean.get(b['key'])
        if n is None:
            # 안 건드린 칸 — 지금 길이를 그대로 쓴다(앞이 밀렸으면 함께 밀린다).
            if nxt['starts_on'] is not None and b['starts_on'] is not None:
                n = (nxt['starts_on'] - b['starts_on']).days
            else:
                n = b['days']
            if not n:
                break
        elif n == b['days']:
            # **프로그램과 같은 값을 적으면 표준으로 돌아간다.** 되돌리기 버튼을
            # 따로 두지 않는 이유가 이것이다 — 같은 일을 하는 수단이 둘이면
            # 좁은 줄에 칸이 하나 더 생기고, 사람은 어느 쪽이 정본인지 묻는다.
            #
            # 박아 두어도 날짜는 같지만 뜻이 다르다: 박힌 경계는 프로그램을
            # 고쳐도 따라오지 않는다. 사람이 "표준대로" 라고 말한 것을 고정으로
            # 기록하면 그 뒤의 프로그램 수정이 조용히 무시된다.
            plan[nxt['key']] = None
        else:
            plan[nxt['key']] = (start + timedelta(days=n)).isoformat()
        cursor = start + timedelta(days=n)

    if not plan:
        return None, '고칠 기간이 없습니다'
    return set_stage_plan(plot_uuid, plan, set_by=set_by)


def _save_overrides(row, ov):
    """구성(뺀 것·더한 것·지침)을 저장 → error|None. 빈 것은 NULL 로 눕힌다."""
    out = {}
    if ov['removed']:
        out['removed'] = sorted(ov['removed'])
    if ov['added']:
        out['added'] = ov['added']
    if ov['guidance']:
        out['guidance'] = ov['guidance']
    try:
        row.stage_overrides = out or None
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception('단계 구성 저장 실패')
        return '저장하지 못했습니다: %s' % exc
    return None


def set_stage_guidance(plot_uuid, stage_key=None, text=None, set_by=None):
    """이 구획의 **단계 지침**을 적는다 → (dict, error).

    프로그램의 지침은 그 작물의 일반 사항이고, 여기 적는 것은 "이 자리에서 이
    시기에 무엇을 하나" 다. 프로그램 카탈로그는 지침을 비운 채로 오는 경우가
    대부분이라, **없어도 적을 수 있어야** 한다.

    빈 글을 주면 지운다(= 프로그램 지침이 다시 보인다).

    ⚠ 프로그램을 고치지 않는다. 구획 화면에서 템플릿을 건드리면 같은 프로그램을
    쓰는 다른 구획이 조용히 함께 바뀐다.
    """
    row, prog, stages, first, err = _plan_context(plot_uuid)
    if err:
        return None, err
    if not stage_key:
        return None, '단계를 지정해야 합니다'
    if stage_key not in {st.get('key') for st in stages}:
        return None, '이 구획에 없는 단계입니다: %s' % stage_key

    text = (text or '').strip()
    if len(text) > 4000:
        return None, '지침이 너무 깁니다 (4000자)'

    ov = row.stage_override_map()
    if text:
        ov['guidance'][stage_key] = text
    else:
        ov['guidance'].pop(stage_key, None)
    err = _save_overrides(row, ov)
    if err:
        return None, err
    return {'stage_key': stage_key,
            'guidance': text or None,
            'stage_schedule': plot_context.stage_schedule_view(row)}, None


def remove_stage(plot_uuid, stage_key=None, set_by=None):
    """이 구획에서 단계를 **뺀다** → (dict, error).

    육묘 없이 바로 정식하는 작기가 있다. 프로그램을 고치면 그 프로그램을 쓰는
    모든 구획이 함께 바뀌므로, 뺀 사실은 구획이 든다.

    **이미 지나간 단계는 뺄 수 없다** — 확인된 전환이 가리키는 단계를 없애면
    원장이 존재하지 않는 단계를 가리키게 되고, 그때 무엇을 했는지의 답이 사라진다.
    남은 단계가 하나도 없게 만드는 것도 막는다.
    """
    row, prog, stages, first, err = _plan_context(plot_uuid)
    if err:
        return None, err
    if not stage_key:
        return None, '단계를 지정해야 합니다'

    idx = None
    for i, st in enumerate(stages):
        if st.get('key') == stage_key:
            idx = i + 1
            break
    if idx is None:
        return None, '이 구획에 없는 단계입니다: %s' % stage_key
    # **원장이 가리키는 단계**와 그 앞은 뺄 수 없다. 원장이 비어 있으면 막을
    # 것이 없다 — 아직 아무 전환도 확인되지 않았으므로 무엇을 뺐다고 해서
    # 잃어버릴 기록이 없다(첫 단계를 건너뛰는 작기가 바로 이 경우다).
    anc = plot_context.stage_anchor(row)
    if anc and idx <= int(anc.get('stage_index') or 1):
        return None, ('이미 지나간 단계는 뺄 수 없습니다 — 되돌리기로 전환을 '
                      '먼저 무르세요')
    if len(stages) <= 1:
        return None, '마지막 남은 단계는 뺄 수 없습니다'

    ov = row.stage_override_map()
    # 더한 단계를 다시 빼는 것은 **목록에서 지우는 것**이다. `removed` 에 적으면
    # 프로그램에 없는 키가 영영 남는다.
    added_keys = {a.get('key') for a in ov['added']}
    if stage_key in added_keys:
        ov['added'] = [a for a in ov['added'] if a.get('key') != stage_key]
    else:
        ov['removed'].add(stage_key)
    ov['guidance'].pop(stage_key, None)

    err = _save_overrides(row, ov)
    if err:
        return None, err
    # 그 단계에 걸린 경계도 함께 푼다 — 없는 단계의 날짜가 남으면 파생이 그
    # 키를 영영 못 찾는다.
    plan = row.stage_plan
    if isinstance(plan, dict) and stage_key in plan:
        left = {k: v for k, v in plan.items() if k != stage_key}
        row.stage_plan = left or None
        db.session.commit()
    return {'stage_key': stage_key,
            'stage_schedule': plot_context.stage_schedule_view(row)}, None


def add_stage(plot_uuid, name=None, days=None, after=None, guidance=None,
              set_by=None):
    """이 구획에 단계를 **더한다** → (dict, error).

    `after` 는 그 단계 **뒤**에 끼운다는 뜻이다(빈 문자열이면 맨 앞, 없으면 맨 뒤).

    키는 서버가 짓는다 — 사람에게 식별자를 묻지 않는다. `custom_` 접두사를 쓰는
    이유는 프로그램이 나중에 단계를 늘려도 키가 부딪히지 않게 하기 위해서다.
    """
    row, prog, stages, first, err = _plan_context(plot_uuid)
    if err:
        return None, err

    name = (name or '').strip()
    if not name:
        return None, '단계 이름이 필요합니다'
    try:
        days = int(days)
    except (TypeError, ValueError):
        return None, '기간이 숫자가 아닙니다'
    if days < 1:
        return None, '기간은 하루 이상이어야 합니다'

    keys = {st.get('key') for st in stages}
    if after not in (None, '') and after not in keys:
        return None, '이 구획에 없는 단계입니다: %s' % after
    # 지나간 자리에 끼우면 이미 확인된 전환의 순번이 틀어진다. 원장이 비어
    # 있으면 막을 것이 없다(빼기와 같은 판단).
    anc = plot_context.stage_anchor(row)
    anchor_index = int((anc or {}).get('stage_index') or 0)
    if anchor_index:
        pos = 0
        if after not in (None, ''):
            pos = [i for i, st in enumerate(stages)
                   if st.get('key') == after][0] + 1
        elif after is None:
            pos = len(stages)
        if pos < anchor_index:
            return None, '이미 지나간 자리에는 넣을 수 없습니다'

    ov = row.stage_override_map()
    n = 1
    while ('custom_%d' % n) in keys:
        n += 1
    key = 'custom_%d' % n

    entry = {'key': key, 'name': name, 'days': days}
    if after is not None:
        entry['after'] = after
    if (guidance or '').strip():
        entry['guidance'] = guidance.strip()[:4000]
    ov['added'] = list(ov['added']) + [entry]

    err = _save_overrides(row, ov)
    if err:
        return None, err
    return {'stage_key': key, 'name': name,
            'stage_schedule': plot_context.stage_schedule_view(row)}, None


def save_as_program(plot_uuid, name=None, set_by=None):
    """이 구획의 일정을 **프로그램으로 등록한다** → (dict, error).

    ## 왜 필요한가

    구획에서 기간을 맞추고 단계를 더하고 지침을 적고 나면, 그 지식은 그 구획
    안에만 있다. 다음 작기·옆 밭은 같은 일을 처음부터 다시 한다 — 프로그램은
    바로 그것(같은 걸 두 번 하지 않기)을 위해 있는 층이다.

    ## 무엇을 담나

    지금 **실제로 따르고 있는 단계 목록**이다(`effective_stages`) — 뺀 단계는
    빠지고 더한 단계는 들어가며 지침은 구획이 적은 것이 담긴다. 기간은 프로그램의
    표준이 아니라 **경계 사이의 실제 날수**다: 그것을 고쳐 둔 것이 이 기능을
    부르는 이유다.

    목표(`targets`)와 목표 항목 정의는 원본 프로그램 것을 그대로 옮긴다 —
    구획이 손대지 않는 값이라 바뀐 것이 없다.

    ## 구획을 새 프로그램으로 옮기지는 않는다

    등록은 **복사**다. 이 구획은 지금 따르던 것을 그대로 따른다 — 등록 한 번이
    진행 중인 작기의 해석을 바꾸면(버전 고정이 옮겨 가면) "그때 무엇을 목표로
    길렀나" 의 답이 조용히 달라진다. 새 프로그램을 이 구획에도 쓰려면 [설정]
    에서 고르는 것이 사람의 결정이다.
    """
    from aot.aot_flask.geo import program_io
    from aot.databases.models import GeoProgram

    row, prog, stages, first, err = _plan_context(plot_uuid)
    if err:
        return None, err

    view = plot_context.stage_schedule_view(row)
    lengths = {v['key']: v['days'] for v in view}

    out_stages = []
    for i, st in enumerate(stages):
        item = {k: v for k, v in st.items() if k != 'after'}
        # 마지막 단계는 "끝까지" 로 둔다 — 끝내는 날은 재배 종료가 정한다.
        if i == len(stages) - 1:
            item['days'] = None
        else:
            n = lengths.get(st.get('key'))
            item['days'] = n if n else st.get('days')
        out_stages.append(item)

    src = GeoProgram.query.filter_by(unique_id=row.program_uuid).first()
    name = (name or '').strip()
    if not name:
        # 이름을 지어 준다 — 사람에게 빈 칸부터 내밀지 않는다. 겹치면 뒤에 번호.
        base = '%s %s' % (row.subject, (row.name or '').strip() or
                          (src.name if src is not None else ''))
        name = ' '.join(base.split()) or row.subject
    exists = {p.name for p in GeoProgram.query.filter_by(name=name).all()}
    if exists:
        n = 2
        while '%s (%d)' % (name, n) in {p.name for p in GeoProgram.query.all()}:
            n += 1
        name = '%s (%d)' % (name, n)

    payload = {
        'name': name,
        'kind': row.kind or 'vegetation',
        'subject': row.subject,
        'variety': row.variety or None,
        'stages': out_stages,
        'source_note': ('구획 "%s" 의 일정에서 등록' % (row.name or row.subject)),
    }
    if src is not None:
        payload['target_defs'] = src.target_def_list()
        payload['resource_defs'] = src.resource_def_list()
        payload['photosynthesis'] = src.photosynthesis
        payload['targets_methods'] = src.targets_methods
        payload['tab_id'] = src.tab_id
        payload['derived_from'] = src.unique_id

    result, err = program_io.create_program(payload, source='user')
    if err:
        return None, err
    return {'program': {'unique_id': result.get('unique_id'),
                        'name': result.get('name')}}, None


def shift_stage(plot_uuid, stage_key=None, days=None, set_by=None):
    """단계 경계를 상대로 옮긴다 → (dict, error). 연기는 +, 앞당김은 −.

    지금 경계가 어디인지는 서버가 알고 있으므로(계획이든 프로그램 기본이든),
    화면은 며칠인지만 말하면 된다. 저장은 **환산한 절대 날짜**다.
    """
    from datetime import timedelta

    try:
        days = int(days)
    except (TypeError, ValueError):
        return None, '며칠인지가 숫자가 아닙니다'
    if days == 0:
        return None, '옮길 날수가 0 입니다'
    if not stage_key:
        return None, '단계를 지정해야 합니다'

    row, prog, stages, first, err = _plan_context(plot_uuid)
    if err:
        return None, err

    sched = plot_context.stage_schedule(row)
    if sched is None:
        return None, '단계를 계산할 수 없습니다'
    target = None
    for b in sched['boundaries']:
        if b['key'] == stage_key:
            target = b
            break
    if target is None:
        return None, '이 구획의 남은 단계가 아닙니다: %s' % stage_key
    if target['starts_on'] is None:
        return None, ('앞 단계에 기간이 없어 이 경계를 셀 수 없습니다 — '
                      '날짜를 직접 정하세요')

    return set_stage_plan(
        plot_uuid,
        {stage_key: (target['starts_on'] + timedelta(days=days)).isoformat()},
        set_by=set_by)


def apply_stage_resources(plot_uuid):
    """현재 단계가 요구하는 자원을 켠다 → (dict, error).

    ## 켤 대상은 현장이 정한다

    프로그램은 역할만 선언하고 함수를 가리키지 않는다(P6 재설계). 그래서 여기서
    켜는 것은 **그 자리에서 찾힌 함수**다. 찾지 못한 역할(`unresolved`)과 후보가
    여럿이라 고르지 않은 역할(`ambiguous`)은 응답에 그대로 담는다 — "적용했다"
    만 받으면 사람은 관수가 걸린 줄 안다.

    ## 선언된 것만 건드린다

    선언에 없는 함수를 끄지 않는다. "이 단계에 없으니 꺼라" 로 읽으면 프로그램과
    무관한 함수까지 멈춘다 — 프로그램은 농장 전체의 함수 목록을 알지 못한다.

    ## 사람이 눌러야 한다

    프로그램이 스스로 부르지 않는다(단계 전환에도, 자동 승인에도 붙이지 않았다).
    관수를 켜는 것은 물이 나오는 일이고, `activate_function` 이 승인 대상인 것과
    같은 이유다. 목표값조차 아직 표시 전용인 마당에 자원만 자동으로 물리 동작을
    하는 것은 앞뒤가 맞지 않는다.

    실행은 기존 경로(`AoTDataToolService._set_function_activation`)를 그대로 쓴다 —
    여기서 DB 를 직접 고치면 데몬에 알리는 일이 빠져 "켜졌다고 나오는데 안 돈다"
    가 된다.
    """
    from aot.ai.services.aot_data_tool_service import AoTDataToolService

    row = GeoPlot.query.filter_by(unique_id=plot_uuid).first()
    if row is None:
        return None, '구획을 찾을 수 없습니다: %s' % plot_uuid

    st = plot_context.stage_of(row)
    if not st or st.get('state') != 'running':
        return None, '진행 중인 단계가 없습니다'

    # 선언(역할)마다 **현장이 찾아 준 함수**를 켠다. 프로그램은 함수를 가리키지
    # 않으므로(P6 재설계) 여기서 켤 대상은 기하 해석의 결과다.
    items = st.get('resources') or []

    # 찾지 못한 역할은 조용히 넘기지 않고 그대로 돌려준다 — "적용했다" 는 답만
    # 받으면 사람은 관수가 걸린 줄 안다. 무엇을 못 했는지가 이 응답의 값이다.
    unresolved = [{'role': r['role'], 'reason': r.get('reason')}
                  for r in items if not r.get('found')]

    todo, ambiguous = [], []
    for r in items:
        if not r.get('found'):
            continue
        fns = r.get('functions') or []
        # **모호하면 고르지 않는다**(R4 와 같은 태도). 한 역할에 함수가 여럿
        # 잡히는 것은 밸브가 여럿인 시설에서 정상이지만, 그중 무엇을 켤지는
        # 자동으로 정할 수 없다 — 자동 선택은 조용히 틀린다.
        if len(fns) > 1:
            ambiguous.append({'role': r['role'],
                              'functions': [{'id': f['id'],
                                             'name': f.get('name')}
                                            for f in fns]})
            continue
        fn = fns[0]
        if not fn.get('active'):
            todo.append({'role': r['role'], **fn})

    done, failed = [], []
    for r in todo:
        try:
            res = AoTDataToolService._set_function_activation(r['id'],
                                                              activate=True)
        except Exception as exc:                      # noqa: BLE001
            failed.append({'id': r['id'], 'name': r.get('name'),
                           'error': str(exc)})
            continue
        # `{"status": "success", ...}` 를 무조건 믿지 않는다 — 이 저장소가 겪은
        # "성공이라고 답하는데 안 돈 것" 계열이다(scheduler fake success).
        if isinstance(res, dict) and res.get('error'):
            failed.append({'id': r['id'], 'name': r.get('name'),
                           'error': res.get('error')})
            continue
        done.append({'id': r['id'], 'name': r.get('name')})

    return {'activated': done, 'failed': failed,
            'unresolved': unresolved, 'ambiguous': ambiguous,
            'skipped': len(items) - len(todo) - len(unresolved)
                       - len(ambiguous)}, None

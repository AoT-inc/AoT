# coding=utf-8
"""식생 구획(작기)의 쓰기 경로 — 검증·저장·종료·삭제.

설계 정본: docs/design/geo-vegetation-planting.md

불변식 VP-1~VP-6 을 **여기 한 곳에서** 강제한다. 라우트마다 검증을 흩으면
새 진입점이 생길 때마다 조용히 빠지고, 그게 이 도메인이 반복해서 겪은
실패다(장치 삭제 17경로 중 도형을 정리하는 곳이 4곳뿐이었던 것처럼).

읽기·파생은 `planting_context` 가 담당한다.
"""
import logging
from datetime import date, datetime

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import planting_context
from aot.databases.models import GeoPlanting

logger = logging.getLogger(__name__)

# VP-4 — feature.properties 에 두면 안 되는 키. 사본은 원본이 바뀌어도 따라오지
# 않아 조용히 갈린다(GB-5 와 같은 결). 색도 여기 넣지 않는다 — 구분색은
# `color` 컬럼이고, feature 에 각인하면 테마를 바꿔도 그 구획만 옛 색으로 남는다.
_FORBIDDEN_PROPS = ('device_id', 'channel_id', 'unique_id', 'color',
                    'zone_uuid', 'zone_id')

_VALID_END_REASONS = ('harvested', 'failed', 'replaced', 'removed')
_VALID_SOURCE_KINDS = ('drawn', 'bay_snapshot', 'copied')


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


def _parse_bed_cm(value, field, allow_zero=False):
    """두둑/고랑 폭 → int cm. 빈 값은 None(모른다). 틀리면 (None, 오류).

    **None 과 0 은 다르다.** 0 은 "고랑 없이 두둑을 붙여 만든다" 는 유효한
    배치이고, None 은 "아직 모른다" 이다. 이 구분이 무너지면 조회가 모르는
    규격으로 계산한 숫자를 확신하며 내민다.
    """
    if value in (None, ''):
        return None, None
    try:
        out = int(round(float(value)))
    except (TypeError, ValueError):
        return None, '%s: 숫자(cm)여야 합니다 (%r)' % (field, value)
    if out < 0 or (out == 0 and not allow_zero):
        return None, '%s: 0보다 커야 합니다 (%r)' % (field, value)
    return out, None


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


def save_planting(data):
    """생성 또는 수정 → (dict, error).

    `unique_id` 가 있으면 수정, 없으면 생성. 수정 시 페이로드에 없는 필드는
    **건드리지 않는다** — 부분 저장에서 "빠진 것 = 지운 것" 이 되면 멀쩡한
    값이 조용히 날아간다(save_overlays I9 와 같은 원칙).

    ## 상위 zone 을 받지도, 경계로 자르지도 않는다

    equipment 와 같은 모델이다: **그냥 그리면 되고 상위는 시스템이 판정한다**
    (`recalculateSpatialRelationships` 가 배관·장치에 대해 하는 일과 같다).
    zone 은 읽을 때 공간 포함으로 파생하므로(`planting_context.zone_for_planting`)
    저장 시점에 알 필요가 없다.

    예전에는 `zone_uuid` 를 받아 그 경계로 클리핑하고 밖이면 거부했다. 두 가지가
    나빴다 — 사용자가 zone 을 먼저 골라야 한다는 절차가 생겼는데 식생 모드에서
    zone 도형은 **클릭조차 되지 않았고**(다른 모드의 레이어다), 두둑이 구역
    경계에 걸치는 것은 실제 농사에서 흔한 일이라 자를 이유도 없었다.
    """
    map_uuid = data.get('map_uuid') or data.get('geo_id')
    unique_id = data.get('unique_id')

    row = None
    if unique_id:
        row = GeoPlanting.query.filter_by(unique_id=unique_id).first()
        if row is None:
            return None, 'planting not found: %s' % unique_id
        map_uuid = map_uuid or row.geo_id

    if not map_uuid:
        return None, 'map_uuid required'

    is_new = row is None

    # ── 기하 ──────────────────────────────────────────────────────────
    feature = data.get('feature')
    if is_new and feature is None:
        return None, 'feature required'

    if feature is not None:
        err = _validate_geometry(feature)
        if err:
            return None, err

        # VP-6 — 종료된 작기의 기하는 수정 불가. 날짜 정정·이름 변경은
        # 허용하되 기하가 바뀌면 "작년에 여기 뭐가 있었나" 의 답이 조용히
        # 달라진다.
        if not is_new and row.ended_on is not None:
            if planting_context.geometry_of(row) != feature.get('geometry'):
                return None, ('종료된 작기의 기하는 수정할 수 없습니다 '
                              '(이력 보호 — VP-6). 새 작기를 만드세요.')

        feature, removed = _strip_forbidden(feature)
        if removed:
            logger.info('[Planting] feature.properties 에서 금지 키 제거: %s',
                        ', '.join(removed))

    # ── 날짜 ──────────────────────────────────────────────────────────
    planted_on, err = _parse_date(data.get('planted_on'), 'planted_on')
    if err:
        return None, err
    ended_on, err = _parse_date(data.get('ended_on'), 'ended_on')
    if err:
        return None, err
    expected_end_on, err = _parse_date(data.get('expected_end_on'),
                                       'expected_end_on')
    if err:
        return None, err

    if is_new and planted_on is None:
        return None, 'planted_on required'

    eff_planted = planted_on if planted_on is not None else (
        row.planted_on if row else None)
    eff_ended = ended_on if 'ended_on' in data else (row.ended_on if row else None)

    # VP-2
    if eff_planted and eff_ended and eff_ended < eff_planted:
        return None, '종료일이 파종일보다 빠릅니다 (%s < %s)' % (
            eff_ended, eff_planted)

    # ── 작물 ──────────────────────────────────────────────────────────
    crop = (data.get('crop') or '').strip() if 'crop' in data else None
    if is_new and not crop:
        return None, 'crop required'

    source_kind = data.get('source_kind') or ('drawn' if is_new else None)
    if source_kind is not None and source_kind not in _VALID_SOURCE_KINDS:
        return None, 'source_kind 허용값 아님: %r' % source_kind

    ended_reason = data.get('ended_reason')
    if ended_reason not in (None, '') and ended_reason not in _VALID_END_REASONS:
        return None, 'ended_reason 허용값 아님: %r' % ended_reason

    # ── 두둑 규격 ─────────────────────────────────────────────────────
    bed_cm, err = _parse_bed_cm(data.get('bed_width_cm'), 'bed_width_cm')
    if err:
        return None, err
    path_cm, err = _parse_bed_cm(data.get('path_width_cm'), 'path_width_cm',
                                 allow_zero=True)
    if err:
        return None, err

    # 한쪽만으로는 배치가 정해지지 않는다. 검사는 **병합 후 값**으로 한다 —
    # 이미 두둑 폭이 저장된 구획의 고랑만 고치는 것은 정상이라, 페이로드만
    # 보고 판정하면 그 정상 수정이 막힌다.
    eff_bed = bed_cm if 'bed_width_cm' in data else (row.bed_width_cm if row else None)
    eff_path = path_cm if 'path_width_cm' in data else (row.path_width_cm if row else None)
    if (eff_bed is None) != (eff_path is None):
        return None, ('두둑 폭과 고랑 폭은 함께 있어야 합니다 '
                      '(두둑=%r, 고랑=%r). 고랑이 없는 배치는 0 으로 적으세요.'
                      % (eff_bed, eff_path))

    # ── 저장 ──────────────────────────────────────────────────────────
    try:
        if is_new:
            row = GeoPlanting(
                geo_id=map_uuid,
                feature=feature,
                crop=crop,
                variety=(data.get('variety') or None),
                planted_on=planted_on,
                ended_on=ended_on,
                expected_end_on=expected_end_on,
                ended_reason=(ended_reason or None),
                source_kind=source_kind or 'drawn',
                source_ref=(data.get('source_ref') or None),
                name=(data.get('name') or None),
                color=(data.get('color') or None),
                bed_width_cm=bed_cm,
                path_width_cm=path_cm,
            )
            db.session.add(row)
        else:
            if feature is not None:
                row.feature = feature
            # 페이로드에 **있는 키만** 반영한다. 없는 키를 None 으로 덮으면
            # 부분 저장이 멀쩡한 값을 지운다.
            for field in ('crop', 'variety', 'name', 'color', 'source_ref'):
                if field not in data:
                    continue
                value = data.get(field)
                if isinstance(value, str):
                    value = value.strip()
                if field == 'crop' and not value:
                    return None, 'crop 은 비울 수 없습니다'
                setattr(row, field, value or None)
            if planted_on is not None:
                row.planted_on = planted_on
            if 'ended_on' in data:
                row.ended_on = ended_on
            if 'expected_end_on' in data:
                row.expected_end_on = expected_end_on
            if 'ended_reason' in data:
                row.ended_reason = ended_reason or None
            if source_kind:
                row.source_kind = source_kind
            # 기하와 달리 종료된 작기에서도 고칠 수 있다 — 나중에 규격을 알게
            # 되어 채워 넣는 것은 "그 자리에 뭐가 있었나" 를 바꾸는 일이 아니다.
            if 'bed_width_cm' in data:
                row.bed_width_cm = bed_cm
            if 'path_width_cm' in data:
                row.path_width_cm = path_cm

        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error('[Planting] 저장 실패: %s', exc)
        return None, str(exc)

    return planting_context.to_dict(row), None


def end_planting(unique_id, ended_on=None, reason='harvested'):
    """작기 종료 → (dict, error). 행을 지우지 않는다.

    지우면 "이 자리에 뭐가 있었나" 의 답이 사라진다 — 연작 장해·윤작 판단의
    근거가 정확히 이 이력이다. `geo_binding` 의 unbind 와 같은 원칙.
    """
    row = GeoPlanting.query.filter_by(unique_id=unique_id).first()
    if row is None:
        return None, 'planting not found: %s' % unique_id

    if reason not in _VALID_END_REASONS:
        return None, 'ended_reason 허용값 아님: %r' % reason

    parsed, err = _parse_date(ended_on, 'ended_on')
    if err:
        return None, err
    parsed = parsed or date.today()

    if row.planted_on and parsed < row.planted_on:
        return None, '종료일이 파종일보다 빠릅니다 (%s < %s)' % (
            parsed, row.planted_on)

    try:
        row.ended_on = parsed
        row.ended_reason = reason
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return None, str(exc)
    return planting_context.to_dict(row), None


def delete_planting(unique_id):
    """오기입 삭제 → (dict, error).

    **정상 종료에는 쓰지 말 것** — 끝난 작기는 `end_planting` 으로 남긴다.
    이것은 잘못 만든 행을 없애는 경로다.
    """
    row = GeoPlanting.query.filter_by(unique_id=unique_id).first()
    if row is None:
        return None, 'planting not found: %s' % unique_id
    try:
        db.session.delete(row)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return None, str(exc)
    return {'ok': True, 'deleted': unique_id}, None


def copy_planting(unique_id, planted_on=None, crop=None):
    """지난 작기의 기하를 그대로 새 작기로 → (dict, error).

    같은 두둑에 매년 심는 경우 매번 다시 그리게 하면 쓸 수 없다. 기하만
    복사하고 기간은 새로 받는다.
    """
    src = GeoPlanting.query.filter_by(unique_id=unique_id).first()
    if src is None:
        return None, 'planting not found: %s' % unique_id

    return save_planting({
        'map_uuid': src.geo_id,
        'feature': src.feature,
        'crop': crop or src.crop,
        'variety': src.variety,
        'name': src.name,
        'color': src.color,
        # 두둑 규격도 함께 옮긴다 — 같은 자리를 다시 심는 것이므로 두둑도
        # 그대로다. 빠뜨리면 복사한 작기만 규격을 모르는 상태가 된다.
        'bed_width_cm': src.bed_width_cm,
        'path_width_cm': src.path_width_cm,
        'planted_on': planted_on or date.today().isoformat(),
        'source_kind': 'copied',
        'source_ref': src.unique_id,
    })

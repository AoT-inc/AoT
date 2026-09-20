# coding=utf-8
"""routes_geo 의 대지/구역/도형 CRUD·hidden_rows·rep_key·description·photo 라우트. blueprint 는 routes_geo 것을 공유한다."""
from flask import current_app, request, jsonify
import json
import os
from flask_login import login_required
from aot.aot_flask.utils import utils_general
from aot.databases.models import GeoMap, GeoShape
from aot.aot_flask.extensions import db
from aot.aot_flask.routes_geo import blueprint  # noqa: E402



# --- Helper Utilities ---
def _next_map_name(base_label="Map"):
    """Generate next incremental map name."""
    existing = GeoMap.query.filter(GeoMap.name.ilike(f"{base_label}%")).all()
    max_idx = 0
    for m in existing:
        try:
            suffix = m.name.replace(base_label, '').strip()
            if suffix:
                num = int(suffix)
                if num > max_idx:
                    max_idx = num
        except Exception:
            continue
    return f"{base_label} {max_idx + 1}"


# =============================================================================
# GeoJSON API Routes (for Pure MapLibre Widget)
# =============================================================================

def _shape_feature_dict(shape):
    """Return the GeoShape.feature column as a dict (JSON column may be str)."""
    feat = shape.feature
    if isinstance(feat, dict):
        return feat
    if isinstance(feat, str) and feat:
        try:
            return json.loads(feat)
        except Exception:
            return {}
    return {}


def _shapes_to_geojson(shape_type, default_color, map_uuid=None):
    """Build a FeatureCollection from GeoShape rows of the given type.

    GeoShape stores the GeoJSON Feature in the `feature` JSON column. The
    hierarchy field is `type` ('site', 'zone', 'feature', 'facility', ...),
    and there is no `name` / `category` column on GeoShape — the human-readable
    name lives inside feature.properties.

    map_uuid, when given, scopes the query to one map's shapes (geo_id).
    Omitting it returns shapes from every map — callers that render onto a
    single map's widget must always pass it, or shapes belonging to other
    maps bleed onto their view (2026-08-09: an "이천시" test shape named
    청와대, located at the real Blue House in Seoul, rendered on the 김제
    widget because this query had no map filter at all).
    """
    query = GeoShape.query.filter_by(type=shape_type)
    if map_uuid:
        query = query.filter_by(geo_id=map_uuid)
    shapes = query.all()
    features = []
    for shape in shapes:
        try:
            feat = _shape_feature_dict(shape)
            geometry = feat.get('geometry')
            if not geometry:
                continue
            props = dict(feat.get('properties') or {})
            props.setdefault('id', shape.unique_id)
            # 도형 uuid 를 **항상** 실어 보낸다. `id` 는 setdefault 라 저장된
            # feature 에 draw id 가 이미 있으면 그것이 남고, MapLibre 는
            # queryRenderedFeatures 에서 문자열 feature.id 를 버린다 — 그래서
            # 도형 클릭이 uuid 를 되찾을 다른 길이 없다.
            props['shape_uuid'] = shape.unique_id
            props.setdefault('name', props.get('name') or '')
            props['category'] = shape_type
            props.setdefault('color', props.get('fill') or default_color)
            features.append({
                'type': 'Feature',
                'id': shape.unique_id,
                'geometry': geometry,
                'properties': props,
            })
        except Exception:
            continue
    return {'type': 'FeatureCollection', 'features': features}


@blueprint.route('/api/geo/sites', methods=['GET'])
@login_required
def api_geo_sites():
    """Get sites as GeoJSON for MapLibre overlay, scoped to ?map_uuid= when given."""
    try:
        return jsonify(_shapes_to_geojson('site', '#DF5353', request.args.get('map_uuid')))
    except Exception as e:
        current_app.logger.exception("api_geo_sites failed")
        return jsonify({'error': str(e)}), 500


@blueprint.route('/api/geo/zones', methods=['GET'])
@login_required
def api_geo_zones():
    """Get zones as GeoJSON for MapLibre overlay, scoped to ?map_uuid= when given."""
    try:
        return jsonify(_shapes_to_geojson('zone', '#28a745', request.args.get('map_uuid')))
    except Exception as e:
        current_app.logger.exception("api_geo_zones failed")
        return jsonify({'error': str(e)}), 500


@blueprint.route('/api/geo/shapes/<string:category>', methods=['GET'])
@login_required
def api_geo_shapes_by_category(category):
    """Get shapes by hierarchy type (site, zone, facility, feature, ...), scoped to ?map_uuid= when given."""
    try:
        return jsonify(_shapes_to_geojson(category, '#995aff', request.args.get('map_uuid')))
    except Exception as e:
        current_app.logger.exception("api_geo_shapes_by_category failed")
        return jsonify({'error': str(e)}), 500


@blueprint.route('/api/geo/zone/<string:zone_uuid>/photo', methods=['POST'])
@login_required
def api_geo_zone_photo(zone_uuid):
    """Zone 대표사진 업로드 (edit_settings 이상). multipart field: photo"""
    import os
    import time as _time
    import uuid as _uuid
    from aot.config import PATH_GEO_ZONE_PHOTOS
    from aot.aot_flask.extensions import db as _db
    from werkzeug.utils import secure_filename

    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    zone = GeoShape.query.filter_by(unique_id=zone_uuid, type='zone').first()
    if not zone:
        return jsonify({'ok': False, 'error': 'zone not found'}), 404

    file = request.files.get('photo')
    if not file or not file.filename:
        return jsonify({'ok': False, 'error': 'photo file required'}), 400

    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
        return jsonify({'ok': False, 'error': 'file type not allowed'}), 400

    unique_filename = '{}_{}'.format(_uuid.uuid4(), filename)
    os.makedirs(PATH_GEO_ZONE_PHOTOS, exist_ok=True)
    file.save(os.path.join(PATH_GEO_ZONE_PHOTOS, unique_filename))

    # dict() 필수 — 제자리 수정은 SQLAlchemy 가 못 본다(rep_key 라우트 주석).
    meta = dict(zone.meta_json or {})
    old_fn = meta.get('photo_filename')
    if old_fn:
        old_path = os.path.join(PATH_GEO_ZONE_PHOTOS, old_fn)
        if os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    photo_url = '/geo_zone_photo/' + unique_filename
    meta['photo_url'] = photo_url
    meta['photo_filename'] = unique_filename
    zone.meta_json = meta
    _db.session.commit()

    from aot.aot_flask.geo.site_summary import invalidate_zone_contents
    invalidate_zone_contents(zone_uuid)
    return jsonify({'ok': True, 'photo_url': photo_url, 'ts': _time.time()})


@blueprint.route('/geo_zone_photo/<path:filename>', methods=['GET'])
@login_required
def serve_geo_zone_photo(filename):
    """Zone 대표사진 서빙."""
    import os
    from flask import send_file, abort
    from aot.config import PATH_GEO_ZONE_PHOTOS

    base = os.path.realpath(PATH_GEO_ZONE_PHOTOS)
    file_path = os.path.realpath(os.path.join(base, filename))
    if not file_path.startswith(base + os.sep) or not os.path.isfile(file_path):
        return abort(404)
    return send_file(file_path)


@blueprint.route('/api/geo/shape/<string:shape_uuid>/description',
                 methods=['POST'])
@login_required
def api_geo_shape_description(shape_uuid):
    """도형(필지·구역)의 설명 — 사람이 적는 한 문단.

    **`meta_json` 에 담는다.** `feature` 가 아닌 이유가 중요하다 — 도형 저장
    (`save_overlays`)은 `feature` 를 통째로 갈아 끼우므로, 거기 두면 지도에서
    도형을 한 번 다시 그리는 것만으로 설명이 사라진다. `meta_json` 은 그 경로가
    건드리지 않는다(실측: `geo_overlays.py` 에 `meta_json` 참조 0건).
    사진(`photo_url`)·대표 측정(`rep_key`)이 이미 같은 자리를 쓴다.

    site 와 zone 이 같은 `GeoShape` 라 **한 라우트가 둘 다 받는다.** 계층마다
    엔드포인트를 따로 두면 같은 검증이 두 벌이 되고, 이 도메인은 그 실패를
    이미 겪었다.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'error': 'Insufficient permission'}), 403

    shape = GeoShape.query.filter_by(unique_id=shape_uuid).first()
    if not shape:
        return jsonify({'ok': False, 'error': 'shape not found'}), 404

    body = request.get_json(force=True, silent=True) or {}
    desc = body.get('description')
    if desc is None:
        return jsonify({'ok': False, 'error': 'description required'}), 422
    desc = str(desc).strip()
    if len(desc) > 2000:
        return jsonify({'ok': False, 'error': 'description too long'}), 422

    # dict() 필수 — 제자리 수정은 SQLAlchemy 가 못 본다(rep_key 라우트 주석).
    meta = dict(shape.meta_json or {})
    if desc:
        meta['description'] = desc
    else:
        meta.pop('description', None)      # 비우면 지운다
    shape.meta_json = meta
    db.session.commit()

    # 필지 요약은 30초 캐시라, 비우지 않으면 방금 적은 설명이 다음 갱신까지
    # 안 보인다("저장했는데 화면이 그대로").
    #
    # 이 도형이 site 면 자기 캐시를, zone 이면 자기 내용 캐시와 **상위 site 의
    # 요약**을 함께 버린다(필지 요약이 자식 이름을 싣는다). `invalidate_rep` 가
    # 같은 이유로 같은 일을 한다 — 전체 `invalidate()` 는 부르지 않는다:
    # `_PARENT_CACHE` 까지 날아가 지도 도형 전량을 다시 훑게 된다.
    try:
        from aot.aot_flask.geo import site_summary
        site_summary.invalidate(shape_uuid)
        site_summary.invalidate_zone_contents(shape_uuid)
        parent = site_summary.parent_site_for_shape(shape_uuid)
        if parent:
            site_summary.invalidate(parent['uuid'])
    except Exception:                                       # noqa: BLE001
        pass
    return jsonify({'ok': True, 'description': desc})


@blueprint.route('/api/geo/zone/<string:zone_uuid>/rep_key', methods=['POST'])
@login_required
def api_geo_zone_rep_key(zone_uuid):
    """구역의 대표 측정 지정 — 현재 블록에서 값을 눌러 정한다.

    도형에 붙인다(`meta_json['rep_key']`). 위젯 옵션에 두면 같은 구역이
    대시보드마다 다른 것을 대표로 내세우고, 지도 라벨·필지 요약·구역 모달이
    서로 다른 값을 말하게 된다.

    `key` 가 비면 지정 해제(우선순위 기본값으로 돌아간다). 값이 실제로
    존재하는 측정인지 검사하지 않는다 — 센서가 잠시 죽어도 지정은 남아야
    하고, `_pick_rep` 이 값이 없을 때만 우선순위로 물러선다.
    """
    from aot.aot_flask.extensions import db as _db

    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    zone = GeoShape.query.filter_by(unique_id=zone_uuid, type='zone').first()
    if not zone:
        return jsonify({'ok': False, 'error': 'zone not found'}), 404

    body = request.get_json(force=True, silent=True) or {}
    key = body.get('key')
    if key is not None and not isinstance(key, str):
        return jsonify({'ok': False, 'error': 'key must be a string or null'}), 422
    key = (key or '').strip() or None

    # dict() 로 **새 객체**를 만든다. meta_json 은 MutableDict 가 아닌 평범한
    # JSON 컬럼이라, 기존 dict 를 제자리에서 고치고 같은 객체를 도로 대입하면
    # SQLAlchemy 가 변경을 못 알아채고 UPDATE 를 아예 내지 않는다 — 에러 없이
    # 저장만 안 된다. meta_json 이 비어 있을 때는 `or {}` 가 새 dict 를 만들어
    # 우연히 동작하므로, 다른 값이 이미 있는 구역에서만 조용히 실패한다.
    meta = dict(zone.meta_json or {})
    if key:
        meta['rep_key'] = key
    else:
        meta.pop('rep_key', None)
    zone.meta_json = meta
    _db.session.commit()

    # 구역 모달·지도 라벨·필지 요약 셋이 이 값을 쓴다 — 하나만 버리면 라벨이
    # 60초 동안 옛 대표를 계속 내건다.
    from aot.aot_flask.geo.site_summary import invalidate_rep
    invalidate_rep(zone)
    return jsonify({'ok': True, 'rep_key': key})


# [현황] 카드에서 뺄 항목 — 항목이 많아지면 화면이 읽히지 않는다. 무엇을 빼도
# 되는지는 그 자리를 쓰는 사람만 안다(노지에 실내 습도 줄, 창이 없는 시설에
# 환기 면적 줄).
#
# `rep_key` 와 **같은 자리·같은 규칙**이다(도형 meta_json). 저장 실패를 조용히
# 넘기지 않도록 카드 이름을 검사한다 — 오타 하나가 아무 데도 안 쓰이는 키를
# 만들어 두면 화면은 계속 전부 보여 주고 사용자는 저장이 안 된 줄 모른다.
def _save_hidden_rows(shape, body):
    """(오류응답, 저장된 목록) — 저장에 성공하면 오류응답이 None."""
    from aot.aot_flask.extensions import db as _db
    from aot.aot_flask.geo.site_summary import (
        hidden_rows_of, _HIDDEN_ROW_CARDS)

    card = (body.get('card') or '').strip()
    if card not in _HIDDEN_ROW_CARDS:
        return jsonify({'ok': False, 'error': 'unknown card'}), 422, None
    keys = body.get('keys')
    if not isinstance(keys, list):
        return jsonify({'ok': False, 'error': 'keys must be a list'}), 422, None
    keys = [k.strip() for k in keys if isinstance(k, str) and k.strip()]

    # dict() 로 새 객체 — 제자리 수정은 SQLAlchemy 가 못 본다(rep_key 주석).
    meta = dict(shape.meta_json or {})
    rows = dict(meta.get('hidden_rows') or {})
    if keys:
        rows[card] = keys
    else:
        # 전부 켠 상태를 빈 목록으로 남기지 않는다 — 기본값(감춘 것 없음)과
        # 같은 뜻이고, 남겨 두면 무엇이 설정된 것인지 읽는 쪽이 매번 판단해야
        # 한다.
        rows.pop(card, None)
    if rows:
        meta['hidden_rows'] = rows
    else:
        meta.pop('hidden_rows', None)
    shape.meta_json = meta
    _db.session.commit()
    return None, None, hidden_rows_of(shape)


@blueprint.route('/api/geo/zone/<string:zone_uuid>/hidden_rows', methods=['POST'])
@login_required
def api_geo_zone_hidden_rows(zone_uuid):
    """구역 [현황] 카드에서 뺄 항목 — 카드 제목 옆 설정에서 정한다."""
    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    zone = GeoShape.query.filter_by(unique_id=zone_uuid, type='zone').first()
    if not zone:
        return jsonify({'ok': False, 'error': 'zone not found'}), 404

    body = request.get_json(force=True, silent=True) or {}
    err, code, rows = _save_hidden_rows(zone, body)
    if err is not None:
        return err, code
    return jsonify({'ok': True, 'hidden_rows': rows})

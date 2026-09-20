# coding=utf-8
"""routes_geo 의 구역·대지 contents·summary·weather·장치 상세 팝업 라우트. blueprint 는 routes_geo 것을 공유한다."""
from flask import current_app, request, jsonify
import math
from flask_login import login_required
from aot.aot_flask.utils import utils_general
from aot.databases.models import GeoShape, Input, Output, PID, Trigger, Conditional, CustomController, Function, DeviceMeasurements
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_geo
from aot.aot_flask.geo.schedule_helpers import pending_schedules
from aot.aot_flask.access import scope
from aot.aot_flask.routes_geo import blueprint  # noqa: E402




def _polygon_area_m2(coords):
    """Shoelace + equirectangular projection for a GeoJSON ring [[lng,lat], ...]."""
    if not coords or len(coords) < 3:
        return 0.0
    R = 6371000.0
    lat0 = sum(c[1] for c in coords) / len(coords)
    cos_lat = math.cos(math.radians(lat0))
    area = 0.0
    n = len(coords)
    for i in range(n):
        x1 = math.radians(coords[i][0]) * cos_lat * R
        y1 = math.radians(coords[i][1]) * R
        x2 = math.radians(coords[(i + 1) % n][0]) * cos_lat * R
        y2 = math.radians(coords[(i + 1) % n][1]) * R
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


@blueprint.route('/api/geo/zone/<string:zone_uuid>/contents', methods=['GET'])
@login_required
def api_geo_zone_contents(zone_uuid):
    """Zone 내부 센서·장치·함수 인벤토리 반환.

    30초 캐시 + 단일 비행(site 요약과 같은 헬퍼). 캐시가 없을 때 로컬 실측
    280ms 였고, 그게 **열 때마다** 나갔다 — 이 응답은 도형 스캔 + 장치별
    DeviceMeasurements + influx 집계라 싸질 수 없다. 사람이 창을 여는
    순간에만 필요한 값이고 30초 안에 달라질 것이 없어서, 계산을 줄이는
    대신 캐시로 덮는 쪽이 맞다. 장치 on/off 는 이 응답이 아니라 별도
    폴링이 따라가므로 캐시가 상태를 늦추지 않는다.

    can_edit 는 권한이라 사용자마다 다르지만 캐시는 전역이다 —
    캐시 밖에서 매번 다시 넣는다(아래).
    """
    from aot.aot_flask.geo.site_summary import cached_zone_contents

    payload = cached_zone_contents(
        zone_uuid, lambda: _build_zone_contents(zone_uuid))
    if payload is None:
        return jsonify({'ok': False, 'error': 'zone not found'}), 404

    payload = dict(payload)
    payload['zone'] = dict(payload['zone'])
    payload['zone']['can_edit'] = utils_general.user_has_permission(
        'edit_settings', silent=True)
    return jsonify(payload)


def _build_area_contents(device_ids, scope_of=None, env=None):
    """장치 참조 집합 → 모달의 인벤토리(센서·장치·기능 + 집계 + 상태).

    **구역 모달과 식생 모달이 이 하나를 함께 쓴다.** 두 벌로 복사하면 같은
    장치를 두 화면이 다르게 세게 되는데, 이 도메인은 정확히 그 실패로 이미
    크게 데었다(`_build_zone_contents` 의 "같은 구역의 센서 수가 화면마다
    달랐다" 주석 참조). 스코프를 정하는 일(어떤 장치가 이 영역의 것인가)은
    호출자가 하고, 여기서는 **정해진 집합을 푸는 일만** 한다.

    `scope_of(unique_id) -> 'plot'|'zone'|None` 를 주면 항목마다 `scope` 를
    붙인다. 식생 모달이 "구획 안의 것" 과 "구역에서 빌려온 것" 을 화면에서
    구분하는 근거다 — 구역 모달은 빌려오는 것이 없으므로 주지 않는다(그러면
    키 자체가 안 붙어 기존 응답 모양이 그대로 유지된다).
    """
    from aot.databases.models import OutputChannel
    from aot.aot_flask.geo.facility_sensors import channel_meta_for_dm

    device_ids = device_ids or set()

    def _scope(uid):
        return {'scope': scope_of(uid)} if scope_of else {}

    # 센서 목록 (Input)
    inputs = (Input.query.filter(Input.unique_id.in_(device_ids)).all()
              if device_ids else [])

    sensors_out = []
    for inp in inputs:
        meas = DeviceMeasurements.query.filter_by(device_id=inp.unique_id).all()
        channels = [channel_meta_for_dm(m) for m in meas]
        row = {
            'unique_id': inp.unique_id,
            'name': inp.name,
            'device': getattr(inp, 'device', ''),
            'is_activated': bool(inp.is_activated),
            'interface': getattr(inp, 'interface', ''),
            'channels': channels,
        }
        row.update(_scope(inp.unique_id))
        sensors_out.append(row)

    # 장치 목록 (Output) — 동일하게 파생만 사용
    outputs_rows = (Output.query.filter(
        Output.unique_id.in_(device_ids)).all()
        if device_ids else [])

    outputs_out = []
    for out in outputs_rows:
        channels = OutputChannel.query.filter_by(output_id=out.unique_id).order_by(OutputChannel.channel).all()
        ch_list = [{'channel': c.channel, 'name': c.name or str(c.channel)} for c in channels]
        if not ch_list:
            ch_list = [{'channel': 0, 'name': out.name}]
        row = {
            'unique_id': out.unique_id,
            'name': out.name,
            'output_type': out.output_type or '',
            'channels': ch_list,
        }
        row.update(_scope(out.unique_id))
        outputs_out.append(row)

    # 함수 목록 (CustomController + Function + Conditional + Trigger + PID)
    # 함수도 지도에 배치되면 마커(device_id=함수 uuid)를 갖는다 — 같은 파생.
    # 복합장치(그릇)는 함수와 같은 테이블에 있지만 성격이 다르다 — Input/Output 을
    # 담는 그릇이지 무언가를 판단하는 규칙이 아니다. 목록에서 섞이면 "이 구역의
    # 기능"에 장치가 끼어 보인다. 가르는 기준은 collect_devices 와 같다.
    try:
        from aot.utils.functions import device_module_names
        _device_names = device_module_names()
    except Exception:
        _device_names = set()

    func_rows = []
    for model, kind in [
        (CustomController, 'custom'),
        (Function,         'function'),
        (Conditional,      'conditional'),
        (Trigger,          'trigger'),
        (PID,              'pid'),
    ]:
        if not device_ids:
            break
        for row in model.query.filter(
                model.unique_id.in_(device_ids)).all():
            row_kind = kind
            if kind == 'custom' and getattr(row, 'device', None) in _device_names:
                row_kind = 'device'
            item = {
                'unique_id': row.unique_id,
                'name': row.name,
                'kind': row_kind,
                'is_activated': bool(getattr(row, 'is_activated', False)),
            }
            item.update(_scope(row.unique_id))
            func_rows.append(item)

    # 현재 환경 — 예전에는 구역 모달 어디에도 "지금 몇 도인가"가 숫자로 없었다.
    # 차트 레전드의 마지막 값에 의존하다 보니, 그래프를 못 읽거나 센서 탭을
    # 넘겨보지 않으면 알 수 없었다. 집계는 필지 요약과 같은 함수를 쓴다 —
    # 한쪽만 고치면 같은 구역이 두 화면에서 다른 온도를 말한다.
    # env 를 이미 계산해 둔 호출자는 넘겨서 **influx 왕복을 한 번 아낀다**.
    # 넘길 수 있는 조건은 하나뿐이다: 그 계산의 대상 집합이 여기 `device_ids`
    # 와 **같은 Input 들을 담을 때**. env 는 Input 만 보므로 Output·Function 이
    # 더 있고 없고는 상관없다(실측: 왕복 1회 약 64ms).
    from aot.aot_flask.geo.site_summary import env_for_devices, status_from
    if env is None:
        try:
            env = env_for_devices(device_ids)
        except Exception:
            current_app.logger.exception("area contents: env aggregation failed")
            env = {'readings': [], 'sensors': {'valid': 0, 'total': 0}}

    # 제목줄 상태 점 — 필지 요약의 행과 같은 판정을 쓴다. env 를 넘겨
    # influx 재조회를 피한다.
    return {
        'sensors': sensors_out,
        'outputs': outputs_out,
        'functions': func_rows,
        'counts': {
            'sensors': len(sensors_out),
            'outputs': len(outputs_out),
            'functions': len(func_rows),
        },
        'env': env,
        'status': status_from(device_ids, env),
    }


def _build_zone_contents(zone_uuid):
    """구역 모달 응답 본체. 못 찾으면 None(캐시에 남기지 않는다)."""
    # 지연 import — routes_geo_shape 를 모듈 최상단에서 가져오면
    # routes_geo_shape ↔ routes_geo_schedule 순환 참조로 죽는다(둘 다
    # routes_geo 의 footer 가 채우는 blueprint 를 거쳐야 한다).
    from aot.aot_flask.routes_geo_shape import _shape_feature_dict

    zone = GeoShape.query.filter_by(unique_id=zone_uuid, type='zone').first()
    if not zone:
        return None

    zone_id = zone.id
    feat = _shape_feature_dict(zone)
    props = feat.get('properties') or {}
    zone_name = props.get('name') or zone.unique_id

    # 면적
    area_m2 = None
    try:
        geom = feat.get('geometry') or {}
        ring = None
        if geom.get('type') == 'Polygon':
            ring = (geom.get('coordinates') or [[]])[0]
        elif geom.get('type') == 'MultiPolygon':
            ring = ((geom.get('coordinates') or [[[]]])[0] or [[]])[0]
        if ring:
            area_m2 = round(_polygon_area_m2(ring), 1)
    except Exception:
        pass

    # 상위 site — 모달의 "상위로" 화살표와 [현황]의 소속 표시에 함께 쓴다.
    # 예전에는 zone.parent_id 만 봤는데 그 컬럼은 운영 데이터에서 전 행이
    # NULL 이라(geo_hierarchy 주석) 소속 줄이 늘 비어 있었다. 공간 포함
    # 관계로 푸는 공용 리졸버로 바꾼다.
    from aot.aot_flask.geo.site_summary import parent_site_for_shape
    try:
        parent_site = parent_site_for_shape(zone.unique_id)
    except Exception:
        current_app.logger.exception("zone contents: parent site lookup failed")
        parent_site = None
    site_name = parent_site['name'] if parent_site else None
    site_uuid = parent_site['uuid'] if parent_site else None

    # ── 소속 판정: 순수 파생 (S3) ────────────────────────────────────────────
    # 과거에는 map_overlay_id 직접 매칭 + 기하 폴백의 합집합이었다. 저장된
    # 컬럼은 복제·zone 재생성·도형 삭제로 끊기거나 남의 지도를 가리켰고
    # (2026-08-03 사고), 합집합은 그 낡은 값으로 엉뚱한 장치까지 끌어왔다.
    # 이제 마커 좌표에서 실시간 파생하는 단일 리졸버만 쓴다 —
    # aot/aot_flask/geo/device_membership.py 가 유일한 정본이다.
    # device_ids_in_area 는 4겹으로 본다: 마커 · 바인딩 · **그릇** · 참조.
    # 예전에는 마커만 보는 device_ids_in_shape 를 썼는데, 그러면
    #  - 복합장치(그릇)가 구역에 놓여 있어도 그 안의 Input/Output 이 빠지고
    #    (실측: 구역 3-1 의 AoT-C 안에 있는 OpenWeather 가 목록에 없었다),
    #  - 마커 없이 바인딩으로만 매인 출력이 통째로 빠진다(출력 16개 중 마커는 1개).
    # 게다가 같은 구역을 두고 지도 라벨·필지 요약(site_summary)은 4겹으로,
    # 이 모달만 1겹으로 세어 **같은 구역의 센서 수가 화면마다 달랐다.**
    # 그래프 구역 필터도 같은 이유로 이미 이쪽으로 옮겼다(b72bc47).
    from aot.aot_flask.geo.device_membership import device_ids_in_area
    geo_device_ids = device_ids_in_area(zone.unique_id) or set()

    inv = _build_area_contents(geo_device_ids)

    # "켜면 무엇이 함께 젖는가" — 식생 모달에만 붙이면 안 된다. 구역에서 켠
    # 밸브도 그 안의 여러 작물에 물을 주므로, 한쪽에만 경고가 있으면
    # "구역에서 켜면 안전하다" 는 잘못된 대비가 생긴다(설계 §5-2).
    try:
        from aot.aot_flask.geo import plot_context
        _cover = plot_context.plots_by_valve_device(zone.geo_id)
        for _out in inv['outputs']:
            names = plot_context.covered_subject_names(
                _cover.get(_out['unique_id']))
            if names:
                _out['also_covers'] = names
    except Exception:
        # 식생이 없는 지도가 정상이다 — 여기서 실패해도 구역 모달은 떠야 한다.
        current_app.logger.exception("zone contents: 관수 교차 계산 실패")

    # 지금 심겨 있는 것 — 농장 지도인데 계층 어디에도 작물이 없었다.
    # 배분 계산(미배정 = **합집합**으로 빼기)은 zone_allocation 이 정본이다.
    allocation = None
    try:
        from aot.aot_flask.geo import plot_context as _pc
        allocation = _pc.zone_allocation(zone)
    except Exception:
        current_app.logger.exception("zone contents: 식생 배분 계산 실패")

    # 다가오는 일정 — 구역 자신을 대상으로 한 농작업(제초·방제 등)과 구역 안
    # 장치의 예약. `target_id` 가 도형 uuid 도 담는다는 것이 근거다.
    schedule = {'own': [], 'devices': []}
    try:
        from aot.aot_flask.geo.site_summary import upcoming_schedule
        schedule = upcoming_schedule(zone, geo_device_ids)
    except Exception:
        current_app.logger.exception("zone contents: 일정 조회 실패")

    sensors_out = inv['sensors']
    outputs_out = inv['outputs']
    func_rows = inv['functions']
    counts = inv['counts']
    env = inv['env']
    zone_status = inv['status']

    from aot.aot_flask.geo.site_summary import rep_key_of, hidden_rows_of

    meta = zone.meta_json or {}
    photo_url = meta.get('photo_url')
    output_order = meta.get('output_order', [])

    # can_edit 는 여기서 넣지 않는다 — 캐시는 전역이라 처음 연 사람의 권한이
    # 다음 사람에게 그대로 간다. 라우트가 응답마다 다시 채운다.
    from aot.aot_flask.geo import irrigation_status, weather_hazards
    # 노지의 마지막 관수 — 이 구역에서 자라는 구획의 프로그램이 "관수" 라고
    # 선언한 함수만 근거다. 영역에 묶인 범용 on/off 를 관수라고 부르지 않는다.
    _irr = None
    try:
        from aot.aot_flask.geo import plot_context as _pc
        for _p in _pc.active_plots(zone.geo_id):
            _irr = irrigation_status.last_irrigation(None, _p)
            if _irr:
                break
    except Exception:                                       # noqa: BLE001
        _irr = None
    return {
        'ok': True,
        'rep_key': rep_key_of(zone),
        # [현황] 카드에서 빼 둔 항목 — 거르는 것은 화면이 한다(site_summary 주석).
        'hidden_rows': hidden_rows_of(zone),
        'irrigation': _irr,
        # 시설과 **같은 판정**(같은 예보 파일) — 노지에서 오히려 더 자주 행동을
        # 부르는 정보다.
        'hazards': weather_hazards.upcoming_cached(),
        'zone': {
            'unique_id': zone.unique_id,
            'name': zone_name,
            'site_name': site_name,
            'site_uuid': site_uuid,
            'area_m2': area_m2,
            'counts': counts,
            'photo_url': photo_url,
            'output_order': output_order,
            'env': env,
            'status': zone_status,
            # 지금 심겨 있는 것. `zone` 안에 두는 이유는 [현황] 탭이 이 객체
            # 하나만 받기 때문이다(buildZoneStatusHtml).
            'allocation': allocation,
            'schedule': schedule,
        },
        'sensors': sensors_out,
        'outputs': outputs_out,
        'functions': func_rows,
    }


@blueprint.route('/api/geo/site/<string:site_uuid>/contents', methods=['GET'])
@login_required
def api_geo_site_contents(site_uuid):
    """필지 안 장치 인벤토리 — 센서·출력. 필지 모달의 [환경·제어]가 쓴다.

    **`_build_area_contents` 를 그대로 쓴다.** 구역 모달·구획 모달이 이미 같은
    함수를 쓰고 있고, 따로 만들면 같은 장치를 화면마다 다르게 세게 된다 —
    이 도메인이 정확히 그 실패로 크게 데었다(그 함수의 docstring 참조).
    여기서 하는 일은 **집합을 정하는 것**뿐이다: 필지 안 구역·시설의 장치.

    `device_ids_in_area` 는 site 도형에도 그대로 동작한다(포함 판정은 종류를
    가리지 않는다).

    ⚠ **시설 안 설비(fitting)에 매인 액추에이터는 뺀다**
    (`include_facility_fittings=False`). 필지 모달에서 시설 안의 측창·도어까지
    늘어놓으면 "이 필지를 어떻게 볼까"가 아니라 "여기서 뭘 다 조작할 수 있나"가
    되어, 정작 필지 단위로 판단할 것이 묻힌다. 설비 액추에이터는 그 시설
    모달에서 본다. 구역 폴리곤·시설 외형에 **직접** 맡긴 장치는 그대로 온다.

    필지 요약(`summary_for_site`)은 이 집합을 쓰지 않는다 — 그쪽은 자식(구역·
    시설)마다 따로 판정한다. 그래서 시설 행의 센서 수는 여기 변경과 무관하게
    자기 설비를 그대로 센다.
    """
    from aot.databases.models import GeoShape as _GS
    from aot.aot_flask.geo.device_membership import device_ids_in_area

    site = _GS.query.filter_by(unique_id=site_uuid).first()
    if not site:
        return jsonify({'ok': False, 'error': 'site not found'}), 404

    inv = _build_area_contents(
        device_ids_in_area(site_uuid, include_facility_fittings=False) or set())

    # "켜면 무엇이 함께 젖는가" — 구역 모달과 같은 경고를 단다. 한쪽에만 있으면
    # "필지에서 켜면 안전하다" 는 잘못된 대비가 생긴다.
    try:
        from aot.aot_flask.geo import plot_context
        _cover = plot_context.plots_by_valve_device(site.geo_id)
        for _out in inv['outputs']:
            names = plot_context.covered_subject_names(
                _cover.get(_out['unique_id']))
            if names:
                _out['also_covers'] = names
    except Exception:                                       # noqa: BLE001
        pass

    payload = {'ok': True}
    payload.update(inv)
    # 권한은 캐시 밖에서 매번(구역과 같은 규칙). 필지에는 구역 전용 쓰기
    # (rep_key·output_order)가 없으므로 제어 권한만 낸다.
    payload['can_edit'] = utils_general.user_has_permission(
        'edit_controllers', silent=True)
    return jsonify(payload)


@blueprint.route('/api/geo/site/<string:site_uuid>/summary', methods=['GET'])
@login_required
def api_geo_site_summary(site_uuid):
    """site(필지) 요약 — 하위 구역·시설 상태 + 오늘 할 일 + 노트.

    zone 은 `/contents` 로 인벤토리를 내지만 site 에는 대응물이 없어, 지도에서
    필지를 눌러도 이름과 면적밖에 볼 게 없었다. 집계 본체는
    aot/aot_flask/geo/site_summary.py 에 있다(정본 설계:
    docs/design/map-site-summary.md).

    `?force=1` 은 30초 캐시를 건너뛴다 — 사람이 새로고침을 누른 경우용.
    """
    from aot.aot_flask.geo import site_summary

    force = request.args.get('force') in ('1', 'true', 'yes')
    try:
        payload = site_summary.summary_for_site(site_uuid, force=force)
    except Exception as e:
        current_app.logger.exception("api_geo_site_summary failed")
        return jsonify({'ok': False, 'error': str(e)}), 500

    if payload is None:
        return jsonify({'ok': False, 'error': 'site not found'}), 404

    result = {'ok': True}
    result.update(payload)
    # 권한은 **캐시 밖에서 매번** 채운다(구역 모달과 같은 규칙) — 요약 자체는
    # 30초 캐시라, 안에 넣으면 권한이 바뀌어도 30초 동안 옛 값이 나간다.
    if isinstance(result.get('site'), dict):
        result['site'] = dict(result['site'])
        result['site']['can_edit'] = utils_general.user_has_permission(
            'edit_settings', silent=True)
    return jsonify(result)


@blueprint.route('/api/geo/site/<string:site_uuid>/weather',
                 methods=['GET', 'POST'])
@login_required
def api_geo_site_weather(site_uuid):
    """대지의 **기상대 지정** — 읽기(GET)와 저장(POST).

    ## 왜 지정이 필요한가

    일사·강우는 대지에 하나 있는 기상대가 재고 구획마다 따로 재지 않는다.
    그래서 구획 화면이 그 값을 보려면 대지의 기상대를 알아야 하는데, 지금까지
    그것을 **측정값 이름으로 추론**하고 있었다(`WEATHER_MARKER_MEASUREMENTS`).
    추론은 아무도 설정을 만지지 않은 설치에서도 값이 보이게 하는 안전망이지만,
    대지에 일사계가 둘이거나 실험용 센서가 섞이면 **사람이 바로잡을 수단이
    없었다.** 여기가 그 수단이다.

    지정이 있으면 지정이 이긴다. 지우면 추론으로 되돌아간다 — 비활성이 아니라
    **지정 전 상태**다.
    """
    from aot.aot_flask.geo import device_binding, device_membership
    from aot.databases.models import GeoShape

    shape = GeoShape.query.filter_by(unique_id=site_uuid).first()
    if shape is None:
        return jsonify({'ok': False, 'error': 'site not found'}), 404

    if request.method == 'GET':
        selected, source = device_membership.weather_device_ids(site_uuid)
        return jsonify({
            'ok': True,
            'source': source,
            'selected': selected,
            'candidates': device_membership.weather_candidates(site_uuid),
            'can_edit': utils_general.user_has_permission(
                'edit_settings', silent=True),
        })

    # ── 저장 ────────────────────────────────────────────────────────────
    # 조작 권한은 그 도형이 놓인 **지도**로 판정한다 — 대지는 지도의 최상위
    # 도형이라 자기 스코프 자원이 따로 없다(`geo_map` 이 정본).
    if not scope.can_operate('geo_map', shape.geo_id):
        return jsonify({'ok': False, 'error': scope.deny_message()}), 403
    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    data = request.get_json(silent=True) or {}
    # ⚠ 키가 **아예 없는 요청**과 "빈 목록으로 해제" 를 가른다. 없는 것을
    #   해제로 읽으면 화면의 다른 실수(조회 실패로 목록을 못 채운 상태에서
    #   저장) 하나가 지정을 통째로 지운다 — 스코프 부여 화면이 같은 함정을
    #   겪었고, 거기서 배운 규칙이다.
    if 'device_ids' not in data:
        return jsonify({'ok': False, 'error': 'device_ids is required'}), 400
    ids = data.get('device_ids')
    if not isinstance(ids, list):
        return jsonify({'ok': False, 'error': 'device_ids must be a list'}), 400

    try:
        created, ended = device_binding.set_site_weather(
            site_uuid, ids, commit=True)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('api_geo_site_weather save failed')
        return jsonify({'ok': False, 'error': str(e)}), 400

    selected, source = device_membership.weather_device_ids(site_uuid)
    return jsonify({'ok': True, 'created': created, 'ended': ended,
                    'source': source, 'selected': selected})


@blueprint.route('/api/geo/device/<string:device_uuid>/detail', methods=['GET'])
@login_required
def api_geo_device_detail(device_uuid):
    """장치 상세 모달용 묶음 — 정체·소속·상태·작동 시간.

    마커의 소형 팝업은 "지도 위에서 빠른 제어"라는 고유 가치가 있어 그대로
    두고(팝업 높이가 커지면 anchor 계산이 깨진다), 이력·소속·노트처럼 파고드는
    정보는 이 응답으로 중앙 모달이 받는다.
    """
    from aot.databases.models import (
        CustomController, DeviceMeasurements, Function, Input, Output,
        OutputChannel)
    from aot.aot_flask.geo.site_summary import (
        parent_area_for_device, status_from)

    channel = request.args.get('channel', '0')

    name = kind = None
    for model, label in ((Input, 'input'), (Output, 'output'),
                         (CustomController, 'custom'), (Function, 'function')):
        row = model.query.filter_by(unique_id=device_uuid).first()
        if row is not None:
            name, kind = row.name, label
            break
    if kind is None:
        return jsonify({'ok': False, 'error': 'device not found'}), 404

    # 복합장치(Device)는 CustomController 와 같은 테이블에 있다 — 가르는 기준은
    # 행이 아니라 그 행의 device 모듈이 is_device 를 선언했는지다
    # (device_module_names 가 유일한 판정처, collect_devices 와 같은 규칙).
    if kind == 'custom':
        try:
            from aot.utils.functions import device_module_names
            if getattr(row, 'device', None) in device_module_names():
                kind = 'device'
        except Exception:
            current_app.logger.debug('device_module_names lookup failed')

    # 개폐형(3-way)인가. 지도 마커가 쓰는 판정과 **같은 집합**을 본다
    # (utils_geo.THREE_WAY_OUTPUT_TYPES = PAIRED_ACTUATOR_OUTPUT_TYPES).
    # 이걸 안 보내면 모달이 개폐 3버튼 대신 ON/OFF 토글을 그린다 — 창문을
    # 여닫는 장치에 켜기/끄기 스위치가 달린다.
    control_kind = 'on_off'
    if kind == 'output':
        output_type = getattr(row, 'output_type', None)
        try:
            from aot.outputs.paired_actuator_common import (
                PAIRED_ACTUATOR_OUTPUT_TYPES)
            if output_type in PAIRED_ACTUATOR_OUTPUT_TYPES:
                control_kind = 'value_3way'
        except Exception:
            current_app.logger.debug('paired actuator type lookup failed')

        # PWM(듀티) 출력이면 켜기/끄기가 아니라 0~100% 를 정하는 장치다.
        # 판정은 출력 모듈이 선언한 채널 타입으로 한다 — output_type 이름으로
        # 넘겨짚으면 모듈이 늘 때마다 여기를 고쳐야 한다.
        # 모듈 import 가 실패하는 환경(GPIO 없는 컨테이너 등)에서는 조용히
        # on_off 로 남는다. 잘못된 UI 를 그리느니 기본형이 낫다.
        if control_kind == 'on_off' and output_type:
            try:
                from aot.utils.outputs import parse_output_information
                info = (parse_output_information() or {}).get(output_type) or {}
                types = set()
                for ch in (info.get('channels_dict') or {}).values():
                    types.update(ch.get('types') or [])
                if 'pwm' in types:
                    control_kind = 'pwm'
            except Exception:
                current_app.logger.debug('output module type lookup failed')

    # 복합장치는 그릇이다 — 안에 든 Input/Output 이 곧 이 장치의 내용물이다.
    # 그릇만 보여 주면 "이 장치가 무엇을 재고 무엇을 움직이는가"를 알 수 없다.
    children = []
    if kind == 'device':
        for model, label in ((Input, 'input'), (Output, 'output')):
            for child in model.query.filter_by(
                    parent_device_id=device_uuid).order_by(model.name).all():
                children.append({'uuid': child.unique_id,
                                 'name': child.name,
                                 'kind': label})

    # 채널 목록 — Input 은 측정 채널, Output 은 출력 채널.
    channels = []
    if kind == 'input':
        for dm in DeviceMeasurements.query.filter_by(
                device_id=device_uuid).order_by(DeviceMeasurements.channel).all():
            channels.append({'channel': dm.channel,
                             'name': dm.name or dm.measurement or ''})
    elif kind == 'output':
        for oc in OutputChannel.query.filter_by(
                output_id=device_uuid).order_by(OutputChannel.channel).all():
            channels.append({'channel': oc.channel,
                             'name': oc.name or str(oc.channel)})

    runtime = {'elapsed_sec': None, 'last_duration_sec': None,
               'next_schedule': None, 'schedules': []}
    if kind in ('output', 'function', 'custom'):
        from aot.utils import runtime as _runtime
        try:
            runtime['elapsed_sec'] = _runtime.get_elapsed_seconds(
                device_uuid, channel) or None
        except Exception:
            pass
        if not runtime['elapsed_sec']:
            try:
                runtime['last_duration_sec'] = _runtime.get_last_duration(
                    device_uuid, channel) or None
            except Exception:
                pass
        # 모달의 '예약 상황' 블록은 이 목록을 그대로 그린다 — 라벨과 같은
        # 조회에서 나와야 한쪽만 갱신되는 순간이 없다.
        runtime['schedules'] = pending_schedules(device_uuid)
        runtime['next_schedule'] = (runtime['schedules'][0]['start']
                                    if runtime['schedules'] else None)

    return jsonify({
        'ok': True,
        'device': {'uuid': device_uuid, 'name': name, 'kind': kind,
                   'channel': channel, 'channels': channels,
                   'children': children, 'control_kind': control_kind},
        'parent': parent_area_for_device(device_uuid),
        'status': status_from({device_uuid}),
        'runtime': runtime,
    })

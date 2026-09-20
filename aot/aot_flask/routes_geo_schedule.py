# coding=utf-8
"""routes_geo 의 예약 CRUD·현지시간·일출몰·함수 활성화·기상청 조회·프로그램 페이지 라우트.
blueprint 는 routes_geo 것을 공유한다."""
from flask import render_template, redirect, url_for, current_app, request, jsonify
import json
import os
from flask_login import login_required
from flask_babel import gettext as _
from aot.aot_flask.utils import utils_general
from aot.databases.models import GeoShape, PID, Trigger, Conditional, CustomController, Function
from aot.aot_flask.extensions import db
from aot.aot_flask.routes_geo import blueprint  # noqa: E402



@blueprint.route('/api/tools/kma_lookup', methods=['POST'])
@login_required
def api_tools_kma_lookup():
    """
    Find Nearest KMA Grid (nx, ny) for given Lat/Lon.
    Uses Nearest Neighbor Search on pre-processed JSON lookup.
    """
    try:
        data = request.get_json()
        user_lat = float(data.get('lat'))
        user_lon = float(data.get('lon'))
        
        # Path to lookup JSON
        json_path = os.path.join(current_app.static_folder, 'json', 'kma_grid_lookup.json')
        
        if not os.path.exists(json_path):
            return jsonify({'ok': False, 'message': 'Lookup data not found'}), 500
            
        with open(json_path, 'r', encoding='utf-8') as f:
            grid_data = json.load(f)
            
        # Nearest Neighbor Search
        min_dist = float('inf')
        nearest_point = None
        
        for point in grid_data:
            # Euclidean distance squared (lat diff^2 + lon diff^2)
            dist = (user_lat - point['lat'])**2 + (user_lon - point['lon'])**2
            
            if dist < min_dist:
                min_dist = dist
                nearest_point = point
                
        if nearest_point:
            return jsonify({
                'ok': True,
                'nx': nearest_point['nx'],
                'ny': nearest_point['ny'],
                'lat': nearest_point['lat'],
                'lon': nearest_point['lon']
            })
        else:
            return jsonify({'ok': False, 'message': 'No matching grid found'}), 404

    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500


# ============================================================
# Programs (관리 프로그램) Route
# ============================================================

@blueprint.route('/geo/programs')
@login_required
def page_programs():
    """설정 > 프로그램 — 관리 프로그램 목록·편집.

    **식생은 대상 중 하나일 뿐이다.** 같은 구조("무엇을, 어떤 단계로, 어떤
    목표로")가 가축·시설물·도로에도 그대로 쓰이므로, 이 화면은 종류(`kind`)를
    가진 프로그램 전체를 다룬다.

    프로그램은 **지도에 속하지 않는 전역 자원**이다(대상의 단계·기간·목표는 어느
    지도에서 쓰든 같다). 그래서 지도 선택 없이 열린다.

    목록·편집은 클라이언트가 `/api/geo/program*` 로 한다 — 서버 렌더 폼을
    또 만들면 같은 검증이 두 벌이 되고, 이 도메인은 그 실패를 이미 겪었다.

    탭은 input 페이지(`routes_input.page_input`)와 같은 방식으로 다룬다 —
    `?tab_id=` 로 현재 탭을 고르고, 레거시(탭 도입 전) 행의 `tab_id IS NULL`
    은 여기서 기본 탭으로 지연 백필한다. 마이그레이션이 이 백필을 하지 않는
    이유는 `alembic_db/.../p6_49_program_tab_20260821.py` 참조.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return redirect(url_for('routes_general.home'))

    from aot.databases.models import GeoProgram
    from aot.services.tab_service import TabService

    tab_id = request.args.get('tab_id', None)
    # 조작할 수 없는 탭은 목록에서 뺀다(그룹 스코프). 정보 격리가 아니다.
    tabs = TabService.visible_tabs_for_page('program')
    current_tab = (TabService.get_tab_by_id(tab_id) if tab_id else None)
    if current_tab is not None and current_tab not in tabs:
        current_tab = None          # URL 로 지정된 스코프 밖 탭
    current_tab = current_tab or TabService.default_visible_tab('program')

    # ⚠ **탭이 하나도 없으면 여기서 만든다.** 이 화면의 편집은 전부 탭을 전제로
    # 하는데(프로그램 행은 `tab_id` 를 갖는다), 새 설치에는 program 탭이 없다 —
    # 다른 페이지는 장치를 **추가할 때** `get_default_tab` 이 만들지만 이 화면의
    # 생성은 클라이언트 API 라 그 경로를 지나지 않는다. 그래서 처음 여는 사람은
    # 탭도 없고 아래 백필도 못 돌아, 이름조차 저장되지 않는 화면을 본다(2026-08-23
    # koat 실측: 사용자가 손으로 탭을 만들자 그때부터 동작했다).
    #
    # **보이는 탭이 없다는 것과 탭이 없다는 것은 다르다** — 그룹 스코프로 남의
    # 탭만 가려진 경우까지 여기서 새 탭을 만들면, 그 사람에게 만들 권한이 없는데도
    # 자원이 늘어난다. 그래서 `get_tabs_for_page`(전체)로 판정한다.
    if current_tab is None and not TabService.get_tabs_for_page('program'):
        TabService.get_default_tab('program')
        tabs = TabService.visible_tabs_for_page('program')
        current_tab = TabService.default_visible_tab('program')

    if current_tab:
        null_count = GeoProgram.query.filter(GeoProgram.tab_id.is_(None)).count()
        if null_count:
            default_tab = TabService.get_default_tab('program')
            GeoProgram.query.filter(GeoProgram.tab_id.is_(None)) \
                .update({'tab_id': default_tab.unique_id})
            db.session.commit()
            tabs = TabService.visible_tabs_for_page('program')

    return render_template('pages/geo/programs.html',
                           active_page='geo_programs',
                           tabs=tabs,
                           current_tab_id=(current_tab.unique_id
                                          if current_tab else None))



# ── 일정: 네 계층 공통 ──────────────────────────────────────────────────────
#
# 대지·구역·식생·시설이 **같은 창(지금부터)·같은 목록**을 쓴다. 예전에는
# 대지만 "오늘 N건" 숫자였고 구역·식생은 목록, 시설은 아예 없었다 — 창이
# 달라서 **대지가 0인데 구역을 열면 내일 일이 있는** 상태가 실제로 났다
# (실측: 3포장 '오늘 0' / 3-2 구역 8/19 08:00 제초). 위 계층이 아래를 덮지
# 못하면 롤업이라고 부를 수 없다.

@blueprint.route('/api/geo/schedule/<string:target_id>', methods=['GET'])
@login_required
def api_schedule_for_target(target_id):
    """이 대상(도형·구획)에 걸린 다가오는 일정."""
    payload = _schedule_payload(target_id)
    if payload is None:
        return jsonify({'ok': False, 'message': 'target not found'}), 404
    return jsonify(dict(payload, ok=True))


def _schedule_payload(target_id):
    """대상 종류를 가려 `upcoming_schedule` 을 부른다. 못 찾으면 None.

    **"그 안에서 일어나는 일" 전부다.** 예전에는 site 만 직속 자식 도형까지
    보고 zone 은 자기 것만 봤으며, 식생은 `GeoShape` 가 아니라 어느 층위에서도
    빠졌다. 그 결과 화면과 AI 가 **다른 답**을 했다 — 실측(2026-08-18 김제):
    구역 '3-1' 모달은 예정 0건인데 `search_schedule('3-1')` 은 2건(그 안 식생의
    드론 점검·지게차)이었고, '3포장' 은 1건 대 7건이었다. 사용자가 방금 만든
    예정이 그 구역 화면에 안 보였다.

    이제 AI 도구와 **같은 헬퍼**(`descendant_target_ids`)를 쓴다. 두 벌로 두면
    한쪽만 고쳐지고, 그 어긋남은 "AI 는 아는데 화면은 모른다" 로 나타난다.

      plot  구획에 **닿는** 장치만(구획 안 + 겹치는 장치 영역) — 최하위라
                자손이 없고, 별도 경로(`_plot_schedule`)가 맡는다.
    """
    from aot.aot_flask.geo import device_membership
    from aot.aot_flask.geo.site_summary import upcoming_schedule
    from aot.utils.geo_hierarchy import descendant_target_ids

    shape = GeoShape.query.filter_by(unique_id=target_id).first()
    if shape is not None:
        ids = device_membership.device_ids_in_area(shape.unique_id) or set()
        try:
            kids, _bd = descendant_target_ids(shape, include_self=False)
        except Exception:
            kids = []
            current_app.logger.exception('schedule: 자손 조회 실패')
        return upcoming_schedule(shape, ids, kids)

    from aot.databases.models import GeoPlot
    row = GeoPlot.query.filter_by(unique_id=target_id).first()
    if row is not None:
        from aot.aot_flask.routes_geo_plot import _plot_schedule
        return _plot_schedule(row)

    # 시설은 GeoFacility 이고 도형(GeoShape)이 따로 있다 — 도형으로 옮겨 푼다.
    from aot.databases.models import GeoFacility
    fac = GeoFacility.query.filter_by(unique_id=target_id).first()
    if fac is not None:
        sh = GeoShape.query.filter_by(
            unique_id=getattr(fac, 'shape_uuid', None)).first()
        if sh is not None:
            ids = device_membership.device_ids_in_area(sh.unique_id) or set()
            # 시설 uuid 도 대상에 넣는다 — 일정·노트는 GeoFacility uuid 로
            # 붙는데 장치·기하는 도형 쪽이라, 도형만 보면 방금 만든 일정이
            # 그 시설 화면에서 안 보인다.
            try:
                kids, _bd = descendant_target_ids(sh, include_self=False)
            except Exception:
                kids = []
            return upcoming_schedule(sh, ids, list(kids) + [fac.unique_id])
        return {'own': [], 'devices': []}
    return None


@blueprint.route('/api/geo/schedule', methods=['POST'])
@login_required
def api_schedule_create():
    """어느 계층에든 일정 하나를 만든다.

    본문: `{target_id, date:'YYYY-MM-DD', time:'HH:MM', content, worker?}`

    **대상은 uuid 로 온다** — 이름으로 고르지 않는다. 이름 리졸버는 같은
    작물이 두 구역에 있을 때 하나를 골라버리는 문제가 있어 구역을 돌려주도록
    정해져 있고(설계 §이름 해석), 이 경로는 사람이 그 모달을 열어 놓고 쓰므로
    고를 것이 없다.

    `action_type='human'` 이라 장치를 움직이지 않는다(APScheduler 트리거 없음).

    **지도 모달은 더 이상 이 경로를 쓰지 않는다**(2026-08-18). 예정을 만드는
    자리는 노트 하나로 모았다 — 노트 본문의 한 구간을 골라 시각을 주면
    `/notes/<id>/schedule` 이 같은 헬퍼(`_create_human_schedule`)를 부른다.
    이 라우트는 API 계약으로 남긴다. **여기에 기대어 새 UI 를 만들지 말 것** —
    화면에 두 번째 입력 경로가 생기는 순간 "쓰기 전에 종류 고르기" 로 되돌아간다.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403

    data = request.get_json(silent=True) or {}
    target_id = (data.get('target_id') or '').strip()
    content = (data.get('content') or '').strip()
    date_str = (data.get('date') or '').strip()
    if not target_id:
        return jsonify({'ok': False, 'message': 'target_id required'}), 400
    if not content:
        return jsonify({'ok': False, 'message': _('Enter what to do')}), 400
    if not date_str:
        return jsonify({'ok': False, 'message': _('Enter a date')}), 400

    label, kind = _schedule_target_label(target_id)
    if label is None:
        return jsonify({'ok': False, 'message': 'target not found'}), 404

    return _create_human_schedule(
        target_id, kind, label, date_str,
        (data.get('time') or '').strip(),
        content, (data.get('worker') or '').strip())


def _create_human_schedule(target_id, kind, label, date_str, time_str,
                           content, worker):
    """사람이 만든 예정 하나. (flask 응답, 상태코드) 를 돌려준다.

    `/api/geo/schedule`(지도 모달)과 `/notes/<id>/schedule`(노트 구간 선택)이
    **함께 쓴다** — 두 벌로 두면 `propose_job` 의 자가승인 같은 함정을 한쪽
    에서만 지키게 된다.
    """
    time_str = time_str or '09:00'

    from aot.tools.aot_data_tool_service import AoTDataToolService as _T
    from aot.ai.services.ai_scheduler_service import AISchedulerService

    anchor_tz, anchor_name, anchor_src = _T._resolve_schedule_anchor(target_id)
    try:
        run_at = _T._schedule_wall_to_utc(date_str, time_str, anchor_tz=anchor_tz)
    except Exception as exc:
        return jsonify({'ok': False,
                        'message': '날짜/시각 형식이 올바르지 않습니다 (%s)' % exc}), 400

    params = {'content': content, 'worker': worker, 'target_type': kind,
              'target_name': label, 'tags': 'human_work'}
    try:
        # ⚠ `propose_job` 은 proposed_by='HUMAN' 이고 승인이 필요 없으면
        # **스스로 approve_job 까지 부른다.** 뒤에서 또 부르면 "not in DRAFT
        # state" 로 죽는데, 행은 이미 만들어진 뒤라 사용자는 "저장 실패" 를
        # 보면서 일정은 생겨 있다(실제로 그렇게 나갔다).
        meta = AISchedulerService.propose_job(
            action_type='human', target_id=target_id, params=params,
            reasoning='[human_schedule] %s @ %s | tags: human_work' % (content, label),
            schedule_time=run_at, proposed_by='HUMAN',
            approval_required=False, source_type='human',
            # 발화 시 스코프를 다시 묻기 위한 신원(§8-7). 'human' 예약은
            # 장치를 움직이지 않지만, 소유자를 남기는 규칙은 예약 종류마다
            # 갈리지 않아야 한다 — 갈리면 어느 종류가 검사되는지 세야 한다.
            user_id=utils_general.current_user_id())
        meta.anchor_tz = anchor_name
        meta.anchor_source = anchor_src
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('schedule: 생성 실패')
        return jsonify({'ok': False, 'message': str(exc)}), 500

    # 방금 만든 것이 바로 보여야 한다 — 모달들이 30초 캐시를 다시 읽는다.
    try:
        from aot.aot_flask.geo.site_summary import (
            invalidate_plot_contents, invalidate_zone_contents_all,
            invalidate)
        invalidate_plot_contents(None)
        invalidate_zone_contents_all()
        invalidate()
    except Exception:
        pass

    return jsonify({'ok': True, 'kind': 'schedule', 'job_id': meta.unique_id,
                    'schedule': _schedule_payload(target_id)})


def _schedule_target_label(target_id):
    """(사람이 읽을 이름, 종류) 또는 (None, None)."""
    from aot.databases.models import GeoFacility, GeoPlot
    # 지연 import — routes_geo_shape 를 모듈 최상단에서 가져오면
    # routes_geo_shape ↔ routes_geo_schedule 순환 참조로 죽는다(둘 다
    # routes_geo 의 footer 가 채우는 blueprint 를 거쳐야 한다).
    from aot.aot_flask.routes_geo_shape import _shape_feature_dict

    shape = GeoShape.query.filter_by(unique_id=target_id).first()
    if shape is not None:
        props = (_shape_feature_dict(shape).get('properties') or {})
        return props.get('name') or target_id, shape.type
    row = GeoPlot.query.filter_by(unique_id=target_id).first()
    if row is not None:
        return row.subject or row.name or target_id, 'plot'
    fac = GeoFacility.query.filter_by(unique_id=target_id).first()
    if fac is not None:
        return getattr(fac, 'name', None) or target_id, 'facility'
    return None, None


@blueprint.route('/api/geo/function/<string:kind>/<string:func_uuid>/activate', methods=['POST'])
@login_required
def api_geo_function_activate(kind, func_uuid):
    """함수(CustomController/Conditional/Trigger/PID/Function) 활성 토글."""
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    data = request.get_json(force=True, silent=True) or {}
    active = bool(data.get('active', True))

    try:
        from aot.aot_flask.utils import (
            utils_controller, utils_conditional, utils_pid, utils_trigger,
        )
        if kind == 'custom':
            msgs = (utils_controller.controller_activate(func_uuid) if active
                    else utils_controller.controller_deactivate(func_uuid))
        elif kind == 'conditional':
            msgs = (utils_conditional.conditional_activate(func_uuid) if active
                    else utils_conditional.conditional_deactivate(func_uuid))
        elif kind == 'pid':
            msgs = (utils_pid.pid_activate(func_uuid) if active
                    else utils_pid.pid_deactivate(func_uuid))
        elif kind == 'trigger':
            msgs = (utils_trigger.trigger_activate(func_uuid) if active
                    else utils_trigger.trigger_deactivate(func_uuid))
        elif kind == 'function':
            # Function 타입은 별도 activate util 없음 — DB 직접 갱신 후 데몬 reload
            row = Function.query.filter_by(unique_id=func_uuid).first()
            if not row:
                return jsonify({'ok': False, 'error': 'not found'}), 404
            row.is_activated = active
            db.session.commit()
            msgs = [{'success': True}]
        else:
            return jsonify({'ok': False, 'error': 'unknown kind'}), 422

        success = any(getattr(m, 'get', lambda k, d=None: d)('success', False)
                      if hasattr(m, 'get') else bool(m)
                      for m in (msgs or []))
        return jsonify({'ok': True, 'active': active, 'success': success})
    except Exception as e:
        current_app.logger.exception("api_geo_function_activate failed")
        return jsonify({'ok': False, 'error': str(e)}), 500




# ──────────────────────────────────────────────────────────────────────────
# 지도 중심의 현지 시각 — 지도 위젯 상단 시간 독이 쓰는 유일한 서버 경로.
#
# 지도는 세계 어디로든 간다. 그러면 "지금 몇 시인가"는 농장의 시간대가 아니라
# **화면 한가운데가 있는 곳의 시간대**로 답해야 한다. 그 판정(좌표→IANA)과
# 태양시 계산은 이미 서버에 하나씩 있으므로(device_tz.resolve_tz_from_coords,
# solar.sun_times) 여기서는 그 둘을 묶어 내보내기만 한다 — 클라이언트가 다시
# 추측하면 시스템 안에 시간대 해석이 두 벌 생긴다.
#
# 시계는 이 응답으로 **초당 폴링하지 않는다.** tz 이름을 받아 브라우저가
# Intl 로 직접 째깍이고, 서버는 좌표가 의미 있게 바뀌거나 현지 날짜가 넘어갈
# 때만 다시 불린다. server_epoch_ms 는 그 째깍임의 기준점 — 브라우저 시계가
# 틀어져 있어도 서버 시각을 따라가게 하는 보정값이다.
# ──────────────────────────────────────────────────────────────────────────
# 좌표 반올림 자릿수. 3자리 ≈ 110m — 그 거리에서 일출/일몰 차이는 1초 미만이라
# 표시에 영향이 없고, solar/device_tz 양쪽 캐시의 적중률만 올라간다.
_LOCAL_TIME_COORD_ROUND = 3


@blueprint.route('/api/geo/local_time', methods=['GET'])
@login_required
def api_geo_local_time():
    """지도 중심 좌표의 현지 시각·시간대·태양시를 반환.

    쿼리: lat, lng (필수).
    응답: tz / tz_abbrev / utc_offset_minutes / server_epoch_ms / local_date
          + status + sunrise_ms / sunset_ms + events(어제~모레의 일출·일몰,
          시각 오름차순 — 독이 직전/다음 사건을 여기서 고른다).

    극야·백야는 오류가 아니라 status('always_day' / 'always_night')로 나간다.
    좌표에서 시간대를 못 찾으면(바다 한가운데 등) 농장 전역 tz 로 떨어지고
    tz_resolved=false 로 알린다 — 표시 쪽이 그걸 밝힐 수 있어야 한다.
    """
    from datetime import timedelta

    from aot.utils.device_tz import resolve_tz_from_coords
    from aot.utils.solar import (EVENT_SUNRISE, EVENT_SUNSET, STATUS_UNKNOWN,
                                 sun_times)
    from aot.utils.timekit import as_tz, system_tz, utc_now

    try:
        lat = round(float(request.args.get('lat')), _LOCAL_TIME_COORD_ROUND)
        lng = round(float(request.args.get('lng')), _LOCAL_TIME_COORD_ROUND)
    except (TypeError, ValueError):
        return jsonify({'error': 'lat and lng are required'}), 400
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return jsonify({'error': 'lat/lng out of range'}), 400

    tz_name = resolve_tz_from_coords(lat, lng)
    tzinfo = as_tz(tz_name) if tz_name else system_tz()
    now = utc_now()
    local_now = now.astimezone(tzinfo)
    offset = local_now.utcoffset()

    times = sun_times(latitude=lat, longitude=lng)

    def _ms(dt):
        return int(dt.timestamp() * 1000) if dt is not None else None

    # 독은 현재 시각을 가운데 두고 **직전 사건은 왼쪽, 다음 사건은 오른쪽**에
    # 놓는다. 그러려면 오늘치 일출/일몰만으로는 모자라다: 자정 직후의 직전
    # 사건은 어제 일몰이고, 일몰 직후의 다음 사건은 내일 일출이다. 어제부터
    # 모레까지 한 벌을 보내면 클라이언트는 자정을 넘겨도 목록 안에서 계속
    # 고를 수 있어, 사건이 지날 때마다 서버를 다시 부르지 않아도 된다.
    events = []
    base_date = local_now.date()
    for day_offset in (-1, 0, 1, 2):
        day = sun_times(latitude=lat, longitude=lng,
                        date=base_date + timedelta(days=day_offset))
        if day is None:
            continue
        for kind in (EVENT_SUNRISE, EVENT_SUNSET):
            at = day.event(kind)
            if at is not None:
                events.append({'kind': kind, 'at': _ms(at)})
    events.sort(key=lambda e: e['at'])

    return jsonify({
        'tz': str(tzinfo),
        'tz_resolved': bool(tz_name),
        'tz_abbrev': local_now.strftime('%Z'),
        'utc_offset_minutes': int(offset.total_seconds() // 60) if offset else 0,
        'server_epoch_ms': int(now.timestamp() * 1000),
        'local_date': local_now.date().isoformat(),
        'status': times.status if times else STATUS_UNKNOWN,
        'sunrise_ms': _ms(times.sunrise) if times else None,
        'sunset_ms': _ms(times.sunset) if times else None,
        'events': events,
        'day_length_seconds': times.day_length_seconds if times else None,
    })


# ──────────────────────────────────────────────────────────────────────────
# 장치/도형(target_id)이 상속하는 위치의 오늘 일출·일몰 — 시계 휠의 "일출/일몰
# 으로 설정" 버튼이 쓰는 유일한 서버 경로. 좌표 해석은 timekit.resolve_coords
# (도형 → 소속 도형 상속 → 장치 자신의 좌표 → 농장 전역) 그대로 쓰고, 태양시
# 계산은 solar.sun_times 를 그대로 쓴다 — 새 캐시를 만들지 않는다. 둘 다 이미
# 좌표+날짜 단위로 캐시돼 있어 같은 장소의 여러 장치가 물어도 astral 재계산은
# 한 번뿐이다.
# ──────────────────────────────────────────────────────────────────────────
@blueprint.route('/api/geo/sun_event', methods=['GET'])
@login_required
def api_geo_sun_event():
    """target_id 가 상속하는 위치의 오늘 일출·일몰을 현지 벽시계 초로 반환.

    쿼리: target_id(필수) — 장치/도형/함수 등의 unique_id.
    응답: ok, status(normal/always_day/always_night/unknown),
          sunrise_seconds / sunset_seconds(현지 자정 기준 초, 없으면 None).
    """
    from aot.utils.device_tz import resolve_tz_from_coords
    from aot.utils.solar import STATUS_UNKNOWN, sun_times
    from aot.utils.timekit import as_tz, resolve_coords, system_tz, utc_now

    target_id = request.args.get('target_id')
    if not target_id:
        return jsonify({'ok': False, 'error': 'target_id is required'}), 400

    lat, lon, _source = resolve_coords(None, target_id=target_id)
    if lat is None or lon is None:
        return jsonify({'ok': False, 'status': STATUS_UNKNOWN, 'error': 'no_location'})

    tz_name = resolve_tz_from_coords(lat, lon)
    tzinfo = as_tz(tz_name) if tz_name else system_tz()
    local_date = utc_now().astimezone(tzinfo).date()
    times = sun_times(latitude=lat, longitude=lon, date=local_date)
    if times is None:
        return jsonify({'ok': False, 'status': STATUS_UNKNOWN, 'error': 'no_data'})

    def _seconds_of_day(dt):
        if dt is None:
            return None
        local = dt.astimezone(tzinfo)
        return local.hour * 3600 + local.minute * 60 + local.second

    return jsonify({
        'ok': True,
        'status': times.status,
        'sunrise_seconds': _seconds_of_day(times.sunrise),
        'sunset_seconds': _seconds_of_day(times.sunset),
    })

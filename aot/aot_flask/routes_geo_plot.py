# coding=utf-8
"""식생 구획(작기) API 라우트 — routes_geo 의 서브모듈.

routes_geo.py 맨 아래에서 import 되어 공유 blueprint 에 등록된다
(routes_geo_iec / routes_geo_commissioning 과 같은 방식).

설계 정본: docs/design/geo-vegetation-plot.md
"""
import logging
from datetime import datetime

from flask import request, jsonify, current_app
from flask_login import current_user, login_required

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import plot_context, plot_io, plot_split
from aot.aot_flask.utils import utils_general
from aot.databases.models import GeoPlot, GeoShape
from aot.aot_flask.routes_geo import blueprint  # noqa: E402

logger = logging.getLogger(__name__)


def _require_edit():
    """쓰기 권한 확인 — 없으면 응답 튜플, 있으면 None.

    **작기 운영 권한(`edit_plots`)으로 연다** (p6_51). 예전에는 `edit_settings`
    였는데, 그러면 작기 기록만 맡기려 해도 장치·시설·네트워크 설정까지 함께
    열어야 했다. `edit_settings` 는 이 권한을 함의하므로 기존 Admin·Editor 의
    동작은 그대로다.

    구획 라우트 9곳이 이 헬퍼 하나를 쓴다 — 게이트를 각자 적으면 한 곳만
    빠뜨려도 그 경로가 조용히 열린다.
    """
    if not utils_general.user_has_permission('edit_plots'):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403
    return None


def _parse_on(value):
    """?on=YYYY-MM-DD → date | None. 형식이 틀리면 None(=오늘)으로 떨어진다."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


# ── 목록 ───────────────────────────────────────────────────────────────────

@blueprint.route('/api/geo/programs', methods=['GET'])
@login_required
def api_programs():
    """재배 프로그램 목록 — 구획에서 고를 선택지.

    대상별로 **품종본이 기본을 이긴다**(같은 대상에 품종본이 있으면 그것을 먼저
    보여준다). 정렬은 대상 → 품종 순이라 화면이 안정적이다.

    `subject`(옛 이름 `crop`)로 좁힐 수 있다.
    """
    from aot.databases.models import GeoProgram

    subject = (request.args.get('subject') or request.args.get('crop')
               or '').strip() or None
    # 대상 종류로 좁힌다 — 식생 구획은 `vegetation` 만 봐야 가축·시설물 프로그램이
    # 작물 선택지에 섞이지 않는다.
    kind = (request.args.get('kind') or '').strip() or None
    # geo/program 화면의 탭 필터 — 호출하는 쪽(bay/facility 폼)은 이 파라미터를
    # 안 쓰므로 안 넘기면 지금까지처럼 전체가 나온다.
    tab_id = (request.args.get('tab_id') or '').strip() or None
    q = GeoProgram.query
    if kind:
        q = q.filter(GeoProgram.kind == kind)
    if subject:
        q = q.filter(GeoProgram.subject == subject)
    if tab_id:
        q = q.filter(GeoProgram.tab_id == tab_id)
    rows = q.order_by(GeoProgram.subject.asc(),
                      GeoProgram.variety.asc()).all()

    # 목록·상세가 같은 형태를 쓰도록 한 함수로 낸다 — 두 벌로 두면 화면이
    # 어느 쪽에서 왔는지에 따라 다른 키를 보게 된다.
    from aot.aot_flask.geo import program_io
    items = [program_io.to_dict(r, with_stages=False) for r in rows]
    return jsonify({'ok': True, 'programs': items, 'count': len(items)})


@blueprint.route('/api/geo/program/<string:program_uuid>', methods=['GET'])
@login_required
def api_program_get(program_uuid):
    """프로그램 상세 — 단계 목록까지. 화면이 "몇 단계 중 몇" 을 그릴 근거다."""
    from aot.databases.models import GeoProgram

    row = GeoProgram.query.filter_by(unique_id=program_uuid).first()
    if row is None:
        return jsonify({'ok': False, 'message': 'program not found'}), 404
    # 목록과 **같은 함수**로 낸다 — 두 벌로 두면 화면이 어느 쪽에서 왔는지에 따라
    # 다른 키를 보게 된다(실제로 `target_methods` 가 상세에서만 빠져 있었다).
    from aot.aot_flask.geo import program_io
    return jsonify({'ok': True, 'program': program_io.to_dict(row)})


@blueprint.route('/api/geo/target-methods', methods=['GET'])
@login_required
def api_target_methods():
    """목표 곡선으로 걸 수 있는 Method 목록.

    Method 는 AoT 가 이미 갖고 있는 **시간축 곡선**이다. 프로그램의 목표에 걸면
    단계별 계단 대신 전 주기에 걸쳐 변하는 목표가 된다.

    새 Method 를 여기서 만들지 않는다 — 만드는 화면(설정 > 메서드)이 따로 있고,
    거기서 곡선을 그리는 편이 훨씬 낫다.
    """
    from aot.databases.models import Method

    rows = Method.query.order_by(Method.name.asc()).all()
    return jsonify({'ok': True, 'methods': [
        {'unique_id': m.unique_id, 'name': m.name,
         'method_type': m.method_type} for m in rows]})


@blueprint.route('/api/geo/target-measurements', methods=['GET'])
@login_required
def api_target_measurements():
    """목표 항목이 고를 수 있는 **측정 종류** 목록.

    `config_devices_units.MEASUREMENTS` 를 그대로 낸다 — 센서·그래프가 이미 쓰는
    어휘이고, 목표가 여기에 붙어야 "이 목표를 재는 센서가 이 구획에 있는가" 를
    답할 수 있다. 새 어휘를 지어내면 그 연결이 영영 수동이 된다.

    **고르지 않아도 된다.** 물리량이 없는 항목(AoT 가 뜻을 모르는 값)은 표시·조언
    전용으로 남고, 그것도 정상이다 — 사람이 관리하는 값이 전부 센서로 잡히는
    시설은 드물다.
    """
    from aot.config_devices_units import MEASUREMENTS

    out = [{'key': k,
            'name': (v.get('name') or k),
            'units': list(v.get('units') or [])}
           for k, v in MEASUREMENTS.items()]
    out.sort(key=lambda x: (x['name'] or '').lower())

    # 종류별 고정 항목도 함께 낸다 — 화면이 **저장하지 않고** 종류를 바꿔 볼 때
    # 새 종류의 항목 목록을 스스로 세울 수 있어야 한다. 없으면 축사로 바꾼 순간
    # 식생 여섯 항목이 화면에 남아 있다가 저장할 때에야 사라진다.
    from aot.aot_flask.geo import program_io
    fixed = {}
    for kind in program_io.VALID_KINDS:
        fixed[kind] = [program_io._public_target_def(dict(d, fixed=True,
                                                          hidden=False))
                       for d in program_io.fixed_target_defs(kind)]
    return jsonify({'ok': True, 'measurements': out, 'count': len(out),
                    'fixed_defs': fixed})


@blueprint.route('/api/geo/coordinator/<string:function_uuid>/plot-targets',
                 methods=['GET'])
@login_required
def api_coordinator_plot_targets(function_uuid):
    """이 코디네이터가 지금 따르는 구획과 그 단계 목표 (**읽기 전용**).

    제어도 같은 값을 읽는다(`coordinator_plot.control_targets`) — 화면과 제어가
    다른 경로로 계산하면 곧 갈라지고, 그 갈라짐은 "화면에는 맞는데 안 그렇게
    돈다" 로만 드러난다.
    """
    from flask_babel import gettext
    from aot.aot_flask.geo import coordinator_plot
    from aot.databases.models import CustomController

    fn = CustomController.query.filter_by(unique_id=function_uuid,
                                          device='env_coordinator').first()
    if fn is None:
        return jsonify({'ok': False, 'message': 'Coordinator not found'}), 404

    data = coordinator_plot.display_state(
        fn, on=_parse_on(request.args.get('on')))

    # 라벨은 서버가 붙인다 — 화면이 각자 들고 있으면 항목을 늘릴 때 한쪽만
    # 늘어난다. 항목 정의가 이미 라벨을 갖고 오므로(`unmapped`) 여기서는 정의가
    # 닿지 않는 축(`gdd_daily` 는 단계가 아니라 photosynthesis 에서 온다)과
    # 제어 축 이름만 채운다.
    labels = {
        'vpd': 'VPD', 'co2': gettext('CO2'), 'dli': gettext('DLI'),
        'gdd_daily': gettext('GDD'),
    }
    for r in (data.get('targets') or []) + (data.get('unmapped') or []):
        # 사용자가 만든 항목은 자기 이름을 갖고 온다 — 덮어쓰지 않는다.
        if not r.get('label'):
            r['label'] = labels.get(r['key'], r['key'])

    # 곡선은 이름으로 보인다 — uuid 는 사람이 읽을 것이 아니다.
    ids = [r['method_id'] for r in (data.get('targets') or []) if r.get('method_id')]
    if ids:
        from aot.databases.models import Method
        names = {m.unique_id: m.name
                 for m in Method.query.filter(Method.unique_id.in_(ids)).all()}
        for r in data['targets']:
            if r.get('method_id'):
                r['method_name'] = names.get(r['method_id'])

    # 기준 구획 지정 버튼을 낼지는 **서버가 정한다** — 화면이 권한을 스스로
    # 판단하면 곧 갈라지고, 그 갈라짐은 "눌러도 403" 으로만 드러난다.
    data['can_pick'] = utils_general.user_has_permission(
        'edit_settings', silent=True)

    data['ok'] = True
    data['function'] = {'unique_id': fn.unique_id, 'name': fn.name,
                        'is_activated': bool(fn.is_activated)}
    return jsonify(data)


@blueprint.route('/api/geo/coordinator/<string:function_uuid>/reference-plot',
                 methods=['POST'])
@login_required
def api_coordinator_set_reference_plot(function_uuid):
    """기준 구획을 지정한다(R4 — 후보가 둘 이상일 때).

    구획이 겹치는 것은 정상이라(간작·혼작) 후보가 둘 이상일 때 서버가 임의로
    고르지 않는다. 이 지정이 그 답이고, 제어는 다음 사이클부터 그 구획의 단계
    목표를 따른다 — 값을 복사해 두지 않으므로 여기서 옮길 것은 없다.
    """
    import json as _json
    from aot.databases.models import CustomController

    denied = _require_edit()
    if denied:
        return denied

    fn = CustomController.query.filter_by(unique_id=function_uuid,
                                          device='env_coordinator').first()
    if fn is None:
        return jsonify({'ok': False, 'message': 'Coordinator not found'}), 404

    plot_uuid = (request.get_json(silent=True) or {}).get('plot_uuid') or ''
    plot_uuid = str(plot_uuid).strip()
    if plot_uuid and GeoPlot.query.filter_by(unique_id=plot_uuid).first() is None:
        return jsonify({'ok': False, 'message': 'Plot not found'}), 404

    try:
        opts = _json.loads(fn.custom_options) if fn.custom_options else {}
    except (TypeError, ValueError):
        opts = {}
    opts['source_plot_id'] = plot_uuid
    fn.custom_options = _json.dumps(opts)
    db.session.commit()
    return jsonify({'ok': True, 'source_plot_id': plot_uuid})


@blueprint.route('/api/geo/program-templates', methods=['GET'])
@login_required
def api_program_templates():
    """템플릿 카탈로그 — **DB 에 깔려 있지 않은** 예시 목록.

    내장 프로그램을 미리 넣지 않는 대신, 필요할 때 여기서 골라 자기 것으로
    만든다. 목록에 남의 작물이 먼저 들어차 있지 않게 하려는 것이다 — AoT 는
    농장 전용이 아니고, 대부분의 사용자는 이 중 한둘만 쓴다.
    """
    try:
        from aot.scripts.seed_programs import catalog
        items = [{
            'key': t['key'], 'name': t['name'], 'subject': t['subject'],
            'kind': t.get('kind'),
            # scope 로 화면이 "카테고리에서 넓게 시작" 과 "작물별로 정확하게
            # 시작" 을 나눠 보여줄 수 있다 — category 는 소속 작물종 키를
            # (members), species 는 소속 카테고리 키를(category) 함께 싣는다.
            'scope': t.get('scope', 'species'),
            'category': t.get('category'),
            'members': t.get('members'),
            'stage_count': len(t['stages']),
            'has_targets': any(st.get('targets') for st in t['stages']),
        } for t in catalog()]
    except Exception as exc:
        current_app.logger.warning('[CropProgram] 카탈로그 로드 실패: %s', exc)
        items = []
    return jsonify({'ok': True, 'templates': items, 'count': len(items)})


@blueprint.route('/api/geo/program', methods=['POST'])
@login_required
def api_program_create():
    """새 프로그램. 사람이 만든 것은 항상 `source='user'` 다 —
    화면에서 내장/외부를 사칭할 수 있으면 "출처가 신뢰를 정한다" 가 무너진다."""
    denied = _require_edit()
    if denied:
        return denied
    from aot.aot_flask.geo import program_io
    data = request.get_json(silent=True) or {}

    # 템플릿에서 시작 — 카탈로그의 단계·목표를 그대로 복사해 **내 것**으로 만든다.
    # 복사이므로 나중에 템플릿이 바뀌어도 내 프로그램은 그대로다.
    tkey = (data.get('template_key') or '').strip()
    if tkey:
        try:
            from aot.scripts.seed_programs import catalog
            tpl = next((t for t in catalog() if t['key'] == tkey), None)
        except Exception:
            tpl = None
        if tpl is None:
            return jsonify({'ok': False,
                            'message': 'template not found: %s' % tkey}), 400
        data = dict(data)
        data.setdefault('name', tpl['name'])
        data.setdefault('subject', tpl['subject'])
        data.setdefault('kind', tpl.get('kind', 'vegetation'))
        data.setdefault('stages', tpl['stages'])
        data.setdefault('photosynthesis', tpl['photosynthesis'])
        # 근거. 템플릿에 **출처가 붙은 단계 지침**이 실려 있으면 그 출처까지
        # 함께 남긴다 — 지침만 남고 출처가 사라지면, 나중에 그 말을 고칠 사람이
        # 판단할 재료가 없다(create_program 이 AI 에게 source_note 를 요구하는
        # 것과 같은 이유). 지침이 없으면 예전과 똑같은 한 줄이다.
        #
        # 번역하지 않는다 — `source_note` 는 DB 에 남는 **데이터**라, 만든 사람의
        # 언어로 굳으면 다른 언어 사용자에게는 영영 그 언어로 보인다. 기존
        # `template:<key>` 와 같은 기계 표지를 쓴다(출처 본문은 적은 사람의 말
        # 그대로다).
        _gsrc = tpl.get('guidance_sources') or []
        data.setdefault('source_note',
                        'template:%s' % tkey if not _gsrc else
                        'template:%s · guidance-source: %s'
                        % (tkey, ' / '.join(_gsrc)))
        # 카테고리 템플릿은 "이건 중앙값입니다, 실제에 맞게 고치세요" 를
        # notes 에 담아 둔다 — 만든 프로그램에도 그대로 남아야 사람이 나중에
        # 이걸 조사된 값으로 오해하지 않는다.
        if tpl.get('notes'):
            data.setdefault('notes', tpl['notes'])

    result, error = program_io.create_program(data, source='user')
    if error:
        return jsonify({'ok': False, 'message': error}), 400
    return jsonify({'ok': True, 'program': result})


@blueprint.route('/api/geo/program/<string:program_uuid>/clone',
                 methods=['POST'])
@login_required
def api_program_clone(program_uuid):
    """복제 — 내장·외부를 고치는 유일한 경로."""
    denied = _require_edit()
    if denied:
        return denied
    from aot.aot_flask.geo import program_io
    result, error = program_io.clone_program(
        program_uuid, request.get_json(silent=True) or {})
    if error:
        status = 404 if '찾을 수 없' in error else 400
        return jsonify({'ok': False, 'message': error}), status
    return jsonify({'ok': True, 'program': result})


@blueprint.route('/api/geo/program/<string:program_uuid>',
                 methods=['POST', 'PUT'])
@login_required
def api_program_update(program_uuid):
    """수정. 내장·외부는 서버가 거절한다(복제해서 고친다)."""
    denied = _require_edit()
    if denied:
        return denied
    from aot.aot_flask.geo import program_io
    result, error = program_io.update_program(
        program_uuid, request.get_json(silent=True) or {})
    if error:
        status = 404 if '찾을 수 없' in error else 400
        return jsonify({'ok': False, 'message': error}), status
    return jsonify({'ok': True, 'program': result})


@blueprint.route('/api/geo/program/<string:program_uuid>',
                 methods=['DELETE'])
@login_required
def api_program_delete(program_uuid):
    """삭제. 쓰는 구획이 있으면 거절한다 — 그 작기가 근거를 잃는다."""
    denied = _require_edit()
    if denied:
        return denied
    from aot.aot_flask.geo import program_io
    result, error = program_io.delete_program(program_uuid)
    if error:
        status = 404 if '찾을 수 없' in error else 400
        return jsonify({'ok': False, 'message': error}), status
    return jsonify(result)


@blueprint.route('/api/geo/plots', methods=['GET'])
@login_required
def api_plots_list():
    """지도의 식생 구획 목록.

    기본은 **재배 중인 것만** 준다. 종료된 작기까지 기본으로 실으면 몇 년 지난
    지도에서 목록도 렌더도 옛 두둑으로 뒤덮인다 — 이력은 요청해야 온다
    (`include_ended=1`).

    `facility_uuid` 로 시설 하나의 구획만 받을 수 있다(시설 편집기용).
    """
    # `map_uuid` 는 **선택**이다. 없으면 전체 지도 — 운영 페이지(`/plots`)가
    # "이번 철에 무엇을 어디에 심었나" 를 한눈에 보려면 지도 경계를 넘어야
    # 한다. 지도 위젯은 계속 자기 지도만 넘긴다.
    map_uuid = request.args.get('map_uuid') or None

    on = _parse_on(request.args.get('on'))
    include_ended = request.args.get('include_ended') in ('1', 'true', 'True')
    # 시작일이 아직 오지 않은 구획(계획). **기본은 끈다** — 이 엔드포인트를
    # 지도 레이어가 그대로 쓰고 있어서, 켜 두면 아직 심지 않은 것이 지도에
    # 그려진다. 목록 화면(`/plots`)만 켜서 부른다.
    include_planned = request.args.get('include_planned') in ('1', 'true', 'True')
    # 시설 편집기가 자기 시설의 구획만 받기 위한 필터. 지도 전체를 받아
    # 클라이언트에서 거르면 시설 하나를 여는 데 지도 전량이 실린다.
    facility_uuid = request.args.get('facility_uuid') or None

    if include_ended:
        q = GeoPlot.query
        if map_uuid:
            q = q.filter_by(geo_id=map_uuid)
        rows = q.order_by(GeoPlot.started_on.desc()).all()
    else:
        rows = plot_context.active_plots(map_uuid, on=on,
                                         include_planned=include_planned)
    if facility_uuid:
        rows = [r for r in rows if r.facility_uuid == facility_uuid]

    # 컨테이너를 한 번만 준비한다 — 구획마다 다시 훑으면 지도 도형 전량
    # 스캔이 행 수만큼 반복된다.
    #
    # 전체 조회(map_uuid 없음)에서는 **지도별로** 한 벌씩 만든다. 하나로 합치면
    # 다른 지도의 zone 이 이 구획을 품은 것으로 잡힌다 — 좌표가 겹치는 지도가
    # 실제로 있다(같은 농장을 두 지도로 보는 구성).
    from aot.aot_flask.geo import device_membership
    container_cache = {}

    def _containers_for(gid):
        if gid not in container_cache:
            container_cache[gid] = device_membership.load_containers(gid)
        return container_cache[gid]

    # 시설 조회도 같은 이유로 한 벌만 — 시설 구획마다 GeoFacility+GeoShape 를
    # 다시 읽으면 행 수만큼 반복된다.
    facilities = {}

    items = [plot_context.to_dict(r, containers=_containers_for(r.geo_id),
                                     facilities=facilities) for r in rows]
    # 지도 이름 — 전체 조회에서는 "어느 지도의 구획인가" 가 목록의 핵심 축이다.
    # 항목마다 GeoMap 을 다시 읽지 않도록 한 번에 만든다.
    map_names = {}
    try:
        from aot.databases.models import GeoMap
        for m in GeoMap.query.all():
            map_names[m.unique_id] = m.name or m.unique_id
    except Exception:                                       # noqa: BLE001
        map_names = {}
    for it in items:
        it['map_name'] = map_names.get(it.get('geo_id'))
    return jsonify({'ok': True, 'plots': items, 'count': len(items)})


@blueprint.route('/api/geo/plot/<string:plot_uuid>', methods=['GET'])
@login_required
def api_plot_get(plot_uuid):
    row = GeoPlot.query.filter_by(unique_id=plot_uuid).first()
    if row is None:
        return jsonify({'ok': False, 'message': 'plot not found'}), 404

    # 자동 승인(P7)은 **여기서만** 판정한다 — 구획 하나를 읽는 자리다.
    #
    # 목록 조회에 넣지 않는 이유: 지도 한 장이 수십 구획이라 목록 읽기가 그만큼
    # 쓰기를 하게 된다. 늦게 기록돼도 내용은 같으므로(날짜를 자료에서 되짚는다)
    # 급할 것이 없다.
    plot_io.auto_advance_stage(plot_uuid)

    out = plot_context.to_dict(row, with_sensors=True)
    # 권한은 캐시 밖에서 매번 채운다(`api_plot_contents` 와 같은 규칙).
    #
    # `can_edit` 는 이 구획을 고칠 수 있는가이고, `can_design` 은 **설계 화면
    # (geo/facility·geo/programs)에 갈 수 있는가**다. 지금은 둘 다 `edit_settings`
    # 라 값이 같지만 의미가 다르다 — 화면이 "여기서 설정합니다" 링크를 보일지
    # 정하는 것은 후자다. 권한 없는 사람에게 그 링크를 보이면 눌러도 리다이렉트만
    # 되고, 무엇이 잘못됐는지 알 길이 없다.
    out['can_edit'] = utils_general.user_has_permission(
        'edit_plots', silent=True)
    out['can_design'] = utils_general.user_has_permission(
        'edit_settings', silent=True)
    out['schedule'] = _plot_schedule(row)
    return jsonify({'ok': True, 'plot': out})


def _plot_schedule(row):
    """구획의 다가오는 일정 — **이 구획에 닿는 것만**.

    ⚠ **[현황] 탭은 이 응답(상세 조회)으로 그려진다.** `/contents` 는
    [환경·제어] 전용이라, 거기 넣으면 API 에는 값이 있는데 화면에는 안 뜬다 —
    실제로 그렇게 만들어 놓고 테스트까지 통과했다(테스트가 "contents 에 필드가
    있는가" 를 봤기 때문이다). 어느 응답이 어느 탭을 그리는지 먼저 볼 것.

    구역 장치까지 넣지 않는다 — 없앤 "구역 패널의 복사본" 이 일정 쪽으로
    되살아난다. 구획 자신을 대상으로 한 이벤트도 함께 본다(지금은 그런 일정을
    만드는 경로가 없어 늘 비지만, 빼 두면 경로가 생겼을 때 화면만 조용히 못
    따라간다).
    """
    from aot.aot_flask.geo import device_membership
    from aot.aot_flask.geo.site_summary import upcoming_schedule

    try:
        geom = plot_context.geometry_of(row)
        plot = set(device_membership.device_ids_in_geometry(
            row.geo_id, geom, _label='plot %s' % row.unique_id) or [])
        valves = {v['device_id'] for v in plot_context.valves_for_plot(row)
                  if v.get('device_id')}
        return upcoming_schedule(row, plot | valves)
    except Exception:
        current_app.logger.exception('plot detail: 일정 조회 실패')
        return {'own': [], 'devices': []}


@blueprint.route('/api/geo/plot/<string:plot_uuid>/contents',
                 methods=['GET'])
@login_required
def api_plot_contents(plot_uuid):
    """식생 구획 모달의 [환경·제어] 인벤토리 — 구역 모달과 **같은 모양**.

    본체는 구역과 공유한다(`_build_area_contents`). 두 벌로 만들면 같은 장치를
    두 화면이 다르게 세게 되고, 이 도메인은 이미 그 실패로 크게 데었다.

    ⚠ 이 응답은 **소유가 아니라 참조**다. 구획은 컨테이너가 아니므로
    (`device_membership._CONTAINER_TYPES` 에 넣지 말 것 — 설계 §256) 여기 실린
    장치는 "이 구획의 것" 이 아니라 "이 구획을 다루려면 손대는 것" 이다.
    그래서 항목마다 `scope` 로 **왜 여기 보이는지**를 함께 낸다.

    캐시는 구역과 같은 30초. can_edit 는 권한이라 캐시 밖에서 매번 채운다.
    """
    from aot.aot_flask.geo.site_summary import cached_plot_contents

    payload = cached_plot_contents(
        plot_uuid, lambda: _build_plot_contents(plot_uuid))
    if payload is None:
        return jsonify({'ok': False, 'error': 'plot not found'}), 404

    payload = dict(payload)
    payload['plot'] = dict(payload['plot'])
    payload['plot']['can_edit'] = utils_general.user_has_permission(
        'edit_plots', silent=True)
    return jsonify(payload)


def _env_of(input_ids):
    """센서 묶음의 현재 환경 — `{'readings', 'sensors': {'valid','total'}}`.

    `valid > 0` 이면 **지금 값을 주고 있다**는 뜻이다. 판정을 `env_for_devices`
    하나로 하는 이유: 필지 요약·구역 모달이 "센서 응답 2/3" 을 셀 때 쓰는 것과
    같은 함수여야 한다. 여기서 따로 세면 같은 센서를 두고 한 화면은 살아 있다
    하고 다른 화면은 죽었다 한다.

    조회가 실패하면 **살아 있는 것으로 본다**(`valid`를 1로). 실패를 "죽었다"
    로 읽으면 인플럭스가 잠깐 흔들릴 때마다 화면이 옆 구획 센서로 갈아탄다.
    """
    if not input_ids:
        return {'readings': [], 'sensors': {'valid': 0, 'total': 0}}
    from aot.aot_flask.geo.site_summary import env_for_devices
    try:
        return env_for_devices(input_ids)
    except Exception:
        current_app.logger.exception('plot contents: 센서 신선도 판정 실패')
        return {'readings': [], 'sensors': {'valid': 1, 'total': 1}}


def _program_targets(row):
    """프로그램이 정한 목표 — 판정은 `coordinator_plot` 이 한다(어휘 한 곳)."""
    from aot.aot_flask.geo import coordinator_plot
    return coordinator_plot.program_targets(row)


def _program_limits(row):
    """프로그램이 정한 한계 — 판정은 `coordinator_plot` 이 한다(어휘 한 곳)."""
    from aot.aot_flask.geo import coordinator_plot
    return coordinator_plot.program_limits(row)


def _inherited_hidden_rows(facility_uuid=None, zone_uuid=None):
    """[현황] 카드에서 뺄 항목 — **구획은 자기 것을 갖지 않고 물려받는다.**

    구획의 [현재]에 뜨는 값은 구획이 가진 것이 아니다. 시설 구획이면 그 동·
    시설의 센서고, 노지 구획이면 그 구역의 센서다(`sensors_for_plot`). 같은
    센서인데 창을 옮겼다고 다른 항목이 보이면, 사용자는 두 화면 중 어느 쪽이
    맞는지 알 방법이 없다.

    **저장은 상위에만 있다.** 구획에 자기 설정을 두면 구획마다 한 벌씩 생겨,
    한 시설에 작기가 열 개면 같은 결정을 열 번 해야 한다 — 그리고 작기가 끝나면
    그 결정이 함께 사라진다. `rep_key` 를 구획 창에 넘기지 않는 것과 같은
    판단이다(그쪽은 아예 쓰지도 않는다).

    출처는 **값이 실제로 오는 쪽**이다 — 시설 구획은 시설, 노지 구획은 구역.
    시설 구획도 `zone_uuid` 를 가질 수 있지만(시설이 구역 안에 있으면), 그
    구역은 값을 주지 않으므로 기준이 될 수 없다.
    """
    from aot.aot_flask.geo import site_summary
    if facility_uuid:
        return site_summary.hidden_rows_for_facility(facility_uuid)
    return site_summary.hidden_rows_for_shape(zone_uuid)


def _program_methods(row):
    """목표가 곡선인 항목 — 판정은 `coordinator_plot` 이 한다(어휘 한 곳)."""
    from aot.aot_flask.geo import coordinator_plot
    return coordinator_plot.program_target_methods(row)


def _sensor_order_key(item):
    """값을 주는 것 → 구획 안 → 가까운 것 순."""
    return (1 if item.get('no_data') else 0,
            0 if item.get('scope') == 'plot' else 1,
            item.get('distance_m') if item.get('distance_m') is not None else 0,
            item.get('name') or '')


def _involvement_key(item):
    """관여도 정렬 키 — 높을수록 위. `sort()` 용이라 **작을수록 앞**으로 뒤집는다.

    관여도의 정의:
      * 덮는 비율(`coverage_pct`)이 있으면 그 값. 측정된 정도라 가장 강한 근거다.
      * 없고 구획 안에 있으면(`plot`) 100 — 구획 전체를 상대한다고 본다.
        비율은 밸브에만 있는 개념이라, 구획 안의 팬·조명에는 잴 것이 없다.
      * 구획 밖에서 적시는데 비율이 없으면 0.
      * `nearest` 는 **직접 관여가 아니다** — 항상 맨 아래로 보내고, 그 안에서만
        가까운 순으로 둔다.
    """
    scope = item.get('scope')
    if scope == 'nearest':
        # 관여도 축 밖. 거리가 가까울수록 앞.
        return (1, item.get('distance_m') if item.get('distance_m') is not None
                else float('inf'), item.get('name') or '')

    pct = item.get('coverage_pct')
    if pct is None:
        pct = 100.0 if scope == 'plot' else 0.0
    return (0, -float(pct), item.get('name') or '')


def _classify_devices(device_ids):
    """장치 id 집합 → `{'inputs','outputs','functions'}` 로 나눈 집합들.

    종류별 폴백("센서가 하나도 없으면 가장 가까운 센서")을 하려면 어느 것이
    센서인지 **미리** 알아야 한다. id 만 뽑는 가벼운 조회 3번이다.
    """
    from aot.databases.models import (Conditional, CustomController, Function,
                                      Input, Output, Trigger, PID)

    if not device_ids:
        return {'inputs': set(), 'outputs': set(), 'functions': set()}

    ids = list(device_ids)

    def _pick(model):
        return {r[0] for r in model.query.with_entities(
            model.unique_id).filter(model.unique_id.in_(ids)).all()}

    funcs = set()
    for model in (CustomController, Function, Conditional, Trigger, PID):
        funcs |= _pick(model)
    return {'inputs': _pick(Input), 'outputs': _pick(Output),
            'functions': funcs}


def _build_facility_plot_contents(row):
    """시설 구획의 [환경·제어] — 기하가 아니라 **부모**로 스코프를 정한다.

    노지 경로(아래)는 전부 기하에 기대고 있다: 폴리곤 안의 마커, 밸브와의 면적
    교차, 가장 가까운 장치. 시설 구획에 그것을 그대로 돌리면 **파생 기하**(구역
    또는 시설 외피)로 마커를 세게 되어, 시설 어딘가에 있는 장치가 전부 이 구획의
    것으로 잡힌다 — 파생값을 사실처럼 쓰는 순간이다.

    대신 구역 → 시설 순으로 좁은 쪽부터 모은다(`facility_sensor_ids` ·
    `facility_control_for_plot` 와 같은 규칙). `scope` 어휘도 그쪽과 같은
    `'bay' | 'facility'` 다 — 화면이 "이건 이 동 것" 과 "온실 공통" 을 구분해
    말할 수 있어야 한다.
    """
    from aot.aot_flask.routes_geo import _build_area_contents

    sensors = plot_context.sensors_for_plot(row)
    control = plot_context.facility_control_for_plot(row)

    scope = {}
    for uid in (sensors.get('in_bay') or []):
        scope[uid] = 'bay'
    for uid in (sensors.get('from_facility') or []):
        scope.setdefault(uid, 'facility')
    for a in control.get('actuators') or []:
        if a.get('output_id'):
            scope[a['output_id']] = a.get('scope') or 'facility'
    for c in control.get('coordinators') or []:
        scope[c['function_id']] = c.get('scope') or 'facility'

    inv = _build_area_contents(set(scope), scope_of=lambda uid: scope.get(uid))

    fac = control.get('facility') or {}
    bay = control.get('bay') or {}
    return {
        'ok': True,
        'plot': {
            'unique_id': row.unique_id,
            'kind': row.kind or 'vegetation',
            'subject': row.subject,
            'variety': row.variety,
            'name': row.name,
            # 면적·치수는 시설에서 낼 수 없는 값이다(위 to_dict 주석 참조).
            'area_m2': None,
            'dims': None,
            'days_since_planted': plot_context.elapsed_days(row),
            'days_to_expected_end': plot_context.days_to_expected_end(row),
            'active': row.is_active(),
            'facility_uuid': fac.get('unique_id'),
            'facility_name': fac.get('name'),
            'bay_id': bay.get('id'),
            'bay_name': bay.get('name'),
            'zone_uuid': sensors.get('zone_uuid'),
            'zone_name': sensors.get('zone_name'),
            # 그 도형이 실제로 무엇인지 — 'zone' | 'site'. 화면이 어느 창을
            # 열지 정하는 근거다(`sensors_for_plot` 주석 참조).
            'zone_kind': sensors.get('zone_kind'),
            # 카드에서 뺄 항목 — 시설의 설정을 그대로 쓴다(위 주석).
            'hidden_rows': _inherited_hidden_rows(
                facility_uuid=fac.get('unique_id')),
            'counts': inv['counts'],
            'env': inv['env'],
            # 프로그램이 정한 목표 — 화면의 밴드 바가 앱 기본 구간 대신 이것을
            # 기준으로 삼는다(_program_targets 주석 참조).
            'targets': _program_targets(row),
            # 한계(온도 주/야간 · 습도) — 목표와 다른 것이다. 화면은 선으로 긋는다.
            'limits': _program_limits(row),
            # 목표가 곡선인 항목 — 숫자가 없으므로 앱 기본 구간도 그리지 않는다.
            'target_methods': _program_methods(row),
            'status': inv['status'],
        },
        'source': sensors.get('source'),
        'sensors': inv['sensors'],
        'outputs': inv['outputs'],
        'functions': inv['functions'],
        # 코디네이터는 Function 목록에도 들어가지만, "이 구역을 누가 맡는가" 는
        # 장치 목록과 다른 질문이라 따로 낸다(스코프·활성 여부가 함께 온다).
        'coordinators': control.get('coordinators') or [],
    }


def _build_plot_contents(plot_uuid):
    """식생 모달 인벤토리 본체. 못 찾으면 None(캐시에 남기지 않는다)."""
    from aot.aot_flask.geo import device_membership
    from aot.aot_flask.routes_geo import _build_area_contents

    row = GeoPlot.query.filter_by(unique_id=plot_uuid).first()
    if row is None:
        return None

    # 시설 구획은 기하가 파생이라 아래 경로를 태울 수 없다.
    if row.facility_uuid and not row.has_own_geometry():
        return _build_facility_plot_contents(row)

    geom = plot_context.geometry_of(row)

    # ── 무엇을 낼 것인가: **이 구획에 닿는 것만** ──────────────────────────
    #
    # 예전에는 구획 안 ∪ 구역 전체 ∪ 밸브를 합집합으로 냈다. 그러면 이 구획에
    # 물 한 방울 주지 않는 밸브까지 목록에 올라와, 식생 패널이 구역 패널의
    # 복사본이 된다 — 그럴 거면 구역 패널을 열면 된다. 실측(김제 새바람):
    # 출력 4개 중 실제로 이 구획에 닿는 것은 2개였고 나머지 둘은 교차가 0이었다.
    #
    #  plot        구획 폴리곤 안에 있다
    #  irrigation  구획 밖이지만 **이 구획을 적신다**(면적이 있는 교차)
    #  nearest     위 둘이 그 종류에서 하나도 없을 때만, 가장 가까운 것 하나
    #
    # 'zone'(구역에 있다는 이유만으로 싣기)은 없앴다. 구역 전체를 보려면 위로
    # 올라가는 화살표가 있다.
    plot_ids = set(device_membership.device_ids_in_geometry(
        row.geo_id, geom, _label='plot %s' % row.unique_id) or [])

    zone = plot_context.zone_for_plot(row)
    zone_ids = set(device_membership.device_ids_in_shape(zone) or []) if zone else set()

    # valves_for_plot 은 **면적이 있는 교차만** 낸다 — 여기 오는 밸브는
    # 전부 실제로 이 구획을 적신다.
    valves = plot_context.valves_for_plot(row)
    valve_ids = {v['device_id'] for v in valves if v.get('device_id')}

    direct = plot_ids | valve_ids

    # 종류별로 비었을 때만 가장 가까운 것 하나를 더한다. 종류를 섞어 판정하면
    # "센서는 있는데 밸브가 없는" 구획에서 센서까지 폴백이 걸린다.
    kinds_direct = _classify_devices(direct)
    kinds_zone = _classify_devices(zone_ids - direct)
    markers = device_membership.load_markers(row.geo_id)

    # 센서는 **있느냐가 아니라 값을 주느냐**로 판정한다. 구획 안에 센서가
    # 놓여 있어도 죽어 있으면 화면은 빈 차트가 되고, 사용자는 "이 구획은 볼
    # 값이 없다" 로 읽는다 — 바로 옆에 멀쩡한 센서가 있는데도.
    #
    # 죽은 센서를 목록에서 **빼지는 않는다.** 빼면 고장이 화면에서 사라져
    # 아무도 고치지 않는다. 대신 대체값을 함께 올리고, 정렬에서 값을 주는
    # 쪽을 위로 보낸다(아래 _sensor_order_key).
    #
    # env 는 여기서 **한 번만** 잰다. 판정에 쓰고, 값을 안 바꿔도 되는 경우
    # (= 인접 센서를 안 끌어온 경우)에는 그대로 아래 인벤토리에 넘긴다 —
    # 예전에는 같은 influx 왕복을 두 번 했다(실측 약 64ms 낭비).
    plot_env = None
    stale_direct = False
    if kinds_direct['inputs']:
        plot_env = _env_of(kinds_direct['inputs'])
        stale_direct = (plot_env.get('sensors') or {}).get('valid', 0) == 0

    nearest = {}          # device_id -> 거리(m)
    nearest_reason = {}   # device_id -> 'missing' | 'stale'
    for kind in ('inputs', 'outputs', 'functions'):
        have = kinds_direct[kind]
        reason = 'missing'
        if kind == 'inputs' and have and stale_direct:
            have = set()          # 있어도 값을 못 주면 없는 것으로 친다
            reason = 'stale'
        if have or not kinds_zone[kind]:
            continue
        for did, dist in plot_context.nearest_devices(
                row, kinds_zone[kind], markers=markers, limit=1):
            nearest[did] = dist
            nearest_reason[did] = reason

    # "켜면 무엇이 함께 젖는가" — 구역 모달과 **같은 함수**로 센다. 여기서
    # 따로 세면 같은 밸브가 두 화면에서 다른 작물 목록을 갖게 된다.
    cover = plot_context.plots_by_valve_device(row.geo_id)

    coverage = {v['device_id']: v.get('coverage_pct')
                for v in valves if v.get('device_id')}

    def _scope_of(uid):
        if uid in plot_ids:
            return 'plot'
        if uid in nearest:
            return 'nearest'
        return 'irrigation'

    # 인접 센서를 끌어왔으면 집합이 달라졌으니 다시 재야 한다. 아니면 위에서
    # 이미 잰 것이 그대로 맞다 — env 는 Input 만 보고, direct 의 Input 은
    # kinds_direct['inputs'] 뿐이다(나머지는 Output·Function).
    added_input = any(d in kinds_zone['inputs'] for d in nearest)
    inv = _build_area_contents(direct | set(nearest), scope_of=_scope_of,
                               env=(None if added_input else plot_env))

    # 가장 가까운 것으로 끌어온 장치는 **거리를 함께 낸다** — 왜 여기 있는지,
    # 얼마나 믿을 값인지 사람이 판단할 근거다.
    for group in ('sensors', 'outputs', 'functions'):
        for item in inv[group]:
            if item['unique_id'] in nearest:
                item['distance_m'] = nearest[item['unique_id']]
                item['nearest_reason'] = nearest_reason.get(item['unique_id'])

    # 값을 못 주는 구획 센서에 표시를 남긴다 — 화면이 "왜 옆 것을 보여주나"
    # 를 설명할 근거이자, 고장이 있다는 사실 자체다.
    if stale_direct:
        for item in inv['sensors']:
            if item.get('scope') == 'plot':
                item['no_data'] = True

    # 값을 주는 센서가 먼저 온다 — 첫 탭이 자동으로 그려지므로, 죽은 센서가
    # 앞에 있으면 열자마자 빈 차트를 보게 된다.
    inv['sensors'].sort(key=_sensor_order_key)

    # 밸브 정보는 출력 행에 붙인다 — 별도 블록으로 내면 화면이 같은 장치를
    # 두 번 그리게 되고, 토글 옆에 있어야 할 경고가 토글에서 멀어진다.
    for out in inv['outputs']:
        pct = coverage.get(out['unique_id'])
        if pct is not None:
            out['coverage_pct'] = pct
        # 자기 자신은 "함께 젖는 것" 이 아니다.
        names = plot_context.covered_subject_names(
            cover.get(out['unique_id']), exclude_uuid=row.unique_id)
        if names:
            out['also_covers'] = names

    # ── 순서: 관여도가 높은 것이 위 ────────────────────────────────────────
    #
    # DB 순서 그대로 두면 이 구획의 75.9% 를 적시는 밸브가 24.1% 짜리 아래로
    # 내려간다(실측). 목록의 첫 줄이 가장 관여도가 낮은 장치면, 급한 상황에서
    # 사람이 맨 위를 누른다.
    #
    # ⚠ **`coverage_pct` 를 붙인 뒤에 정렬한다.** 순서를 바꾸면 정렬 시점에
    # 비율이 아직 없어 전부 0으로 읽히고, 조용히 **이름순**으로 떨어진다.
    # 실제로 그렇게 나갔다: 둘 다 irrigation 인 구획(블랙틴)에서 39.8% 가
    # 60.2% 보다 위였다. plot 과 irrigation 이 섞인 구획은 스코프만으로도
    # 우연히 맞아서 한동안 드러나지 않았다.
    #
    # 정렬은 **서버가** 한다 — 화면마다 각자 정렬하면 같은 구획이 창마다 다른
    # 순서로 보이고, AI 도구가 보는 순서와도 갈린다.
    #
    # 구역 모달은 이 정렬을 쓰지 않는다. 그쪽은 사람이 드래그로 정한 순서
    # (`output_order`)가 있고, 그것은 명시적 의사표시라 계산이 이겨선 안 된다.
    for group in ('outputs', 'functions'):
        inv[group].sort(key=_involvement_key)

    sensors = plot_context.sensors_for_plot(row)

    return {
        'ok': True,
        'plot': {
            'unique_id': row.unique_id,
            'kind': row.kind or 'vegetation',
            'subject': row.subject,
            'variety': row.variety,
            'name': row.name,
            'area_m2': round(plot_context.area_m2(row), 1),
            'dims': plot_context.dimensions(row),
            'days_since_planted': plot_context.elapsed_days(row),
            'days_to_expected_end': plot_context.days_to_expected_end(row),
            'active': row.is_active(),
            'zone_uuid': sensors.get('zone_uuid'),
            'zone_name': sensors.get('zone_name'),
            # 그 도형이 실제로 무엇인지 — 'zone' | 'site'. 화면이 어느 창을
            # 열지 정하는 근거다(`sensors_for_plot` 주석 참조).
            'zone_kind': sensors.get('zone_kind'),
            # 카드에서 뺄 항목 — 구역의 설정을 그대로 쓴다(위 주석).
            'hidden_rows': _inherited_hidden_rows(
                zone_uuid=sensors.get('zone_uuid')),
            'counts': inv['counts'],
            'env': inv['env'],
            # 프로그램이 정한 목표 — 화면의 밴드 바가 앱 기본 구간 대신 이것을
            # 기준으로 삼는다(_program_targets 주석 참조).
            'targets': _program_targets(row),
            # 한계(온도 주/야간 · 습도) — 목표와 다른 것이다. 화면은 선으로 긋는다.
            'limits': _program_limits(row),
            # 목표가 곡선인 항목 — 숫자가 없으므로 앱 기본 구간도 그리지 않는다.
            'target_methods': _program_methods(row),
            'status': inv['status'],
        },
        # 대표값의 출처 — 목록(위 sensors/outputs)이 "손댈 수 있는 것 전부"
        # 라면 이쪽은 "이 구획을 대표하는 값이 어디서 오는가" 하나다. 둘은
        # 다른 질문이라 한쪽으로 합치지 말 것.
        'source': sensors.get('source'),
        'sensors': inv['sensors'],
        'outputs': inv['outputs'],
        'functions': inv['functions'],
    }


# ── 쓰기 ───────────────────────────────────────────────────────────────────

@blueprint.route('/api/geo/plot', methods=['POST'])
@login_required
def api_plot_save():
    """생성 또는 수정. `unique_id` 가 있으면 수정."""
    denied = _require_edit()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    result, error = plot_io.save_plot(data)
    if error:
        status = 404 if 'not found' in error.lower() else 400
        return jsonify({'ok': False, 'message': error}), status
    return jsonify({'ok': True, 'plot': result})


@blueprint.route('/api/geo/plot/<string:plot_uuid>/end',
                 methods=['POST'])
@login_required
def api_plot_end(plot_uuid):
    """작기 종료 — 행을 지우지 않고 종료일을 적는다."""
    denied = _require_edit()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    result, error = plot_io.end_plot(
        plot_uuid,
        ended_on=data.get('ended_on'),
        reason=data.get('reason') or 'harvested')
    if error:
        status = 404 if 'not found' in error.lower() else 400
        return jsonify({'ok': False, 'message': error}), status
    return jsonify({'ok': True, 'plot': result})


def _current_user_name():
    """확인한 사람 — 원장에 남는다. 로그인 정보가 없으면 비운다(지어내지 않는다)."""
    try:
        return getattr(current_user, 'name', None) or None
    except Exception:
        return None

@blueprint.route('/api/geo/plot/<string:plot_uuid>/stage',
                 methods=['POST'])
@login_required
def api_plot_stage_accept(plot_uuid):
    """단계 전환을 확인한다 — **이 한 줄이 기준점을 옮긴다.**

    이후 단계는 여기 적힌 날부터 계산된다. 그래서 날짜는 지어내지 않고 화면이
    보낸 것을 그대로 쓴다(제안값을 사람이 고칠 수 있다).
    """
    denied = _require_edit()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    result, error = plot_io.accept_stage(
        plot_uuid,
        stage_key=data.get('stage_key'),
        stage_index=data.get('stage_index'),
        started_on=data.get('started_on'),
        source=data.get('source') or 'manual',
        decided_by=_current_user_name(),
        note=data.get('note'))
    if error:
        status = 404 if '찾을 수 없습니다' in error else 400
        return jsonify({'ok': False, 'message': error}), status
    from aot.aot_flask.geo.site_summary import invalidate_plot_contents
    invalidate_plot_contents(plot_uuid)
    return jsonify({'ok': True, 'event': result})


@blueprint.route('/api/geo/plot/<string:plot_uuid>/stage',
                 methods=['DELETE'])
@login_required
def api_plot_stage_undo(plot_uuid):
    """마지막으로 확인된 전환을 되돌린다 — 행은 남는다(`undone_at`)."""
    denied = _require_edit()
    if denied:
        return denied

    result, error = plot_io.undo_stage(
        plot_uuid, decided_by=_current_user_name())
    if error:
        return jsonify({'ok': False, 'message': error}), 400
    from aot.aot_flask.geo.site_summary import invalidate_plot_contents
    invalidate_plot_contents(plot_uuid)
    return jsonify({'ok': True, 'event': result})


@blueprint.route('/api/geo/plot/<string:plot_uuid>/resources',
                 methods=['POST'])
@login_required
def api_plot_resources_apply(plot_uuid):
    """현재 단계에 선언된 자원 함수를 켠다 — **사람이 눌러야 한다.**

    프로그램이 스스로 부르지 않는다(단계 전환에도, 자동 승인에도 붙이지 않았다).
    관수를 켜는 것은 물이 나오는 일이다.
    """
    denied = _require_edit()
    if denied:
        return denied

    result, error = plot_io.apply_stage_resources(plot_uuid)
    if error:
        status = 404 if '찾을 수 없습니다' in error else 400
        return jsonify({'ok': False, 'message': error}), status
    from aot.aot_flask.geo.site_summary import invalidate_plot_contents
    invalidate_plot_contents(plot_uuid)
    return jsonify({'ok': True, 'result': result})


@blueprint.route('/api/geo/plot/<string:plot_uuid>/copy',
                 methods=['POST'])
@login_required
def api_plot_copy(plot_uuid):
    """지난 작기의 기하로 새 작기를 만든다."""
    denied = _require_edit()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    result, error = plot_io.copy_plot(
        plot_uuid,
        started_on=data.get('started_on'),
        subject=data.get('subject'))
    if error:
        status = 404 if 'not found' in error.lower() else 400
        return jsonify({'ok': False, 'message': error}), status
    return jsonify({'ok': True, 'plot': result})


@blueprint.route('/api/geo/plot/<string:plot_uuid>/succeed',
                 methods=['POST'])
@login_required
def api_plot_succeed(plot_uuid):
    """작기를 끝내고 **같은 자리를 이어받는다**(종료 + 승계, 한 번에).

    `/end` 와 나눈 이유: 종료만 하는 것도 정상이고(그 자리를 당분간 비운다),
    이어심기는 그 위에 얹는 선택이다. 한 엔드포인트에 옵션으로 넣으면 "종료" 가
    무엇을 하는지가 요청마다 달라진다.

    `program_uuid` 를 **키 자체로 보내지 않으면** 지난 작기 것을 물려받고,
    `null` 로 보내면 비운다(휴지기). 둘은 다른 뜻이다.
    """
    denied = _require_edit()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    kw = {}
    if 'program_uuid' in data:
        kw['program_uuid'] = data.get('program_uuid') or None
    if 'variety' in data:
        kw['variety'] = data.get('variety') or None

    result, error = plot_io.succeed_plot(
        plot_uuid,
        ended_on=data.get('ended_on'),
        reason=data.get('reason') or 'harvested',
        subject=data.get('subject'),
        started_on=data.get('started_on'),
        **kw)
    if error:
        status = 404 if 'not found' in error.lower() else 400
        return jsonify({'ok': False, 'message': error}), status
    from aot.aot_flask.geo.site_summary import invalidate_plot_contents
    invalidate_plot_contents(plot_uuid)
    return jsonify({'ok': True, **result})


@blueprint.route('/api/geo/plot/<string:plot_uuid>', methods=['DELETE'])
@login_required
def api_plot_delete(plot_uuid):
    """오기입 삭제. 정상 종료는 /end 를 쓴다."""
    denied = _require_edit()
    if denied:
        return denied

    result, error = plot_io.delete_plot(plot_uuid)
    if error:
        status = 404 if 'not found' in error.lower() else 400
        return jsonify({'ok': False, 'message': error}), status
    return jsonify(result)


# ── 파생 조회 ──────────────────────────────────────────────────────────────

@blueprint.route('/api/geo/plot/<string:plot_uuid>/sensors',
                 methods=['GET'])
@login_required
def api_plot_sensors(plot_uuid):
    """구획이 참조할 장치 — 저장된 값이 아니라 매번 파생한 결과."""
    row = GeoPlot.query.filter_by(unique_id=plot_uuid).first()
    if row is None:
        return jsonify({'ok': False, 'message': 'plot not found'}), 404
    return jsonify({'ok': True,
                    'sensors': plot_context.sensors_for_plot(row)})


@blueprint.route('/api/geo/zone/<string:zone_uuid>/allocation',
                 methods=['GET'])
@login_required
def api_zone_allocation(zone_uuid):
    """zone 의 면적 배분 — 구획별 면적/비율 + 미배정.

    겹침이 정상이라 비율 합은 100%를 넘을 수 있다. 응답에 합계를 싣지 않는
    이유가 그것이다(`overlaps` 로 겹침 여부만 알린다).
    """
    zone = GeoShape.query.filter_by(unique_id=zone_uuid).first()
    if zone is None:
        return jsonify({'ok': False, 'message': 'zone not found'}), 404

    on = _parse_on(request.args.get('on'))
    return jsonify({'ok': True,
                    'allocation': plot_context.zone_allocation(zone, on=on)})


@blueprint.route('/api/geo/plots/history', methods=['POST'])
@login_required
def api_plots_history():
    """"이 자리에 뭐가 있었나" — 기하가 겹치는 작기 목록.

    연작 장해·윤작 판단의 근거다. 기준 기하는 본문으로 받는다:
      - `plot_uuid` 를 주면 그 구획의 기하
      - 또는 `geometry` 를 직접
    GET 이 아닌 이유는 폴리곤이 URL 에 담기지 않기 때문이다.
    """
    data = request.get_json(silent=True) or {}
    map_uuid = data.get('map_uuid')
    geom = data.get('geometry')

    if data.get('plot_uuid'):
        src = GeoPlot.query.filter_by(
            unique_id=data['plot_uuid']).first()
        if src is None:
            return jsonify({'ok': False, 'message': 'plot not found'}), 404
        geom = plot_context.geometry_of(src)
        map_uuid = map_uuid or src.geo_id
    elif data.get('zone_uuid'):
        zone = GeoShape.query.filter_by(unique_id=data['zone_uuid']).first()
        if zone is None:
            return jsonify({'ok': False, 'message': 'zone not found'}), 404
        geom = plot_context.geometry_of(zone)
        map_uuid = map_uuid or zone.geo_id

    if not map_uuid or not geom:
        return jsonify({'ok': False,
                        'message': 'map_uuid and geometry required'}), 400

    pairs = plot_context.plots_overlapping(map_uuid, geom)
    items = []
    for row, overlap_m2 in pairs:
        d = plot_context.to_dict(row)
        d['overlap_m2'] = round(overlap_m2, 1)
        items.append(d)
    return jsonify({'ok': True, 'history': items, 'count': len(items)})


# ── 분할 (미리보기 / 적용) ─────────────────────────────────────────────────
#
# **미리보기를 저장하지 않는다.** 분할은 결정적이라(같은 도형 + 같은 파라미터 →
# 항상 같은 결과) 미리보기는 보관할 상태가 아니라 다시 계산하면 되는 것이다.
# 그래서 임시 저장소도, TTL 도, 만료 처리도 없다 — 지도는 preview 로 그리고,
# 적용은 같은 파라미터로 재계산해서 만든다.
#
# 도형이 그 사이에 바뀌면 결과도 바뀐다. 그것이 맞다 — 사람이 밭 모양을 고쳤으면
# 새 모양대로 나뉘어야 한다.

def split_args_from(src):
    """요청에서 분할 파라미터를 뽑는다 → (kwargs, 오류문구).

    **식생 전용이 아니다.** 장치 담당 구역 분할(`routes_geo_device_split`)도
    같은 파라미터를 쓰므로 여기 하나를 공유한다 — 두 벌로 두면 한쪽에만 옵션이
    붙어 미리보기와 실제 결과가 갈린다.
    """
    shape_id = src.get('zone_id') or src.get('shape_id')
    if not shape_id:
        return None, 'zone_id is required'

    def _num(key):
        v = src.get(key)
        if v in (None, ''):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError('%s must be a number' % key)

    def _num_list(key):
        """조각별 폭 목록. POST(JSON)는 배열 그대로, GET(쿼리스트링)은 값이
        문자열뿐이라 콤마로 구분해 받는다(`widths_cm=500,1000,300`)."""
        v = src.get(key)
        if v in (None, ''):
            return None
        if isinstance(v, (list, tuple)):
            items = v
        else:
            items = [x for x in str(v).split(',') if x.strip() != '']
        try:
            return [float(x) for x in items]
        except (TypeError, ValueError):
            raise ValueError('%s must be a list of numbers' % key)

    orientation = src.get('orientation') or None
    if hasattr(orientation, 'strip'):
        orientation = orientation.strip().lower()

    try:
        return {
            'shape_id': shape_id,
            'parts': int(_num('parts')) if _num('parts') is not None else None,
            'strip_width_cm': _num('strip_width_cm'),
            # 있으면 parts/strip_width_cm 보다 우선한다(split_shape 의 규칙 —
            # 대체가 아니라 항상 함께 넘긴다, 상호배타 판단은 그쪽에서 한다).
            'widths_cm': _num_list('widths_cm'),
            'edge_margin_m': _num('edge_margin_m') or 0,
            # 이보다 짧은 조각은 버린다(cm). 두둑 기준 기본값(2m)은 장치 담당
            # 구역에는 너무 커서 좁은 구역이 조용히 사라진다 — 호출자가 정할 수
            # 있게 열어 둔다. **미리보기와 적용이 같은 값을 써야** 화면에서 본
            # 조각 수와 실제로 만들어지는 수가 갈리지 않는다.
            'min_length_cm': _num('min_length_cm'),
            # 생략(None)이면 split_shape() 이 모드(strip_width_cm 유무)로
            # 기본값을 정한다 — 여기서 'long' 을 하드코딩하면 그 분기와
            # 어긋날 수 있으므로 그대로 통과시킨다.
            'orientation': orientation,
            # 각도가 있으면 위 orientation 은 서버(split_shape)에서 무시된다 —
            # 대체가 아니라 공존이다. UI 는 둘 중 하나만 채워 보낸다.
            'angle_deg': _num('angle_deg'),
        }, None
    except ValueError as exc:
        return None, str(exc)


def split_kwargs_from(args):
    """`split_args_from` 결과 → `plot_split.split_shape` 키워드.

    한 곳에서 만든다 — 미리보기와 적용이 각자 조립하면 옵션 하나가 빠진 쪽만
    다른 결과를 낸다.
    """
    kwargs = dict(
        parts=args['parts'], strip_width_cm=args['strip_width_cm'],
        widths_cm=args.get('widths_cm'),
        edge_margin_m=args['edge_margin_m'], orientation=args['orientation'],
        angle_deg=args.get('angle_deg'))
    min_cm = args.get('min_length_cm')
    if min_cm is not None:
        kwargs['min_bed_length_m'] = float(min_cm) / 100.0
    return kwargs


def compute_split(args):
    """(strips, info, shape) 또는 (None, (응답, 코드))."""
    shape = GeoShape.query.filter_by(unique_id=args['shape_id']).first()
    if shape is None:
        return None, (jsonify({'ok': False,
                               'message': 'shape not found: %s' % args['shape_id']}), 404)
    strips, info = plot_split.split_shape(shape, **split_kwargs_from(args))
    if strips is None:
        return None, (jsonify({'ok': False, 'message': info}), 400)
    return (strips, info, shape), None


@blueprint.route('/api/geo/plot/split-preview', methods=['GET'])
@login_required
def api_plot_split_preview():
    """분할 제안을 계산해 돌려준다 — 아무것도 저장하지 않는다.

    지도가 이것을 점선으로 그린다. 사람이 보고 판단한 뒤 apply 로 넘어간다.
    """
    args, err = split_args_from(request.args)
    if err:
        return jsonify({'ok': False, 'message': err}), 400
    out, fail = compute_split(args)
    if fail:
        return fail
    strips, info, shape = out
    return jsonify({'ok': True, 'strips': strips, 'info': info,
                    'shape_uuid': shape.unique_id, 'geo_id': shape.geo_id})


@blueprint.route('/api/geo/plot/split-apply', methods=['POST'])
@login_required
def api_plot_split_apply():
    """미리보기와 **같은 파라미터로 재계산**해 구획을 만든다.

    미리보기에서 본 폴리곤을 클라이언트가 되돌려보내지 않는다 — 그러면 화면에서
    한 번 계산하고 저장할 때 다른 것을 보낼 수 있는 경로가 생긴다. 서버가 다시
    계산하는 편이 "본 것과 저장된 것이 같다" 를 구조로 보장한다.
    """
    denied = _require_edit()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    args, err = split_args_from(data)
    if err:
        return jsonify({'ok': False, 'message': err}), 400
    if not (data.get('subject') or '').strip():
        return jsonify({'ok': False, 'message': 'subject is required'}), 400
    out, fail = compute_split(args)
    if fail:
        return fail
    strips, info, shape = out

    name_base = (data.get('name') or '').strip()
    created, errors = [], []
    for strip in strips:
        payload = {
            'map_uuid': shape.geo_id,
            'feature': {'type': 'Feature', 'properties': {},
                        'geometry': strip['geometry']},
            'kind': data.get('kind') or 'vegetation',
            'subject': data.get('subject'),
            'variety': data.get('variety'),
            'started_on': data.get('started_on'),
            'expected_end_on': data.get('expected_end_on'),
            'color': data.get('color'),
            'source_kind': 'copied',
            'source_ref': shape.unique_id,
        }
        if name_base:
            payload['name'] = '%s %d' % (name_base, strip['index'])
        row, error = plot_io.save_plot(payload)
        if error:
            errors.append({'index': strip['index'], 'message': error})
            continue
        row.pop('feature', None)
        created.append(row)

    # 일부만 저장된 것을 성공으로 말하지 않는다 — 지도에는 몇 개만 뜨는데
    # 응답은 성공이면 사용자는 나머지가 어디 갔는지 알 방법이 없다.
    return jsonify({'ok': not errors, 'created': created, 'info': info,
                    'errors': errors,
                    'message': (None if not errors else
                                '%d of %d pieces failed to save'
                                % (len(errors), len(strips)))})

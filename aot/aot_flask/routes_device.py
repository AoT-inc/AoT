# coding=utf-8
"""Device 페이지 라우트.

Device 는 새 저장소가 아니라 is_device=True 로 선언된 Custom Function 모듈이
만드는 CustomController 행이다(aot/utils/functions.py device_module_names 참조,
설계 근거 .local/plans/device_group_console_plan.md). 그래서 추가·활성화·설정
편집·삭제는 새로 만들지 않고 기존 /function_submit, /function?function_type=...
경로를 device.html 의 JS가 직접 호출한다 — 이 파일이 새로 담당하는 건 (a) 목록
페이지 렌더링과 (b) 하위 Input/Output 구성을 모아 주는 요약 엔드포인트뿐이다.

탭 시스템은 쓰지 않는다. routes_tab.py/TabService 는 page_type
'dashboard'/'input'/'output'/'function' 화이트리스트가 탭 생성·복제·삭제·고아
정리 여러 곳에 하드코딩돼 있어(조사로 확인), 'device' 를 추가하려면 그 전부를
함께 고쳐야 하고 기존 4개 페이지의 탭 동작을 망가뜨릴 위험이 있다. 장치는
Input(151종)/Output(54종)만큼 개수가 많을 이유가 없어 탭 분류가 당장 필요하지도
않다. 대신 TabService.get_default_tab('device') 로 장치 전용 탭을 하나만 만들어
모든 장치를 거기 몰아넣는다 — 이 함수는 page_type 화이트리스트가 없어 새 값을
그대로 받아들인다(코드 확인). 사용자에게 탭 UI로 노출하지 않고, Function 페이지의
탭 필터(tab_id 기준)에 장치가 절대 걸리지 않게 하는 격리 장치로만 쓴다(is_device
스캐너 필터와의 이중 방어).

@phase active
@stability experimental
@dependency CustomController, Input, Output, device_blueprint
"""
import json

import flask_login
from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _

from aot.aot_flask.extensions import db
from aot.aot_flask.routes_static import inject_variables
from aot.aot_flask.utils import utils_general
from aot.databases.models import (
    CustomController, DeviceMeasurements, DeviceMember, Input, InputChannel,
    Output, OutputChannel,
)
from aot.services.tab_service import TabService
from aot.utils.device_blueprint import (
    link_member, linkable_members, member_device_map, parent_device_names,
    unlink_member,
)
from aot.utils.functions import device_module_names, parse_function_information

blueprint = Blueprint('routes_device',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')


@blueprint.context_processor
@flask_login.login_required
def inject_dictionary():
    return inject_variables()


def _channel_name(custom_options_json, fallback):
    """채널 커스텀옵션의 'name'(Channel Name) 필드를 표시용 이름으로 우선한다.
    device_blueprint.py 가 청사진의 channels[].name 을 저장하는 자리가 바로
    여기다(입력은 InputChannel, 출력은 OutputChannel — 3절 버그 수정 참조)."""
    try:
        opts = json.loads(custom_options_json) if custom_options_json else {}
    except Exception:
        opts = {}
    name = opts.get('name') if isinstance(opts, dict) else None
    return name if name else fallback


def _device_tab_id():
    """장치 전용 고정 탭(사용자에게 노출 안 함). 모듈 docstring 참조."""
    tab = TabService.get_default_tab('device')
    return tab.unique_id if tab else None


@blueprint.route('/device', methods=['GET'])
@flask_login.login_required
def page_device():
    """장치 목록. 탭 없이 카드로 나열한다."""
    dict_controllers = parse_function_information()
    device_names = device_module_names(dict_controllers)

    devices = []
    if device_names:
        devices = (CustomController.query
                   .filter(CustomController.device.in_(device_names))
                   .order_by(CustomController.position_y)
                   .all())

    # "장치: " 접두어는 여기서만 붙인다 — 각 device_*.py의 function_name 자체에는
    # 넣지 않는다(custom_function_options.html의 공용 메타 스트립이 그 값을
    # "이름: {function_name}"으로도 보여줘서, 접두어를 박아두면 "이름: 장치: X"
    # 로 라벨이 겹치는 버그가 있었다 — 모듈 쪽 주석 참조).
    choices_devices = sorted(
        ({'value': name,
          'item': "{}: {}".format(_('Device'), dict_controllers[name].get('function_name', name))}
         for name in device_names),
        key=lambda c: str(c['item']))

    # 장치 카드도 Input/Output과 대칭으로 "다른 장치의 하위로도 연결돼 있는가"를
    # 배지로 보여준다(설계 Phase 8/9 — 계층은 항상 참조 관계이므로 이 맵은
    # secondary만 본다. primary parent_device_id는 오늘 어떤 장치 모듈도 다른
    # 장치를 청사진으로 만들지 않아 실질적으로 항상 비어 있다).
    dict_device_parent_map = member_device_map('device')
    dict_device_names = parent_device_names(device_names)

    return render_template(
        'pages/device.html',
        devices=devices,
        dict_controllers=dict_controllers,
        choices_devices=choices_devices,
        dict_device_parent_map=dict_device_parent_map,
        dict_device_names=dict_device_names,
        device_tab_id=_device_tab_id())


@blueprint.route('/device/<device_id>/summary', methods=['GET'])
@flask_login.login_required
def device_summary(device_id):
    """하위 Input/Output 구성(정적 정의)을 모아 반환. 폴링 대상이 아니다 —
    실시간 값·상태는 클라이언트가 /data_batch, /inputstate, /outputstate,
    /outputcommcapable 를 직접 폴링한다(design plan 3.4)."""
    device = CustomController.query.filter_by(unique_id=device_id).first()
    if not device:
        return jsonify({'error': 'not found'}), 404

    dict_controllers = parse_function_information()
    device_info = dict_controllers.get(device.device, {})

    result = {
        'device': {
            'unique_id': device.unique_id,
            'name': device.name,
            'is_activated': bool(device.is_activated),
            'device_type_name': device_info.get('function_name', device.device),
        },
        'inputs': [],
        'outputs': [],
    }

    inputs = Input.query.filter_by(parent_device_id=device.unique_id).all()
    for inp in inputs:
        channels = []
        dms = {dm.channel: dm for dm in DeviceMeasurements.query.filter_by(
            device_id=inp.unique_id).all()}
        for ic in InputChannel.query.filter_by(input_id=inp.unique_id).order_by(
                InputChannel.channel).all():
            dm = dms.get(ic.channel)
            fallback_name = (dm.name if dm and dm.name else f"CH{ic.channel}")
            channels.append({
                'channel': ic.channel,
                'name': _channel_name(ic.custom_options, fallback_name),
                'measurement': dm.measurement if dm else None,
                'unit': dm.unit if dm else None,
                'measurement_id': dm.unique_id if dm else None,
                'is_enabled': bool(dm.is_enabled) if dm else False,
            })
        inputs_entry = {
            'unique_id': inp.unique_id,
            'name': inp.name,
            'is_activated': bool(inp.is_activated),
            'tab_id': inp.tab_id,
            'channels': channels,
        }
        result['inputs'].append(inputs_entry)

    outputs = Output.query.filter_by(parent_device_id=device.unique_id).all()
    for out in outputs:
        channels = []
        for oc in OutputChannel.query.filter_by(output_id=out.unique_id).order_by(
                OutputChannel.channel).all():
            channels.append({
                'channel': oc.channel,
                'name': _channel_name(oc.custom_options, f"CH{oc.channel}"),
            })
        outputs_entry = {
            'unique_id': out.unique_id,
            'name': out.name,
            'tab_id': out.tab_id,
            'channels': channels,
        }
        result['outputs'].append(outputs_entry)

    # secondary(참조) 소속 — 다른 장치가 primary로 소유하거나 다른 장치의
    # secondary인 항목을 이 장치 구성에도 "참조"로 보여준다(설계 Phase 8/9).
    # "구성" 트리(위 inputs/outputs, primary 전용)와 달리 활성화 cascade와는
    # 무관 — 순수 표시·탐색용이다.
    secondary_rows = DeviceMember.query.filter_by(device_id=device.unique_id).all()
    secondary_input_ids = [r.member_id for r in secondary_rows if r.member_type == 'input']
    secondary_output_ids = [r.member_id for r in secondary_rows if r.member_type == 'output']
    secondary_device_ids = [r.member_id for r in secondary_rows if r.member_type == 'device']

    result['secondary_inputs'] = [
        {'unique_id': i.unique_id, 'name': i.name, 'tab_id': i.tab_id}
        for i in Input.query.filter(Input.unique_id.in_(secondary_input_ids)).all()
    ] if secondary_input_ids else []
    result['secondary_outputs'] = [
        {'unique_id': o.unique_id, 'name': o.name, 'tab_id': o.tab_id}
        for o in Output.query.filter(Output.unique_id.in_(secondary_output_ids)).all()
    ] if secondary_output_ids else []
    result['sub_devices'] = [
        {'unique_id': d.unique_id, 'name': d.name,
         'device_type_name': dict_controllers.get(d.device, {}).get('function_name', d.device)}
        for d in CustomController.query.filter(CustomController.unique_id.in_(secondary_device_ids)).all()
    ] if secondary_device_ids else []

    return jsonify(result)


@blueprint.route('/save_device_layout', methods=['POST'])
@flask_login.login_required
def save_device_layout():
    """장치 카드 순서 저장 — save_input_layout(routes_input.py)과 동일 패턴.

    device_names 로 필터하는 이유: 이 엔드포인트가 받는 id는 항상 렌더링된
    장치 카드에서 온 값이지만, 클라이언트가 임의 unique_id를 보내는 경우에도
    Device가 아닌 CustomController(일반 Function)의 position_y가 이 화면
    조작으로 바뀌지 않도록 방어한다.
    """
    if not utils_general.user_has_permission('edit_controllers'):
        return redirect(url_for('routes_general.home'))

    device_names = device_module_names()
    data = request.get_json()
    items = [d for d in (data or []) if 'id' in d and 'y' in d]
    items.sort(key=lambda d: (d['y'], d['id']))
    for rank, each_item in enumerate(items):
        dev = CustomController.query.filter(
            CustomController.unique_id == each_item['id'],
            CustomController.device.in_(device_names)).first()
        if dev:
            dev.position_y = rank
    db.session.commit()
    return "success"


@blueprint.route('/device/<device_id>/candidates', methods=['GET'])
@flask_login.login_required
def device_candidates(device_id):
    """이 장치에 아직 연결되지 않은 Input/Output/Device 목록 — 연결 후보
    (설계 6.4, 다대다·계층 지원으로 "미소속만"이라는 제약을 해제 — Phase 8/9)."""
    inputs, outputs, devices = linkable_members(device_id)
    return jsonify({
        'inputs': [{'unique_id': i.unique_id, 'name': i.name} for i in inputs],
        'outputs': [{'unique_id': o.unique_id, 'name': o.name} for o in outputs],
        'devices': [{'unique_id': d.unique_id, 'name': d.name} for d in devices],
    })


@blueprint.route('/device/<device_id>/link', methods=['POST'])
@flask_login.login_required
def device_link(device_id):
    """Input/Output/Device 하나를 이 장치 구성에 연결한다(설계 6.4/8/9)."""
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'error': 'permission denied'}), 403
    data = request.get_json(silent=True) or {}
    member_type = data.get('type')
    member_id = data.get('id')
    if member_type not in ('input', 'output', 'device') or not member_id:
        return jsonify({'error': 'invalid request'}), 400
    err = link_member(device_id, member_type, member_id)
    if err:
        return jsonify({'error': err}), 400
    return jsonify({'success': True})


@blueprint.route('/device/<device_id>/unlink', methods=['POST'])
@flask_login.login_required
def device_unlink(device_id):
    """이 장치에 연결된 Input/Output/Device 하나를 해제한다(설계 6.4/8/9)."""
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'error': 'permission denied'}), 403
    data = request.get_json(silent=True) or {}
    member_type = data.get('type')
    member_id = data.get('id')
    if member_type not in ('input', 'output', 'device') or not member_id:
        return jsonify({'error': 'invalid request'}), 400
    err = unlink_member(device_id, member_type, member_id)
    if err:
        return jsonify({'error': err}), 400
    return jsonify({'success': True})

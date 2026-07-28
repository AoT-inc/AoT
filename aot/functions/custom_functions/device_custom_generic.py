# coding=utf-8
"""AoT 복합장치: 사용자 정의(Custom) — 고정 청사진 없음.

Phase 7(.local/plans/device_group_console_plan.md 6절 "사용자 정의 복합장치").
Modbus PLC(`device_modbus_plc_generic.py`)처럼 접속정보·채널을 자동 생성하는
고정 청사진이 없다 — 이 모듈은 빈 컨테이너 하나만 만든다. 사용자는 장치를
추가한 뒤 톱니바퀴 → "연결된 Input/Output"/"하위 장치" 섹션(Phase 6/8/9,
`aot/utils/device_blueprint.py`의 link_member/linkable_members)에서 이미 갖고
있는(또는 다른 장치에 이미 속한) Input/Output/Device를 자유롭게 골라 붙여
넣는다 — 청사진을 코드로 짜지 않고도 "이 항목들을 한 장치로 묶어서 본다"는
결과를 얻는다.

새 생성 메커니즘이 아니다 — Phase 6이 만든 연결 UI를 그대로 재사용할 뿐이라
execute_at_creation/execute_at_modification도 필요 없다(만들 것도, 저장 시
재전파할 접속정보도 없음).

@phase active
@stability experimental
@dependency device_blueprint
"""
from flask_babel import lazy_gettext

FUNCTION_INFORMATION = {
    'function_name_unique': 'device_custom_generic',
    # "장치: " 접두어를 여기 넣지 않는 이유는 device_modbus_plc_generic.py의
    # 동일 주석 참조 — 접두어는 routes_device.py의 choices_devices에서만 붙인다.
    'function_name': lazy_gettext('Custom (no fixed type)'),
    'function_name_short': lazy_gettext('Custom Device'),

    'is_device': True,
    'device_category': 'custom',

    # device_modbus_plc_generic.py와 동일한 이유(측정 채널을 직접 갖지 않음)
    # 로 "측정값 설정" 그룹을 끈다.
    'options_disabled': [
        'measurements_select',
        'measurements_configure',
    ],

    'message': lazy_gettext(
        'A user-defined composite device with no fixed blueprint. Nothing is created '
        'automatically — add it, then use "Linked Inputs/Outputs" and "Sub-devices" in its '
        'settings to attach any existing Input, Output, or other Device as members, even '
        'ones that already belong to another device.'
    ),

    # 청사진 없음 — 'device_blueprint' 키 자체를 생략한다. create_blueprint_members()는
    # blueprint가 없거나 비어 있으면 아무것도 만들지 않는다(device_blueprint.py 확인).
}


class CustomModule:
    """빈 컨테이너 — loop()/listener() 를 선언하지 않으므로 has_loop=False로
    판정된다(device_modbus_plc_generic.py와 동일한 근거)."""

    def __init__(self, function, testing=False):
        pass

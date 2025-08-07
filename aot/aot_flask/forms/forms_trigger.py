# -*- coding: utf-8 -*-
#
# forms_trigger.py - Function Flask Forms
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import DecimalField
from wtforms import IntegerField
from wtforms import StringField
from wtforms import widgets
from wtforms.widgets import NumberInput

from aot.config_translations import TRANSLATIONS


class Trigger(FlaskForm):
    function_id = StringField('함수 ID', widget=widgets.HiddenInput())
    function_type = StringField('함수 유형', widget=widgets.HiddenInput())
    name = StringField('이름')
    log_level_debug = BooleanField('디버그 로그 활성화')

    # 엣지 감지 (Edge detection)
    measurement = StringField('측정값')
    edge_detected = StringField('엣지 감지 시')

    # 일출/일몰
    rise_or_set = StringField('일출 또는 일몰')
    latitude = DecimalField('위도 (소수점)', widget=NumberInput(step='any'))
    longitude = DecimalField('경도 (소수점)', widget=NumberInput(step='any'))
    zenith = DecimalField('천정각', widget=NumberInput(step='any'))
    date_offset_days = IntegerField('날짜 오프셋 (일)', widget=NumberInput())
    time_offset_minutes = IntegerField('시간 오프셋 (분)', widget=NumberInput())

    # 리모컨 적외선 수신
    program = StringField('프로그램')
    word = StringField('명령어')

    # 타이머
    period = DecimalField('주기 (초)', widget=NumberInput(step='any'))
    timer_start_offset = IntegerField('시작 지연 (초)', widget=NumberInput())
    timer_start_time = StringField('시작 시간 (HH:MM)')
    timer_end_time = StringField('종료 시간 (HH:MM)')

    # 메서드
    trigger_actions_at_period = BooleanField('주기마다 동작 실행')
    trigger_actions_at_start = BooleanField('활성화 시 동작 실행')

    # 출력
    unique_id_1 = StringField('조건 ID 1')
    unique_id_2 = StringField('조건 ID 2')
    output_state = StringField('상태 조건')
    output_duration = DecimalField('조건 지속 시간 (초)', widget=NumberInput(step='any'))
    output_duty_cycle = DecimalField('조건 듀티 사이클 (%)', widget=NumberInput(step='any'))

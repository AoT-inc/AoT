# -*- coding: utf-8 -*-
#
# forms_conditional.py - Miscellaneous Flask Forms
#

from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import DecimalField
from wtforms import IntegerField
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import widgets
from wtforms.widgets import NumberInput

from aot.config import CONDITIONAL_CONDITIONS


#
# Conditionals
#

class Conditional(FlaskForm):
    function_id = StringField('Function ID', widget=widgets.HiddenInput())
    function_type = StringField('Function Type', widget=widgets.HiddenInput())
    name = StringField('이름')
    conditional_import = StringField('파이썬 코드 가져오기 (Import)')
    conditional_initialize = StringField('파이썬 코드 초기화')
    conditional_statement = StringField('실행할 파이썬 코드')
    conditional_status = StringField('상태 확인 파이썬 코드')
    period = DecimalField(
        "주기 (초)",
        widget=NumberInput(step='any'))
    log_level_debug = BooleanField('디버그 로그 활성화')
    use_pylint = BooleanField('Pylint 사용')
    message_include_code = BooleanField('메시지에 코드 포함')
    refractory_period = DecimalField(
        "불응기 (초)",
        widget=NumberInput(step='any'))
    start_offset = DecimalField(
        "시작 지연 (초)",
        widget=NumberInput(step='any'))
    pyro_timeout = DecimalField(
        "타임아웃 (초)",
        widget=NumberInput(step='any'))
    condition_type = SelectField(
        '조건 유형',
        choices=[('', '선택하세요')] + CONDITIONAL_CONDITIONS)
    add_condition = SubmitField('추가')


class ConditionalConditions(FlaskForm):
    conditional_id = StringField(
        'Conditional ID', widget=widgets.HiddenInput())
    conditional_condition_id = StringField(
        'Conditional Condition ID', widget=widgets.HiddenInput())

    # Measurement
    input_id = StringField('Input ID', widget=widgets.HiddenInput())
    measurement = StringField('측정값')
    max_age = IntegerField(
        '최대 허용 기간 (초)',
        widget=NumberInput())

    # GPIO 상태
    gpio_pin = IntegerField(
        "핀 번호: GPIO (BCM)",
        widget=NumberInput())

    output_id = StringField('출력 장치')
    controller_id = StringField('컨트롤러')

    save_condition = SubmitField('저장')
    delete_condition = SubmitField('삭제')
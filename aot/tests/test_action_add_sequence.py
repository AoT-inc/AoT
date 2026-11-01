# coding=utf-8
"""시퀀스 함수에 액션을 추가하는 경로(`utils_action.action_add`)가 오류 없이 끝난다.

"액션 추가" 를 누르면 행은 만들어지는데 `'Trigger' object is not callable` 이
토스트로 뜨던 결함의 회귀 방지. 원인은 `which_controller()` 의 반환값을 `_` 로
받아 gettext 가 가려진 것이었다 — 구조 검사는 `test_gettext_shadowing.py` 가
하고, 여기서는 **실제로 그 경로를 끝까지 밟는다**(저장 뒤 `_("Action added")` 가
호출되는 줄이 터지던 곳이다).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.config import AOT_DB_PATH
from aot.databases.models import Actions, Trigger


@pytest.fixture()
def app_ctx():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = AOT_DB_PATH
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = False  # 의존성 검사 분기까지 밟는다
    db.init_app(app)
    Babel(app)
    with app.test_request_context():
        trigger = Trigger()
        trigger.name = 'seq'
        trigger.trigger_type = 'trigger_sequence'
        trigger.save()
        yield trigger
        Actions.query.filter(Actions.function_id == trigger.unique_id).delete()
        db.session.delete(trigger)
        db.session.commit()


def _form(trigger, action_type):
    return SimpleNamespace(
        device_id=SimpleNamespace(data=trigger.unique_id),
        function_type=SimpleNamespace(data='trigger'),
        action_type=SimpleNamespace(data=action_type))


@pytest.mark.parametrize('action_type', ['output_on_off', 'output_pwm'])
def test_add_action_to_sequence_has_no_error(app_ctx, action_type):
    from aot.aot_flask.utils import utils_action
    with patch.object(utils_action, 'return_dependencies',
                      return_value=([], None, '')), \
            patch('aot.aot_client.DaemonControl', return_value=MagicMock()):
        messages, _dep_name, dep_list, action_id, page_refresh, _msg = \
            utils_action.action_add(_form(app_ctx, action_type), {})

    assert messages['error'] == []
    assert messages['success']
    assert action_id and page_refresh and not dep_list
    assert Actions.query.filter(Actions.unique_id == action_id).count() == 1


@pytest.mark.parametrize('module', [
    'output_on_off', 'output_pwm', 'output_ramp_pwm',
    'output_value', 'output_volume'])
def test_output_option_placeholder_is_translatable(module):
    """새 시퀀스 액션 행의 출력 선택 자리표시자가 영어 "Output" 로 굳지 않는다.

    선택 상자의 `title`/첫 항목이 옵션의 `name` 이라, 평문 str 이면 번역을 못
    탄다. gettext 지연 객체여야 한다.
    """
    import importlib
    info = importlib.import_module(f'aot.actions.{module}').ACTION_INFORMATION
    name = next(o['name'] for o in info['custom_options'] if o['id'] == 'output')
    assert not isinstance(name, str)


def test_unmet_dependency_return_keeps_positions(app_ctx):
    """의존성 미충족이면 안내문은 마지막 자리로, action_id/page_refresh 는 비어서 온다."""
    from aot.aot_flask.utils import utils_action
    unmet = [('a', 'b', 'c', 'pkg')]
    with patch.object(utils_action, 'return_dependencies',
                      return_value=(unmet, None, '설치 필요')):
        messages, dep_name, dep_list, action_id, page_refresh, dep_message = \
            utils_action.action_add(_form(app_ctx, 'output_on_off'), {})

    assert messages['error']
    assert dep_name == 'output_on_off'
    assert dep_list == ['pkg']
    assert action_id is None and page_refresh is False
    assert dep_message == '설치 필요'

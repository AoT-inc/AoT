# coding=utf-8
"""UART/FTDI 접속 위치 입력칸 — 드라이버 선언 키와 폼 조각의 키가 같아야 한다.

드라이버는 `uart_location` / `ftdi_location` 을 선언하는데 폼 조각이 예전 키
(`uart`, `ftdi_address`)를 검사해서, 칸이 아예 그려지지 않았다. 그러면 추가
시점의 기본값(/dev/ttyAMA0)을 고칠 방법이 없어 USB 시리얼·Pi 5 사용자가
막힌다. 여기서는 (1) 선언된 모든 위치 키에 그리는 조각이 있고, (2) 실제로
칸이 그려지며, (3) 저장하면 남는지를 본다.
"""
import os
import re
from unittest import mock

import pytest
from flask import Flask, render_template_string, request

import aot
from aot.aot_flask.extensions import db
from aot.aot_flask.forms.forms_input import InputMod
from aot.aot_flask.forms.forms_output import OutputMod
from aot.aot_flask.utils import utils_input, utils_output
from aot.databases.models import Input, Output

ROOT = os.path.dirname(os.path.dirname(aot.__file__))
TEMPLATES = os.path.join(os.path.dirname(aot.__file__), 'aot_flask', 'templates')
PARTIAL_DIR = os.path.join(TEMPLATES, 'pages', 'form_options')
PARTIAL_FOR = {'uart_location': 'UART.html', 'ftdi_location': 'FTDI.html'}


def _declaring_modules(key):
    """`options_enabled` 안에 key 를 선언한 입력·출력 모듈 파일."""
    found = []
    for sub in ('inputs', 'outputs'):
        base = os.path.join(os.path.dirname(aot.__file__), sub)
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith('.py'):
                    continue
                path = os.path.join(dirpath, fn)
                text = open(path, encoding='utf-8').read()
                if re.search(r"options_enabled'?\"?\s*:\s*\[[^\]]*'%s'" % key, text):
                    found.append(os.path.relpath(path, ROOT))
    return found


@pytest.mark.parametrize('key', sorted(PARTIAL_FOR))
def test_partial_gates_on_declared_key(key):
    """조각이 드라이버가 선언하는 바로 그 키로 열린다."""
    assert _declaring_modules(key), 'no module declares %s' % key
    text = open(os.path.join(PARTIAL_DIR, PARTIAL_FOR[key]), encoding='utf-8').read()
    gate = text.split('%}', 1)[0]
    assert "'%s' in dict_options['options_enabled']" % key in gate
    assert "form.%s(" % key in text


@pytest.fixture
def app():
    app = Flask(__name__, template_folder=TEMPLATES)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', WTF_CSRF_ENABLED=False,
                      SECRET_KEY='t', TESTING=True)
    db.init_app(app)
    from flask_babel import Babel
    Babel(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _render(partial, form, device, enabled, disabled=()):
    return render_template_string(
        "{% include 'pages/form_options/" + partial + "' %}",
        form=form, each_device=device,
        dict_options={'options_enabled': list(enabled), 'options_disabled': list(disabled)},
        dict_translation={
            'uart_location': {'title': 'UART Device', 'phrase': 'uart phrase'},
            'ftdi_location': {'title': 'FTDI Device', 'phrase': 'ftdi phrase'},
            'i2c_location': {'title': 'I2C Address', 'phrase': 'i2c phrase'},
            'i2c_bus': {'title': 'I2C Bus', 'phrase': 'bus phrase'}})


@pytest.mark.parametrize('key,attr', [('uart_location', 'uart_location'),
                                      ('ftdi_location', 'ftdi_location')])
def test_field_renders_with_stored_value(app, key, attr):
    dev = Input(unique_id='in-1', name='s', device='X', **{attr: '/dev/ttyUSB0'})
    with app.test_request_context():
        html = _render(PARTIAL_FOR[key], InputMod(), dev, [key])
    assert 'name="%s"' % key in html
    assert 'value="/dev/ttyUSB0"' in html
    assert 'disabled' not in html


def test_field_hidden_when_not_declared(app):
    dev = Input(unique_id='in-1', name='s', device='X')
    with app.test_request_context():
        assert 'uart_location' not in _render('UART.html', InputMod(), dev, [])


def test_field_disabled_when_locked(app):
    dev = Input(unique_id='in-1', name='s', device='X', uart_location='/dev/ttyAMA0')
    with app.test_request_context():
        html = _render('UART.html', InputMod(), dev, [], disabled=['uart_location'])
    assert 'name="uart_location"' in html and 'disabled' in html


def test_output_form_renders_field_too(app):
    dev = Output(unique_id='out-1', name='p', output_type='X', uart_location='/dev/serial0')
    with app.test_request_context():
        html = _render('UART.html', OutputMod(), dev, ['uart_location'])
    assert 'value="/dev/serial0"' in html


def test_input_save_persists_uart_and_ftdi_location(app):
    Input(unique_id='in-1', name='s', device='X', uart_location='/dev/ttyAMA0').save()
    data = {'input_id': 'in-1', 'name': 's', 'unique_id': 'in-1',
            'uart_location': '/dev/ttyUSB0', 'ftdi_location': 'ftdi://ftdi:232h/1'}
    with app.test_request_context(method='POST', data=data):
        form = InputMod()
        with mock.patch.object(utils_input, 'parse_input_information',
                               return_value={'X': {'options_enabled': ['uart_location']}}), \
                mock.patch('aot.aot_flask.access.scope.can_operate_device', return_value=True), \
                mock.patch.object(utils_input, 'check_input_channels_exist',
                                  side_effect=lambda d, dev, uid, m: m), \
                mock.patch.object(utils_input.utils_measurement, 'measurement_mod_form',
                                  side_effect=lambda m, r, f: (m, r)):
            try:
                utils_input.input_mod(form, request.form)
            except KeyError:
                pass  # 이후 단계(채널·옵션 처리)는 이 테스트의 관심 밖이다
            db.session.commit()
        db.session.expire_all()
    saved = Input.query.filter_by(unique_id='in-1').first()
    assert saved.uart_location == '/dev/ttyUSB0'
    assert saved.ftdi_location == 'ftdi://ftdi:232h/1'


# --- I2C 스캔 -----------------------------------------------------------------

I2CDETECT_OUT = """\
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- 44 -- -- -- -- -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- -- -- -- UU -- -- --
70: -- -- -- -- -- -- 76 --
"""


def test_parse_i2cdetect_addresses_and_in_use():
    from aot.aot_flask.utils import utils_i2c_scan as S
    found, in_use = S.parse_i2cdetect(I2CDETECT_OUT)
    assert found == ['0x44', '0x76']
    assert in_use == ['0x5c']
    assert S.parse_i2cdetect('') == ([], [])


def test_scan_bus_paths():
    from aot.aot_flask.utils import utils_i2c_scan as S
    done = mock.Mock(returncode=0, stdout=I2CDETECT_OUT, stderr='')
    with mock.patch.object(S, 'available_buses', return_value=[1]):
        with mock.patch.object(S.subprocess, 'run', return_value=done) as run:
            res = S.scan_bus(1)
        run.assert_called_once()
        assert run.call_args[0][0] == ['i2cdetect', '-y', '1']  # 셸을 거치지 않는다
        assert res == {'ok': True, 'bus': 1, 'addresses': ['0x44', '0x76'],
                       'in_use': ['0x5c']}
        assert S.scan_bus(9)['error'] == 'no_bus'
        with mock.patch.object(S.subprocess, 'run', side_effect=FileNotFoundError):
            assert S.scan_bus(1)['error'] == 'no_tool'
        with mock.patch.object(S.subprocess, 'run',
                               return_value=mock.Mock(returncode=1, stdout='', stderr='x')):
            assert S.scan_bus(1)['error'] == 'failed'


def _call_route(env, query):
    from aot.aot_flask import routes_input
    view = routes_input.page_i2c_scan.__wrapped__
    with mock.patch('aot.utils.system_environment.detect', return_value=env):
        app = Flask(__name__)
        with app.test_request_context('/i2c_scan' + query):
            resp = view()
    return resp


def test_route_unsupported_in_docker_and_without_i2c():
    for env in ({'platform_type': 'docker', 'capabilities': {'i2c': True}},
                {'platform_type': 'pi', 'capabilities': {'i2c': False}}):
        assert _call_route(env, '?bus=1').get_json() == {'ok': False, 'error': 'unsupported'}


def test_route_scans_and_rejects_bad_bus():
    from aot.aot_flask.utils import utils_i2c_scan as S
    env = {'platform_type': 'pi', 'capabilities': {'i2c': True}}
    with mock.patch.object(S, 'scan_bus', return_value={'ok': True}) as scan:
        assert _call_route(env, '?bus=3').get_json() == {'ok': True}
        scan.assert_called_once_with(3)
    resp = _call_route(env, '?bus=abc')
    assert resp[1] == 400


def test_i2c_partial_has_working_scan_button(app):
    dev = Input(unique_id='in-1', name='s', device='X', i2c_location='0x44', i2c_bus=1)
    with app.test_request_context():
        html = _render('I2C.html', InputMod(), dev, ['i2c_location'])
    assert 'aotI2cScan(this)' in html and "'i2c_scan'" not in html

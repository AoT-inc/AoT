# coding=utf-8
"""/settings/pi — raspi-config 상태 읽기와 버튼 명령 (subprocess 는 전부 모킹)."""
import subprocess
from unittest import mock

import pytest

from aot.utils import system_pi


def _fake_run(values):
    """getter 이름 -> stdout 문자열. raspi-config 는 켜짐=0, 꺼짐=1 을 stdout 으로 낸다."""
    def run(args, **kwargs):
        assert args[:2] == ['raspi-config', 'nonint']
        return subprocess.CompletedProcess(args, 0, stdout=values[args[2]] + '\n', stderr='')
    return run


def test_zero_means_enabled_and_one_means_disabled():
    values = {'get_i2c': '0', 'get_onewire': '1', 'get_serial_hw': '0',
              'get_serial_cons': '1', 'get_spi': '1', 'get_ssh': '0'}
    with mock.patch.object(system_pi, 'raspi_config_available', return_value=True), \
            mock.patch.object(system_pi.subprocess, 'run', side_effect=_fake_run(values)):
        s = system_pi.get_raspi_config_settings()
    assert s['available'] is True
    assert s['i2c_enabled'] is True
    assert s['one_wire_enabled'] is False
    assert s['serial_enabled'] is True
    assert s['serial_console_enabled'] is False
    assert s['spi_enabled'] is False
    assert s['ssh_enabled'] is True
    assert s['hostname']


def test_unreadable_value_is_none():
    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 127, stdout='', stderr='unknown')
    with mock.patch.object(system_pi, 'raspi_config_available', return_value=True), \
            mock.patch.object(system_pi.subprocess, 'run', side_effect=run):
        s = system_pi.get_raspi_config_settings()
    assert s['i2c_enabled'] is None


def test_missing_raspi_config_binary_is_none():
    with mock.patch.object(system_pi, 'raspi_config_available', return_value=True), \
            mock.patch.object(system_pi.subprocess, 'run', side_effect=FileNotFoundError):
        assert system_pi.get_raspi_config_settings()['ssh_enabled'] is None


def test_unavailable_without_raspi_config_runs_nothing():
    with mock.patch.object(system_pi, 'raspi_config_available', return_value=False), \
            mock.patch.object(system_pi.subprocess, 'run') as run:
        s = system_pi.get_raspi_config_settings()
    assert s['available'] is False and 'i2c_enabled' not in s
    run.assert_not_called()


def test_available_false_in_docker():
    with mock.patch('aot.utils.system_environment.is_docker', return_value=True), \
            mock.patch.object(system_pi.shutil, 'which', return_value='/usr/bin/raspi-config'):
        assert system_pi.raspi_config_available() is False


class _Btn:
    def __init__(self, data=False):
        self.data = data


class _Form:
    def __init__(self, pressed):
        names = ['enable_i2c', 'disable_i2c', 'enable_one_wire', 'disable_one_wire',
                 'enable_serial', 'disable_serial', 'enable_serial_console',
                 'disable_serial_console', 'enable_spi', 'disable_spi',
                 'enable_ssh', 'disable_ssh', 'change_hostname',
                 'change_pigpiod_sample_rate']
        for n in names:
            setattr(self, n, _Btn(n == pressed))


@pytest.mark.parametrize('button,command', [
    ('enable_i2c', 'do_i2c 0'), ('disable_i2c', 'do_i2c 1'),
    ('enable_one_wire', 'do_onewire 0'), ('disable_one_wire', 'do_onewire 1'),
    ('enable_serial', 'do_serial_hw 0'), ('disable_serial', 'do_serial_hw 1'),
    ('enable_serial_console', 'do_serial_cons 0'),
    ('disable_serial_console', 'do_serial_cons 1'),
    ('enable_spi', 'do_spi 0'), ('disable_spi', 'do_spi 1'),
    ('enable_ssh', 'do_ssh 0'), ('disable_ssh', 'do_ssh 1'),
])
def test_button_runs_matching_command(button, command):
    from aot.aot_flask.utils import utils_settings
    with mock.patch.object(utils_settings, 'raspi_config_available', return_value=True), \
            mock.patch.object(utils_settings, 'cmd_output', return_value=('', '', 0)) as cmd, \
            mock.patch.object(utils_settings, 'url_for', return_value='/'), \
            mock.patch.object(utils_settings, 'gettext', side_effect=lambda m, **k: m), \
            mock.patch.object(utils_settings, 'flash_success_errors'):
        utils_settings.settings_pi_mod(_Form(button))
    cmd.assert_called_once_with('raspi-config nonint ' + command, user='root')


def test_no_command_without_raspi_config():
    from aot.aot_flask.utils import utils_settings
    with mock.patch.object(utils_settings, 'raspi_config_available', return_value=False), \
            mock.patch.object(utils_settings, 'cmd_output') as cmd, \
            mock.patch.object(utils_settings, 'gettext', side_effect=lambda m, **k: m), \
            mock.patch.object(utils_settings, 'flash'):
        utils_settings.settings_pi_mod(_Form('enable_i2c'))
    cmd.assert_not_called()


@pytest.mark.parametrize('filename,state', [
    ('pigpiod_low.service', 'low'), ('pigpiod_high.service', 'high'),
    ('pigpiod_disabled.service', 'disabled'),
    ('pigpiod_uninstalled.service', 'uninstalled'), (None, ''),
])
def test_pigpiod_state_from_service_files(tmp_path, filename, state):
    if filename:
        (tmp_path / filename).touch()
    assert system_pi.get_pigpiod_state(str(tmp_path)) == state

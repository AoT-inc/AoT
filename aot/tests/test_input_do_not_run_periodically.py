# coding=utf-8
"""명령으로만 값을 받는 입력은 주기 읽기를 하지 않는다 (2026-09-25).

`AoT: Test Input: Save your own measurement value`(TEST_SAVE_VALUE) 는
`'do_not_run_periodically': True` 를 선언하고 값은 사용자 정의 명령
(측정값 저장)으로만 받는다. 그런데 `InputController` 가 이 플래그를 보지 않고
`get_measurement()` 가 오버라이드됐다는 이유만으로 주기 읽기를 돌렸다. 빈
`get_measurement()` 는 None 을 돌려주므로 매 주기 StopIteration 이 났고, 3번마다
"StopIteration raised 3 times. Possibly could not read input" 이 ERROR 로
시스템 로그에 쌓였다.

이 파일이 잠그는 것:
- 플래그를 선언한 입력은 has_loop=False 가 되어 주기 읽기(update_measure)가
  돌지 않는다.
- 플래그가 없는 폴링 입력의 실제 읽기 실패는 지금처럼 ERROR 로 남는다.
"""
import logging
import types
from unittest import mock

import pytest

from aot.controllers import controller_input as ci
from aot.inputs import aot_test_input_save_value as save_value_module
from aot.inputs.base_input import AbstractInput
from aot.utils.inputs import parse_input_information


class _FailingPollInput(AbstractInput):
    """주기 읽기를 하지만 매번 값을 못 읽는 입력."""

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

    def initialize(self):
        pass

    def get_measurement(self):
        return None


def _input_dev(device):
    dev = mock.MagicMock()
    dev.unique_id = 'test-input'
    dev.name = 'test input'
    dev.device = device
    dev.interface = None
    dev.period = 15
    dev.start_offset = 0
    dev.pre_output_id = None
    dev.log_level_debug = False
    return dev


def _make_controller(monkeypatch, device, dict_inputs, module_cls):
    input_dev = _input_dev(device)

    def fake_db(table, **kwargs):
        if table is ci.Input:
            return input_dev
        if table is ci.SMTP:
            return None
        return mock.MagicMock()

    monkeypatch.setattr(ci, 'db_retrieve_table_daemon', fake_db)
    monkeypatch.setattr(ci, 'parse_input_information', lambda: dict_inputs)
    monkeypatch.setattr(
        ci, 'load_module_from_file',
        lambda path, kind: (types.SimpleNamespace(
            InputModule=lambda dev: module_cls(dev, testing=True)), 'ok'))
    monkeypatch.setattr(ci, 'DaemonControl', mock.MagicMock)

    controller = ci.InputController(mock.MagicMock(), 'test-input')
    controller.initialize_variables()
    return controller


def test_save_value_input_declares_flag():
    info = parse_input_information()['TEST_SAVE_VALUE']
    assert info.get('do_not_run_periodically') is True


def test_command_only_input_is_not_polled(monkeypatch, caplog):
    dict_inputs = {'TEST_SAVE_VALUE': parse_input_information()['TEST_SAVE_VALUE']}
    controller = _make_controller(
        monkeypatch, 'TEST_SAVE_VALUE', dict_inputs, save_value_module.InputModule)

    assert controller.has_loop is False
    assert controller.comm_capable() is False

    # 여러 주기가 지나도 읽기를 시도하지 않는다.
    with mock.patch.object(controller, 'update_measure') as update_measure, \
            caplog.at_level(logging.ERROR):
        for _ in range(5):
            controller.next_measurement = 0
            controller.loop()
    update_measure.assert_not_called()
    assert 'StopIteration' not in caplog.text


def test_polling_input_read_failure_still_logged(monkeypatch):
    dict_inputs = {'FAILING_POLL': {'file_path': 'unused'}}
    controller = _make_controller(
        monkeypatch, 'FAILING_POLL', dict_inputs, _FailingPollInput)

    assert controller.has_loop is True

    with mock.patch.object(controller.logger, 'error') as log_error:
        for _ in range(3):
            controller.update_measure()
    messages = [c.args[0] for c in log_error.call_args_list]
    assert any('StopIteration raised 3 times' in m for m in messages)
    assert controller.measurement_success is False

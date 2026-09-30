# coding=utf-8
"""condition() 이 데몬 응답 지연(Pyro TimeoutError)에도 사이클을 죽이지 않는지 확인."""
import logging
from unittest import mock

import Pyro5.errors

from aot.controllers.base_conditional import AbstractConditional

FULL_ID = "3eba687f-ff3a-49dd-9f04-8228521f3f13"


def _make():
    with mock.patch("aot.controllers.base_conditional.DaemonControl"):
        return AbstractConditional(logging.getLogger("t"), "fid", "")


def test_condition_retries_once_then_returns_value():
    cond = _make()
    cond.control.get_condition_measurement.side_effect = [
        Pyro5.errors.TimeoutError("receiving: timeout"), 21.5]
    assert cond.condition(FULL_ID) == 21.5
    assert cond.control.get_condition_measurement.call_count == 2


def test_condition_returns_none_when_daemon_keeps_timing_out():
    cond = _make()
    cond.control.get_condition_measurement.side_effect = \
        Pyro5.errors.TimeoutError("receiving: timeout")
    assert cond.condition(FULL_ID) is None


def test_condition_dict_returns_none_on_communication_error():
    cond = _make()
    cond.control.get_condition_measurement_dict.side_effect = \
        Pyro5.errors.CommunicationError("connection lost")
    assert cond.condition_dict(FULL_ID) is None

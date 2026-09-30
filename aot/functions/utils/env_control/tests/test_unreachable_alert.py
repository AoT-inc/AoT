"""목표에 못 닿을 때의 경보 — 장치 점검 요구는 능동 장치가 있을 때만 (2026-09-26).

실측(영양 육묘장 09-24~26 밤): VPD 를 올릴 수단이 창·커튼(수동)뿐이라 실외가
허락하지 않으면 못 닿는데, "[action required] … Actuator check needed" 가 36회 나왔고
긴급 메일 경로까지 탔다.
"""
import logging
import types

import pytest

from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    HelpersMixin,
)
from aot.functions.utils.env_control.types import TargetVar


class _Host(HelpersMixin):
    def __init__(self):
        self.logger = logging.getLogger('test_unreachable_alert')
        self.mails = []
        self._last_situation_modes = []
        self._unattainable_state = {}

    def _send_critical_email(self, key, body):
        self.mails.append(key)


def _situation(level):
    return types.SimpleNamespace(
        modes=[], authority={'VPD_up': level, 'VPD_down': level,
                             'T_up': level, 'T_down': level,
                             'RH_up': level, 'RH_down': level},
        target={'vpd': TargetVar(1.0, 0.1, 1.2)},
        deviation_native={'vpd': -0.8})


@pytest.mark.parametrize('level,expect_mail', [('P', False), ('A', True)])
def test_수동_장치뿐이면_점검을_요구하지_않는다(monkeypatch, caplog, level, expect_mail):
    import aot.functions.utils.env_control.authority as au
    lv = {'P': au.LEVEL_PASSIVE, 'A': au.LEVEL_ACTIVE}[level]
    monkeypatch.setattr(au, 'detect_unattainable', lambda **k: ['vpd'])
    monkeypatch.setattr(au, 'needed_direction_authority', lambda auth, var, dev: lv)
    host = _Host()
    with caplog.at_level(logging.INFO, logger='test_unreachable_alert'):
        host._emit_authority_alerts(_situation(lv))
    warned = any('action required' in r.getMessage() for r in caplog.records)
    assert warned is expect_mail
    assert bool(host.mails) is expect_mail

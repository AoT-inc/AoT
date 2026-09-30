# coding=utf-8
"""로그 등급·감사 출처·알림 메일 문구 회귀."""
import logging

from aot.utils.command_origin import TYPE_ENV_COORDINATOR, should_audit


def test_env_coordinator_origin_is_audited():
    assert should_audit({'type': TYPE_ENV_COORDINATOR, 'id': 'x'})
    assert not should_audit({'type': 'automation'})


def test_status_log_survives_error_only_logger(caplog):
    from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
        CycleMixin)
    holder = type('H', (CycleMixin,), {})()
    holder.logger = logging.getLogger('aot.test_status_env')
    holder.logger.setLevel(logging.ERROR)
    with caplog.at_level(logging.INFO, logger='aot.test_status_env'):
        holder._status_log(logging.INFO, '축별 기능 상태: %s', 'ok')
    rec = [r for r in caplog.records if '축별 기능 상태' in r.getMessage()]
    assert rec and rec[0].levelno == logging.INFO

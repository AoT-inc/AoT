# coding=utf-8
"""Conditional의 Refractory Period(불응기) — 액션 반복 발동 억제.

`refractory_period`는 forms_conditional.py 에만 있고 템플릿·저장 경로·DB 컬럼
어디에도 없던 죽은 필드였다(2026-09-25 발견). 지금까지 period 마다 조건이
계속 참이면 conditional_statement 가 매 주기 self.run_action()/
self.run_all_actions() 를 불러 알림이 그만큼 반복 발송됐고, 유일한 우회책은
`hasattr(self, ...)` 로 직접 래치를 구현하는 것뿐이었다(docs/Functions.md
예시 7).

이 테스트는 `AbstractConditional._refractory_gate()` — run_action()/
run_all_actions() 가 실제로 액션을 디스패치하기 전에 거치는 게이트 — 를
DB·Pyro 없이 검증한다. `db_retrieve_table_daemon`/`session_scope` 를 가짜로
바꿔치기해서, `set_custom_option()`(Conditional.custom_options 에 마지막 발동
시각을 저장하는 기존 인프라)이 쓴 값을 다음 판정이 그대로 읽게 한다 — 이게
"데몬이 재시작돼도 불응기가 유지된다"는 요구사항의 핵심이다.

DB·데몬·무선을 쓰지 않는다(라이브 DB 대상 테스트 금지 규칙).
"""
import json
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

from aot.controllers.base_conditional import AbstractConditional
from aot.controllers.controller_conditional import ConditionalController


class _FakeControl:
    """DaemonControl 대역 — 실제 Pyro RPC를 전혀 만들지 않는다."""

    def __init__(self):
        self.trigger_action_calls = []
        self.trigger_all_actions_calls = []

    def trigger_action(self, action_id, value=None, debug=False):
        self.trigger_action_calls.append((action_id, value))
        return {}

    def trigger_all_actions(self, function_id, message='', debug=False):
        self.trigger_all_actions_calls.append((function_id, message))
        return message


class _FakeSession:
    """session_scope(AOT_DB_PATH) 가 내주는 세션 대역.

    query(Conditional).filter(...).first() 체인만 흉내내고, 항상 같은 row
    객체를 돌려준다 — set_custom_option() 이 그 row.custom_options 를 직접
    수정하므로, 다음 db_retrieve_table_daemon() 호출도 같은 객체를 봐야
    "저장된 값을 다시 읽는다"가 성립한다.
    """

    def __init__(self, row):
        self._row = row

    def query(self, _model):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._row

    def commit(self):
        pass


def _row(refractory_period=0.0, custom_options='{}'):
    return SimpleNamespace(
        unique_id='cccccccc-0000-0000-0000-000000000000',
        refractory_period=refractory_period,
        custom_options=custom_options)


def _patch_db(monkeypatch, row):
    """db_retrieve_table_daemon()과 session_scope()를 모두 이 row에 묶는다."""
    monkeypatch.setattr(
        'aot.controllers.base_conditional.db_retrieve_table_daemon',
        lambda *a, **k: row)

    @contextmanager
    def _fake_session_scope(*_args, **_kwargs):
        yield _FakeSession(row)

    monkeypatch.setattr(
        'aot.controllers.base_conditional.session_scope', _fake_session_scope)


def _make_conditional(row):
    cond = AbstractConditional(
        logger=Mock(), function_id=row.unique_id, message='')
    cond.control = _FakeControl()
    return cond


def _last_fired(row):
    return json.loads(row.custom_options).get('__aot_refractory_last_fired_ts__')


class TestRefractoryDisabled:
    """refractory_period 가 0(기본값)이면 기존 동작과 동일 — 매번 발동한다."""

    def test_zero_allows_every_call(self, monkeypatch):
        row = _row(refractory_period=0.0)
        _patch_db(monkeypatch, row)
        cond = _make_conditional(row)

        cond.run_all_actions()
        cond.run_all_actions()

        assert len(cond.control.trigger_all_actions_calls) == 2

    def test_conditional_row_missing_fails_open(self, monkeypatch):
        """Conditional 행을 못 읽으면(DB 오류·행 삭제) 억제하지 않는다 —
        불응기 판정 실패가 알림 자체를 막아서는 안 된다."""
        monkeypatch.setattr(
            'aot.controllers.base_conditional.db_retrieve_table_daemon',
            lambda *a, **k: None)
        cond = _make_conditional(_row())

        cond.run_all_actions()

        assert len(cond.control.trigger_all_actions_calls) == 1
        assert cond.action_fired is True


class TestRefractoryCooldown:
    """refractory_period > 0 — 마지막 발동 후 그 시간 동안 재발동을 억제한다."""

    def test_first_fire_is_allowed_and_records_timestamp(self, monkeypatch):
        row = _row(refractory_period=300)
        _patch_db(monkeypatch, row)
        cond = _make_conditional(row)

        cond.run_all_actions()

        assert len(cond.control.trigger_all_actions_calls) == 1
        assert cond.action_fired is True
        assert _last_fired(row) is not None

    def test_next_cycle_within_cooldown_is_suppressed(self, monkeypatch):
        row = _row(
            refractory_period=300,
            custom_options=json.dumps(
                {'__aot_refractory_last_fired_ts__': time.time()}))
        _patch_db(monkeypatch, row)
        cond = _make_conditional(row)

        # 새 check_conditionals() 주기 시작을 흉내(컨트롤러가 매 주기 리셋)
        cond._refractory_gate_result = None
        cond.run_all_actions()

        assert cond.control.trigger_all_actions_calls == []
        assert cond.action_fired is False

    def test_cycle_after_cooldown_elapsed_fires_again(self, monkeypatch):
        row = _row(
            refractory_period=60,
            custom_options=json.dumps(
                {'__aot_refractory_last_fired_ts__': time.time() - 61}))
        _patch_db(monkeypatch, row)
        cond = _make_conditional(row)

        cond._refractory_gate_result = None
        cond.run_all_actions()

        assert len(cond.control.trigger_all_actions_calls) == 1
        assert cond.action_fired is True

    def test_run_action_is_suppressed_and_returns_none(self, monkeypatch):
        row = _row(
            refractory_period=300,
            custom_options=json.dumps(
                {'__aot_refractory_last_fired_ts__': time.time()}))
        _patch_db(monkeypatch, row)
        cond = _make_conditional(row)
        cond._refractory_gate_result = None

        result = cond.run_action('dddddddd-0000-0000-0000-000000000000')

        assert result is None
        assert cond.control.trigger_action_calls == []
        assert cond.action_fired is False

    def test_multiple_actions_in_same_cycle_do_not_suppress_each_other(self, monkeypatch):
        """한 알림 이벤트에서 장치를 켜고 이메일도 보내는 것처럼 같은 사이클
        안의 여러 run_action()/run_all_actions() 호출은 서로를 억제하면 안
        된다 — 불응기는 사이클 사이에만 적용된다."""
        row = _row(refractory_period=300)
        _patch_db(monkeypatch, row)
        cond = _make_conditional(row)

        cond.run_action('dddddddd-0000-0000-0000-000000000000')
        cond.run_all_actions()

        assert len(cond.control.trigger_action_calls) == 1
        assert len(cond.control.trigger_all_actions_calls) == 1


class TestControllerResetsRefractoryGateEveryCycle:
    """ConditionalController.check_conditionals() 는 action_fired 와 함께
    _refractory_gate_result 도 매 주기 시작에서 리셋해야 한다 — 안 그러면
    첫 주기의 판정이 데몬이 도는 내내 굳어버린다."""

    def _make_controller(self):
        ctrl = ConditionalController.__new__(ConditionalController)
        ctrl.pause_loop = False
        ctrl.is_activated = True
        ctrl.period = 60
        ctrl.timer_period = time.time() - 1
        ctrl.unique_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        ctrl.logger = Mock()
        ctrl.message_include_code = False
        return ctrl

    def test_reset_before_running_user_code(self, monkeypatch):
        cond_row = Mock()
        cond_row.name = 'Test Conditional'
        monkeypatch.setattr(
            'aot.controllers.controller_conditional.db_retrieve_table_daemon',
            lambda *a, **k: cond_row)

        ctrl = self._make_controller()
        ctrl.time_conditional = time.time()
        ctrl.conditional_run = Mock(action_fired=True, _refractory_gate_result=True)

        ctrl.check_conditionals()

        assert ctrl.conditional_run.action_fired is False
        assert ctrl.conditional_run._refractory_gate_result is None

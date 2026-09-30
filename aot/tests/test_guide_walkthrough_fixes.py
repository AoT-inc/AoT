# coding=utf-8
"""가이드 따라 하기에서 나온 오류 목록의 회귀 테스트.

- 수동 출력 제어가 감사로그를 한 번만 남기는지(웹 라우트와 데몬 게이트가 둘 다 적던 것).
- 위젯 옵션 부분 저장이 동시에 와도 서로의 키를 지우지 않는지.
"""
import os
import threading
import time

import pytest

os.environ["ALEMBIC_RUNNING"] = "1"


def _call_output_mod(monkeypatch, daemon_result):
    from aot.aot_flask import routes_general as rg

    calls = []

    class _Daemon:
        def output_on_off(self, *a, **kw):
            return daemon_result

    class _Scope:
        @staticmethod
        def can_operate_device(_):
            return True

    monkeypatch.setattr(rg, 'DaemonControl', _Daemon)
    monkeypatch.setattr(rg.utils_general, 'user_has_permission', lambda _: True)
    monkeypatch.setattr(rg, 'scope', _Scope)
    monkeypatch.setattr(rg, 'db_retrieve_table', lambda _: type(
        'Q', (), {'filter': lambda self, *_: type(
            'R', (), {'first': lambda self: None})()})())
    monkeypatch.setattr(rg, 'audit_log', lambda *a, **kw: calls.append(kw))
    monkeypatch.setattr(rg, '_output_success_message', lambda *a, **kw: 'ok')
    view = rg.output_mod.__wrapped__
    return view, calls


def test_manual_output_success_is_not_audited_twice(monkeypatch):
    """데몬 게이트가 이미 출처와 함께 남긴다 — 라우트가 또 적으면 한 번의 클릭이 두 줄이 된다."""
    view, calls = _call_output_mod(monkeypatch, (0, 'ok'))
    assert view('out', '0', 'on', 'value', '90').startswith('SUCCESS')
    assert calls == []


def test_manual_output_failure_is_still_recorded(monkeypatch):
    """RPC 시간 초과처럼 데몬이 기록하지 못하는 실패는 여기가 유일한 흔적이다."""
    view, calls = _call_output_mod(monkeypatch, (1, 'timeout'))
    assert view('out', '0', 'on', 'value', '90').startswith('ERROR')
    assert len(calls) == 1 and calls[0]['result'] == 'failure'


def test_widget_options_lock_serializes_read_modify_write():
    """락 안에서는 한 번에 하나만 — 앞 요청이 쓴 값을 뒤 요청이 읽는다."""
    from aot.aot_flask.routes_dashboard import _widget_options_lock

    state = {'opts': {}}

    def save(key):
        with _widget_options_lock():
            current = dict(state['opts'])
            time.sleep(0.05)   # 락이 없으면 여기서 서로 옛 값을 읽는다
            current[key] = True
            state['opts'] = current

    threads = [threading.Thread(target=save, args=(k,))
               for k in ('site', 'zone', 'facility')]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert state['opts'] == {'site': True, 'zone': True, 'facility': True}


def test_action_row_select_leaves_room_for_caret():
    """동작 줄 셀렉트의 ▼ 는 오른쪽 20px 을 쓴다 — 버튼 padding-right 가 그보다 커야 글자를 안 덮는다."""
    import re

    css_path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask', 'static',
                            'css', 'components', 'aot-action-row.css')
    css = open(css_path, encoding='utf-8').read()
    rule = re.search(
        r'\.aot-action-field-select\.bootstrap-select > \.dropdown-toggle \{([^}]*)\}', css)
    assert rule, '동작 줄 셀렉트 버튼 규칙이 없다'
    pad = re.search(r'padding-right:\s*(\d+)px', rule.group(1))
    assert pad and int(pad.group(1)) >= 20
    # fit-width 가 라벨을 inline 으로 돌리면 text-overflow 가 안 들어 `…` 없이 잘린다
    assert re.search(r'fit-width > \.dropdown-toggle \.filter-option-inner-inner \{\s*display: block',
                     css)

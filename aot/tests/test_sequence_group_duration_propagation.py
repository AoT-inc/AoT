# coding=utf-8
"""장치 그룹은 작동시간 하나를 공유한다 — 어느 경로로 고쳐도 그렇다.

AJAX 경로(`/function_sequence_update_action_duration`)는 오래전부터 그룹 전원에
시간을 퍼뜨렸지만, 함수 옵션 페이지의 폼 저장 경로(`utils_action.action_mod`)만
빠져 있었다. 그 결과 그룹원 한 명만 시간이 바뀌고, 위젯은 각자의 값을 그대로
보여 주는데(`widget_trigger_sequence` 렌더) 실제 실행은 대표 하나의 값만 쓴다
(`controller_trigger_sequence._build_slots`). 즉 화면에 뜬 시간 중 하나는
거짓말이었다 — 관수 시간이라 현장에서 오판을 부른다.
"""
import json
from unittest.mock import MagicMock, patch

import pytest


def _action(uid, group, duration, function_id='fn-1'):
    a = MagicMock()
    a.unique_id = uid
    a.function_id = function_id
    a.action_type = 'output_state'
    a.custom_options = json.dumps({'group_name': group, 'action_duration': duration})
    return a


def _run_action_mod(target, members, request_form):
    """`action_mod` 의 그룹 전파 구간만 실제 코드로 돌린다.

    폼/DB 전체를 세우는 대신 Actions 조회와 커밋만 대역으로 두고, 전파 로직
    자체는 손대지 않은 원본을 태운다.
    """
    from aot.aot_flask.utils import utils_action as ua

    form = MagicMock()
    form.action_id.data = target.unique_id

    query = MagicMock()
    query.filter.return_value.first.return_value = target
    query.filter.return_value.all.return_value = members

    def _fake_custom_options_return_json(errors, dict_actions, request_form_,
                                         mod_dev=None, device=None):
        return errors, mod_dev.custom_options

    with patch.object(ua, 'Actions') as MockActions, \
         patch.object(ua, 'db') as mock_db, \
         patch.object(ua, 'custom_options_return_json',
                      side_effect=_fake_custom_options_return_json), \
         patch.object(ua, 'parse_action_information',
                      return_value={'output_state': {}}), \
         patch.object(ua, 'which_controller', return_value=('Trigger', 'fn-1')):
        MockActions.query = query
        MockActions.function_id = MagicMock()
        MockActions.unique_id = MagicMock()
        mock_db.session = MagicMock()
        ua.action_mod(form, request_form)


def _duration_of(action):
    return json.loads(action.custom_options).get('action_duration')


class TestGroupDurationPropagation:

    def test_같은_그룹_멤버에게_시간이_퍼진다(self):
        target = _action('a1', 'A', 1800)
        peer = _action('a2', 'A', 1800)
        _run_action_mod(target, [peer], {'action_duration': '3600'})

        assert _duration_of(target) == 3600
        assert _duration_of(peer) == 3600, "그룹원에게 전파되지 않았다"

    def test_다른_그룹은_건드리지_않는다(self):
        target = _action('a1', 'A', 1800)
        other = _action('a2', 'B', 900)
        _run_action_mod(target, [other], {'action_duration': '3600'})

        assert _duration_of(other) == 900, "다른 그룹 시간까지 덮었다"

    def test_그룹이_없으면_아무에게도_안_퍼진다(self):
        target = _action('a1', '', 1800)
        loner = _action('a2', '', 900)
        _run_action_mod(target, [loner], {'action_duration': '3600'})

        assert _duration_of(loner) == 900

    def test_시간을_안_보낸_저장은_전파하지_않는다(self):
        """그룹명만 바꾸는 저장이 남의 시간을 덮어쓰면 안 된다."""
        target = _action('a1', 'A', 1800)
        peer = _action('a2', 'A', 900)
        _run_action_mod(target, [peer], {'group_name': 'A'})

        assert _duration_of(peer) == 900

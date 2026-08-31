# coding=utf-8
"""per_day → shared 로 돌아가도 요일별 그룹·작동시간이 사라지지 않아야 한다.

예전에는 창 시간(start/end/period)만 대표 요일에서 shared 로 옮기고
groups/durations 는 버렸다. shared 모드는 요일별 맵을 읽지 않으므로, 요일별로
짜 둔 그룹 구성과 관수 시간이 버튼 한 번에 조용히 사라졌다 — 전역값은 이미
다른 값이라 되돌릴 수도 없었다.

대표 요일은 창 시간과 **같은 규칙**(첫 활성 요일)이어야 한다. 규칙이 갈리면
"어떤 요일이 공통이 된 것인가" 를 사용자가 알 수 없다.
"""
import json
from unittest.mock import MagicMock, patch

import flask
import pytest

import aot.aot_flask.routes_function as rf


def _entry(start='05:30', end='21:00', period=3600, enabled=True, **extra):
    e = {'start': start, 'end': end, 'period': period, 'enabled': enabled}
    e.update(extra)
    return e


def _per_day_schedule(days):
    return {
        'version': 1,
        'mode': 'per_day',
        'shared': _entry(),
        'days': {str(i): days[i] for i in range(7)},
    }


def _action(uid, opts):
    a = MagicMock()
    a.unique_id = uid
    a.function_id = 'fn-1'
    a.custom_options = json.dumps(opts)
    return a


def _switch_to_shared(old_schedule, actions):
    """저장된 per_day 스케줄을 두고, shared 스케줄을 저장 요청한다."""
    app = flask.Flask(__name__)
    trigger = MagicMock(unique_id='fn-1', timer_schedule=json.dumps(old_schedule))

    new_schedule = {
        'version': 1,
        'mode': 'shared',
        'shared': _entry(),
        'days': {str(i): _entry() for i in range(7)},
    }

    tq = MagicMock()
    tq.filter_by.return_value.first.return_value = trigger
    aq = MagicMock()
    aq.filter.return_value.all.return_value = actions

    with app.test_request_context(json={'function_id': 'fn-1', 'schedule': new_schedule}), \
         patch.object(rf, 'Trigger', MagicMock(query=tq)), \
         patch.object(rf, 'Actions', MagicMock(query=aq)), \
         patch.object(rf, 'db', MagicMock()), \
         patch.object(rf, 'DaemonControl', MagicMock()), \
         patch.object(rf.utils_general, 'user_has_permission', return_value=True):
        resp = rf.function_sequence_update_schedule.__wrapped__()
    body = resp[0] if isinstance(resp, tuple) else resp
    return body.get_json()


def _opts(action):
    return json.loads(action.custom_options)


class TestPerDayToShared:

    def test_대표요일의_그룹과_시간이_전역으로_올라간다(self):
        days = [_entry(enabled=False) for _ in range(7)]
        # 첫 활성 요일 = 수요일(3). 여기 설정이 공통이 되어야 한다.
        days[3] = _entry(enabled=True,
                         groups={'a1': 'A', 'a2': 'A'},
                         durations={'a1': 1800.0, 'a2': 1800.0})
        actions = [_action('a1', {'group_name': '', 'action_duration': 60.0}),
                   _action('a2', {'group_name': '', 'action_duration': 60.0})]

        out = _switch_to_shared(_per_day_schedule(days), actions)

        assert out.get('status') == 'success'
        assert _opts(actions[0])['group_name'] == 'A'
        assert _opts(actions[0])['action_duration'] == 1800.0
        assert _opts(actions[1])['group_name'] == 'A'

    def test_대표요일은_창시간과_같은_첫_활성요일이다(self):
        days = [_entry(enabled=False) for _ in range(7)]
        days[2] = _entry(enabled=True, groups={'a1': '화요일그룹'})
        days[5] = _entry(enabled=True, groups={'a1': '금요일그룹'})
        actions = [_action('a1', {'group_name': ''})]

        _switch_to_shared(_per_day_schedule(days), actions)

        assert _opts(actions[0])['group_name'] == '화요일그룹', \
            "창 시간과 다른 요일을 대표로 골랐다"

    def test_요일별_설정이_없으면_전역값을_건드리지_않는다(self):
        days = [_entry(enabled=True) for _ in range(7)]
        actions = [_action('a1', {'group_name': 'X', 'action_duration': 60.0})]

        _switch_to_shared(_per_day_schedule(days), actions)

        assert _opts(actions[0])['group_name'] == 'X'
        assert _opts(actions[0])['action_duration'] == 60.0

    def test_대표요일에_없는_스텝은_전역값이_유지된다(self):
        days = [_entry(enabled=False) for _ in range(7)]
        days[0] = _entry(enabled=True, groups={'a1': 'A'})   # a2 는 없음
        actions = [_action('a1', {'group_name': ''}),
                   _action('a2', {'group_name': '기존값'})]

        _switch_to_shared(_per_day_schedule(days), actions)

        assert _opts(actions[0])['group_name'] == 'A'
        assert _opts(actions[1])['group_name'] == '기존값'

    def test_shared에서_shared로는_아무것도_옮기지_않는다(self):
        old = {'version': 1, 'mode': 'shared', 'shared': _entry(),
               'days': {str(i): _entry(groups={'a1': '무시돼야함'}) for i in range(7)}}
        actions = [_action('a1', {'group_name': '그대로'})]

        _switch_to_shared(old, actions)

        assert _opts(actions[0])['group_name'] == '그대로'

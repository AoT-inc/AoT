# coding=utf-8
"""입력(센서) 켜기/끄기 — configure.input_activate (2026-10-30 claude.ai 체험 피드백 2-1·3-2).

- 일반 입력에 켜고 끄는 op 가 없어 `input_edit` 에 active 를 넣다 거절됐다. GIS 입력의
  `gis_input_activate` 와 같은 모양으로 `input_activate` 를 둔다(안쪽 도구 `activate_input`).
- 켜기·끄기 모두 승인 대상이다. 끄기의 되읽기에는 이 입력을 쓰는 것들과 놓인 곳이 실린다(자동으로 끄지 않는다).
- 이미 같은 상태면 승인 없이 그렇다고 답한다.
- 받지 않는 인자를 받는 다른 operation 을 거절 문구가 가리킨다.
- 운영 묶음 목록(토큰)에는 오르지 않는다 — 장치 정의(devices) 모듈이다.
"""
import json
import unittest
from unittest import mock

import pytest

from aot.config import ProdConfig


def _plan(tool, args, kind='input'):
    from aot.tools.domain import dispatch

    def resolve(ref, **kw):
        return 'ok', {'kind': kind, 'id': 'id-1', 'name': str(ref),
                      'path': 'map > %s' % ref, 'matched': 'exact'}
    with mock.patch.object(dispatch.targets, 'resolve', resolve), \
            mock.patch.object(dispatch.targets, 'snapshot', lambda t: {}):
        return dispatch.plan(tool, args)


class RegistryTest(unittest.TestCase):

    def test_op_maps_to_its_own_inner_write_tool_and_needs_approval(self):
        from aot.tools import tool_registry as R
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        o = find_op(OPS, 'configure', 'input_activate')
        self.assertEqual({'input': 'activate_input'}, o.inner)
        self.assertEqual(('target', 'active'), o.required)
        self.assertIn('activate_input', R.approval_required_tools())
        self.assertIn('activate_input', R.write_tools())

    def test_registry_passes_its_own_contract(self):
        from aot.tools.domain import contract
        self.assertEqual([], contract.problems())

    def test_it_is_a_devices_module_tool_and_never_in_the_old_list(self):
        from aot.tools import tool_registry as R
        self.assertIn('activate_input', R.module_tools('devices'))
        self.assertIn('activate_input', R.DOMAIN_ONLY_TOOLS)
        self.assertNotIn('activate_input', R.profile_tools(R.TOOL_PROFILE_OPERATIONS))

    def test_operations_list_does_not_grow_but_configuration_lists_it(self):
        from aot.tools import tool_registry as R
        from aot.tools.domain import surface
        from aot.tools.domain.registry_data import OPS
        ents = {}
        for prof in (R.TOOL_PROFILE_OPERATIONS, R.TOOL_PROFILE_CONFIGURATION):
            ents[prof] = surface.entries(OPS, lambda n, p=prof: R.tool_in_profile(n, p),
                                         set(R.approval_required_tools()))
        ops_cfg = next(e for e in ents[R.TOOL_PROFILE_OPERATIONS] if e['name'] == 'configure')
        self.assertNotIn('input_activate', ops_cfg['description'])
        full_cfg = next(e for e in ents[R.TOOL_PROFILE_CONFIGURATION] if e['name'] == 'configure')
        self.assertIn('input_activate', full_cfg['inputSchema']['properties']['op']['enum'])
        self.assertIn('active', full_cfg['inputSchema']['properties'])
        self.assertIn('input_activate', full_cfg['description'])

    def test_active_names_the_ops_that_take_it(self):
        from aot.tools.domain.registry_data import OPS
        for o in OPS:
            if o.tool == 'configure' and 'active' in o.extra_args:
                self.assertIn('input_activate', o.extra_args['active'])
                self.assertIn('gis_input_activate', o.extra_args['active'])

    def test_input_edit_points_to_the_switch(self):
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        self.assertIn('input_activate', find_op(OPS, 'configure', 'input_edit').use)


class PlanTest(unittest.TestCase):

    def test_off_is_planned_for_the_inner_tool(self):
        v = _plan('configure', {'op': 'input_activate', 'target': '토양센서', 'active': False})
        self.assertEqual('call', v[0], v)
        self.assertEqual('activate_input', v[1])
        self.assertEqual('id-1', v[2]['input_id'])
        self.assertIs(False, v[2]['active'])

    def test_active_is_required_so_a_missing_value_never_turns_it_on(self):
        v = _plan('configure', {'op': 'input_activate', 'target': 'x'})
        self.assertEqual('refuse', v[0])
        body = json.loads(v[1][0]['text'])
        self.assertEqual('missing_argument', body['reason_code'])
        self.assertIn('active', body['message'])

    def test_input_edit_with_active_says_which_op_takes_it(self):
        v = _plan('configure', {'op': 'input_edit', 'target': 'x', 'active': False})
        self.assertEqual('refuse', v[0])
        body = json.loads(v[1][0]['text'])
        self.assertEqual('unknown_argument', body['reason_code'])
        self.assertIn('does not take active', body['message'])
        self.assertIn('configure.input_activate', body['message'])
        self.assertIn('configure.gis_input_activate', body['message'])

    def test_no_hint_when_no_other_op_takes_the_argument(self):
        v = _plan('configure', {'op': 'input_edit', 'target': 'x', 'bogus': 1})
        body = json.loads(v[1][0]['text'])
        self.assertIn('does not take bogus. It takes:', body['message'])
        self.assertNotIn('use configure', body['message'])

    def test_no_hint_when_many_ops_take_it(self):
        # name 은 열두 operation 이 받는다 — 가리켜 봐야 소음이다.
        v = _plan('configure', {'op': 'input_activate', 'target': 'x', 'active': True, 'name': 'n'})
        body = json.loads(v[1][0]['text'])
        self.assertNotIn('name: use', body['message'])


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'input_activate.db'}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


def _svc():
    from aot.tools.aot_data_tool_service import AoTDataToolService
    return AoTDataToolService


def _input(name='토양수분 A', is_activated=True, device='LinuxCommand'):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import DeviceMeasurements, Input
    row = Input(unique_id=set_uuid())
    row.name = name
    row.device = device
    row.is_activated = is_activated
    row.period = 60.0
    row.cmd_command = 'echo 1'
    db.session.add(row)
    db.session.commit()
    m = DeviceMeasurements(unique_id=set_uuid())
    m.device_id = row.unique_id
    m.name = '토양수분'
    m.measurement = 'moisture'
    m.unit = 'percent'
    m.channel = 0
    m.is_enabled = True
    db.session.add(m)
    db.session.commit()
    return row


def _daemon(err=0):
    d = mock.MagicMock()
    d.controller_activate.return_value = (err, 'ok')
    d.controller_deactivate.return_value = (err, 'ok')
    return mock.patch('aot.aot_client.DaemonControl', return_value=d), d


def test_turning_off_saves_and_tells_the_daemon(app):
    from aot.databases.models import Input
    with app.test_request_context():
        inp = _input()
        patch, d = _daemon()
        with patch:
            out = _svc().activate_input(input_id=inp.unique_id, active=False)
        assert out.get('status') == 'deactivated', out
        assert Input.query.filter_by(unique_id=inp.unique_id).first().is_activated is False
        d.controller_deactivate.assert_called_once_with(inp.unique_id)
        d.controller_activate.assert_not_called()


def test_text_false_turns_it_off_not_on(app):
    # 도메인 스키마의 active 는 type 이 없어 호스트가 글자로 보낼 수 있다 — bool('false') 는 참이다.
    from aot.databases.models import Input
    with app.test_request_context():
        inp = _input()
        patch, _d = _daemon()
        with patch:
            out = _svc().activate_input(input_id=inp.unique_id, active='false')
        assert out.get('status') == 'deactivated', out
        assert Input.query.filter_by(unique_id=inp.unique_id).first().is_activated is False


def test_same_state_changes_nothing_and_says_so(app):
    with app.test_request_context():
        inp = _input(is_activated=False)
        patch, d = _daemon()
        with patch:
            out = _svc().activate_input(input_id=inp.unique_id, active=False)
        assert out['status'] == 'unchanged'
        assert 'already off' in out['message']
        d.controller_deactivate.assert_not_called()


def test_unreadable_value_is_refused_without_changing(app):
    from aot.databases.models import Input
    with app.test_request_context():
        inp = _input()
        out = _svc().activate_input(input_id=inp.unique_id, active='maybe')
        assert 'error' in out
        assert Input.query.filter_by(unique_id=inp.unique_id).first().is_activated is True


def test_turning_on_runs_the_web_checks_and_changes_nothing_when_they_fail(app):
    from aot.aot_flask.extensions import db
    from aot.databases.models import Input
    with app.test_request_context():
        inp = _input(is_activated=False)
        inp.period = 0
        db.session.commit()
        patch, d = _daemon()
        with patch:
            out = _svc().activate_input(input_id=inp.unique_id, active=True)
        assert 'Period must be set' in out['error'], out
        assert Input.query.filter_by(unique_id=inp.unique_id).first().is_activated is False
        d.controller_activate.assert_not_called()


def test_turning_on_a_valid_input_works(app):
    from aot.databases.models import Input
    with app.test_request_context():
        inp = _input(is_activated=False)
        patch, d = _daemon()
        ok = {'success': [], 'info': [], 'warning': [], 'error': []}
        with patch, mock.patch('aot.aot_flask.utils.utils_input.input_activation_checks',
                               return_value=ok):
            out = _svc().activate_input(input_id=inp.unique_id, active=True)
        assert out.get('status') == 'activated', out
        assert Input.query.filter_by(unique_id=inp.unique_id).first().is_activated is True
        d.controller_activate.assert_called_once_with(inp.unique_id)


def test_daemon_trouble_is_reported_as_unconfirmed_not_as_done(app):
    with app.test_request_context():
        inp = _input()
        patch, d = _daemon(err=1)
        with patch:
            out = _svc().activate_input(input_id=inp.unique_id, active=False)
        assert out['status'] == 'success_with_warning'
        assert out['performed'] == 'unknown'


def test_gis_input_text_false_no_longer_activates(app):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import GeoLayer
    with app.test_request_context():
        row = GeoLayer(unique_id=set_uuid())
        row.name = 'g'
        row.is_activated = True
        db.session.add(row)
        db.session.commit()
        out = _svc().activate_gis_input(layer_id=row.unique_id, active='false')
        assert out.get('status') == 'deactivated', out
        assert GeoLayer.query.filter_by(unique_id=row.unique_id).first().is_activated is False


# ── 영향 목록 ────────────────────────────────────────────────────────────────

def _pid(input_id, name='온도 PID', active=True):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import PID
    row = PID(unique_id=set_uuid())
    row.name = name
    row.measurement = '%s,%s' % (input_id, set_uuid())
    row.is_activated = active
    db.session.add(row)
    db.session.commit()
    return row


def _controller(name, device, options, active=True):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import CustomController
    row = CustomController(unique_id=set_uuid())
    row.name = name
    row.device = device
    row.is_activated = active
    row.custom_options = json.dumps(options)
    db.session.add(row)
    db.session.commit()
    return row


def test_readback_for_off_lists_what_uses_the_sensor_and_does_not_turn_them_off(app):
    from aot.databases.models import PID
    from aot.tools.data_tools import input_impact
    with app.test_request_context():
        inp = _input('토양수분 A')
        pid = _pid(inp.unique_id, '관수 PID')
        _pid(inp.unique_id, '꺼진 PID', active=False)
        _controller('평균', 'average_last_multiple', {'select_measurement': '%s,x' % inp.unique_id})
        text = input_impact.readback(inp.unique_id, False)
        assert "Turn OFF input '토양수분 A'" in text
        assert 'WARNING: 2 running items' in text
        assert "PID '관수 PID'" in text and "function '평균'" in text
        assert '꺼진 PID' not in text                     # 이미 꺼진 것은 경고하지 않는다
        assert 'nothing is turned off with it' in text
        assert PID.query.filter_by(unique_id=pid.unique_id).first().is_activated is True


def test_readback_for_off_with_no_dependents_says_none_found(app):
    from aot.tools.data_tools import input_impact
    with app.test_request_context():
        inp = _input()
        text = input_impact.readback(inp.unique_id, False)
        assert 'No running item was found' in text
        assert 'WARNING' not in text


def test_readback_for_on_is_short(app):
    from aot.tools.data_tools import input_impact
    with app.test_request_context():
        inp = _input(is_activated=False)
        _pid(inp.unique_id)
        text = input_impact.readback(inp.unique_id, True)
        assert text.startswith("Turn ON input")
        assert 'WARNING' not in text


def test_condition_and_trigger_users_are_found(app):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import Conditional, ConditionalConditions, Trigger
    from aot.tools.data_tools import input_impact
    with app.test_request_context():
        inp = _input()
        cond = Conditional(unique_id=set_uuid())
        cond.name = '고온 조건'
        cond.is_activated = True
        db.session.add(cond)
        db.session.commit()
        c = ConditionalConditions(unique_id=set_uuid())
        c.conditional_id = cond.unique_id
        c.measurement = '%s,m' % inp.unique_id
        db.session.add(c)
        t = Trigger(unique_id=set_uuid())
        t.name = '엣지 트리거'
        t.is_activated = True
        t.measurement = '%s,m' % inp.unique_id
        db.session.add(t)
        db.session.commit()
        kinds = {(i['kind'], i['name']) for i in input_impact.dependents(inp.unique_id)['active']}
        assert kinds == {('condition', '고온 조건'), ('trigger', '엣지 트리거')}


def test_environment_control_found_through_the_facility_the_sensor_serves(app):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import GeoBinding
    from aot.tools.data_tools import input_impact
    with app.test_request_context():
        inp = _input()
        fac = set_uuid()
        b = GeoBinding(spatial_kind='sensor_role', spatial_id=fac, role='indoor_temp',
                       device_kind='input', device_id=inp.unique_id)
        db.session.add(b)
        db.session.commit()
        _controller('온실 통합 제어', 'env_coordinator', {'geo_facility_id': fac})
        _controller('다른 온실', 'env_coordinator', {'geo_facility_id': set_uuid()})
        got = input_impact.dependents(inp.unique_id)['active']
        assert got == [{'kind': 'env_control', 'name': '온실 통합 제어'}]
        assert "environment control '온실 통합 제어'" in input_impact.readback(inp.unique_id, False)


def test_a_failing_lookup_still_returns_the_rest(app):
    from aot.tools.data_tools import input_impact
    with app.test_request_context():
        inp = _input()
        _pid(inp.unique_id)
        with mock.patch.object(input_impact, '_facility_ids', side_effect=RuntimeError('x')):
            got = input_impact.dependents(inp.unique_id)
        assert [i['kind'] for i in got['active']] == ['pid']


def test_long_lists_are_cut_to_four_names_and_a_count(app):
    from aot.tools.data_tools import input_impact
    with app.test_request_context():
        inp = _input()
        for i in range(6):
            _pid(inp.unique_id, 'PID%d' % i)
        text = input_impact.readback(inp.unique_id, False)
        assert '6 running items' in text and 'and 2 more' in text
        assert 'PID5' not in text


# ── 승인 되읽기·제목·건너뛰기 ─────────────────────────────────────────────────

def test_gate_read_back_and_title_use_the_impact_text(app):
    from aot.tools import mcp_safety_gate as gate
    with app.test_request_context():
        inp = _input('토양수분 A')
        _pid(inp.unique_id, '관수 PID')
        args = {'input_id': inp.unique_id, 'active': False}
        assert "PID '관수 PID'" in gate.read_back_text('activate_input', args)
        assert "PID '관수 PID'" in gate._build_human_briefing('activate_input', args)
        assert gate.synthesize_title('activate_input', args) == '토양수분 A 끄기'
        args['active'] = True
        assert gate.synthesize_title('activate_input', args) == '토양수분 A 켜기'


def test_read_back_falls_back_when_the_input_is_gone(app):
    from aot.tools import mcp_safety_gate as gate
    with app.test_request_context():
        text = gate.read_back_text('activate_input', {'input_id': 'nope', 'active': False})
        assert text                                       # 기본 문구 — 되읽기가 끊기지 않는다


def test_pending_response_reads_back_through_the_say_ask(app):
    from aot.tools.domain import act_say
    with app.test_request_context():
        inp = _input('토양수분 A')
        _pid(inp.unique_id, '관수 PID')
        from aot.tools import mcp_safety_gate as gate
        body = {'status': 'pending_approval', 'confirmation_id': 'c-1',
                'confirm_with_user': gate.read_back_text(
                    'activate_input', {'input_id': inp.unique_id, 'active': False}),
                'next': {'1_ask': 'x', '2_answer': 'y', '3_run': 'z: w'}, 'message': 'm'}
        out = act_say.approval_body(body)
        assert "관수 PID" in out['say']['ask']
        assert out['say']['ask'].endswith('please approve.')


def test_already_in_that_state_is_answered_without_asking_for_approval(app):
    from aot.tools.domain import dispatch
    with app.test_request_context():
        inp = _input(is_activated=False)
        out = dispatch._already_so('activate_input', {'input_id': inp.unique_id, 'active': False})
        body = json.loads(out[0]['text'])
        assert body['status'] == 'success' and body['unchanged'] is True
        assert 'already off' in body['message']
        # 다른 상태면 평소 흐름(승인)으로 간다.
        assert dispatch._already_so('activate_input', {'input_id': inp.unique_id, 'active': True}) is None
        # 다른 도구·알아볼 수 없는 값·없는 입력은 건드리지 않는다.
        assert dispatch._already_so('modify_input', {'input_id': inp.unique_id, 'active': False}) is None
        assert dispatch._already_so('activate_input', {'input_id': inp.unique_id, 'active': 'maybe'}) is None
        assert dispatch._already_so('activate_input', {'input_id': 'nope', 'active': False}) is None


if __name__ == '__main__':
    unittest.main()


# ── 실제 게이트·승인 큐를 지나는 한 바퀴 ───────────────────────────────────────

from aot.tests.test_mcp_tool_profiles import CFG, _AppFixture, _PREFIX   # noqa: E402


class InputSwitchFlowTest(_AppFixture):
    """configure.input_activate: 끄기 요청 → 승인 대기(되읽기에 영향 목록) → 승인 = 실행. 같은 상태면 승인 없이 답."""

    def setUp(self):
        super().setUp()
        from aot.tools.domain import contract
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)
        p = mock.patch('aot.tools.tool_execution.domain_surface_enabled', lambda: True)
        p.start()
        self.addCleanup(p.stop)
        self.role = self._auth(self._issue('Admin', 'full', CFG))
        from aot.databases import set_uuid
        from aot.databases.models import Input, PID
        self.inp = Input(unique_id=set_uuid())
        self.inp.name = _PREFIX + '토양센서'
        self.inp.device = 'LinuxCommand'
        self.inp.is_activated = True
        self.inp.period = 60.0
        self.inp.cmd_command = 'echo 1'
        self.db.session.add(self.inp)
        self.pid = PID(unique_id=set_uuid())
        self.pid.name = _PREFIX + '관수 PID'
        self.pid.measurement = '%s,%s' % (self.inp.unique_id, set_uuid())
        self.pid.is_activated = True
        self.db.session.add(self.pid)
        self.db.session.commit()
        self.inp_id, self.pid_id = self.inp.unique_id, self.pid.unique_id
        self.pid_name = self.pid.name
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        from aot.databases.models import Input, PID
        self.db.session.rollback()
        PID.query.filter_by(unique_id=self.pid_id).delete()
        Input.query.filter_by(unique_id=self.inp_id).delete()
        self.db.session.commit()

    def _call(self, tool, args):
        from aot.tools import mcp_auth
        from aot.tools import tool_execution as te
        out = te._execute_tool(self.app, tool, dict(args),
                               agent_id='user:%s' % _PREFIX.lower(), role=self.role,
                               scope_user_uuid=getattr(self.role, 'user_id', None),
                               transport='mcp_http',
                               tool_profile=mcp_auth.tool_profile_of(self.role))
        return json.loads(out[0]['text'])

    def test_off_asks_with_the_impact_and_approval_runs_it(self):
        from aot.databases.models import Input
        args = {'op': 'input_activate', 'target': self.inp_id, 'active': False}
        first = self._call('configure', args)
        self.assertEqual('pending_approval', first.get('status'), first)
        ask = first['say']['ask']
        self.assertIn('Turn OFF input', ask)
        self.assertIn(self.pid_name, ask)                       # 이 센서를 쓰는 PID 가 되읽기에 실린다
        self.assertIn('nothing is turned off with it', ask)
        self.assertTrue(Input.query.filter_by(unique_id=self.inp_id).first().is_activated)

        patch, d = _daemon()
        with patch:
            answer = self._call('control', {'op': 'confirm', 'target': first['confirmation_id'],
                                            'decision': 'approve'})
        self.assertTrue(answer.get('executed'), answer)
        self.db.session.remove()
        self.assertFalse(Input.query.filter_by(unique_id=self.inp_id).first().is_activated)
        from aot.databases.models import PID
        self.assertTrue(PID.query.filter_by(unique_id=self.pid_id).first().is_activated)
        d.controller_deactivate.assert_called_once_with(self.inp_id)

    def test_already_off_is_answered_without_a_pending_approval(self):
        from aot.databases.models import MCPConfirmation
        from aot.databases.models import Input
        Input.query.filter_by(unique_id=self.inp_id).update({'is_activated': False})
        self.db.session.commit()
        before = MCPConfirmation.query.count()
        out = self._call('configure', {'op': 'input_activate', 'target': self.inp_id,
                                       'active': False})
        self.assertEqual('success', out.get('status'), out)
        self.assertTrue(out.get('unchanged'))
        self.db.session.remove()
        self.assertEqual(before, MCPConfirmation.query.count())

    def test_input_edit_with_active_is_refused_and_points_to_the_switch(self):
        out = self._call('configure', {'op': 'input_edit', 'target': self.inp_id,
                                       'active': False})
        self.assertEqual('unknown_argument', out.get('reason_code'), out)
        self.assertIn('configure.input_activate', out['message'])

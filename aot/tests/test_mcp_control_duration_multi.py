# -*- coding: utf-8 -*-
"""control 의 가동 시간과 여러 장치 한 번에 (2026-10-30 claude.ai 시험 4-4 · 4-7).

4-4  30초 가동을 부탁했는데 device_set 은 duration_* 를 받지 않았고(unknown_argument), device_schedule 은
     duration_minutes=0.5 를 받아 놓고 0분으로 깎아 저장했다 — 0 은 "타이머 없음" 이라 실행 때 계속 켜진다.
4-7  "3-1 장치 전부 꺼줘" 가 네 번의 승인 대기로 갈라졌고, 그 번호들을 confirmation_ids 목록으로 승인하자
     "target required" 로 거절됐다.
"""
import json
from types import SimpleNamespace
from unittest import mock

import pytest
import pytz

from aot.outputs.command_forms import (
    parse_run_seconds, run_time_text, timed_run_refusal)
from aot.tests.test_mcp_tool_profiles import OPS, _AppFixture, _PREFIX


# ── 숫자 해석 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize('sec, minutes, want', [
    (30, None, 30), ('30', None, 30), (None, 0.5, 30), (None, '0.5', 30),
    (None, 5, 300), (None, None, None), ('', None, None), (1.4, None, 1),
])
def test_run_time_is_exact_seconds(sec, minutes, want):
    assert parse_run_seconds(sec, minutes) == (want, None)


@pytest.mark.parametrize('sec, minutes', [
    (0, None), (None, 0), (-5, None), ('abc', None), (0.2, None), (None, 0.001),
    (float('nan'), None), (30, 1),
])
def test_run_time_is_refused_not_truncated(sec, minutes):
    got, err = parse_run_seconds(sec, minutes)
    assert got is None and err, (sec, minutes, got)


def test_run_time_text():
    assert [run_time_text(s) for s in (30, 60, 300, 90)] == ['30 s', '1 min', '5 min', '1 min 30 s']


def test_timer_only_for_on():
    assert 'only applies to state' in timed_run_refusal('off', 'virtual_on_off_single')
    assert 'only applies to state' in timed_run_refusal('set_value', 'virtual_on_off_single')


@pytest.fixture
def scheduling_stubs(monkeypatch):
    """출력 조회·시간대·propose_job 만 갈아끼운다(모델 모듈은 건드리지 않는다)."""
    captured = {}
    output = SimpleNamespace(unique_id='dddddddd-0000-0000-0000-000000000000', name='밸브1')
    monkeypatch.setattr('aot.services.resolvers.device_resolver.resolve_output',
                        lambda *a, **k: SimpleNamespace(row=output, error=None, reason=None))
    monkeypatch.setattr('aot.utils.device_tz.resolve_location_tz',
                        lambda *_a, **_k: pytz.timezone('Asia/Seoul'))

    def _fake_propose(**kwargs):
        captured['proposed'] = kwargs
        return SimpleNamespace(id=1, unique_id='job', anchor_tz=None, anchor_source=None)

    monkeypatch.setattr('aot.ai.services.ai_scheduler_service.AISchedulerService.propose_job',
                        staticmethod(_fake_propose))
    return captured


# ── 예약: 분을 정수로 깎지 않는다 ────────────────────────────────────────────

@pytest.mark.parametrize('kwargs, seconds, text', [
    ({'duration_minutes': 0.5}, 30, '30 s'),
    ({'duration_minutes': '0.5'}, 30, '30 s'),
    ({'duration_seconds': 45}, 45, '45 s'),
    ({'duration_minutes': 5}, 300, '5 min'),
    ({}, 300, '5 min'),
])
def test_schedule_keeps_sub_minute_runs(scheduling_stubs, kwargs, seconds, text):
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    out = S.schedule_device_control_tool('밸브1', delay_seconds=600, **kwargs)
    assert out.get('status') == 'success', out
    got = scheduling_stubs['proposed']
    assert got['duration_sec'] == seconds
    assert got['params']['duration_seconds'] == seconds
    assert '(for %s)' % text in out['message']
    assert out['duration_seconds'] == seconds


@pytest.mark.parametrize('kwargs', [
    {'duration_minutes': 0}, {'duration_minutes': 0.001}, {'duration_seconds': 0},
    {'duration_minutes': 'x'}, {'duration_minutes': 1, 'duration_seconds': 60},
])
def test_schedule_refuses_a_run_time_it_cannot_keep(scheduling_stubs, kwargs):
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    out = S.schedule_device_control_tool('밸브1', delay_seconds=600, **kwargs)
    assert out.get('error') and out['dispatched'] is False, out
    assert 'proposed' not in scheduling_stubs


def test_scheduled_job_runs_for_the_stored_seconds():
    """예약이 실행될 때 초가 그대로 operate_device 로 간다(분보다 초가 먼저)."""
    from aot.ai.services.ai_action_service import AIActionService
    seen = {}

    def fake(cls, device_id, state, **kw):
        seen.update(kw)
        return {'status': 'success'}

    with mock.patch('aot.tools.aot_data_tool_service.AoTDataToolService.operate_device_tool',
                    classmethod(fake)):
        AIActionService.execute_action(
            'control_output', 'out-1',
            {'state': 'on', 'duration_seconds': 30, 'duration_minutes': 0.5}, _approved=True)
    assert seen == {'duration_seconds': 30}, seen


# ── 도메인 표면: 승인 흐름 ───────────────────────────────────────────────────

class _Daemon:
    calls = []

    def __init__(self, *a, **k):
        pass

    def output_on_off(self, uid, state, output_type=None, amount=None, output_channel=None):
        _Daemon.calls.append({'id': uid, 'state': state, 'type': output_type, 'amount': amount})
        return None, 'ok'


class ControlFlowTest(_AppFixture):

    def setUp(self):
        super().setUp()
        from aot.tools.domain import contract
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)
        for p in (mock.patch('aot.tools.tool_execution.domain_surface_enabled', lambda: True),
                  mock.patch('aot.aot_client.DaemonControl', _Daemon)):
            p.start()
            self.addCleanup(p.stop)
        _Daemon.calls = []
        self.role = self._auth(self._issue('Editor', 'full', OPS))
        self._drop_outputs()                               # 앞선 실행이 남긴 것
        self.outs = [self._output('ctl2 밸브 %s' % n) for n in 'ABC']
        self.names = [o.name for o in self.outs]
        self.uids = [o.unique_id for o in self.outs]
        self.addCleanup(self._drop_outputs)

    def _output(self, name, otype='virtual_on_off_single'):
        from aot.databases import set_uuid
        from aot.databases.models import Output, OutputChannel
        out = Output(unique_id=set_uuid())
        out.name = name
        out.output_type = otype
        out.is_ai_enabled = True
        self.db.session.add(out)
        ch = OutputChannel(unique_id=set_uuid())
        ch.output_id = out.unique_id
        ch.channel = 0
        self.db.session.add(ch)
        self.db.session.commit()
        return out

    def _drop_outputs(self):
        """이 파일이 만든 출력('ctl2 ' 이름)만 지운다."""
        from aot.databases.models import Output, OutputChannel
        self.db.session.rollback()
        ids = [o.unique_id for o in Output.query.filter(Output.name.like('ctl2 %')).all()]
        if ids:
            OutputChannel.query.filter(OutputChannel.output_id.in_(ids)).delete(
                synchronize_session=False)
            Output.query.filter(Output.unique_id.in_(ids)).delete(synchronize_session=False)
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

    def _ai_off(self, uids):
        from aot.databases.models import Output
        Output.query.filter(Output.unique_id.in_(uids)).update(
            {'is_ai_enabled': False}, synchronize_session=False)
        self.db.session.commit()

    def _pending_count(self):
        from aot.databases.models import MCPConfirmation
        self.db.session.remove()
        return MCPConfirmation.query.count()

    # 4-4 -------------------------------------------------------------------

    def test_device_set_takes_seconds_and_runs_a_timed_on(self):
        first = self._call('control', {'op': 'device_set', 'target': self.names[0],
                                       'state': 'on', 'duration_seconds': 30})
        self.assertEqual('pending_approval', first.get('status'), first)
        self.assertIn('duration seconds 30', first['say']['ask'])        # 되읽기에 가동 시간이 든다
        self.assertEqual([], _Daemon.calls)                       # 요청은 승인이 아니다
        done = self._call('control', {'op': 'confirm', 'target': first['confirmation_id'],
                                      'decision': 'approve'})
        self.assertTrue(done.get('executed'), done)
        self.assertEqual([{'id': self.uids[0], 'state': 'on', 'type': 'sec',
                           'amount': 30.0}], _Daemon.calls)

    def test_device_set_takes_minutes_too_without_truncation(self):
        first = self._call('control', {'op': 'device_set', 'target': self.names[0],
                                       'state': 'on', 'duration_minutes': '0.5'})
        self.assertEqual('pending_approval', first.get('status'), first)
        self._call('control', {'op': 'confirm', 'target': first['confirmation_id'],
                               'decision': 'approve'})
        self.assertEqual(30.0, _Daemon.calls[0]['amount'])

    def test_run_time_refused_before_the_approval_queue(self):
        before = self._pending_count()
        for extra in ({'state': 'off', 'duration_seconds': 30},
                      {'state': 'on', 'duration_seconds': 0},
                      {'state': 'on', 'duration_minutes': 0.001},
                      {'state': 'on', 'duration_seconds': 30, 'duration_minutes': 1}):
            got = self._call('control', dict(op='device_set', target=self.names[0], **extra))
            self.assertEqual('refused', got.get('status'), (extra, got))
            self.assertIn(got.get('reason_code'), ('bad_run_time', 'no_timed_run'), got)
            self.assertIn('checked before any permission or approval', got['message'])
        self.assertEqual(before, self._pending_count())
        self.assertEqual([], _Daemon.calls)

    def test_pwm_output_has_no_timed_run(self):
        out = self._output('ctl2 조광', otype='pwm_dimmer')
        name = out.name
        with mock.patch('aot.outputs.command_forms._output_module_traits',
                        lambda t: (['pwm'], False)):
            got = self._call('control', {'op': 'device_set', 'target': name,
                                         'state': 'on', 'duration_seconds': 30})
        self.assertEqual('refused', got.get('status'), got)
        self.assertIn('no timed run', got.get('message', ''))

    # 4-7 -------------------------------------------------------------------

    def test_confirm_takes_a_list_of_ids_without_a_target(self):
        ids = []
        for n in self.names[:2]:
            r = self._call('control', {'op': 'device_set', 'target': n, 'state': 'off'})
            self.assertEqual('pending_approval', r.get('status'), r)
            ids.append(r['confirmation_id'])
        for form in (ids, json.dumps(ids)):
            self.assertEqual(2, self._pending_count())
            got = self._call('control', {'op': 'confirm', 'decision': 'reject',
                                         'confirmation_ids': form})
            self.assertEqual('batch_complete', got.get('status'), got)
            self.assertEqual(2, got['count'])
            self.assertEqual(2, got['succeeded'])
            break
        self.assertEqual([], _Daemon.calls)

    def test_confirm_without_target_or_ids_says_what_is_missing(self):
        got = self._call('control', {'op': 'confirm', 'decision': 'approve'})
        self.assertIn('confirmation_id', json.dumps(got), got)
        self.assertNotEqual('target_required', got.get('reason_code'))

    def test_several_targets_one_read_back_one_approval(self):
        first = self._call('control', {'op': 'device_set', 'target': json.dumps(self.names),
                                       'state': 'off'})
        self.assertEqual('pending_approval', first.get('status'), first)
        # 응답 계약: status → say → next → data
        self.assertEqual(['status', 'say', 'next'], list(first)[:3], first)
        self.assertEqual(3, len(first['confirmation_ids']))
        for n in self.names:                              # 서버가 푼 대상이 되읽기에 모두 들어 있다
            self.assertIn(n, first['say']['ask'])
        self.assertIn('please approve', first['say']['ask'])
        self.assertEqual(3, self._pending_count())
        self.assertEqual([], _Daemon.calls)               # 요청은 승인이 아니다
        self.assertIn("confirmation_ids=", first['next']['after_user'])
        self.assertTrue(all(i in first['next']['after_user'] for i in first['confirmation_ids']))

        done = self._call('control', {'op': 'confirm', 'decision': 'approve',
                                      'confirmation_ids': first['confirmation_ids']})
        self.assertEqual(['status', 'say', 'next'], list(done)[:3], done)
        self.assertEqual(3, done['succeeded'], done)
        self.assertEqual(set(self.uids), {c['id'] for c in _Daemon.calls})
        self.assertTrue(all(c['state'] == 'off' for c in _Daemon.calls))
        self.assertIn('3 approved and done', done['say']['tell'])

    def test_an_excluded_target_stops_the_whole_request_before_anything_is_queued(self):
        self._ai_off(self.uids[1:2])
        before = self._pending_count()
        got = self._call('control', {'op': 'device_set', 'target': self.names, 'state': 'off'})
        self.assertNotEqual('pending_approval', got.get('status'), got)
        self.assertIn('excluded from AI', got.get('message', ''))
        self.assertEqual(before, self._pending_count())
        self.assertEqual([], _Daemon.calls)

    def test_a_target_the_inner_tool_refuses_is_reported_not_read_back(self):
        """해석은 통과했지만 안쪽 도구가 한 대상을 거절한 경우 — 나머지만 되읽고, 빠진 것은 알린다."""
        from aot.tools import tool_execution as te
        orig = te._execute_tool
        bad = self.uids[1]

        def fake(app, name, args, **kw):
            if args.get('device_id') == bad:
                return [{'type': 'text', 'text': json.dumps(
                    {'status': 'refused', 'reason_code': 'rate_limited', 'message': 'too many calls'})}]
            return orig(app, name, args, **kw)

        # 틀은 안쪽 호출을 `tool_execution._execute_tool` 로 부른다(함수 안 import) — 그 이름을 바꿔 건다.
        with mock.patch.object(te, '_execute_tool', fake):
            first = self._call('control', {'op': 'device_set', 'target': self.names, 'state': 'off'})
        self.assertEqual('pending_approval', first.get('status'), first)
        self.assertEqual(2, len(first['confirmation_ids']))
        self.assertEqual(1, len(first['not_requested']))
        self.assertIn(self.names[1], first['say']['tell'])
        self.assertNotIn(self.names[1], first['say']['ask'])

    def test_other_writes_still_take_one_target(self):
        got = self._call('control', {'op': 'function_on', 'target': ['a-function', 'b-function']})
        self.assertEqual('single_target_only', got.get('reason_code'), got)

    def test_too_many_targets_are_refused(self):
        got = self._call('control', {'op': 'device_set', 'state': 'off',
                                     'target': ['v%d' % i for i in range(9)]})
        self.assertEqual('too_many_targets', got.get('reason_code'), got)

    def test_resending_one_id_for_a_batch_is_refused(self):
        got = self._call('control', {'op': 'device_set', 'state': 'off',
                                     'target': self.names[:2],
                                     '_confirmation_id': 'x'})
        self.assertEqual('single_target_only', got.get('reason_code'), got)

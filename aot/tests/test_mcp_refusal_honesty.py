# coding=utf-8
"""거부된 쓰기를 "완료" 로 말하지 않게 — 응답이 사람에게 할 말을 싣는다.

2026-09-23 재측정(288회)에서 두 가지가 드러났다.

- **거짓 완료 보고.** 쓰기가 거부됐는데(write_disabled) 모델이 submit_advice
  를 부르고 "완료했습니다" 라고 답했다(4건). 거부 응답은 이유와 다음 할 일만
  말했지, 사용자에게 "적용되지 않았다" 고 말하라고는 하지 않았다.
- **id 노출.** 답에 uuid 가 나온 14건 중 13건이 거부 직후, 거부된 변경을 풀어
  쓰면서 앞 조회의 id 를 옮긴 것이었다. 나머지 1건은 이름이 같은 장치 둘을 id
  로만 구분해 되물었다(후보에 구분 단서가 없었다).

여기서 고정하는 계약:

  1. 쓰기가 일어나지 않은 모든 응답(거부·승인 대기·승인 거절·실패)은
     `performed: false` 와 `_reading` 규칙을 싣는다. 기존 칸은 그대로다.
  2. 승인 대기는 "아직 안 됨 — 사람 승인 대기" 로 말하게 한다.
  3. 읽기 도구는 건드리지 않는다. 되묻는 응답만 예외로 "id 를 보이지 말 것".
  4. submit_advice 는 조언 ≠ 실행을 응답에서 밝힌다.
  5. 인앱 AI 도 같은 표시를 받는다.
  6. 이름이 같은 장치 후보는 각자 사람이 구분할 단서(where)를 갖는다.
  7. 추가 크기는 작다(거부 한 건에 400바이트 미만).
"""
import json
import os
import unittest
import uuid
from unittest import mock

from aot.aot_flask.extensions import db
from aot.databases.models import AIAdvice, MCPConfirmation
from aot.tests.test_mcp_record_write_guard import _Fixture
from aot.tools import mcp_safety_gate as gate
from aot.tools import tool_execution as te

_READING_DONE_WORDS = ('NOT made', 'do not describe it as done')


def _uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# 1. 표시 규칙 자체 (DB 불필요)
# ---------------------------------------------------------------------------

class TestMarkNotPerformed(unittest.TestCase):

    def test_refusal_gets_flag_and_rule_first_and_keeps_fields(self):
        body = {'status': 'refused', 'reason_code': 'write_disabled',
                'message': 'm', 'tool_name': 'create_note'}
        out = gate.annotate_write_outcome('create_note', 'refused', dict(body))
        self.assertIs(out['performed'], False)
        self.assertEqual(out['_reading'][0], gate.NOT_PERFORMED_READING)
        self.assertIn(gate.NO_IDS_READING, out['_reading'])
        for k, v in body.items():
            self.assertEqual(out[k], v, k)

    def test_pending_says_not_done_yet(self):
        out = gate.annotate_write_outcome(
            'operate_device', 'pending_approval',
            {'status': 'pending_approval', 'reason_code': 'awaiting_user'})
        self.assertIs(out['performed'], False)
        self.assertEqual(out['_reading'], [gate.PENDING_READING])

    def test_rejected_and_expired_approvals_are_not_performed(self):
        for state in ('approval_rejected', 'approval_expired'):
            with self.subTest(state=state):
                out = gate.annotate_write_outcome(
                    'operate_device', state, {'status': 'refused'})
                self.assertIs(out['performed'], False)
                self.assertEqual(out['_reading'][0], gate.NOT_PERFORMED_READING)

    def test_failed_write_allows_retry(self):
        out = gate.annotate_write_outcome(
            'create_note', 'failed', {'status': 'error', 'message': 'x'})
        self.assertIs(out['performed'], False)
        self.assertEqual(out['_reading'][0], gate.FAILED_READING)

    def test_executed_write_and_reads_are_untouched(self):
        ok = {'status': 'success'}
        self.assertEqual(gate.annotate_write_outcome('create_note', 'executed',
                                                     dict(ok)), ok)
        for state in ('refused', 'failed'):
            self.assertEqual(gate.annotate_write_outcome(
                'get_plot', state, {'status': 'error'}), {'status': 'error'})

    def test_replayed_approval_only_marked_when_it_failed(self):
        good = {'status': 'already_executed', 'result': {'status': 'success'}}
        self.assertNotIn('performed', gate.annotate_write_outcome(
            'operate_device', 'already_executed', dict(good)))
        bad = {'status': 'already_executed', 'result': {'status': 'error'}}
        self.assertIs(gate.annotate_write_outcome(
            'create_note', 'already_executed', bad)['performed'], False)

    def test_existing_reading_is_kept_after_the_rule(self):
        out = gate.mark_not_performed({'status': 'refused', '_reading': 'old'})
        self.assertEqual(out['_reading'][-1], 'old')
        again = gate.mark_not_performed(out)
        self.assertEqual(again['_reading'].count(gate.NOT_PERFORMED_READING), 1)

    def test_disambiguation_asks_without_ids_for_reads_and_writes(self):
        amb = {'status': 'needs_disambiguation', 'candidates': [{}]}
        read = gate.annotate_write_outcome('resolve_target', 'executed', dict(amb))
        self.assertNotIn('performed', read)
        self.assertIn(gate.CANDIDATES_NO_IDS, read['_reading'])
        write = gate.annotate_write_outcome('create_note', 'failed', dict(amb))
        self.assertIs(write['performed'], False)
        self.assertEqual(write['_reading'],
                         [gate.DISAMBIGUATION_READING, gate.CANDIDATES_NO_IDS])
        dev = gate.annotate_write_outcome(
            'get_device_detail', 'failed',
            {'error': 'x', 'needs_disambiguation': True, 'candidates': []})
        self.assertIn(gate.CANDIDATES_NO_IDS, dev['_reading'])

    def test_rules_are_short(self):
        """규칙은 응답에 실린다 — 호출마다 무는 값이라 짧아야 한다."""
        for rule in (gate.NOT_PERFORMED_READING, gate.PENDING_READING,
                     gate.FAILED_READING, gate.DISAMBIGUATION_READING,
                     gate.CANDIDATES_NO_IDS, gate.NO_IDS_READING):
            self.assertLess(len(rule), 160, rule)


# ---------------------------------------------------------------------------
# 2. 실행층 (_execute_tool — stdio·HTTP·REST 공통) 과 인앱 경로
# ---------------------------------------------------------------------------

class TestPhysicalOutcomeUnknown(unittest.TestCase):
    """장치 명령이 나간 뒤의 실패는 "안 됨" 이 아니라 "모름" (리뷰 1)."""

    def _assert_unknown(self, out, rule=None):
        self.assertEqual(out['performed'], gate.PERFORMED_UNKNOWN, out)
        self.assertEqual(out['_reading'][0], rule or gate.UNCONFIRMED_READING)
        self.assertNotIn(gate.FAILED_READING, out['_reading'])

    def test_sent_then_failed_is_unknown(self):
        for body in ({'error': 'Device control failed: Output ON timed out',
                      'dispatched': True},
                     # 표시가 없는 실패(처리기 예외 등)도 모름 쪽으로 둔다.
                     {'status': 'error', 'message': 'boom'}):
            with self.subTest(body=body):
                self._assert_unknown(gate.annotate_write_outcome(
                    'operate_device', 'failed', dict(body)))

    def test_nested_flag_from_set_output_state(self):
        body = {'status': 'error', 'device_id': 'x', 'state': 'on',
                'result': {'status': 'error', 'message': 'm',
                           'result': {'error': 'timed out', 'dispatched': True}}}
        self._assert_unknown(gate.annotate_write_outcome(
            'set_output_state', 'failed', body))

    def test_definite_pre_dispatch_failures_stay_not_performed(self):
        cases = [
            {'error': 'Device (output) to control not found: v1', 'dispatched': False},
            {'error': 'x', 'needs_disambiguation': True, 'candidates': []},
            {'status': 'not_found', 'message': 'm'},
            # 인앱 승인 토큰 없음·요청자 거부 — 보내기 전에 막혔다.
            {'status': 'error', 'result': {'status': 'error', 'blocked': True}},
        ]
        for body in cases:
            with self.subTest(body=body):
                out = gate.annotate_write_outcome('operate_device', 'failed',
                                                  dict(body))
                self.assertIs(out['performed'], False, out)
        for state in ('refused', 'pending_approval', 'approval_rejected'):
            with self.subTest(state=state):
                out = gate.annotate_write_outcome(
                    'operate_device', state, {'status': 'refused'})
                self.assertIs(out['performed'], False, out)

    def test_schedule_gets_its_own_check(self):
        self._assert_unknown(gate.annotate_write_outcome(
            'schedule_device_control', 'failed',
            {'error': 'Error while scheduling device control: x',
             'dispatched': True}), gate.UNCONFIRMED_SCHEDULE_READING)

    def test_approval_replay_of_a_sent_failure_is_unknown(self):
        out = gate.annotate_write_outcome(
            'operate_device', 'already_executed',
            {'status': 'already_executed',
             'result': {'error': 'timed out', 'dispatched': True}})
        self._assert_unknown(out)
        out = gate.annotate_write_outcome(
            'operate_device', 'already_executed',
            {'status': 'already_executed',
             'result': {'error': 'bad', 'dispatched': False}})
        self.assertIs(out['performed'], False)

    def test_unknown_is_not_downgraded(self):
        out = gate.mark_unconfirmed({'error': 'x'}, 'operate_device')
        self.assertEqual(gate.mark_not_performed(out)['performed'],
                         gate.PERFORMED_UNKNOWN)

    def test_non_physical_write_failure_is_still_not_made(self):
        out = gate.annotate_write_outcome(
            'create_note', 'failed', {'error': 'x', 'dispatched': True})
        self.assertIs(out['performed'], False)


class TestNotPerformedVocabulary(unittest.TestCase):
    """쓰기 도구의 자기 status 단어도 "안 됨" 이다(리뷰 2)."""

    def test_write_status_words_change_the_call_state(self):
        for status, want in gate.NOT_PERFORMED_STATUSES.items():
            with self.subTest(status=status):
                self.assertEqual(gate.call_state(
                    None, {'status': status}, tool_name='archive_note'), want)
                out = gate.annotate_write_outcome(
                    'archive_note', want, {'status': status})
                self.assertIs(out['performed'], False)

    def test_shelve_validation_and_quota_are_failures_not_refusals(self):
        """지식 적재의 입력 검증·하루 한도는 권한·정책 거부가 아니다(검토 4)."""
        for status in ('rejected', 'quota_exceeded'):
            with self.subTest(status=status):
                self.assertEqual(gate.NOT_PERFORMED_STATUSES[status], 'failed')
                self.assertEqual(gate.call_state(
                    None, {'status': status}, tool_name='knowledge_shelve'),
                    'failed')
                out = gate.annotate_write_outcome(
                    'knowledge_shelve', 'failed', {'status': status})
                self.assertIs(out['performed'], False)
                self.assertEqual(out['_reading'][0], gate.FAILED_READING)

    def test_reads_keep_their_not_found_answer(self):
        self.assertEqual(gate.call_state(
            None, {'status': 'not_found'}, tool_name='get_archived_document'),
            'executed')
        self.assertEqual(gate.call_state(None, {'status': 'refused'}),
                         'executed')   # 도구 이름이 없으면 예전 판정 그대로

    def test_record_handlers_status_words_are_in_the_vocabulary(self):
        """처리기가 쓰는 단어가 어휘 밖으로 새지 않게 — 소스에서 직접 센다."""
        import re
        from aot.tools.data_tools import record
        src = open(record.__file__, encoding='utf-8').read()
        used = set(re.findall(r'"status": "([a-z_]+)"', src))
        ok = {'success', 'error', 'created', 'modified', 'deleted', 'done',
              'archived', 'restored', 'updated'}
        self.assertFalse(used - ok - set(gate.NOT_PERFORMED_STATUSES),
                         used - ok)


class TestCapKeepsReading(unittest.TestCase):
    """캡이 `_reading` 을 자르지 않는다(리뷰 4)."""

    def test_low_cap_trims_data_not_guidance(self):
        rules = [gate.NOT_PERFORMED_READING, gate.NO_IDS_READING,
                 gate.CANDIDATES_NO_IDS]
        res = {'status': 'refused', 'performed': False, '_reading': list(rules),
               'items': [{'name': 'item %d' % i, 'blob': 'x' * 200}
                         for i in range(60)]}
        out = te._cap_result(res, 'create_note', max_tokens=600)
        self.assertIn('_truncated', out)
        self.assertLess(len(out['items']), 60)
        self.assertEqual(out['_reading'], rules)
        self.assertNotIn('_reading_truncated', out)


class TestRefusalPayloads(_Fixture):

    def _assert_not_done(self, body, pending=False):
        self.assertIs(body.get('performed'), False, body)
        first = body['_reading'][0]
        if pending:
            self.assertEqual(first, gate.PENDING_READING)
        else:
            for w in _READING_DONE_WORDS:
                self.assertIn(w, first)

    def test_write_disabled(self):
        with mock.patch.dict(os.environ, {'AOT_MCP_WRITE_ENABLED': '0'}):
            body = self._call('create_note', self._note_args(),
                              self._role('Editor'))
        self.assertEqual(body['reason_code'], 'write_disabled')
        self.assertIn('submit_advice', body['message'])
        self.assertEqual(body['call_state'], 'refused')
        self._assert_not_done(body)

    def test_insufficient_role(self):
        body = self._call('create_note', self._note_args(),
                          self._role('Editor', readonly=True))
        self.assertEqual(body['reason_code'], 'insufficient_role')
        self._assert_not_done(body)

    def test_group_scope(self):
        self._scope_to_other_group()
        body = self._call('create_note',
                          self._note_args(target_id=self.output_id,
                                          target_type='output'),
                          self._role('Editor'),
                          scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual(body['reason_code'], 'group_scope')
        self._assert_not_done(body)
        self.assertEqual(self._notes(), 0)

    def _pending(self):
        return self._call('operate_device',
                          {'device_id': self.output_id, 'state': 'on'},
                          self._role('Editor'))

    def test_pending_approval(self):
        body = self._pending()
        self.assertEqual(body['status'], 'pending_approval')
        self.assertEqual(body['call_state'], 'pending_approval')
        self.assertIn('confirmation_id', body)
        self._assert_not_done(body, pending=True)

    def test_rejected_confirmation(self):
        cid = self._pending()['confirmation_id']
        gate.reject(cid, user_id=self.user_uuids['Editor'])
        body = self._call('operate_device',
                          {'device_id': self.output_id, 'state': 'on',
                           '_confirmation_id': cid}, self._role('Editor'))
        self.assertEqual(body['reason_code'], 'confirmation_rejected')
        self.assertEqual(body['call_state'], 'approval_rejected')
        self._assert_not_done(body)

    def test_not_approved(self):
        cid = self._pending()['confirmation_id']
        status, result = gate.execute_approved(cid)
        self.assertEqual(status, 'refused')
        self.assertEqual(result['reason_code'], 'not_approved')
        self._assert_not_done(result)
        db.session.remove()
        self.assertEqual(MCPConfirmation.query.filter_by(
            unique_id=cid).first().status, 'pending')

    def test_audit_ledger_unchanged(self):
        """1-F 장부 칸은 그대로다 — 표시는 응답에만 붙는다."""
        with mock.patch.dict(os.environ, {'AOT_MCP_WRITE_ENABLED': '0'}):
            self._call('create_note', self._note_args(), self._role('Editor'))
        row = self._last_audit()
        self.assertEqual(row.call_state, 'refused')
        self.assertEqual(row.confirmation_status, 'rejected')
        self.assertEqual(row.result_summary, 'write_disabled')

    def test_refusal_growth_is_small(self):
        """추가분 — 흔한 거부 한 건에 400바이트 미만."""
        with mock.patch.dict(os.environ, {'AOT_MCP_WRITE_ENABLED': '0'}):
            body = self._call('create_note', self._note_args(),
                              self._role('Editor'))
        added = {k: body[k] for k in ('performed', '_reading')}
        size = len(json.dumps(added, ensure_ascii=False).encode('utf-8'))
        self.assertLess(size, 400, size)

    def test_in_app_chat_refusal_is_marked_too(self):
        from aot.ai.services.ai_action_service import AIActionService
        import flask_login
        self._clear_scope_cache()
        user = self._user('Monitor')
        with self.app.test_request_context():
            flask_login.login_user(user)
            res = AIActionService.execute_action(
                'virtual_tool_call', 'system_internal',
                {'tool_name': 'create_note', 'arguments': self._note_args()})
        self.assertEqual(res.get('reason_code'), 'insufficient_role', res)
        self._assert_not_done(res)

    def test_in_app_mcp_path_carries_the_flag_on_top(self):
        with mock.patch.dict(os.environ, {'AOT_MCP_WRITE_ENABLED': '0'}):
            res = te.execute_for_agent(self.app, 'create_note',
                                       self._note_args())
        self.assertEqual(res['status'], 'error', res)
        self.assertIs(res.get('performed'), False)
        self._assert_not_done(res['result'])


class TestExecutionLayerOutcomes(_Fixture):
    """실행층을 실제로 지나는 경로 — 시간 초과·보관 노트 없음·승인 응답 거부."""

    def _approved_cid(self, tool='operate_device', args=None):
        if args is None:
            args = {'device_id': self.output_id, 'state': 'on'}
        cid = self._call(tool, args, self._role('Editor'))['confirmation_id']
        res = gate.approve(cid, user_id=self.user_uuids['Editor'])
        self.assertEqual(res.get('status'), 'success', res)
        return cid

    @staticmethod
    def _timeout_proxy():
        import Pyro5.errors

        class _Proxy:
            def output_on(self, *a, **k):
                raise Pyro5.errors.TimeoutError('call timeout')

            def output_off(self, *a, **k):
                raise Pyro5.errors.TimeoutError('call timeout')
        return mock.patch('aot.aot_client.DaemonControl.proxy',
                          lambda self: _Proxy())

    def test_daemon_timeout_is_reported_as_unknown(self):
        cid = self._approved_cid()
        with self._timeout_proxy():
            body = self._call('operate_device',
                              {'device_id': self.output_id, 'state': 'on',
                               '_confirmation_id': cid}, self._role('Editor'))
        self.assertEqual(body['call_state'], 'failed', body)
        self.assertIn('timed out', body['error'])
        self.assertIs(body['dispatched'], True)
        self.assertEqual(body['performed'], gate.PERFORMED_UNKNOWN)
        self.assertEqual(body['_reading'][0], gate.UNCONFIRMED_READING)
        self.assertNotIn('NOT made', ' '.join(body['_reading']))

    def test_approval_time_timeout_replays_as_unknown(self):
        cid = self._approved_cid()
        with self._timeout_proxy():
            status, result = gate.execute_approved(cid)
        self.assertEqual(status, 'failed')
        self.assertIs(result.get('dispatched'), True, result)
        # 승인 실행 기록 자체도 "모름" 을 싣는다 — 승인 화면이 이 표시를 읽는다.
        # 행 상태 어휘는 늘리지 않는다(failed 그대로).
        self.assertEqual(result.get('performed'), gate.PERFORMED_UNKNOWN)
        db.session.remove()
        row = MCPConfirmation.query.filter_by(unique_id=cid).first()
        self.assertEqual(row.status, 'failed')
        self.assertEqual(json.loads(row.result_json)['performed'],
                         gate.PERFORMED_UNKNOWN)
        body = self._call('operate_device',
                          {'device_id': self.output_id, 'state': 'on',
                           '_confirmation_id': cid}, self._role('Editor'))
        self.assertEqual(body['call_state'], 'already_executed', body)
        self.assertEqual(body['performed'], gate.PERFORMED_UNKNOWN)

    def test_in_app_agent_sees_unknown_on_top(self):
        cid = self._approved_cid()
        with self._timeout_proxy():
            res = te.execute_for_agent(
                self.app, 'operate_device',
                {'device_id': self.output_id, 'state': 'on',
                 '_confirmation_id': cid})
        self.assertEqual(res['status'], 'error', res)
        self.assertEqual(res.get('performed'), gate.PERFORMED_UNKNOWN, res)

    def test_unknown_device_is_a_definite_failure(self):
        cid = self._call('operate_device',
                         {'device_id': 'no-such-valve-xyz', 'state': 'on'},
                         self._role('Editor')).get('confirmation_id')
        if cid is None:
            self.skipTest('gate refused the unknown name before approval')
        gate.approve(cid, user_id=self.user_uuids['Editor'])
        body = self._call('operate_device',
                          {'device_id': 'no-such-valve-xyz', 'state': 'on',
                           '_confirmation_id': cid}, self._role('Editor'))
        self.assertEqual(body['call_state'], 'failed', body)
        self.assertIs(body['performed'], False, body)

    def test_archive_not_found_is_not_performed_and_ledgered(self):
        args = {'note_id': _uuid()}
        cid = self._approved_cid('archive_note', args)
        body = self._call('archive_note', dict(args, _confirmation_id=cid),
                          self._role('Editor'))
        self.assertEqual(body['status'], 'not_found', body)
        self.assertEqual(body['call_state'], 'failed')
        self.assertIs(body['performed'], False)
        row = self._last_audit()
        self.assertEqual(row.call_state, 'failed')
        self.assertEqual(row.result_summary, 'not_found')

    def test_confirmation_answer_refused_for_role(self):
        body = self._call('respond_to_confirmation',
                          {'confirmation_id': _uuid(), 'decision': 'approve'},
                          self._role('Editor', readonly=True))
        self.assertEqual(body['reason_code'], 'insufficient_role', body)
        self.assertEqual(body['call_state'], 'refused')
        self.assertIs(body['performed'], False)
        self.assertEqual(self._last_audit().call_state, 'refused')

    def test_in_app_physical_gate_is_pending_and_token_block_is_refused(self):
        from aot.ai.services.ai_action_service import AIActionService
        import flask_login
        self._clear_scope_cache()
        with self.app.test_request_context():
            flask_login.login_user(self._user('Admin'))
            res = AIActionService.execute_action(
                'mcp_tool_call', 'operate_device',
                {'tool_name': 'operate_device',
                 'arguments': {'device_id': self.output_id, 'state': 'on'}})
            self.assertIs(res.get('performed'), False, res)
            self.assertEqual(res['_reading'], [gate.PENDING_READING])
            res = AIActionService.execute_action(
                'control_output', self.output_id, {'state': 'on'})
        self.assertIs(res.get('performed'), False, res)
        self.assertEqual(res['_reading'][0], gate.NOT_PERFORMED_READING)


class TestAdviceIsNotAction(_Fixture):

    def tearDown(self):
        db.session.rollback()
        AIAdvice.query.filter(AIAdvice.advice.like('refusal-honesty%')).delete(
            synchronize_session=False)
        db.session.commit()
        super().tearDown()

    def test_advice_response_says_nothing_was_applied(self):
        with mock.patch.dict(os.environ, {'AOT_MCP_WRITE_ENABLED': '0'}):
            body = self._call('submit_advice',
                              {'advice': 'refusal-honesty ' + _uuid()[:8]},
                              self._role('Editor'))
        self.assertEqual(body['status'], 'success', body)
        self.assertEqual(body['call_state'], 'executed')
        self.assertNotIn('performed', body)
        rule = ' '.join(body['_reading'])
        self.assertIn('not the note or change the user asked for', rule)
        self.assertIn('do not report the request as done', rule)
        self.assertIn('not id', rule)


if __name__ == '__main__':
    unittest.main()

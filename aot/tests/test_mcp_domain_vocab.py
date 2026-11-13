# coding=utf-8
"""공통 인자 어휘 확장 — `text title duration state offset samples include_* only_*` (재설계 PR 2, 2026-11-03).

고정하는 계약:
  1. 새 이름으로 부르면 안쪽 도구는 예전과 같은 인자를 받는다(안쪽 이름·인자는 바뀌지 않는다).
  2. 옛 이름도 똑같이 계획되고 `renamed` 에 "새 이름은 이것" 이 남는다. 옛 이름이 명부에 살아 있으면 건드리지 않는다.
  3. 단위는 이름이 아니라 값에 있다 — `duration` 은 안쪽 인자의 단위(초·분)로 바뀐다. 옛 `duration_minutes=15` 는 15분이다.
  4. 도움말 어휘표는 인자 없는 help 에만 있고 도구 목록 토큰에는 안 실린다.
"""
import json
import unittest
from unittest import mock


def _plan(tool, args, kind=None):
    from aot.tools.domain import dispatch

    def resolve(ref, **kw):
        return 'ok', {'kind': kind, 'id': 'id-1', 'name': str(ref),
                      'path': 'map > %s' % ref, 'matched': 'exact'}
    with mock.patch.object(dispatch.targets, 'resolve', resolve), \
            mock.patch.object(dispatch.targets, 'snapshot', lambda t: {}):
        return dispatch.plan(tool, args)


def _inner(verdict):
    assert verdict[0] == 'call', verdict
    return {k: v for k, v in verdict[2].items() if not k.startswith('_')}


class VocabConvertersTest(unittest.TestCase):

    def test_duration_reads_numbers_and_units(self):
        from aot.tools.domain import vocab
        for given, seconds in ((90, 90), ('90', 90), ('90s', 90), ('15m', 900), ('2h', 7200),
                               ('1h30m', 5400), (' 15 m ', 900), (0.5, 0.5)):
            self.assertEqual(seconds, vocab.duration_seconds(given), given)

    def test_duration_for_uses_the_inner_unit(self):
        from aot.tools.domain import vocab
        self.assertEqual(900, vocab.duration_for('duration_seconds', '15m'))
        self.assertEqual(15, vocab.duration_for('duration_minutes', '15m'))
        self.assertEqual(0.5, vocab.duration_for('duration_minutes', '30s'))
        self.assertEqual(600, vocab.duration_for('step_duration', 600))

    def test_bad_duration_is_refused(self):
        from aot.tools.domain import vocab
        for bad in ('soon', '', None, True, -5, '15x'):
            with self.assertRaises(ValueError, msg=repr(bad)):
                vocab.duration_seconds(bad)

    def test_onoff(self):
        from aot.tools.domain import vocab
        for v in ('on', 'ON', True, 1, 'true', 'enable'):
            self.assertIs(True, vocab.onoff(v), v)
        for v in ('off', False, 0, 'false', 'disable'):
            self.assertIs(False, vocab.onoff(v), v)
        for v in ('maybe', None, 2):
            self.assertIsNone(vocab.onoff(v), v)


class NewNamesReachTheSameInnerArgsTest(unittest.TestCase):

    def test_note_add_text_and_title(self):
        got = _inner(_plan('record', {'op': 'note_add', 'target': 'z', 'text': 'hello', 'title': 'T'},
                           kind='zone'))
        self.assertEqual('hello', got['note'])
        self.assertEqual('T', got['name'])

    def test_notice_text(self):
        got = _inner(_plan('record', {'op': 'notice_add', 'title': 'T', 'text': 'body'}))
        self.assertEqual({'title': 'T', 'body': 'body'}, got)

    def test_schedule_text_and_duration_in_minutes(self):
        got = _inner(_plan('record', {'op': 'schedule_edit', 'target': 'job', 'text': 'weed',
                                      'duration': '1h'}, kind='schedule'))
        self.assertEqual('weed', got['content'])
        self.assertEqual(60, got['duration_minutes'])

    def test_device_set_duration_is_seconds(self):
        got = _inner(_plan('control', {'op': 'device_set', 'target': 'valve', 'state': 'on',
                                       'duration': '15m'}, kind='output'))
        self.assertEqual(900, got['duration_seconds'])
        self.assertNotIn('duration_minutes', got)

    def test_bad_duration_stops_before_the_inner_tool(self):
        v = _plan('control', {'op': 'device_set', 'target': 'valve', 'state': 'on',
                              'duration': 'soon'}, kind='output')
        self.assertEqual('refuse', v[0])
        self.assertEqual('bad_duration', json.loads(v[1][0]['text'])['reason_code'])

    def test_activate_state_becomes_the_inner_boolean(self):
        on = _inner(_plan('configure', {'op': 'input_activate', 'target': 'i', 'state': 'on'}, kind='input'))
        off = _inner(_plan('configure', {'op': 'input_activate', 'target': 'i', 'state': 'off'}, kind='input'))
        self.assertIs(True, on['active'])
        self.assertIs(False, off['active'])
        v = _plan('configure', {'op': 'input_activate', 'target': 'i', 'state': 'sometimes'}, kind='input')
        self.assertEqual('bad_state', json.loads(v[1][0]['text'])['reason_code'])

    def test_sequence_step_state_and_duration(self):
        got = _inner(_plan('control', {'op': 'sequence_step', 'action_id': 'a', 'state': 'off',
                                       'duration': 120}))
        self.assertIs(False, got['enabled'])
        self.assertEqual(120, got['duration_seconds'])

    def test_samples_include_and_only_names(self):
        self.assertEqual(5, _inner(_plan('measure', {'op': 'history', 'target': 'z', 'samples': 5},
                                         kind='zone'))['limit'])
        self.assertTrue(_inner(_plan('find', {'op': 'plots', 'include_sensors': True}))['with_sensors'])
        self.assertTrue(_inner(_plan('find', {'op': 'functions', 'only_active': True}))['active_only'])
        self.assertEqual(40, _inner(_plan('find', {'op': 'devices', 'offset': 40}))['offset'])

    def test_subject_kind_and_program_id(self):
        got = _inner(_plan('cultivate', {'op': 'plot_edit', 'target': 'p', 'subject_kind': 'vegetation',
                                         'program_id': 'prog'}, kind='plot'))
        self.assertEqual('vegetation', got['kind'])
        self.assertEqual('prog', got['program_uuid'])


class OldNamesStillWorkTest(unittest.TestCase):
    """옛 이름 호출은 새 이름 호출과 같은 안쪽 인자로 계획된다."""

    def _same(self, tool, old, new, kind=None):
        a = _plan(tool, old, kind=kind)
        b = _plan(tool, new, kind=kind)
        self.assertEqual(_inner(b), _inner(a))

    def test_text_group(self):
        self._same('record', {'op': 'note_add', 'target': 'z', 'note': 'hi', 'name': 'T'},
                   {'op': 'note_add', 'target': 'z', 'text': 'hi', 'title': 'T'}, 'zone')
        self._same('record', {'op': 'notice_add', 'title': 'T', 'body': 'b'},
                   {'op': 'notice_add', 'title': 'T', 'text': 'b'})
        self._same('record', {'op': 'schedule_add', 'at': '2026-11-05', 'content': 'weed'},
                   {'op': 'schedule_add', 'at': '2026-11-05', 'text': 'weed'})
        self._same('record', {'op': 'advice_submit', 'advice': 'x'}, {'op': 'advice_submit', 'text': 'x'})
        self._same('screen', {'op': 'card', 'message': 'm'}, {'op': 'card', 'text': 'm'})
        self._same('cultivate', {'op': 'stage_guidance', 'target': 'p', 'stage_key': 's', 'guidance': 'g'},
                   {'op': 'stage_guidance', 'target': 'p', 'stage_key': 's', 'text': 'g'}, 'plot')

    def test_old_duration_units_keep_their_meaning(self):
        self._same('control', {'op': 'device_set', 'target': 'v', 'state': 'on', 'duration_minutes': 15},
                   {'op': 'device_set', 'target': 'v', 'state': 'on', 'duration': '15m'}, 'output')
        self._same('control', {'op': 'device_set', 'target': 'v', 'state': 'on', 'duration_seconds': 90},
                   {'op': 'device_set', 'target': 'v', 'state': 'on', 'duration': 90}, 'output')
        self._same('control', {'op': 'device_schedule', 'target': 'v', 'at': '2026-11-05 06:00',
                               'state': 'on', 'duration_minutes': 10},
                   {'op': 'device_schedule', 'target': 'v', 'at': '2026-11-05 06:00',
                    'state': 'on', 'duration': '10m'}, 'output')
        self._same('record', {'op': 'schedule_edit', 'target': 'j', 'duration_minutes': 45},
                   {'op': 'schedule_edit', 'target': 'j', 'duration': '45m'}, 'schedule')

    def test_state_group(self):
        self._same('configure', {'op': 'input_activate', 'target': 'i', 'active': True},
                   {'op': 'input_activate', 'target': 'i', 'state': 'on'}, 'input')
        self._same('control', {'op': 'sequence_step', 'action_id': 'a', 'enabled': False},
                   {'op': 'sequence_step', 'action_id': 'a', 'state': 'off'})

    def test_other_groups(self):
        self._same('measure', {'op': 'history', 'target': 'z', 'limit': 3},
                   {'op': 'history', 'target': 'z', 'samples': 3}, 'zone')
        self._same('find', {'op': 'plots', 'with_sensors': True}, {'op': 'plots', 'include_sensors': True})
        self._same('find', {'op': 'functions', 'active_only': True}, {'op': 'functions', 'only_active': True})
        self._same('cultivate', {'op': 'plot_edit', 'target': 'p', 'kind': 'vegetation', 'program_uuid': 'x'},
                   {'op': 'plot_edit', 'target': 'p', 'subject_kind': 'vegetation', 'program_id': 'x'}, 'plot')
        self._same('find', {'op': 'programs', 'kind': 'vegetation'}, {'op': 'programs', 'subject_kind': 'vegetation'})

    def test_old_names_are_reported_only_when_used(self):
        from aot.tools.domain import renames
        _args, got = renames.resolve('record', {'op': 'note_add', 'target': 'z', 'note': 'hi', 'name': 'T'})
        self.assertEqual({'op=note_add': 'note', 'note': 'text', 'name': 'title'}, got)
        _args, got = renames.resolve('record', {'op': 'note_add', 'target': 'z', 'text': 'hi'})
        self.assertEqual({'op=note_add': 'note'}, got)
        _args, got = renames.resolve('record', {'op': 'note', 'target': 'z', 'text': 'hi'})
        self.assertEqual({}, got)

    def test_name_stays_name_where_it_is_the_things_name(self):
        got = _inner(_plan('cultivate', {'op': 'plot_edit', 'target': 'p', 'name': 'North bed'}, kind='plot'))
        self.assertEqual('North bed', got['name'])

    def test_the_old_names_are_in_the_removal_table_with_dates(self):
        from aot.tools.domain import renames
        olds = {r[0] for r in renames.rows()}
        for old in ('note', 'body', 'content', 'message', 'advice', 'guidance', 'duration_seconds',
                    'duration_minutes', 'step_duration', 'active', 'enabled', 'with_sensors',
                    'with_options', 'active_only', 'program_uuid', 'record.note(name)', 'record.note_add', 'record.note_edit',
                    'measure.history(limit)', 'cultivate.plot_edit(kind)'):
            self.assertIn(old, olds)


class ListStaysLightTest(unittest.TestCase):

    def test_new_names_are_in_the_list_old_names_are_not(self):
        from aot.tools import tool_registry as R
        from aot.tools.domain import surface
        from aot.tools.domain.registry_data import OPS
        ents = {e['name']: e for e in surface.entries(OPS, lambda n: True, set(R.approval_required_tools()))}
        record = ents['record']['inputSchema']['properties']
        for new in ('text', 'title'):
            self.assertIn(new, record)
        for old in ('note', 'body', 'content', 'advice'):
            self.assertNotIn(old, record)
        control = ents['control']['inputSchema']['properties']
        self.assertIn('duration', control)
        for old in ('duration_seconds', 'duration_minutes'):
            self.assertNotIn(old, control)

    def test_vocabulary_table_is_in_help_not_in_the_list(self):
        from aot.tools.domain import dispatch, surface
        card = dispatch.help_card('')
        self.assertIn('vocabulary', card)
        for word in ('text', 'duration', 'state', 'offset', 'samples', 'include_<x>', 'only_<x>'):
            self.assertIn(word, card['vocabulary'])
        self.assertEqual(surface.VOCAB_HELP, card['vocabulary'])

    def test_every_vocab_word_has_a_schema_or_a_help_line(self):
        from aot.tools.domain import registry, surface
        for word in registry.VOCAB:
            if word == 'op':
                continue
            self.assertTrue(word in surface.VOCAB_SCHEMA or word in surface.VOCAB_HELP, word)

    def test_the_contract_accepts_include_and_only_prefixes(self):
        from aot.tools.domain import registry
        self.assertTrue(registry.is_vocab('include_ended'))
        self.assertTrue(registry.is_vocab('only_active'))
        self.assertFalse(registry.is_vocab('with_options'))


if __name__ == '__main__':
    unittest.main()

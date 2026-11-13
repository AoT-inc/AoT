# coding=utf-8
"""2026-11-03 MCP 수정 S3 #6·#8·#11·#13·#14 — 응답 문구가 사실을 말한다."""
import json
import unittest

from aot.tools.domain import act_say, dispatch


def _out(body):
    return [{'type': 'text', 'text': json.dumps(body)}]


class OldNames(unittest.TestCase):

    def setUp(self):
        dispatch._INNER_TO_OP.clear()
        self.addCleanup(dispatch._INNER_TO_OP.clear)

    def test_get_device_list_in_a_note_becomes_find_devices(self):
        body = {'devices': {'note': 'Use get_device_list / find.devices for the full list'}}
        dispatch._domain_hints(body)
        self.assertNotIn('get_device_list', json.dumps(body))
        self.assertIn('find.devices', body['devices']['note'])


class NamedErrors(unittest.TestCase):

    def test_resolved_id_in_an_error_is_replaced_by_the_name_the_user_gave(self):
        out = _out({'status': 'error', 'message': "could not locate '5133d6ca-1' — it may not be placed"})
        got = json.loads(dispatch._name_resolved_ids(
            out, {'target': {'id': '5133d6ca-1', 'name': '미러-온습도01'}})[0]['text'])
        self.assertIn("'미러-온습도01'", got['message'])
        self.assertNotIn('5133d6ca', got['message'])

    def test_success_and_other_text_are_left_alone(self):
        out = _out({'status': 'success', 'message': 'id 5133d6ca-1'})
        self.assertIs(out, dispatch._name_resolved_ids(out, {'target': {'id': '5133d6ca-1', 'name': 'x'}}))


class NoteSay(unittest.TestCase):

    def _say(self, changed):
        nxt = {}
        say = {}
        body = {'status': 'modified', 'changed': changed, 'note_id': 'n1'}
        act_say._note(body, say, nxt)
        return say.get('tell')

    def test_what_changed_is_named_not_the_inner_field(self):
        self.assertEqual('Updated the text.', self._say(['note']))
        self.assertEqual('Updated the title and text.', self._say(['title', 'note']))


if __name__ == '__main__':
    unittest.main()

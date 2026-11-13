# coding=utf-8
"""2026-11-03 MCP 수정 S3 #4·#5 — 승인 대기 목록의 판정·제목·시각, 되읽기 문구."""
import json
import unittest
from unittest import mock

from aot.tools import mcp_safety_gate as gate
from aot.tools import tool_execution as te
from aot.tools.domain import act_say


class Josa(unittest.TestCase):

    def test_object_particle_follows_the_sound(self):
        self.assertEqual('을', gate._eul('TEST-SEL-1'))      # 일
        self.assertEqual('를', gate._eul('TEST-SEL-2'))      # 이
        self.assertEqual('을', gate._eul('온실 문'))         # ㄴ 받침
        self.assertEqual('를', gate._eul('환풍기'))
        self.assertEqual('을', gate._eul('SEL-R'))          # 알
        self.assertEqual('을(를)', gate._eul('팬#'))


class TimedReadback(unittest.TestCase):

    def _name(self):
        return mock.patch.object(gate, '_resolve_device_display_name', lambda _i: 'TEST-SEL-1')

    def test_duration_goes_into_the_sentence_not_into_arguments(self):
        with self._name():
            text = gate.read_back_text('set_output_state', {'device_id': 'x', 'state': 'on', 'duration_seconds': 30})
        self.assertEqual('TEST-SEL-1 을 30초 동안 켜기', text.split(' (')[0] if ' (' in text else text)
        self.assertNotIn('duration', text)
        self.assertNotIn('seconds', text)

    def test_minutes_and_hours(self):
        self.assertEqual('2분', gate._duration_label({'duration_seconds': 120}))
        self.assertEqual('1시간 30분', gate._duration_label({'duration': '5400'}))
        self.assertIsNone(gate._duration_label({'duration_seconds': 0}))

    def test_title_carries_the_time(self):
        with self._name():
            self.assertEqual('TEST-SEL-1 켜기 · 30초', gate.synthesize_title(
                'set_output_state', {'device_id': 'x', 'state': 'on', 'duration_seconds': 30}))
            self.assertEqual('TEST-SEL-1 켜기', gate.synthesize_title(
                'set_output_state', {'device_id': 'x', 'state': 'on'}))

    def test_note_delete_title_names_the_note(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        with mock.patch.object(AoTDataToolService, 'note_brief', lambda _i: {'title': '시험 노트'}):
            self.assertEqual("노트 삭제: '시험 노트'", gate.synthesize_title('delete_note', {'note_id': 'n'}))
        with mock.patch.object(AoTDataToolService, 'note_brief', lambda _i: None):
            self.assertEqual('노트 삭제', gate.synthesize_title('delete_note', {'note_id': 'n'}))


class AskLine(unittest.TestCase):

    def test_korean_readback_gets_a_korean_ending(self):
        self.assertEqual('TEST-SEL-1 을 30초 동안 켜기 — 맞으면 승인해 주세요.',
                         act_say.ask_line('TEST-SEL-1 을 30초 동안 켜기'))

    def test_english_readback_keeps_the_english_ending(self):
        self.assertEqual('Fan 1 on — if this is right, please approve.', act_say.ask_line('Fan 1 on'))


class PendingListProfile(unittest.TestCase):

    def test_domain_only_tool_is_not_masked_when_the_domain_surface_is_on(self):
        res = {'pending': [{'tool_name': 'set_output_state', 'params': {}, 'title': 'x'}]}
        with mock.patch.object(te, 'domain_surface_enabled', lambda: True):
            out = te._mask_out_of_profile_pending(res, 'ops')
        self.assertEqual('set_output_state', out['pending'][0].get('tool_name'))
        self.assertNotIn('out_of_profile_note', out)


if __name__ == '__main__':
    unittest.main()

# coding=utf-8
"""시간 규칙 가드 — 진입점과 스캐너 시험.

구현은 `aot/scripts/check_time_rules.py` 다(훅·CI 도 같은 것을 부른다). 이 테스트는
(1) 스캐너가 의도대로 잡고 놓아주는지, (2) 저장소 전체가 기준선(`time_rules_baseline.json`)
보다 나빠지지 않았는지를 본다. 규칙·교체표·메시지는 스크립트에 있다.

기준선을 낮출 때: `python3 aot/scripts/check_time_rules.py --update-baseline`
(또는 `AOT_TIME_BASELINE_UPDATE=1 pytest aot/tests/test_time_rules_guard.py`).
"""
import os
import unittest

from aot.scripts import check_time_rules as guard
from aot.scripts.check_time_rules import scan_js, scan_python

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestScannerRules(unittest.TestCase):
    """스캐너 자신이 의도대로 잡고 놓아주는지."""

    def rules(self, src):
        return sorted(r for _, r in scan_python(src))

    def test_catches_fixed_offset_shift(self):
        self.assertEqual(self.rules(
            "now_kst = datetime.utcnow() + timedelta(hours=9)\n"),
            ['fixed_offset_shift', 'kst_name', 'naive_now'])
        self.assertEqual(self.rules(
            "d = (utc_now() - timedelta(hours=5)).date()\n"),
            ['fixed_offset_shift'])

    def test_plain_interval_is_fine(self):
        self.assertEqual(self.rules("t = start + timedelta(hours=6)\n"), [])
        self.assertEqual(self.rules("t = x + timedelta(hours=ttl)\n"), [])

    def test_catches_literals(self):
        self.assertEqual(self.rules("tz = pytz.timezone('Asia/Seoul')\n"),
                         ['raw_tz', 'tz_literal'])
        self.assertEqual(self.rules("s = '+09:00'\n"), ['offset_literal'])
        self.assertEqual(self.rules("o = 9 * 3600\n"), ['seconds_9h'])
        self.assertEqual(self.rules("o = 32400\n"), ['seconds_9h'])

    def test_docstrings_prose_and_utc_are_fine(self):
        self.assertEqual(self.rules(
            'def f():\n    """예: Asia/Seoul, +09:00"""\n'
            "    x = 'ISO 8601 예 2026-10-24T15:00+09:00'\n"
            "    tz = pytz.timezone('UTC')\n"), [])

    def test_tz_ok_needs_a_reason(self):
        self.assertEqual(self.rules(
            "s = '+09:00'  # tz-ok: 외부 API 규격이 고정 오프셋\n"), [])
        self.assertEqual(self.rules("s = '+09:00'  # tz-ok:\n"),
                         ['offset_literal'])

    def test_slash_labels_are_not_timezones(self):
        self.assertEqual(self.rules("a = 'On/Off'\nb = 'Humidity/Temperature'\n"), [])

    def test_zero_offset_is_not_a_hardcoded_zone_but_parsing_by_hand_is_caught(self):
        # '+00:00' 는 시간대 하드코딩이 아니지만 ISO 를 손으로 다루는 것(iso_by_hand)이다
        self.assertEqual(self.rules("s = x.replace('Z', '+00:00')\n"), ['iso_by_hand'])
        self.assertEqual(self.rules("s = '+00:00'\n"), [])

    def test_names(self):
        self.assertEqual(self.rules("utc_date = 1\n"), ['utc_date_display'])
        self.assertEqual(self.rules("tz_s = 1\n"), ['tz_s_offset'])

    def test_js(self):
        self.assertEqual([r for _, r in scan_js("const z = 'Asia/Seoul';\n")],
                         ['tz_literal'])
        self.assertEqual(scan_js("// 'Asia/Seoul' 예\n"), [])


class TestNoNewHardcodedTime(unittest.TestCase):

    def test_no_new_violations(self):
        # 기준선은 0 으로 비어 있고, 구조상 못 바꾸는 곳만 check_time_rules.EXCEPTIONS 에 사유와 함께 있다
        self.assertEqual(guard.load_baseline(os.path.join(_ROOT, guard._BASELINE_REL)), {})
        code, msg, _ = guard.check(_ROOT)
        self.assertEqual(code, 0, msg)


if __name__ == '__main__':
    unittest.main()

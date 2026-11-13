# coding=utf-8
"""`aot/scripts/check_time_rules.py` 자체의 시험 — 교체표 규칙, 메시지, --staged.

하위 세션은 설계서를 읽지 않고 이 가드의 실패 메시지로만 교정받는다. 그래서
"잡는가" 만이 아니라 "줄 번호와 대안을 말하는가" 를 고정한다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from aot.scripts import check_time_rules as g

_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(g.__file__)), 'check_time_rules.py')


def detail(src, rel=None):
    return g.scan_python_detail(src, rel)


class TestOldEntry(unittest.TestCase):

    def test_import_and_call_are_caught_with_replacement(self):
        hits = detail("from aot.utils.time_utils import serialize_ts\n"
                      "x = serialize_ts(row.ts)\n")
        self.assertEqual([(h.line, h.rule) for h in hits],
                         [(1, 'old_entry'), (2, 'old_entry')])
        self.assertTrue(all('iso_at' in h.hint for h in hits))

    def test_module_attribute_call_is_caught(self):
        hits = detail("from aot.utils import device_tz\n"
                      "tz = device_tz.resolve_location_tz(tid)\n")
        self.assertEqual([(h.line, h.rule) for h in hits], [(2, 'old_entry')])
        self.assertIn('tz_of(id)', hits[0].hint)

    def test_utc_now_only_the_import_from_the_old_module(self):
        old = detail("from aot.utils.time_utils import utc_now\nt = utc_now()\n")
        self.assertEqual([(h.line, h.rule) for h in old], [(1, 'old_entry')])
        self.assertEqual(detail("from aot.utils.timekit import utc_now\nt = utc_now()\n"), [])

    def test_unrelated_same_named_method_is_not_flagged(self):
        # 좌표를 바꾸는 to_local 메서드(water_net 어댑터)는 시간 입구가 아니다
        self.assertEqual(detail("class A:\n    def to_local(self, lng, lat):\n"
                                "        return self.to_local(lng, lat)\n"), [])

    def test_top_level_duplicate_definition_is_flagged(self):
        hits = detail("def get_local_now():\n    return 1\nx = get_local_now()\n")
        self.assertEqual([(h.line, h.rule) for h in hits],
                         [(1, 'old_entry'), (3, 'old_entry')])

    def test_tz_ok_without_reason_is_not_accepted(self):
        src = "from aot.utils.time_utils import to_local  # tz-ok:\n"
        self.assertEqual([h.rule for h in detail(src)], ['old_entry'])
        src = "from aot.utils.time_utils import to_local  # tz-ok: 이유\n"
        self.assertEqual(detail(src), [])

    def test_exempt_files_are_not_scanned(self):
        self.assertFalse(g.is_scanned_py('aot/utils/timekit.py'))
        self.assertFalse(g.is_scanned_py('aot/utils/device_tz.py'))
        self.assertTrue(g.is_scanned_py('aot/utils/time_utils.py'))
        self.assertFalse(g.is_scanned_py('aot/tests/test_x.py'))


class TestOtherRules(unittest.TestCase):

    def rules(self, src):
        return sorted(h.rule for h in detail(src))

    def test_naive_now(self):
        for expr in ('datetime.datetime.utcnow()', 'datetime.now()', 'date.today()',
                     'datetime.utcfromtimestamp(t)'):
            self.assertEqual(self.rules('x = %s\n' % expr), ['naive_now'], expr)
        self.assertEqual(self.rules('x = datetime.now(tz)\n'), [])
        self.assertEqual(self.rules('x = datetime.now(timezone.utc)\n'), [])

    def test_raw_tz(self):
        for expr in ("pytz.timezone(name)", "ZoneInfo(name)", "tz.localize(d)",
                     "time.mktime(t)", "time.localtime(t)"):
            self.assertEqual(self.rules('x = %s\n' % expr), ['raw_tz'], expr)
        self.assertEqual(self.rules("x = pytz.timezone('UTC')\n"), [])

    def test_iso_by_hand(self):
        for expr in ("s.replace('Z', '+00:00')", "t[:-1] + '+00:00'",
                     'f"{h}.{f}+00:00"'):
            self.assertEqual(self.rules('x = %s\n' % expr), ['iso_by_hand'], expr)

    def test_private_helper(self):
        self.assertEqual(self.rules('def _naive_utc(dt):\n    return dt\n'), ['private_helper'])
        self.assertEqual(self.rules('def _wall_tz(t):\n    return t\n'), [])


class TestMessage(unittest.TestCase):

    def test_report_names_file_line_and_replacement(self):
        src = "from aot.utils.time_utils import serialize_ts\nx = serialize_ts(v)\n"
        found = {'aot/foo/bar.py': detail(src)}
        worse = g.worse_than(g.counts_of(found), {})
        msg = g.format_report(worse, found)
        self.assertIn('aot/foo/bar.py:2', msg)
        self.assertIn('→ iso_at(값, 장소id)', msg)
        self.assertIn('장소와 무관하면 iso_at(값, FARM)', msg)
        self.assertIn('# tz-ok: 이유', msg)
        self.assertIn('from aot.utils.timekit import', msg)

    def test_every_replacement_target_is_a_real_new_entry(self):
        from aot.utils import timekit
        import re
        for old, (new, _, _, _) in g.REPLACEMENTS.items():
            for name in re.findall(r'(?<![.\w])([a-z_]+)\(', new):
                if name in ('str',):
                    continue
                self.assertIn(name, timekit.PUBLIC_ENTRIES, '%s → %s' % (old, new))

    def test_baseline_only_fails_when_it_grows(self):
        counts = {'a.py::old_entry': 3}
        self.assertEqual(g.worse_than(counts, {'a.py::old_entry': 3}), [])
        self.assertEqual(g.worse_than(counts, {'a.py::old_entry': 5}), [])
        self.assertEqual(g.worse_than(counts, {'a.py::old_entry': 2}),
                         [('a.py::old_entry', 3, 2)])


class _RepoCase(unittest.TestCase):
    """임시 git 저장소에서 가드 CLI 를 돌리는 공통 바탕."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, 'aot', 'x'))
        self.git('init', '-q')
        self.git('config', 'user.email', 't@t')
        self.git('config', 'user.name', 't')
        self.base = os.path.join(self.tmp, 'base.json')
        with open(self.base, 'w') as fh:
            json.dump({}, fh)

    def git(self, *a):
        return subprocess.run(['git'] + list(a), cwd=self.tmp, capture_output=True, text=True)

    def run_guard(self, *extra, exceptions=()):
        exc = os.path.join(self.tmp, 'exceptions.json')
        with open(exc, 'w', encoding='utf-8') as fh:
            json.dump(list(exceptions), fh)
        return subprocess.run([sys.executable, _SCRIPT, '--root', self.tmp,
                               '--baseline', self.base, '--exceptions', exc] + list(extra),
                              capture_output=True, text=True)

    def write(self, rel, text):
        path = os.path.join(self.tmp, rel)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)
        return path


@unittest.skipUnless(shutil.which('git'), 'git 이 필요합니다')
class TestStagedMode(_RepoCase):

    def test_staged_blob_decides_not_the_worktree(self):
        self.write('aot/x/a.py', "from datetime import datetime\nn = datetime.utcnow()\n")
        self.git('add', 'aot/x/a.py')
        # 워킹트리는 고쳐 두었지만 인덱스는 아직 위반이다 — 인덱스를 본다
        self.write('aot/x/a.py', "n = 1\n")
        res = self.run_guard('--staged')
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn('aot/x/a.py:2', res.stderr)
        self.assertIn('→ utc_now()', res.stderr)

    def test_unstaged_violation_is_ignored(self):
        self.write('aot/x/a.py', "n = 1\n")
        self.git('add', 'aot/x/a.py')
        self.write('aot/x/b.py', "from datetime import datetime\nn = datetime.utcnow()\n")
        self.assertEqual(self.run_guard('--staged').returncode, 0)
        self.assertEqual(self.run_guard().returncode, 1)         # 워킹트리 전체는 본다

    def test_baseline_absorbs_existing_hits(self):
        self.write('aot/x/a.py', "from datetime import datetime\nn = datetime.utcnow()\n")
        self.git('add', 'aot/x/a.py')
        with open(self.base, 'w') as fh:
            json.dump({'aot/x/a.py::naive_now': 1}, fh)
        self.assertEqual(self.run_guard('--staged').returncode, 0)

    def test_update_baseline_writes_current_counts(self):
        self.write('aot/x/a.py', "from datetime import datetime\nn = datetime.utcnow()\n")
        self.assertEqual(self.run_guard('--update-baseline').returncode, 0)
        with open(self.base) as fh:
            self.assertEqual(json.load(fh), {'aot/x/a.py::naive_now': 1})


class TestExceptionTable(unittest.TestCase):
    """S10 — 기준선은 0, 예외는 (파일, 규칙, 글자 조각, 사유) 표 하나."""

    SRC = "from datetime import datetime\nn = datetime.utcnow()\n"

    def found(self, src=None, rel='aot/x/a.py'):
        return {rel: detail(src or self.SRC, rel)}

    def test_repo_baseline_is_empty(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(g.__file__))))
        self.assertEqual(g.load_baseline(os.path.join(root, g._BASELINE_REL)), {})

    def test_every_repo_exception_has_a_reason(self):
        for rel, rule, anchor, reason in g.EXCEPTIONS:
            self.assertTrue(str(reason).strip(), (rel, rule))
            self.assertIn(rule, g.RULES, (rel, rule))

    def test_matching_exception_hides_the_violation(self):
        ex = [('aot/x/a.py', 'naive_now', 'utcnow', '사유')]
        self.assertEqual(g.apply_exceptions(self.found(), ex), {})
        self.assertEqual(g._exception_errors(self.found(), ex), [])

    def test_exception_without_reason_hides_nothing_and_is_reported(self):
        ex = [('aot/x/a.py', 'naive_now', 'utcnow', '  ')]
        self.assertTrue(g.apply_exceptions(self.found(), ex))
        errs = g._exception_errors(self.found(), ex)
        self.assertEqual(len(errs), 1)
        self.assertIn('사유', errs[0][1])

    def test_violation_outside_the_table_is_still_a_violation(self):
        ex = [('aot/x/other.py', 'naive_now', None, '사유')]
        left = g.apply_exceptions(self.found(), ex)
        self.assertEqual(list(left), ['aot/x/a.py'])

    def test_anchor_must_match_the_line_not_the_line_number(self):
        ex = [('aot/x/a.py', 'naive_now', 'utcfromtimestamp', '사유')]
        self.assertTrue(g.apply_exceptions(self.found(), ex))          # 글자 조각이 어긋남
        moved = "\n\n\n" + self.SRC                                    # 줄이 밀려도 따라온다
        ex = [('aot/x/a.py', 'naive_now', 'utcnow', '사유')]
        self.assertEqual(g.apply_exceptions(self.found(moved), ex), {})

    def test_other_rule_in_same_file_is_not_covered(self):
        src = self.SRC + "import pytz\nz = pytz.timezone(name)\n"
        ex = [('aot/x/a.py', 'naive_now', None, '사유')]
        left = g.apply_exceptions(self.found(src), ex)
        self.assertEqual({h.rule for h in left['aot/x/a.py']}, {'raw_tz'})

    def test_stale_exception_is_reported(self):
        ex = [('aot/x/a.py', 'raw_tz', None, '사유')]
        errs = g._exception_errors(self.found(), ex)
        self.assertEqual(len(errs), 1)
        self.assertIn('맞는 위반이 없습니다', errs[0][1])

    def test_localize_on_a_non_timezone_receiver_is_not_flagged(self):
        self.assertEqual(detail("data = utils_function_status.localize(data)\n"), [])
        self.assertEqual([h.rule for h in detail("t = tz.localize(dt)\n")], ['raw_tz'])
        self.assertEqual([h.rule for h in detail("t = pytz.timezone('UTC')\nu = local_tz.localize(x)\n")],
                         ['raw_tz'])

    def test_private_helper_that_delegates_to_timekit_is_a_thin_adapter(self):
        thin = "from aot.utils.timekit import utc_now\ndef _now():\n    return utc_now()\n"
        self.assertEqual(detail(thin), [])
        own = "def _now():\n    return 1\n"
        self.assertEqual([h.rule for h in detail(own)], ['private_helper'])


@unittest.skipUnless(shutil.which('git'), 'git 이 필요합니다')
class TestExceptionTableCli(TestStagedMode):
    """같은 임시 저장소로 CLI 의 종료 코드를 본다."""

    def test_violation_fails_and_an_exception_with_reason_passes(self):
        self.write('aot/x/a.py', self.SRC_V)
        self.assertEqual(self.run_guard().returncode, 1)
        ex = [['aot/x/a.py', 'naive_now', 'utcnow', '시험용 사유']]
        self.assertEqual(self.run_guard(exceptions=ex).returncode, 0)

    def test_exception_without_reason_fails_even_if_it_matches(self):
        self.write('aot/x/a.py', self.SRC_V)
        res = self.run_guard(exceptions=[['aot/x/a.py', 'naive_now', 'utcnow', '']])
        self.assertEqual(res.returncode, 1)
        self.assertIn('사유', res.stderr)

    def test_stale_exception_fails_the_full_run_but_not_staged(self):
        self.write('aot/x/a.py', "n = 1\n")
        self.git('add', 'aot/x/a.py')
        ex = [['aot/x/a.py', 'naive_now', 'utcnow', '사유']]
        res = self.run_guard(exceptions=ex)
        self.assertEqual(res.returncode, 1)
        self.assertIn('맞는 위반이 없습니다', res.stderr)
        self.assertEqual(self.run_guard('--staged', exceptions=ex).returncode, 0)

    SRC_V = "from datetime import datetime\nn = datetime.utcnow()\n"


if __name__ == '__main__':
    unittest.main()

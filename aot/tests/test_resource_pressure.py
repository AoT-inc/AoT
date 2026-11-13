# coding=utf-8
"""자원 압박 판정(R1, 관찰만)과 웹 응답 시간 집계를 고정한다.

- 신호: PSI 는 컨테이너 cgroup 파일이 있으면 그것, 없으면 /proc/pressure.
  메모리 가용률은 컨테이너 한도 기준(페이지 캐시 제외), 없으면 MemAvailable.
- 판정: 가장 나쁜 신호 하나가 단계를 정한다. 부하 평균은 PSI 가 없을 때만.
  파이 스로틀 현재 비트는 최소 '주의'.
- 히스테리시스: 올라갈 때 즉시, 내려갈 때 DOWN_HOLD_S 동안 낮아야.
- 웹: 워커 p95 는 합칠 수 없어 가장 나쁜 워커. 표본이 적거나 파일이 낡으면 없음.
"""
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from aot.utils import resource_pressure as rp
from aot.utils import web_latency as wl

PSI = ("some avg10={s:.2f} avg60=1.00 avg300=0.50 total=123\n"
       "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


class SignalTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cg = os.path.join(self.tmp.name, 'cgroup')
        self.proc = os.path.join(self.tmp.name, 'pressure')
        os.makedirs(self.cg)
        os.makedirs(self.proc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_psi(self):
        parsed = rp.parse_psi(PSI.format(s=12.5))
        self.assertEqual(parsed['some']['avg10'], 12.5)
        self.assertEqual(parsed['full']['avg10'], 0.0)
        self.assertIsNone(rp.parse_psi('garbage'))
        self.assertIsNone(rp.parse_psi(None))

    def test_psi_takes_worse_of_own_cgroup_and_machine(self):
        """도커에서 데몬 쪽 판정이 웹 컨테이너의 정체를 놓치지 않게, 기기 전체도 본다."""
        _w(os.path.join(self.cg, 'cpu.pressure'), PSI.format(s=40))
        _w(os.path.join(self.proc, 'cpu'), PSI.format(s=5))
        self.assertEqual(rp.read_psi('cpu', self.cg, self.proc), (40.0, 'cgroup'))
        _w(os.path.join(self.proc, 'cpu'), PSI.format(s=55))
        self.assertEqual(rp.read_psi('cpu', self.cg, self.proc), (55.0, 'proc'))

    def test_cpu_usage_against_limit_and_throttle(self):
        rp._reset_for_tests()
        stat = os.path.join(self.cg, 'cpu.stat')
        _w(stat, 'usage_usec 1000000\nuser_usec 1\nthrottled_usec 0\nnr_throttled 0\n')
        self.assertEqual(rp.cpu_usage(self.cg, now=100.0, cores=4), (None, None))   # 기준점
        # 10초 동안 30코어초 사용(4코어 한도의 75%), 그중 2초 스로틀
        _w(stat, 'usage_usec 31000000\nthrottled_usec 2000000\n')
        with patch.object(rp, '_online_cpus', return_value=4):
            used, thr = rp.cpu_usage(self.cg, now=110.0, cores=4)
        self.assertAlmostEqual(used, 75.0)
        self.assertAlmostEqual(thr, 5.0)     # CPU 4개 몫의 스로틀 합 2초 / (10초 × 4)
        rp._reset_for_tests()

    def test_cpu_usage_quick_recall_keeps_baseline(self):
        """캐시가 만료된 순간 두 스레드가 함께 부르면, 뒤 호출이 기준점을 덮어써 None 이
        되던 것 — 1초 안의 재호출은 직전 결과를 돌려주고 기준점을 그대로 둔다."""
        rp._reset_for_tests()
        stat = os.path.join(self.cg, 'cpu.stat')
        _w(stat, 'usage_usec 0\n')
        rp.cpu_usage(self.cg, now=100.0, cores=1)
        _w(stat, 'usage_usec 5000000\n')
        first = rp.cpu_usage(self.cg, now=110.0, cores=1)
        self.assertAlmostEqual(first[0], 50.0)
        _w(stat, 'usage_usec 5100000\n')
        self.assertEqual(rp.cpu_usage(self.cg, now=110.3, cores=1), first)
        _w(stat, 'usage_usec 10000000\n')
        self.assertAlmostEqual(rp.cpu_usage(self.cg, now=120.0, cores=1)[0], 50.0)
        rp._reset_for_tests()

    def test_cpu_usage_counter_reset(self):
        rp._reset_for_tests()
        stat = os.path.join(self.cg, 'cpu.stat')
        _w(stat, 'usage_usec 9000000\n')
        rp.cpu_usage(self.cg, now=100.0, cores=1)
        _w(stat, 'usage_usec 100\n')                    # 컨테이너 재시작 등으로 줄었다
        self.assertEqual(rp.cpu_usage(self.cg, now=110.0, cores=1), (None, None))
        _w(stat, 'usage_usec 2000100\n')
        self.assertAlmostEqual(rp.cpu_usage(self.cg, now=120.0, cores=1)[0], 20.0)
        rp._reset_for_tests()

    def test_cpu_allowance_keeps_fraction(self):
        """1.5코어 한도를 1코어로 내리면 포화가 150% 로 나온다."""
        _w(os.path.join(self.cg, 'cpu.max'), '150000 100000\n')
        with patch.object(rp, '_online_cpus', return_value=8):
            self.assertAlmostEqual(rp.cpu_allowance(self.cg), 1.5)
        _w(os.path.join(self.cg, 'cpu.max'), 'max 100000\n')
        with patch.object(rp, '_online_cpus', return_value=4):
            self.assertAlmostEqual(rp.cpu_allowance(self.cg), 4.0)

    def test_cpu_usage_without_cgroup_v2(self):
        rp._reset_for_tests()
        self.assertEqual(rp.cpu_usage(self.cg, now=1.0, cores=4), (None, None))

    def test_memory_takes_lower_of_container_and_machine(self):
        _w(os.path.join(self.cg, 'memory.max'), str(1000 * 1024 * 1024))
        _w(os.path.join(self.cg, 'memory.current'), str(200 * 1024 * 1024))   # 컨테이너 80%
        meminfo = os.path.join(self.tmp.name, 'meminfo')
        _w(meminfo, 'MemTotal:  4000000 kB\nMemAvailable:  400000 kB\n')       # 기기 10%
        self.assertAlmostEqual(rp.mem_available_pct(self.cg, meminfo), 10.0)

    def test_psi_falls_back_to_proc(self):
        # 베어메탈: cgroup 루트에는 pressure 파일이 없다
        _w(os.path.join(self.proc, 'io'), PSI.format(s=7))
        self.assertEqual(rp.read_psi('io', self.cg, self.proc), (7.0, 'proc'))

    def test_psi_absent(self):
        self.assertEqual(rp.read_psi('memory', self.cg, self.proc), (None, None))

    def test_memory_uses_container_limit_without_page_cache(self):
        _w(os.path.join(self.cg, 'memory.max'), str(1000 * 1024 * 1024))
        _w(os.path.join(self.cg, 'memory.current'), str(900 * 1024 * 1024))
        _w(os.path.join(self.cg, 'memory.stat'),
           'anon 1\ninactive_file %d\nactive_file 2\n' % (400 * 1024 * 1024))
        # 실제 사용 500MB / 한도 1000MB → 가용 50%
        self.assertAlmostEqual(rp.mem_available_pct(self.cg, '/nonexistent'), 50.0)

    def test_memory_without_limit_uses_meminfo(self):
        _w(os.path.join(self.cg, 'memory.max'), 'max')
        meminfo = os.path.join(self.tmp.name, 'meminfo')
        _w(meminfo, 'MemTotal:  4000000 kB\nMemFree: 1 kB\nMemAvailable:  1000000 kB\n')
        self.assertAlmostEqual(rp.mem_available_pct(self.cg, meminfo), 25.0)

    def test_parse_throttled(self):
        self.assertEqual(rp.parse_throttled('throttled=0x50005\n'), 0x50005)
        self.assertEqual(rp.parse_throttled('throttled=0x0'), 0)
        self.assertIsNone(rp.parse_throttled('error'))

    def test_throttled_none_without_vcgencmd(self):
        rp._reset_for_tests()
        with patch.object(rp.shutil, 'which', return_value=None), \
                patch.object(rp.os.path, 'exists', return_value=False):
            self.assertIsNone(rp.throttled_bits(now=1000.0))

    def test_temperature(self):
        path = os.path.join(self.tmp.name, 'temp')
        _w(path, '61234\n')
        self.assertAlmostEqual(rp.cpu_temperature_c(path), 61.234)
        self.assertIsNone(rp.cpu_temperature_c(os.path.join(self.tmp.name, 'none')))


def _sig(**kw):
    base = {'cpu_psi': 1.0, 'memory_psi': 0.0, 'io_psi': 0.0, 'load_per_core': 0.1,
            'cpu_used_pct': 10.0, 'cpu_throttled_pct': 0.0,
            'mem_available_pct': 60.0, 'web_p95_ms': 40.0, 'throttled_bits': None}
    base.update(kw)
    return base


class StageTest(unittest.TestCase):

    def test_quiet_is_normal(self):
        self.assertEqual(rp.raw_stage(_sig()), (rp.STAGE_NORMAL, []))

    def test_worst_signal_wins(self):
        stage, reasons = rp.raw_stage(_sig(cpu_psi=25, web_p95_ms=1500))
        self.assertEqual(stage, rp.STAGE_OVERLOAD)
        self.assertEqual(reasons, ['web_p95_ms'])

    def test_web_p95_alone_does_not_raise(self):
        """한가한 서버의 원래 무거운 요청(맥미니 26-11-10: CPU 0.9%·PSI 0.18·가용 메모리 23%)."""
        sig = _sig(cpu_psi=0.18, cpu_used_pct=0.9, mem_available_pct=23.0, web_p95_ms=758.0)
        self.assertEqual(rp.raw_stage(sig), (rp.STAGE_NORMAL, []))
        self.assertEqual(rp.raw_stage(_sig(web_p95_ms=2500.0))[0], rp.STAGE_NORMAL)

    def test_web_p95_counts_with_resource_corroboration(self):
        # CPU PSI 가 주의 문턱(20)의 절반 이상이면 웹 p95 가 단계를 끌어올린다
        self.assertEqual(rp.raw_stage(_sig(cpu_psi=10.0, web_p95_ms=1200.0)),
                         (rp.STAGE_OVERLOAD, ['web_p95_ms']))
        self.assertEqual(rp.raw_stage(_sig(cpu_psi=9.9, web_p95_ms=1200.0))[0], rp.STAGE_NORMAL)
        self.assertEqual(rp.raw_stage(_sig(cpu_used_pct=40.0, web_p95_ms=300.0))[0],
                         rp.STAGE_WATCH)
        self.assertEqual(rp.raw_stage(_sig(io_psi=15.0, web_p95_ms=300.0))[0], rp.STAGE_WATCH)
        # 메모리는 주의 문턱(가용 15%) 아래일 때만 받친다
        self.assertEqual(rp.raw_stage(_sig(mem_available_pct=14.0, web_p95_ms=1200.0))[0],
                         rp.STAGE_OVERLOAD)

    def test_web_p95_corroborated_by_load_only_without_psi(self):
        no_psi = dict(cpu_psi=None, memory_psi=None, io_psi=None, cpu_used_pct=None)
        self.assertEqual(rp.raw_stage(_sig(load_per_core=0.5, web_p95_ms=1200.0, **no_psi))[0],
                         rp.STAGE_OVERLOAD)
        self.assertEqual(rp.raw_stage(_sig(load_per_core=0.3, web_p95_ms=1200.0, **no_psi))[0],
                         rp.STAGE_NORMAL)
        # PSI 가 있으면 부하 평균은 받침이 되지 않는다
        self.assertEqual(rp.raw_stage(_sig(load_per_core=3.0, web_p95_ms=1200.0))[0],
                         rp.STAGE_NORMAL)

    def test_low_memory_is_worse(self):
        self.assertEqual(rp.raw_stage(_sig(mem_available_pct=10))[0], rp.STAGE_WATCH)
        self.assertEqual(rp.raw_stage(_sig(mem_available_pct=5))[0], rp.STAGE_OVERLOAD)

    def test_load_ignored_when_psi_present(self):
        self.assertEqual(rp.raw_stage(_sig(load_per_core=3.0))[0], rp.STAGE_NORMAL)

    def test_load_used_when_no_psi(self):
        stage, reasons = rp.raw_stage(_sig(cpu_psi=None, memory_psi=None, io_psi=None,
                                           load_per_core=2.0))
        self.assertEqual((stage, reasons), (rp.STAGE_OVERLOAD, ['load_per_core']))

    def test_current_throttle_is_at_least_watch(self):
        self.assertEqual(rp.raw_stage(_sig(throttled_bits=0x4)), (rp.STAGE_WATCH, ['throttled']))
        # 부팅 이후 이력 비트(16~19)만 서 있으면 지금은 느리지 않다
        self.assertEqual(rp.raw_stage(_sig(throttled_bits=0x50000))[0], rp.STAGE_NORMAL)

    def test_missing_signals_are_normal(self):
        empty = {k: None for k in _sig()}
        self.assertEqual(rp.raw_stage(empty), (rp.STAGE_NORMAL, []))

    def test_s2_thresholds(self):
        """S2(일반 PC) 1차 조정: CPU PSI 과부하 30, CPU 한도 대비 사용률 70/85."""
        self.assertEqual(rp.raw_stage(_sig(cpu_psi=33))[0], rp.STAGE_OVERLOAD)    # P3 120명 중앙
        self.assertEqual(rp.raw_stage(_sig(cpu_psi=19.6))[0], rp.STAGE_NORMAL)
        self.assertEqual(rp.raw_stage(_sig(cpu_used_pct=45))[0], rp.STAGE_NORMAL)  # P2 120명
        self.assertEqual(rp.raw_stage(_sig(cpu_used_pct=74))[0], rp.STAGE_WATCH)   # P2 160명
        self.assertEqual(rp.raw_stage(_sig(cpu_used_pct=95)), (rp.STAGE_OVERLOAD, ['cpu_used_pct']))

    def test_single_spike_does_not_raise(self):
        """첫 로드 한 번의 튐이 단계를 올리지 않는다 — 10초 이어져야 오른다."""
        tr = rp.StageTracker(hold_s=60, up_hold_s=10)
        self.assertEqual(tr.update(rp.STAGE_OVERLOAD, 0), rp.STAGE_NORMAL)
        self.assertEqual(tr.update(rp.STAGE_NORMAL, 5), rp.STAGE_NORMAL)
        self.assertEqual(tr.update(rp.STAGE_OVERLOAD, 20), rp.STAGE_NORMAL)    # 대기 처음부터
        self.assertEqual(tr.update(rp.STAGE_OVERLOAD, 25), rp.STAGE_NORMAL)
        self.assertEqual(tr.update(rp.STAGE_OVERLOAD, 30), rp.STAGE_OVERLOAD)  # 10초 이어짐

    def test_rise_goes_to_lowest_seen_in_window(self):
        tr = rp.StageTracker(hold_s=60, up_hold_s=10)
        tr.update(rp.STAGE_OVERLOAD, 0)
        tr.update(rp.STAGE_WATCH, 5)
        self.assertEqual(tr.update(rp.STAGE_OVERLOAD, 10), rp.STAGE_WATCH)
        tr.update(rp.STAGE_OVERLOAD, 15)
        self.assertEqual(tr.update(rp.STAGE_OVERLOAD, 20), rp.STAGE_OVERLOAD)

    def test_rise_wait_is_cut_when_back_to_current(self):
        tr = rp.StageTracker(hold_s=60, up_hold_s=10)
        tr.update(rp.STAGE_WATCH, 0)
        tr.update(rp.STAGE_NORMAL, 5)                # 원래 단계로 돌아옴 — 대기 끊김
        self.assertEqual(tr.update(rp.STAGE_WATCH, 11), rp.STAGE_NORMAL)
        self.assertEqual(tr.update(rp.STAGE_WATCH, 21), rp.STAGE_WATCH)

    def test_two_step_rise(self):
        tr = rp.StageTracker(hold_s=60, up_hold_s=10)
        tr.update(rp.STAGE_WATCH, 0)
        tr.update(rp.STAGE_OVERLOAD, 5)
        self.assertEqual(tr.update(rp.STAGE_OVERLOAD, 10), rp.STAGE_WATCH)    # 창 최솟값
        self.assertEqual(tr.update(rp.STAGE_OVERLOAD, 15), rp.STAGE_WATCH)
        self.assertEqual(tr.update(rp.STAGE_OVERLOAD, 20), rp.STAGE_OVERLOAD)

    def test_hysteresis_goes_down_only_after_hold(self):
        tr = rp.StageTracker(hold_s=60, up_hold_s=0)
        self.assertEqual(tr.update(rp.STAGE_OVERLOAD, 0), rp.STAGE_OVERLOAD)   # 즉시 올라감
        self.assertEqual(tr.update(rp.STAGE_NORMAL, 10), rp.STAGE_OVERLOAD)
        self.assertEqual(tr.update(rp.STAGE_NORMAL, 50), rp.STAGE_OVERLOAD)
        self.assertEqual(tr.update(rp.STAGE_NORMAL, 70), rp.STAGE_NORMAL)      # 60초 낮았음

    def test_hysteresis_goes_down_to_worst_seen_in_window(self):
        """과부하 뒤 60초 동안 주의가 섞였으면, 그 순간 값이 정상이어도 주의까지만."""
        tr = rp.StageTracker(hold_s=60, up_hold_s=0)
        tr.update(rp.STAGE_OVERLOAD, 0)
        tr.update(rp.STAGE_NORMAL, 10)
        tr.update(rp.STAGE_WATCH, 40)
        self.assertEqual(tr.update(rp.STAGE_NORMAL, 70), rp.STAGE_WATCH)
        # 이어서 60초 더 정상이면 정상으로
        self.assertEqual(tr.update(rp.STAGE_NORMAL, 100), rp.STAGE_WATCH)
        self.assertEqual(tr.update(rp.STAGE_NORMAL, 130), rp.STAGE_NORMAL)

    def test_hysteresis_rise_resets_wait(self):
        tr = rp.StageTracker(hold_s=60, up_hold_s=0)
        tr.update(rp.STAGE_WATCH, 100)
        tr.update(rp.STAGE_NORMAL, 110)
        tr.update(rp.STAGE_WATCH, 150)              # 다시 올라 대기 시간이 처음부터
        self.assertEqual(tr.update(rp.STAGE_NORMAL, 175), rp.STAGE_WATCH)

    def test_current_caches_and_survives_errors(self):
        rp._reset_for_tests()
        rp._tracker = rp.StageTracker(up_hold_s=0)
        calls = []

        def fake():
            calls.append(1)
            return _sig(cpu_psi=25)
        with patch.object(rp, 'read_signals', fake):
            a = rp.current(now=1000.0)
            b = rp.current(now=1002.0)
            self.assertIs(a, b)
            self.assertEqual(len(calls), 1)
            self.assertEqual((a['stage'], a['stage_name']), (rp.STAGE_WATCH, 'watch'))
        with patch.object(rp, 'read_signals', side_effect=RuntimeError('x')):
            c = rp.current(now=1010.0)
            # 판정이 실패하면 직전 단계를 그대로 둔다(정상으로 떨어뜨리지 않는다)
            self.assertEqual(c['stage'], rp.STAGE_WATCH)
            self.assertEqual(c['reasons'], ['error'])
        rp._reset_for_tests()

    def test_memory_cgroup_v1_limit(self):
        with tempfile.TemporaryDirectory() as root:
            _w(os.path.join(root, 'memory', 'memory.limit_in_bytes'), str(800 * 1024 * 1024))
            _w(os.path.join(root, 'memory', 'memory.usage_in_bytes'), str(700 * 1024 * 1024))
            _w(os.path.join(root, 'memory', 'memory.stat'),
               'cache 1\ntotal_inactive_file %d\n' % (100 * 1024 * 1024))
            self.assertAlmostEqual(rp.mem_available_pct(root, '/nonexistent'), 25.0)


class WebLatencyTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(os.environ, {'AOT_WEB_LATENCY_DIR': self.tmp.name})
        self._env.start()
        # 배경 기록 스레드는 띄우지 않는다 — 시험이 끝난 뒤 실제 경로에 쓰지 않게.
        self._flusher = patch.object(wl, '_ensure_flusher', lambda: None)
        self._flusher.start()
        wl._reset_for_tests()

    def tearDown(self):
        self._flusher.stop()
        self._env.stop()
        wl._reset_for_tests()
        self.tmp.cleanup()

    def _file(self, name, **row):
        with open(os.path.join(self.tmp.name, name), 'w', encoding='utf-8') as f:
            json.dump(row, f)

    def test_summarize(self):
        s = wl.summarize(list(range(1, 101)))
        self.assertEqual((s['n'], s['p50'], s['p95']), (100, 51, 95))

    def test_begin_end_flush_roundtrip(self):
        for i in range(30):
            tok = wl.begin(now=100.0 + i)
            wl.end(tok, now=100.0 + i + 0.01 * (i + 1))   # 10ms ~ 300ms
        self.assertTrue(wl.flush(now=130.0))
        agg = wl.aggregate()
        self.assertEqual((agg['workers'], agg['n'], agg['inflight']), (1, 30, 0))
        self.assertAlmostEqual(agg['p95_ms'], 290.0, delta=1)

    def test_stuck_requests_are_visible(self):
        """끝난 요청만 세면 스레드가 전부 막힌 순간 신호가 사라진다 — 진행 중도 표본이다."""
        for _ in range(6):
            wl.begin(now=100.0)
        self.assertTrue(wl.flush(now=103.0))
        agg = wl.aggregate()
        self.assertEqual(agg['inflight'], 6)
        self.assertAlmostEqual(agg['p95_ms'], 3000.0)
        self.assertAlmostEqual(agg['oldest_inflight_ms'], 3000.0)

    def test_old_samples_leave_window(self):
        for i in range(30):
            wl.record(900.0, now=0.0)
        for i in range(25):
            wl.record(20.0, now=100.0 + i)   # 처음 것들은 60초 창 밖
        wl.flush(now=125.0)
        self.assertEqual(wl.aggregate()['p95_ms'], 20.0)

    def test_nothing_to_write_when_idle(self):
        self.assertIsNone(wl.flush(now=1.0))

    def test_pages_and_login_are_excluded(self):
        """페이지 렌더·로그인은 원래 느리다 — 넣으면 한 사람이 화면만 열어도 '주의'(S2)."""
        ex = wl.is_excluded
        self.assertTrue(ex('/dashboard/x', {'Sec-Fetch-Dest': 'document'}))
        self.assertTrue(ex('/dashboard/x', {'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}))
        self.assertTrue(ex('/login_password', {'Accept': 'application/json'}))
        self.assertTrue(ex('/logout', {}))
        self.assertTrue(ex('/static/js/a.js', {}))
        self.assertFalse(ex('/data_batch', {'Accept': 'application/json, text/javascript, */*; q=0.01',
                                           'Sec-Fetch-Dest': 'empty'}))
        self.assertFalse(ex('/daemonactive', {'Accept': '*/*'}))
        self.assertFalse(ex('/data_batch', None))   # 머리를 못 읽어도 막지 않는다
        # HTML 조각을 받는 XHR 폴링(jQuery dataType:'html')은 페이지가 아니다
        self.assertFalse(ex('/widget_fragment', {'Accept': 'text/html, */*; q=0.01',
                                                'X-Requested-With': 'XMLHttpRequest'}))

    def test_hooks_in_a_flask_app(self):
        """세 훅(시작·페이지 표시·끝)을 실제 Flask 요청으로 — 페이지·로그인은 빠지고,
        폴링·문자열 응답·HTML 조각 XHR·예외로 끝난 요청은 남는다."""
        from flask import Flask, jsonify
        from aot.aot_flask.app import register_web_latency
        app = Flask(__name__)

        @app.route('/page')
        def page():
            return '<html>' + 'x' * 5000 + '</html>'

        @app.route('/alive')
        def alive():
            return 'alive'

        @app.route('/json')
        def js():
            return jsonify(ok=True)

        @app.route('/login_password', methods=['POST'])
        def login():
            return 'ok'

        @app.route('/boom')
        def boom():
            raise RuntimeError('x')

        register_web_latency(app)
        c = app.test_client()
        doc = {'Accept': 'text/html,*/*;q=0.8', 'Sec-Fetch-Dest': 'document'}
        xhr = {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'text/html, */*; q=0.01'}
        c.get('/page', headers=doc)        # 빠짐(시작에서)
        c.get('/page')                      # 빠짐(끝에서 — 머리 없는 클라이언트의 큰 HTML)
        c.post('/login_password')           # 빠짐(경로)
        c.get('/page', headers=xhr)         # 남음(스크립트가 받은 HTML)
        c.get('/alive')                     # 남음(문자열 폴링 — text/html 이지만 작다)
        c.get('/json')                      # 남음
        c.get('/boom')                      # 남음(예외로 끝나도 센다)
        snap = wl.snapshot()
        self.assertEqual((snap['n'], snap['inflight']), (4, 0))

    def test_page_response_heuristic(self):
        """문자열 폴링('alive')도 Flask 기본값으로 text/html 이다 — 크기와 출처로 가른다."""
        page = wl.is_page_response
        self.assertTrue(page(False, 'text/html', 45000))       # 머리 없는 클라이언트의 화면
        self.assertFalse(page(False, 'text/html', 5))           # /daemonactive 'alive'
        self.assertFalse(page(True, 'text/html', 45000))        # 스크립트가 받은 HTML 조각
        self.assertFalse(page(False, 'application/json', 45000))
        self.assertFalse(page(False, 'text/html', None))        # 길이 모름(스트리밍)
        self.assertTrue(wl.is_fetch({'X-Requested-With': 'XMLHttpRequest'}))
        self.assertTrue(wl.is_fetch({'Sec-Fetch-Dest': 'empty'}))
        self.assertFalse(wl.is_fetch({'Accept': '*/*'}))
        self.assertFalse(wl.is_fetch(None))

    def test_html_response_is_dropped_at_end(self):
        tok = wl.begin(now=10.0)
        wl.end(tok, now=11.0, keep=False)            # 응답이 HTML 이었던 요청
        for i in range(5):
            wl.end(wl.begin(now=20.0 + i), now=20.01 + i)
        wl.flush(now=30.0)
        agg = wl.aggregate()
        self.assertEqual((agg['n'], agg['inflight']), (5, 0))
        self.assertLess(agg['p95_ms'], 20.0)

    def test_end_without_begin_is_harmless(self):
        wl.end(None)
        wl.end(12345)

    def test_worst_trusted_worker_and_stale_files(self):
        now = time.time()
        self._file('a-1.json', n=50, p50=10, p95=40, t=now)
        self._file('a-2.json', n=50, p50=30, p95=300, t=now - 5)
        self._file('a-3.json', n=50, p50=900, p95=9000, t=now - 100)    # 낡음: 무시
        self._file('a-4.json', n=50, p50=900, p95=9000, t=now - 10000)  # 아주 낡음: 지움
        agg = wl.aggregate(now=now)
        self.assertEqual((agg['workers'], agg['n'], agg['p95_ms']), (2, 100, 300.0))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, 'a-4.json')))

    def test_worker_with_few_samples_does_not_decide(self):
        """느린 요청 두 건만 받은 워커가 다른 워커 표본에 업혀 '과부하' 를 만들면 안 된다."""
        now = time.time()
        self._file('a-1.json', n=60, p50=10, p95=40, t=now)
        self._file('a-2.json', n=2, p50=4000, p95=4000, t=now)
        self.assertEqual(wl.aggregate(now=now)['p95_ms'], 40.0)

    def test_broken_files_are_skipped(self):
        now = time.time()
        self._file('a-1.json', n=60, p50=10, p95=40, t=now)
        with open(os.path.join(self.tmp.name, 'a-2.json'), 'w') as f:
            f.write('[1, 2]')
        with open(os.path.join(self.tmp.name, 'a-3.json'), 'w') as f:
            f.write('{broken')
        old_tmp = os.path.join(self.tmp.name, 'a-9.json.tmp')
        with open(old_tmp, 'w') as f:
            f.write('{}')
        os.utime(old_tmp, (now - 10000, now - 10000))
        self.assertEqual(wl.aggregate(now=now)['p95_ms'], 40.0)
        self.assertFalse(os.path.exists(old_tmp))

    def test_no_folder_is_none(self):
        with patch.dict(os.environ, {'AOT_WEB_LATENCY_DIR': os.path.join(self.tmp.name, 'x')}):
            self.assertIsNone(wl.aggregate())


class InputDriverTest(unittest.TestCase):

    def test_records_available_signals_only(self):
        from aot.inputs import aot_resource_pressure as mod
        snap = dict(_sig(cpu_psi=12.0, web_p95_ms=260.0), stage=1, temperature_c=None,
                    psi_source='proc', raw_stage=1, stage_name='watch', reasons=['cpu_psi'])
        inst = mod.InputModule.__new__(mod.InputModule)
        got = {}
        inst.is_enabled = lambda chan: True
        inst.value_set = lambda chan, value: got.__setitem__(chan, value)
        with patch.object(rp, 'current', return_value=snap):
            inst.get_measurement()
        self.assertEqual(got[0], 1)
        self.assertEqual(got[1], 12.0)
        self.assertAlmostEqual(got[6], 0.26)      # ms → s
        self.assertNotIn(7, got)                  # 스로틀 없음(파이 아님)
        self.assertNotIn(8, got)                  # 온도 없음
        self.assertEqual(set(mod.measurements_dict), set(range(11)))


if __name__ == '__main__':
    unittest.main()

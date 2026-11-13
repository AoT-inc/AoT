# -*- coding: utf-8 -*-
"""디지털트윈 판정 모듈(aot/utils/twin_gate.py) — 잠금·플래그·실행 시각·하트비트.

DB 는 쓰지 않는다: Misc 조회는 `_load_misc` 를 갈아끼운다.
"""
import datetime
import os
import sys
import types
import unittest
from unittest import mock

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))

from aot.utils import twin_gate as tg  # noqa: E402

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)


def _supported(profile='MEDIUM', model=None, mem=16.0, env=None):
    patches = [
        mock.patch('aot.config.mcp_config.HARDWARE_PROFILE', profile),   # 판정에 쓰이지 않는다(아래 시험)
        mock.patch('aot.utils.system_environment.pi_model', return_value=model),
        mock.patch('aot.utils.system_environment.mem_total_gb', return_value=mem),
        mock.patch.dict(os.environ, env or {}, clear=False),
    ]
    for p in patches:
        p.start()
    try:
        return tg.twin_supported()
    finally:
        for p in reversed(patches):
            p.stop()


class TwinSupportedTest(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(_supported(), (True, ''))

    def test_hardware_profile_is_not_a_lock(self):
        """서버가 기본 구성에 들어간 뒤로 compose 기본값 LOW 는 잠금 사유가 아니다. 잠금은 기기 고정값(파이 모델·메모리)뿐."""
        self.assertEqual(_supported(profile='LOW'), (True, ''))
        self.assertEqual(_supported(profile='low'), (True, ''))
        self.assertEqual(_supported(profile='LOW', mem=2.0), (False, tg.REASON_LOW_MEMORY))
        self.assertEqual(_supported(profile='LOW', model='Raspberry Pi 3 Model B Rev 1.2'),
                         (False, tg.REASON_PI_MODEL))

    def test_profile_option_is_gone(self):
        for name in ('REASON_PROFILE_LOW', 'TWIN_LOCKED_PROFILES', 'IGNORE_PROFILE_ENV', 'ignore_profile_flag'):
            self.assertFalse(hasattr(tg, name), name)
        self.assertNotIn('profile_low', tg.LOCK_MESSAGES)

    def test_memory_threshold(self):
        self.assertEqual(_supported(mem=2.0), (False, tg.REASON_LOW_MEMORY))
        # 공칭 4 GB 보드는 3.7~3.8 GB 로 보고된다 — 통과해야 한다.
        self.assertEqual(_supported(mem=3.75), (True, ''))
        self.assertEqual(_supported(mem=3.4), (False, tg.REASON_LOW_MEMORY))

    def test_container_memory_limit_is_not_device_size(self):
        """aot_twin 컨테이너의 자기 한도(768M)나 개발용 앱 한도(3 GB)가 '이 기기가 작다' 로 읽히면 안 된다."""
        from aot.utils import system_environment as env
        files = {'/proc/meminfo': 'MemTotal:       16384000 kB\n', '/sys/fs/cgroup/memory.max': str(768 * 1024 * 1024)}
        with mock.patch.object(env, '_read_file', side_effect=lambda p: files.get(p)):
            self.assertEqual(env.mem_total_gb(), 0.75)                      # 기존 의미(이 프로세스가 쓸 수 있는 양)
            self.assertAlmostEqual(env.mem_total_gb(host_only=True), 15.63, places=1)
            files['/proc/meminfo'] = 'MemTotal:        2000000 kB\n'        # 진짜 작은 기기는 여전히 잠긴다
            self.assertLess(env.mem_total_gb(host_only=True), tg.TWIN_MIN_MEM_GB)
            files.pop('/proc/meminfo')                                      # 측정 불가면 한도라도 쓴다
            self.assertEqual(env.mem_total_gb(host_only=True), 0.75)

    def test_gate_asks_for_host_memory(self):
        with mock.patch('aot.config.mcp_config.HARDWARE_PROFILE', 'MEDIUM'), \
                mock.patch('aot.utils.system_environment.pi_model', return_value=None), \
                mock.patch('aot.utils.system_environment.mem_total_gb', return_value=16.0) as m:
            tg.twin_supported()
        m.assert_called_once_with(host_only=True)

    def test_unknown_memory_does_not_lock(self):
        self.assertEqual(_supported(mem=None), (True, ''))

    def test_pi_models(self):
        for model in ('Raspberry Pi Zero 2 W Rev 1.0', 'Raspberry Pi Model B Rev 2',
                      'Raspberry Pi 2 Model B Rev 1.1', 'Raspberry Pi 3 Model B Plus Rev 1.3'):
            self.assertEqual(_supported(model=model), (False, tg.REASON_PI_MODEL), model)
        for model in ('Raspberry Pi 4 Model B Rev 1.4', 'Raspberry Pi 5 Model B Rev 1.0'):
            self.assertEqual(_supported(model=model, mem=8.0), (True, ''), model)
        # 4 모델도 메모리가 모자라면 잠긴다
        self.assertEqual(_supported(model='Raspberry Pi 4 Model B Rev 1.4', mem=1.8),
                         (False, tg.REASON_LOW_MEMORY))


def _misc(**kw):
    return types.SimpleNamespace(**kw)


class TwinEnabledTest(unittest.TestCase):
    def test_flag_off(self):
        with mock.patch.object(tg, '_load_misc', return_value=_misc(twin_enabled=False)):
            self.assertFalse(tg.twin_enabled())

    def test_no_row(self):
        with mock.patch.object(tg, '_load_misc', return_value=None):
            self.assertFalse(tg.twin_enabled())
            self.assertFalse(tg.twin_flag())

    def test_on_and_supported(self):
        with mock.patch.object(tg, '_load_misc', return_value=_misc(twin_enabled=True)), \
                mock.patch.object(tg, 'twin_supported', return_value=(True, '')):
            self.assertTrue(tg.twin_enabled())

    def test_on_but_locked_is_off(self):
        with mock.patch.object(tg, '_load_misc', return_value=_misc(twin_enabled=True)), \
                mock.patch.object(tg, 'twin_supported', return_value=(False, tg.REASON_LOW_MEMORY)):
            self.assertTrue(tg.twin_flag())
            self.assertFalse(tg.twin_enabled())


class RunTimesTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(tg.normalize_run_times('6:10, 18:10;6:10'), ('06:10,18:10', None))
        self.assertEqual(tg.normalize_run_times('18:10,06:10'), ('06:10,18:10', None))

    def test_errors(self):
        self.assertEqual(tg.normalize_run_times('')[1], 'empty')
        self.assertEqual(tg.normalize_run_times(None)[1], 'empty')
        self.assertEqual(tg.normalize_run_times('24:00')[1], 'format')
        self.assertEqual(tg.normalize_run_times('6:7')[1], 'format')
        self.assertEqual(tg.normalize_run_times('abc')[1], 'format')
        many = ','.join('%02d:00' % h for h in range(13))
        self.assertEqual(tg.normalize_run_times(many)[1], 'too_many')

    def test_run_times_falls_back_to_default(self):
        for raw in (None, '', 'garbage'):
            with mock.patch.object(tg, '_load_misc', return_value=_misc(twin_run_times=raw)):
                self.assertEqual(tg.run_times(), ['06:10', '18:10'])
        with mock.patch.object(tg, '_load_misc', return_value=_misc(twin_run_times='07:00')):
            self.assertEqual(tg.run_times(), ['07:00'])


class HeartbeatTest(unittest.TestCase):
    def test_none_is_stale(self):
        with mock.patch.object(tg, '_load_misc', return_value=_misc(twin_heartbeat=None)):
            self.assertIsNone(tg.read_heartbeat())
            self.assertTrue(tg.heartbeat_stale())

    def test_fresh_and_old(self):
        fresh = {'at': '2026-10-21T11:59:30Z', 'status': 'running'}
        old = {'at': '2026-10-21T11:50:00Z', 'status': 'running'}
        self.assertFalse(tg.heartbeat_stale(180, heartbeat=fresh, now=NOW))
        self.assertTrue(tg.heartbeat_stale(180, heartbeat=old, now=NOW))
        self.assertFalse(tg.heartbeat_stale(3600, heartbeat=old, now=NOW))

    def test_bad_timestamp_is_stale(self):
        for at in (None, '', 'yesterday', {}):
            self.assertTrue(tg.heartbeat_stale(180, heartbeat={'at': at, 'x': 1}, now=NOW))

    def test_epoch_and_naive_accepted(self):
        self.assertFalse(tg.heartbeat_stale(
            180, heartbeat={'at': NOW.timestamp() - 10}, now=NOW))
        self.assertFalse(tg.heartbeat_stale(
            180, heartbeat={'at': '2026-10-21T11:59:50'}, now=NOW))

    def test_read_heartbeat_json_string_and_non_dict(self):
        with mock.patch.object(tg, '_load_misc',
                               return_value=_misc(twin_heartbeat='{"at": "x"}')):
            self.assertEqual(tg.read_heartbeat(), {'at': 'x'})
        with mock.patch.object(tg, '_load_misc', return_value=_misc(twin_heartbeat='[1]')):
            self.assertIsNone(tg.read_heartbeat())
        with mock.patch.object(tg, '_load_misc', return_value=_misc(twin_heartbeat='not json')):
            self.assertIsNone(tg.read_heartbeat())

    def test_write_heartbeat_shape(self):
        stored = {}
        with mock.patch.object(tg, '_store_heartbeat',
                               side_effect=lambda d: stored.update(d) or True):
            ok = tg.write_heartbeat('running', version='0.1', sites=3, plots=7,
                                    last_run_at=NOW, failures=1, now=NOW)
        self.assertTrue(ok)
        self.assertEqual(stored, {
            'at': '2026-10-21T12:00:00Z', 'status': 'running', 'version': '0.1',
            'sites': 3, 'plots': 7, 'last_run_at': '2026-10-21T12:00:00Z',
            'failures': 1, 'locked_reason': None})
        self.assertFalse(tg.heartbeat_stale(180, heartbeat=stored, now=NOW))

    def test_write_heartbeat_failure_is_false(self):
        with mock.patch.object(tg, '_store_heartbeat', side_effect=RuntimeError('db')):
            self.assertFalse(tg.write_heartbeat('idle'))


if __name__ == '__main__':
    unittest.main()

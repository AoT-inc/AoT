# coding=utf-8
"""gunicorn 워커 수 산정.

워커 수는 **메모리를 직접 먹는 값**이다. 워커마다 앱을 통째로 적재하므로
(실측 2026-09-09 로컬 도커: RSS 404MB), 코어만 보고 늘리면 메모리가 빠듯한
기기에서 스왑으로 넘어가 오히려 느려진다. 그래서 코어와 메모리 중 **작은 쪽**
을 택하고, 라즈베리파이·저메모리는 아예 1로 묶는다.

워커를 늘릴 수 있게 된 배경은 docs/design/scheduler-process-separation.md 7절 —
예약을 실행하는 프로세스가 데몬 하나로 정리되기 전까지 이 값은 1이어야 했다.
"""
import os
import unittest

from aot.utils import system_environment as se

_HERE = os.path.dirname(__file__)
_ROOT = os.path.join(_HERE, '..')


def _env(platform='debian', cores=4, mem=4.0):
    return {'platform_type': platform, 'cpu_cores': cores, 'mem_total_gb': mem}


class TestWorkerSizingIsMemoryAware(unittest.TestCase):

    def test_raspberry_pi_stays_single(self):
        """운영 농장 다수가 파이다. 늘려서 얻는 것보다 스왑으로 잃는 것이 크다."""
        self.assertEqual(
            se.recommended_workers(_env(platform=se.PLATFORM_RASPBERRY_PI)), 1)

    def test_low_memory_stays_single(self):
        self.assertEqual(
            se.recommended_workers(_env(mem=se.LOW_MEMORY_GB - 0.1)), 1)

    def test_memory_can_bind_below_core_count(self):
        """코어가 많아도 메모리가 모자라면 코어 수를 따라가지 않는다."""
        many_cores_little_mem = se.recommended_workers(_env(cores=16, mem=3.0))
        self.assertLess(many_cores_little_mem, 16)
        self.assertGreaterEqual(many_cores_little_mem, 1)

    def test_cores_can_bind_below_memory_allowance(self):
        """메모리가 남아도 코어보다 많이 띄우지 않는다 — GIL 을 벗어나려는
        것이 목적이지 프로세스를 쌓는 것이 목적이 아니다."""
        self.assertLessEqual(se.recommended_workers(_env(cores=2, mem=64.0)), 2)

    def test_never_zero(self):
        """0 이면 gunicorn 이 뜨지 않는다. 어떤 값이 와도 최소 1."""
        for mem in (None, 0.1, 1.0, se.RESERVED_MEM_GB):
            self.assertGreaterEqual(
                se.recommended_workers(_env(cores=1, mem=mem)), 1)

    def test_capped(self):
        self.assertLessEqual(
            se.recommended_workers(_env(cores=64, mem=256.0)), se.WORKERS_MAX)


class TestResolveHonoursEnvOverride(unittest.TestCase):

    def setUp(self):
        self._saved = os.environ.pop('GUNICORN_WORKERS', None)

    def tearDown(self):
        os.environ.pop('GUNICORN_WORKERS', None)
        if self._saved is not None:
            os.environ['GUNICORN_WORKERS'] = self._saved

    def test_env_wins(self):
        os.environ['GUNICORN_WORKERS'] = '3'
        self.assertEqual(se.resolve_gunicorn_workers(), (3, 'env'))

    def test_garbage_falls_back_to_auto(self):
        """설정 오타가 기동을 막으면 안 된다."""
        os.environ['GUNICORN_WORKERS'] = 'many'
        workers, source = se.resolve_gunicorn_workers()
        self.assertEqual(source, 'auto')
        self.assertGreaterEqual(workers, 1)

    def test_zero_is_refused(self):
        os.environ['GUNICORN_WORKERS'] = '0'
        workers, _ = se.resolve_gunicorn_workers()
        self.assertGreaterEqual(workers, 1)


class TestGunicornConfUsesTheResolver(unittest.TestCase):

    def test_workers_is_not_hardcoded(self):
        """`workers = 1` 로 되돌아가면 이 테스트가 잡는다 — 되돌릴 때는
        스케줄러 분리(설계 문서 7절)까지 같이 되돌아갔는지 확인할 것."""
        with open(os.path.join(_ROOT, '..', 'install', 'gunicorn_conf.py'),
                  encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('resolve_gunicorn_workers', src)
        self.assertNotIn('\nworkers = 1\n', src)


if __name__ == '__main__':
    unittest.main()

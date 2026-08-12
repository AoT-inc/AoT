# coding=utf-8
"""`DaemonControl(extended_timeout=True)` 가 실제로 더 긴 타임아웃을 받는가.

`extended_timeout` 은 "이 호출은 진짜 장치 명령을 보내니 오래 걸릴 수 있다"
(원격 출력, ChirpStack 다운링크 등)를 뜻하고, 상한을 10초에서 120초로 올린다.
그런데 상한을 계산해 놓고 **쓰지 않는 자리가 두 곳** 있었다.

1. 캐시가 값 하나였다. 먼저 만들어진 인스턴스가 계산한 타임아웃이 그대로
   재사용돼, `extended_timeout=True` 로 만들어도 앞서 만들어진 일반
   인스턴스의 10초를 물려받았다.
2. 캐시가 비어 있을 때조차 `min(misc.rpyc_timeout, self._MAX_RPC_TIMEOUT)`
   으로 **항상 일반 상한**을 썼다 — `cap` 은 계산만 되고 버려졌다.

둘이 겹쳐서 `extended_timeout=True` 는 어느 경로로도 10초를 넘지 못했다.
플래그는 있고, 인자도 넘겨지고, 아무 에러도 없다. 그냥 효과가 없다.

캐시를 상한별 dict 로 바꾸고 `cap` 을 실제로 쓰도록 고쳤다. 이 테스트는 그
둘을 각각 고정한다.

    python3 aot/tests/test_daemon_rpc_timeout_cap.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..')))

import aot.aot_client as aot_client  # noqa: E402
from aot.aot_client import DaemonControl  # noqa: E402

#: DB 의 사용자 설정값. 두 상한(10 / 120) 사이에 두어야 캡이 실제로 적용되는지
#: 구분된다 — 상한보다 작으면 어느 캡을 써도 같은 값이 나와 검사가 무의미해진다.
_USER_TIMEOUT = 60


class _FakeMisc:
    rpyc_timeout = _USER_TIMEOUT


class ExtendedTimeoutTest(unittest.TestCase):

    def setUp(self):
        self._original = aot_client.db_retrieve_table_daemon
        aot_client.db_retrieve_table_daemon = lambda *a, **kw: _FakeMisc()
        DaemonControl._rpc_timeout_cache = {}

    def tearDown(self):
        aot_client.db_retrieve_table_daemon = self._original
        DaemonControl._rpc_timeout_cache = {}

    def test_caps_differ(self):
        """전제 확인 — 두 상한이 실제로 다르고 사용자 값이 그 사이에 있다."""
        self.assertLess(DaemonControl._MAX_RPC_TIMEOUT, _USER_TIMEOUT)
        self.assertLess(_USER_TIMEOUT, DaemonControl._MAX_RPC_TIMEOUT_EXTENDED)

    def test_extended_gets_the_larger_cap(self):
        self.assertEqual(DaemonControl._MAX_RPC_TIMEOUT,
                         DaemonControl().pyro_timeout)
        self.assertEqual(_USER_TIMEOUT,
                         DaemonControl(extended_timeout=True).pyro_timeout)

    def test_a_normal_instance_does_not_poison_a_later_extended_one(self):
        """캐시가 값 하나였을 때의 실패 모드 — 순서만으로 결과가 갈렸다."""
        DaemonControl()                                   # 먼저 10 을 캐시
        self.assertEqual(_USER_TIMEOUT,
                         DaemonControl(extended_timeout=True).pyro_timeout)

    def test_an_extended_instance_does_not_poison_a_later_normal_one(self):
        """반대 방향도 같다 — 일반 호출이 120 상한을 물려받으면 안 된다."""
        DaemonControl(extended_timeout=True)              # 먼저 60 을 캐시
        self.assertEqual(DaemonControl._MAX_RPC_TIMEOUT,
                         DaemonControl().pyro_timeout)

    def test_cache_is_keyed_by_cap(self):
        DaemonControl()
        DaemonControl(extended_timeout=True)
        self.assertEqual(
            {DaemonControl._MAX_RPC_TIMEOUT,
             DaemonControl._MAX_RPC_TIMEOUT_EXTENDED},
            set(DaemonControl._rpc_timeout_cache),
            "캐시가 상한별로 갈리지 않습니다 — 값 하나로 되돌아갔습니다.")

    def test_explicit_timeout_still_wins_but_is_capped(self):
        self.assertEqual(5, DaemonControl(pyro_timeout=5).pyro_timeout)
        self.assertEqual(DaemonControl._MAX_RPC_TIMEOUT,
                         DaemonControl(pyro_timeout=9999).pyro_timeout)
        self.assertEqual(DaemonControl._MAX_RPC_TIMEOUT_EXTENDED,
                         DaemonControl(pyro_timeout=9999,
                                       extended_timeout=True).pyro_timeout)

    def test_db_unavailable_falls_back_to_eight_seconds(self):
        """DB 를 못 읽으면 8초. 캐시에 넣지 않아 다음 호출이 다시 시도한다."""
        aot_client.db_retrieve_table_daemon = lambda *a, **kw: None
        self.assertEqual(8, DaemonControl().pyro_timeout)
        self.assertEqual({}, DaemonControl._rpc_timeout_cache)


if __name__ == '__main__':
    unittest.main()

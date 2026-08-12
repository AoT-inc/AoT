# coding=utf-8
"""데몬 재시작 지연이 다시 '순수 대기'로 돌아가지 않게 고정한다.

`sample_rate` 는 Settings > General 에서 사용자가 정하는 값이고, 실제로 15 초로
쓰는 설치가 있다. 컨트롤러 루프가 그 값을 **끊기지 않는** `time.sleep()` 으로
쉬면 정지 지시를 최대 한 주기 늦게 알아채므로, 종료 시간이 하는 일과 무관하게
sample_rate 에 비례한다 — 2026-08-12 로컬 실측(출력 31개, 6개 rate 전부 15 초)에서
종료 38.4 초 중 Output 컨트롤러가 8.3 초, Widget 컨트롤러가 14.4 초를 그냥 자고
있었고, 출력 31개의 실제 종료 처리 합계는 15 ms 였다. 수정 후 1.84 초.

기본값은 0.05~0.25 초라 기본 설정 그대로인 설치에서는 드러나지 않는다. 그래서
"우리 서버는 멀쩡한데" 로 넘어가기 쉬운 계열이다.

이 계열은 조용히 되돌아간다: 되돌려도 기능은 전부 정상이고 테스트도 통과하며,
로그에는 "controller stopped" 만 남는다. 그래서 시간을 직접 잰다.
"""
import threading
import time
import unittest

from aot.controllers.base_controller import AbstractController


# 되돌림이 일어나면 이 값만큼 통째로 기다리게 된다. 정상 동작과 회귀를 명확히
# 가르려고 현실적인 sample_rate(15 s)보다 크게 잡았다.
LONG_SAMPLE_RATE_S = 30.0
# 깨어나는 데 허용하는 시간. 스레드 하나 깨우는 일이라 여유를 둬도 회귀
# (= LONG_SAMPLE_RATE_S 만큼 대기)와 겹치지 않는다.
WAKE_BUDGET_S = 3.0


class _CountingController(AbstractController, threading.Thread):
    """루프 횟수만 세는 최소 컨트롤러. DB·장치를 건드리지 않는다."""

    def __init__(self):
        threading.Thread.__init__(self)
        super().__init__(threading.Event(), unique_id=None, name=__name__)
        self.daemon = True
        self.loop_count = 0
        self.finally_ran = threading.Event()

    def initialize_variables(self):
        self.sample_rate = LONG_SAMPLE_RATE_S
        self.running = True
        self.ready.set()

    def loop(self):
        self.loop_count += 1

    def run_finally(self):
        self.finally_ran.set()


class TestControllerStopLatency(unittest.TestCase):
    def _started_controller(self):
        controller = _CountingController()
        controller.start()
        self.assertTrue(
            controller.ready.wait(WAKE_BUDGET_S),
            "컨트롤러가 기동하지 못했다")
        # 첫 loop() 를 지나 대기에 들어갈 틈을 준다.
        deadline = time.time() + WAKE_BUDGET_S
        while controller.loop_count < 1 and time.time() < deadline:
            time.sleep(0.01)
        self.assertGreaterEqual(controller.loop_count, 1)
        return controller

    def test_stop_controller_wakes_the_loop_immediately(self):
        """정지 지시는 sample_rate 를 기다리지 않는다."""
        controller = self._started_controller()

        started = time.time()
        controller.stop_controller()
        controller.join(WAKE_BUDGET_S)
        elapsed = time.time() - started

        self.assertFalse(
            controller.is_alive(),
            f"stop_controller() 후 {WAKE_BUDGET_S}s 안에 스레드가 끝나지 않았다 — "
            f"루프가 끊기지 않는 sleep(sample_rate) 으로 돌아갔을 것")
        self.assertLess(elapsed, WAKE_BUDGET_S)

    def test_run_finally_still_runs_on_the_shortened_path(self):
        """종료를 앞당겨도 마무리 훅은 그대로 실행된다.

        Output 컨트롤러는 여기서 각 장치의 Shutdown State 를 내보낸다 — 빨라진
        대신 이게 안 돌면 종료가 장치를 끄지 못한다.
        """
        controller = self._started_controller()
        controller.stop_controller()
        controller.join(WAKE_BUDGET_S)

        self.assertTrue(
            controller.finally_ran.is_set(),
            "run_finally() 가 실행되지 않았다")

    def test_loop_still_paced_while_running(self):
        """대기가 '깨울 수 있게' 바뀐 것이지 없어진 것이 아니다.

        이게 빠지면 루프가 전력으로 돌아 CPU 를 태운다 — 종료는 빨라지고 평소가
        망가지는, 알아채기 어려운 쪽의 회귀다.
        """
        controller = self._started_controller()
        try:
            time.sleep(0.5)
            self.assertEqual(
                controller.loop_count, 1,
                f"sample_rate={LONG_SAMPLE_RATE_S}s 인데 0.5s 동안 "
                f"{controller.loop_count}회 돌았다 — 루프 간 대기가 사라졌다")
        finally:
            controller.stop_controller()
            controller.join(WAKE_BUDGET_S)


if __name__ == '__main__':
    unittest.main()

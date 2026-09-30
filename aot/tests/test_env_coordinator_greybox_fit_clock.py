# coding=utf-8
"""
학습 시계가 재초기화를 건너 흐르는가 — 2026-09-28.

물리 모델 재학습은 두 조건을 함께 요구한다: 샘플 `N_MIN_SAMPLES`(120) 와 마지막
시도로부터 6시간. 컨트롤러는 옵션 저장·데몬 리로드마다 다시 만들어지므로(로컬 실측
7일간 155회), 시계가 객체와 함께 0 으로 돌아가면 **6시간이 영영 흐르지 않는다.**

⚠ 이 파일이 있는 이유: 시계를 영속화하면서 저장 시점을 "학습을 시도한 순간" 하나로
뒀는데, 그 시도가 6시간을 채워야 오므로 재시작이 더 잦으면 저장이 한 번도 일어나지
않았다 — 고치려던 덫을 그대로 남긴 것이었다(라이브 DB 에서 `greybox_fit_ts` 가 계속
None 인 것을 보고 발견). 그래서 **시계의 시작**도 저장한다.
"""

import time
import unittest
from unittest import mock

from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
from aot.functions.utils.env_control.greybox.shadow import GreyboxShadow


class _Log:
    def __init__(self):
        self.lines = []

    def __getattr__(self, _name):
        def _fn(msg, *a, **k):
            self.lines.append(str(msg) % a if a else str(msg))
        return _fn


def _coord(store=None, samples=0):
    """재초기화 직후의 컨트롤러 — 영속 상태는 `store` 한 곳에 모인다."""
    c = CycleMixin.__new__(CycleMixin)
    c.logger = _Log()
    c.update_period = 600.0
    state = dict(store or {})
    c._read_calibration_state = lambda: dict(state)
    c._merge_calibration_state = lambda upd: state.update(upd)
    c._persisted = state

    sh = GreyboxShadow()
    for i in range(samples):
        sh._input_buf.append((
            (24.0 + 0.01 * i, 60.0, 500.0),
            {'T_ext': 15.0, 'RH_ext': 55.0, 'CO2_ext': 410.0, 'solar': 0.0, 'wind': 1.0},
            {'heat': 0.0, 'cool': 0.0, 'vent': 10.0, 'fog': 0.0, 'co2_inj': 0.0},
        ))
    c._greybox_shadow_inst = sh
    return c


class TestFitClockSurvivesRestart(unittest.TestCase):

    def test_처음이면_시계_시작을_저장한다(self):
        c = _coord()
        c._maybe_run_greybox_identification(600.0)
        self.assertIn('greybox_fit_ts', c._persisted,
                      '시작을 저장하지 않으면 재시작마다 시계가 0 으로 돌아간다')

    def test_재초기화가_잦아도_시계는_이어진다(self):
        """같은 영속 상태를 물려받은 새 객체 5개 — 시작 시각이 흔들리지 않아야 한다."""
        store = {}
        first = None
        for _ in range(5):
            c = _coord(store)
            c._maybe_run_greybox_identification(600.0)
            store = c._persisted
            first = first or store['greybox_fit_ts']
        self.assertEqual(first, store['greybox_fit_ts'])

    def test_6시간이_지나고_샘플이_차면_학습한다(self):
        from aot.functions.utils.env_control.greybox import identification as ident
        old = time.time() - 7 * 3600
        c = _coord({'greybox_fit_ts': old}, samples=ident.N_MIN_SAMPLES + 5)
        new_params = GreyboxShadow().params
        new_params.n_updates = 1
        with mock.patch.object(
                ident, 'fit', return_value=new_params) as fit:
            c._maybe_run_greybox_identification(600.0)
        self.assertTrue(fit.called, '시계와 샘플이 모두 찼는데 학습을 시도하지 않았다')
        self.assertIn('greybox_params', c._persisted)
        self.assertNotEqual(old, c._persisted['greybox_fit_ts'], '다음 주기까지 대기')

    def test_6시간_전에는_시도하지_않는다(self):
        from aot.functions.utils.env_control.greybox import identification as ident
        c = _coord({'greybox_fit_ts': time.time() - 600.0},
                   samples=ident.N_MIN_SAMPLES + 5)
        with mock.patch.object(ident, 'fit') as fit:
            c._maybe_run_greybox_identification(600.0)
        self.assertFalse(fit.called)

    def test_샘플이_모자라면_시도하지_않는다(self):
        from aot.functions.utils.env_control.greybox import identification as ident
        c = _coord({'greybox_fit_ts': time.time() - 7 * 3600}, samples=10)
        with mock.patch.object(ident, 'fit') as fit:
            c._maybe_run_greybox_identification(600.0)
        self.assertFalse(fit.called)


if __name__ == '__main__':
    unittest.main()

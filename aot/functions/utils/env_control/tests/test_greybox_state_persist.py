# coding=utf-8
"""
학습 창·KPI 기록이 재초기화를 견디는가 — 2026-09-28.

컨트롤러 객체는 옵션 저장·데몬 리로드마다 다시 만들어진다(로컬 실측 7일간 155회).
학습 창이 메모리에만 있으면 그때마다 0 으로 돌아가는데, 600 초 주기에서 학습에 필요한
`N_MIN_SAMPLES`(120) 는 **20시간 연속**이라 사실상 한 번도 차지 않는다. 실제로
2026-09-22~28 엿새 동안 재학습이 0회였다.

저장하는 것은 **측정과 명령**(데이터)이지 모델 출력이 아니다 — 그래서 물리식이 바뀌어
계수를 버릴 때도 이 창은 그대로 쓴다.
"""

import time

import pytest

from aot.functions.utils.env_control.greybox import shadow as gs
from aot.functions.utils.env_control.greybox.shadow import GreyboxShadow


def _fill(sh, n, T0=24.0, dt_solar=0.0):
    """학습 입력 이력을 n개 채운다(step 을 타지 않고 직접 — 이 시험의 관심은 저장이다)."""
    for i in range(n):
        state = (T0 + 0.01 * i, 60.0 + 0.02 * i, 500.0 + i)
        ext = {'T_ext': 15.0, 'RH_ext': 55.0, 'CO2_ext': 410.0,
               'solar': dt_solar, 'wind': 1.5}
        cmds = {'heat': 0.0, 'cool': 0.0, 'vent': 20.0 + i % 5, 'fog': 0.0,
                'co2_inj': 0.0, 'shade': 100.0, 'curtain': 100.0}
        sh._input_buf.append((state, ext, cmds))


class TestRoundTrip:
    def test_이어받으면_학습에_쓸_수_있다(self):
        a = GreyboxShadow()
        _fill(a, 200)
        blob = a.export_state(dt=600.0)

        b = GreyboxShadow()
        rep = b.load_state(blob, dt=600.0)
        assert rep['input'] == 200 and rep['skipped'] is None

        states, exts, cmds, valid = b.fit_window()
        assert len(states) == 200 and len(exts) == 199 == len(cmds) == len(valid)
        assert exts[0]['T_ext'] == pytest.approx(15.0)
        assert cmds[0]['vent'] == pytest.approx(20.0)
        # 학습 문턱을 넘긴 상태로 이어받는다 — 이것이 이 작업의 목적이다.
        from aot.functions.utils.env_control.greybox.identification import N_MIN_SAMPLES
        assert len(exts) >= N_MIN_SAMPLES

    def test_저장_개수_상한(self):
        a = GreyboxShadow()
        _fill(a, gs.PERSIST_INPUT_MAX + 50)
        blob = a.export_state(dt=60.0)
        assert len(blob['input']) == gs.PERSIST_INPUT_MAX
        # 가장 최근 것을 남긴다(옛것을 남기면 지금 시설과 멀어진다)
        assert blob['input'][-1][0][2] == pytest.approx(500.0 + gs.PERSIST_INPUT_MAX + 49)

    def test_KPI_기록도_이어받는다(self):
        a = GreyboxShadow()
        for i in range(20):
            a._skill.append(('mild_day', 0.4, 0.9, 2.0, 3.0))
        b = GreyboxShadow()
        rep = b.load_state(a.export_state(dt=60.0), dt=60.0)
        assert rep['skill'] == 20
        assert b.skill_report()['regimes']['mild_day']['n'] == 20

    def test_없는_구간_이름은_버린다(self):
        a = GreyboxShadow()
        a._skill.append(('없는구간', 0.1, 0.2, 0.3, 0.4))
        assert a.export_state(dt=60.0)['skill'] == []


class TestRefusals:
    """이어받지 않는 경우는 **말한다** — 조용히 버리면 왜 처음부터인지 알 수 없다."""

    def test_주기가_바뀌면_버린다(self):
        a = GreyboxShadow()
        _fill(a, 50)
        b = GreyboxShadow()
        rep = b.load_state(a.export_state(dt=60.0), dt=600.0)
        assert rep['skipped'] == 'cycle_changed' and rep['input'] == 0
        assert b.fit_window() == ([], [], [], [])

    def test_주기_미세_차이는_같은_것으로_본다(self):
        a = GreyboxShadow()
        _fill(a, 10)
        b = GreyboxShadow()
        assert b.load_state(a.export_state(dt=600.0), dt=600.2)['input'] == 10

    def test_너무_오래된_저장분은_버린다(self):
        a = GreyboxShadow()
        _fill(a, 50)
        blob = a.export_state(dt=60.0)
        blob['saved_at'] = time.time() - gs.PERSIST_MAX_AGE_S - 60
        b = GreyboxShadow()
        assert b.load_state(blob, dt=60.0)['skipped'] == 'too_old'

    def test_모르는_스키마는_버린다(self):
        blob = GreyboxShadow().export_state(dt=60.0)
        blob['v'] = gs.STATE_SCHEMA + 1
        assert GreyboxShadow().load_state(blob, dt=60.0)['skipped'] == 'schema'

    def test_옛_판_저장분도_받는다(self):
        """버리면 업데이트 한 번에 이미 쌓인 창을 통째로 잃는다."""
        a = GreyboxShadow()
        _fill(a, 20)
        blob = a.export_state(dt=600.0)
        blob['v'] = 1
        blob['input'] = [e[:3] for e in blob['input']]   # v1 은 시각이 없다
        blob.pop('hist', None); blob.pop('prev', None)
        b = GreyboxShadow()
        rep = b.load_state(blob, dt=600.0)
        assert rep['input'] == 20 and rep['skipped'] is None
        assert b.fit_window(dt=600.0)[3] == [True] * 19   # 시각 없음 → 판단 안 함

    def test_없거나_깨진_저장분(self):
        assert GreyboxShadow().load_state(None, dt=60.0)['skipped'] == 'none'
        assert GreyboxShadow().load_state({}, dt=60.0)['skipped'] == 'none'
        assert GreyboxShadow().load_state('문자열', dt=60.0)['skipped'] == 'none'

    def test_한_줄이_깨져도_나머지는_이어받는다(self):
        a = GreyboxShadow()
        _fill(a, 10)
        blob = a.export_state(dt=60.0)
        blob['input'][3] = ['깨짐']
        b = GreyboxShadow()
        assert b.load_state(blob, dt=60.0)['input'] == 9


class TestSize:
    def test_저장_크기가_수십KB_안에_있다(self):
        """DB 텍스트 칼럼에 10분마다 쓴다 — 크기를 재 두지 않으면 조용히 커진다."""
        import json
        a = GreyboxShadow()
        _fill(a, gs.PERSIST_INPUT_MAX)
        for _ in range(gs.PERSIST_SKILL_MAX):
            a._skill.append(('mild_night', 0.5, 0.7, 1.0, 2.0))
        blob = json.dumps(a.export_state(dt=600.0))
        assert len(blob) < 300_000, '%d 바이트 — 상한을 다시 보라' % len(blob)


class TestCoordinatorWiring:
    def test_학습_시계도_이어받는다(self):
        """재초기화마다 6시간 시계가 0 이면 학습 시도가 영영 오지 않는다."""
        import inspect
        from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin as m
        src = inspect.getsource(m.CycleMixin._maybe_run_greybox_identification)
        assert "greybox_fit_ts" in src
        save = inspect.getsource(m.CycleMixin._maybe_save_greybox_state)
        assert 'greybox_shadow_state' in save

    def test_객체를_만들_때_이어받는다(self):
        import inspect
        from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin as m
        src = inspect.getsource(m.CycleMixin.__dict__['_greybox_shadow'].fget)
        assert 'load_state' in src


class TestContinuity:
    """이어지지 않는 전이를 학습에 넣지 않는가 (2026-09-28).

    입력 버퍼의 이웃 두 항목은 "한 사이클 전이" 로 쓰인다. 재시작·센서 끊김으로
    사이에 구멍이 나면 두 시점은 이웃이 아닌데, 시각이 없으면 그 쌍이 정상 전이처럼
    학습에 들어가 "두 시간이 한 사이클 만에 흘렀다" 가 된다. 로컬 재초기화 간격
    중앙값이 18분이라 드문 일이 아니다.
    """

    def _buf(self, sh, gaps):
        """gaps 초 간격으로 항목을 넣는다(첫 항목 기준)."""
        t = 1_000_000.0
        for i, g in enumerate([0.0] + list(gaps)):
            t += g
            sh._input_buf.append(((24.0 + i, 60.0, 500.0),
                                  {'T_ext': 15.0, 'RH_ext': 55.0, 'CO2_ext': 410.0,
                                   'solar': 0.0, 'wind': 1.0},
                                  {'vent': 10.0}, t))

    def test_구멍_난_쌍은_무효로_표시한다(self):
        sh = GreyboxShadow()
        self._buf(sh, [600.0, 7200.0, 600.0])      # 두 번째가 2시간 구멍
        _s, _e, _c, valid = sh.fit_window(dt=600.0)
        assert valid == [True, False, True]

    def test_시각을_모르면_판단하지_않는다(self):
        """옛 저장분(시각 없음)은 예전처럼 전부 유효로 본다."""
        sh = GreyboxShadow()
        for i in range(3):
            sh._input_buf.append(((24.0, 60.0, 500.0), {}, {}))
        assert sh.fit_window(dt=600.0)[3] == [True, True]

    def test_학습이_무효_전이를_건너뛴다(self):
        import math
        from aot.functions.utils.env_control.greybox.identification import fit, N_MIN_SAMPLES
        from aot.functions.utils.env_control.greybox.model import step as gstep
        from aot.functions.utils.env_control.greybox.params import GreyboxParams
        p = GreyboxParams()
        states, exts, cmds = [(22.0, 65.0, 480.0)], [], []
        T, RH, CO2 = states[0]
        for i in range(N_MIN_SAMPLES + 10):
            ext = {'T_ext': 14.0 + 6.0 * math.sin(i / 20.0), 'RH_ext': 60.0,
                   'CO2_ext': 410.0, 'solar': 0.0, 'wind': 1.0}
            cmd = {'heat': 0.0, 'cool': 0.0, 'vent': 20.0, 'fog': 0.0, 'co2_inj': 0.0}
            T, RH, CO2 = gstep(T, RH, CO2, ext, cmd, p, 600.0)
            states.append((T, RH, CO2)); exts.append(ext); cmds.append(cmd)
        # 한 쌍을 말도 안 되는 값으로 망가뜨린다 — 구멍을 건너뛴 전이의 모양이다
        states[50] = (states[50][0] + 25.0, states[50][1], states[50][2])
        valid = [True] * len(exts)
        valid[49] = valid[50] = False
        out = fit(states, exts, cmds, dt=600.0, prev_params=p, valid=valid)
        assert out is not None
        bad = fit(states, exts, cmds, dt=600.0, prev_params=p)
        assert bad is not None
        assert out.rmse_T < bad.rmse_T, '구멍을 건너뛰지 않으면 오차가 더 커야 한다'


class TestHorizonHistorySurvives:
    """H스텝 평가 이력이 재시작을 견디는가 (2026-09-28).

    KPI 한 건에는 직전 10사이클 이력이 필요하다. 이어받지 않으면 재초기화마다
    10사이클을 버리는데, 로컬은 재초기화 간격 중앙값이 18분(≈2사이클)이라 **KPI 가
    영영 쌓이지 않는다** — 실제로 0건이었다.
    """

    def _with_hist(self, n):
        sh = GreyboxShadow()
        for i in range(n):
            sh._hist.append({'state': (24.0 + i * 0.1, 60.0, 500.0),
                             'ext': {'T_ext': 15.0, 'RH_ext': 55.0, 'CO2_ext': 410.0,
                                     'solar': 0.0, 'wind': 1.0},
                             'cmds': {'vent': 10.0}, 'dt': 600.0,
                             'regime': 'mild_night'})
        sh._prev_T, sh._prev_RH, sh._prev_CO2 = 24.0, 60.0, 500.0
        sh._prev_pred_T, sh._prev_pred_RH = 24.2, 60.5
        return sh

    def test_바로_이어지면_이력과_직전_예측을_받는다(self):
        a = self._with_hist(10)
        b = GreyboxShadow()
        rep = b.load_state(a.export_state(dt=600.0), dt=600.0)
        assert rep['hist'] == 10 and rep['prev'] is True
        assert b._prev_pred_T == pytest.approx(24.2)
        # 다음 한 사이클이면 KPI 한 건이 나온다(10사이클을 다시 기다리지 않는다)
        assert len(b._hist) == 10

    def test_오래_쉬었으면_이어지는_것은_버린다(self):
        """연속을 전제로 하는 값이라, 구멍이 나면 이어받으면 안 된다."""
        a = self._with_hist(10)
        blob = a.export_state(dt=600.0)
        blob['saved_at'] = time.time() - 3600.0      # 한 시간 쉬었다
        b = GreyboxShadow()
        rep = b.load_state(blob, dt=600.0)
        assert rep['hist'] == 0 and rep['prev'] is False
        assert rep['input'] >= 0            # 학습 창은 시각으로 따로 가린다

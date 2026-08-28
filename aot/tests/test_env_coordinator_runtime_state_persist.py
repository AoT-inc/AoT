# coding=utf-8
"""사이클 간 보존해야 하는 상태 두 가지 — 추세 히스토리와 게이트-온리 환경 스냅샷.

`EnvCoordinator` 는 사이클마다(활성 시설당 5~10분 주기) **새로 만들어진다**
(로그 실측: "EnvCoordinator initialised" 가 사이클마다 반복). `integral`·
`prev_commands`·`active_vars`·캘리브레이션은 이 재생성을 견디도록 이미
`function_runtime_state` 에 저장·복원되는데, 추세 히스토리
(`TrendState.history`, 2점 이상 최소제곱 회귀의 재료)만 그 목록에서 빠져
있었다 — 매 사이클 빈 상태로 다시 시작해 회귀에 필요한 점 2개를 영원히 못
모으므로 추세는 **항상 0** 이었고, 맵 팝업 [현황] 카드는 0 을 안 보여주므로
추세 줄이 에러도 로그도 없이 조용히 사라졌다. 실측(2026-08-28): 서로 다른
3개 시설의 `summary_json.trend` 가 전부 `{T:0.0, RH:0.0, CO2:0.0}` 또는
`None` 이었다.
"""

from unittest.mock import MagicMock

import pytest

from aot.functions.custom_functions.env_coordinator import CustomModule
from aot.functions.utils.env_control.situation import TrendState, _slope_per_min


# ─────────────────────────────────────────────────────────────────────────────
# TrendState — JSON 왕복이 회귀 계산을 깨지 않는가
# ─────────────────────────────────────────────────────────────────────────────

class TestTrendStateSurvivesJsonRoundTrip:
    """저장은 `json.dumps(history)`, 복원은 `TrendState(history=json.loads(...))`
    이다. JSON 은 튜플을 배열로 낸다 — `_slope_per_min` 이 `for t, v in points`
    로 그대로 풀어 쓰므로 튜플로 되돌릴 필요는 없다는 것이 코드의 전제다.
    그 전제가 실제로 맞는지 여기서 확인한다.
    """

    def test_list_pairs_unpack_the_same_as_tuples(self):
        tuples = [(0.0, 20.0), (60.0, 21.0), (120.0, 22.0)]
        as_json_round_trip = [list(p) for p in tuples]   # json.loads(json.dumps(...))
        assert _slope_per_min(tuples) == _slope_per_min(as_json_round_trip)

    def test_two_points_after_restore_produce_a_nonzero_slope(self):
        """복원 직후 사이클에서 관측 1점만 추가되어도, 이미 저장돼 있던 1점과
        합쳐 2점이 되어 기울기가 0 이 아니어야 한다 — 이게 이 저장의 요점이다."""
        restored = TrendState(history={'T': [[0.0, 20.0]]})
        # 이번 사이클 관측을 그대로 추가(실제로는 _update_trend 가 한다).
        restored.history['T'].append((60.0, 21.0))
        assert _slope_per_min(restored.history['T']) == pytest.approx(1.0)

    def test_a_fresh_history_still_yields_zero_not_an_error(self):
        """복원할 게 없는 첫 실행은 예전과 같이 동작해야 한다(회귀 없음)."""
        fresh = TrendState()
        assert _slope_per_min(fresh.history.get('T', [])) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# RuntimeStateMixin — 저장·복원 경로가 trend_state_json 을 실제로 다루는가
# ─────────────────────────────────────────────────────────────────────────────

class TestRuntimeStateMixinWiresTrendState:
    """DB 왕복 전체를 세우는 대신, 이 경로가 존재한다는 것을 소스에서 고정한다
    — 다른 세 상태(integral·prev_commands·active_vars)와 나란히 다뤄지는지가
    핵심이라, 실제 SQLAlchemy 세션을 stub 하는 것보다 이 배선이 빠지지 않는
    것을 지키는 편이 이 회귀에 더 가깝다."""

    def _src(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), '..', 'functions',
            'custom_functions', 'env_coordinator_impl',
            '_runtime_state_mixin.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_load_restores_trend_state(self):
        src = self._src()
        assert 'row.trend_state_json' in src
        assert 'self._trend_state = TrendState(' in src

    def test_save_persists_trend_state(self):
        src = self._src()
        assert 'row.trend_state_json = json.dumps(_trend.history)' in src

    def test_restore_failure_does_not_crash_the_cycle(self):
        """저장된 JSON 이 깨져 있어도(수동 편집·구버전 잔재) 사이클은 계속
        돌아야 한다 — 추세 하나가 안전 동작을 막으면 안 된다."""
        src = self._src()
        block = src.split('if trend_raw:', 1)[1].split('if cal_raw:', 1)[0]
        assert 'except Exception' in block

    def test_window_sec_is_not_persisted(self):
        """`assess()` 가 매 호출마다 그 사이클의 `cycle_sec` 기준으로
        `window_sec` 을 다시 정하므로, 저장해도 곧바로 덮어써진다 — 저장하는
        건 `history` 뿐이어야 한다(설명 주석이 그 낱말을 언급하는 것과,
        실제로 `row.` 필드에 대입하는 것은 다른 이야기라 코드만 본다)."""
        src = self._src()
        code_only = '\n'.join(
            ln.split('#', 1)[0] for ln in src.splitlines())
        assert 'json.dumps(_trend.history)' in code_only
        assert 'window_sec' not in code_only


# ─────────────────────────────────────────────────────────────────────────────
# 게이트-온리 요약도 현재 환경(photo)을 실어야 한다
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def coord():
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c.photosynth_mode_enabled = False
    c.dli_target = 0.0
    c._daily_acc = None
    from aot.functions.utils.env_control.photosynthesis import CropParams
    c._crop_params_cache = CropParams()   # _plot_targets() DB 조회를 우회
    return c


class TestGateOnlySummaryStillReportsTheEnvironment:
    """게이트는 "이번 사이클에 제어 명령을 안 냈다" 는 뜻이지 "환경을 안
    쟀다" 는 뜻이 아니다. `internal` 은 게이트 평가보다 앞서 이미 수집돼
    있으므로, 게이트로 조기 종료해도 현재 온습도·광량·VPD 는 화면에
    나와야 한다(2026-08-28: 게이트 상태와 환경 표시를 묶었던 것을 풀었다).
    """

    def test_photo_snapshot_reads_purely_from_internal(self, coord):
        internal = {'light': 400.0, 'CO2': 800.0, 'T': 24.0, 'RH': 65.0,
                   'VPD': 1.0}
        photo = coord._build_photo_snapshot(internal)
        assert photo['temp'] == 24.0
        assert photo['rh'] == 65.0
        assert photo['vpd'] == 1.0
        assert photo['co2'] == 800.0

    def test_missing_values_do_not_raise(self, coord):
        # 게이트가 아주 이른 시점에 걸리면 internal 이 비어 있을 수 있다.
        photo = coord._build_photo_snapshot({})
        assert photo['enabled'] is False
        assert 'rate_rel_pct' not in photo

    def test_normal_path_and_gate_only_path_share_one_source(self):
        """두 경로가 각자 광합성 스냅샷을 계산하면 갈라진다 — 갈라지면 같은
        사이클인데 게이트 여부에 따라 다른 숫자가 나올 수 있다."""
        import os
        path = os.path.join(
            os.path.dirname(__file__), '..', 'functions',
            'custom_functions', 'env_coordinator_impl', '_cycle_mixin.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        assert src.count('def _build_photo_snapshot') == 1
        # 게이트-온리 요약과 정상 요약 둘 다 이 헬퍼를 통해서만 photo 를 만든다.
        assert "'photo': self._build_photo_snapshot(internal)" in src
        assert 'photo = self._build_photo_snapshot(internal)' in src

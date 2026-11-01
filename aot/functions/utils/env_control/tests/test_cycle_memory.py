# coding=utf-8
"""재시작 첫 사이클 — 판단 규칙의 사이클 간 기억이 재시작을 넘는다 (2026-10-10 영양 육묘장).

## 실측

    14:08 사이클  일사 594 W/m² · 실내 28.4 °C · 선 26.4 °C → 하한 47 %(근거 51)
    14:13:44      데몬 재시작
    14:14 첫 사이클  일사 159.6 W/m²(지나가는 구름 — 이력 띠 150~200 안) → '해 없음' → 창 0 %(근거 1)
    14:24         일사 598 W/m² → 하한 다시 섬

재시작이 없으면(리플레이) 같은 14:14 입력에서 해 있음 이력이 이어져 하한 37 %(근거 51)였다.
결함은 일사 부하 환기만의 것이 아니다 — 스크린(DLI·하루 이동 수·일사 이력)·고온 보호 래치·하드
한계 래치가 모두 재시작에 '꺼져 있었다' 로 돌아갔다. 정본은 `env_control/cycle_memory.py`.
"""
import contextlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aot.functions.custom_functions.env_coordinator import CustomModule
from aot.functions.custom_functions.env_coordinator_impl import _runtime_state_mixin as RSM
from aot.functions.utils.env_control import cycle_memory as CM
from aot.functions.utils.env_control import solar_vent as SV
from aot.functions.utils.env_control.coordinator import CoordinatorState
from aot.functions.utils.env_control.heat_protect import (
    HeatProtectDecision, HeatProtectState,
)
from aot.functions.utils.env_control.screen_policy import ScreenState
from aot.functions.utils.env_control.types import TargetVar

T_SAVE = 1791608904.0          # 2026-10-10 14:08:24 KST — 재시작 전 마지막 사이클
T_FIRST = 1791609243.0         # 14:14:03 — 재시작 뒤 첫 사이클


def _ctx(solar, T_int=28.7, T_ext=27.9):
    return {'T_int': T_int, 'T_ext': T_ext, 'internal': {'_outdoor_solar': solar},
            'external': {}, 'heat_protect': HeatProtectDecision(tier=0, threshold=30.0),
            'temp_max': 36.0, 'T_ceiling': 29.0}


def _target():
    return {'_temperature_constraint': TargetVar(value=25.8, tolerance=1.0, priority=1.0)}


def _coord():
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c.unique_id = 'fn-yy'
    c._status_log = MagicMock()
    c._coord_state = CoordinatorState()
    c._last_cycle_ts = 0.0
    c._constraint_breach_state = {'T_max': False, 'T_min': False, 'RH_max': False,
                                  'RH_min': False, 'fog_RH': False}
    c._light_breach_state = {'max': False, 'min': False}
    return c


def _cycle(c, solar):
    sit = SimpleNamespace(context=_ctx(solar), target=_target())
    c._evaluate_solar_vent(sit, HeatProtectDecision(tier=0, threshold=30.0))
    return sit.context['solar_vent']


@pytest.fixture
def runtime_db(tmp_path, monkeypatch):
    """`function_runtime_state` 한 표짜리 SQLite — 저장·복원을 진짜 행으로 거친다."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from aot.databases.models import FunctionRuntimeState
    eng = create_engine('sqlite:///%s' % (tmp_path / 'rt.db'))
    FunctionRuntimeState.__table__.create(bind=eng)

    @contextlib.contextmanager
    def _scope(_path):
        s = Session(eng)
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(RSM, 'session_scope', _scope)
    return eng


def _restart(monkeypatch, now):
    """새 프로세스 — 빈 기억의 코디네이터가 저장된 행에서 되살린다."""
    monkeypatch.setattr(RSM.time, 'time', lambda: now)
    c = _coord()
    c._load_runtime_state()
    return c


# ─────────────────────────────────────────────────────────────────────────────
# 1. 결함 — 기억이 없으면 이력 띠 안의 일사가 '해 없음' 이다
# ─────────────────────────────────────────────────────────────────────────────

class TestTheFault:

    def test_a_fresh_memory_reads_the_cloud_dip_as_no_sun(self):
        dec = _cycle(_coord(), 159.6)
        assert not dec.active and dec.why_off == 'no_sun'

    def test_without_a_restart_the_hysteresis_rides_through_the_dip(self):
        c = _coord()
        assert _cycle(c, 593.7).active
        dec = _cycle(c, 159.6)
        assert dec.active and dec.floor_pct > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. 재시작 — 저장된 행에서 되살린 첫 사이클
# ─────────────────────────────────────────────────────────────────────────────

class TestRestartFirstCycle:

    def test_the_solar_floor_stands_on_the_first_cycle_after_a_restart(
            self, runtime_db, monkeypatch):
        before = _coord()
        assert _cycle(before, 593.7).active
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE)
        before._save_runtime_state()

        after = _restart(monkeypatch, T_FIRST)
        assert after._solar_vent_state.sun_on and after._solar_vent_state.on
        dec = _cycle(after, 159.6)
        assert dec.active, dec.describe()
        assert dec.floor_pct > 0.0
        # 첫 사이클에 '켬' 을 한 번 말한다(새 프로세스의 로그에 상태가 남는다).
        after._status_log.assert_called_once()

    def test_screen_dli_moves_and_sun_survive_the_restart(self, runtime_db, monkeypatch):
        before = _coord()
        before._screen_state = ScreenState(
            day_key='2026-10-10', dli_mol=9.4, cloud_ratio=0.8, cloud_ts=T_SAVE,
            sun_on=True, shade_mode='free', moves_today={'shade': 3},
            pending={'shade': (0.0, T_SAVE - 60.0)}, night_close_on=False)
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE)
        before._save_runtime_state()

        st = _restart(monkeypatch, T_FIRST)._screen_state
        assert st.day_key == '2026-10-10'
        assert st.dli_mol == pytest.approx(9.4)
        assert st.sun_on and st.cloud_ratio == pytest.approx(0.8)
        assert st.moves_today == {'shade': 3}
        assert st.pending == {'shade': (0.0, T_SAVE - 60.0)}
        assert isinstance(st.pending['shade'], tuple)

    def test_a_standing_heat_protection_is_not_released_by_a_restart(
            self, runtime_db, monkeypatch):
        before = _coord()
        before._heat_state = HeatProtectState(
            latched=True, tier=1, entered_at=T_SAVE - 900.0, sun_on=True, shade_on=True)
        before._constraint_breach_state['T_max'] = True
        before._night_condensation_escape = True
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE)
        before._save_runtime_state()

        after = _restart(monkeypatch, T_FIRST)
        hs = after._heat_state
        assert hs.latched and hs.tier == 1 and hs.entered_at == pytest.approx(T_SAVE - 900.0)
        assert after._constraint_breach_state['T_max'] is True
        assert after._night_condensation_escape is True

    def test_the_memory_does_not_clobber_the_calibration_keys(self, runtime_db, monkeypatch):
        before = _coord()
        before._solar_vent_state = SV.SolarVentState(sun_on=True, on=True)
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE)
        before._save_runtime_state()
        from sqlalchemy.orm import Session
        from aot.databases.models import FunctionRuntimeState
        with Session(runtime_db) as s:
            row = s.query(FunctionRuntimeState).first()
            blob = json.loads(row.calibration_state_json)
            blob['greybox_fit_ts'] = 123.0
            row.calibration_state_json = json.dumps(blob)
            s.commit()
        before._save_runtime_state()
        with Session(runtime_db) as s:
            blob = json.loads(s.query(FunctionRuntimeState).first().calibration_state_json)
        assert blob['greybox_fit_ts'] == 123.0
        assert blob[CM.STORE_KEY]['_solar_vent_state'] == {'sun_on': True, 'on': True,
                                                            'on_since': None,
                                                            'blind_on': False}


# ─────────────────────────────────────────────────────────────────────────────
# 3. 낡은 기억·깨진 기억
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleOrBroken:

    def test_a_memory_older_than_the_bound_is_dropped(self):
        owner = SimpleNamespace(_solar_vent_state=SV.SolarVentState(sun_on=True, on=True))
        blob = json.loads(json.dumps(CM.export_memory(owner, T_SAVE)))
        fresh = SimpleNamespace()
        assert CM.restore_memory(fresh, blob, T_SAVE + CM.MEMORY_MAX_AGE_S + 1.0) == []
        assert not hasattr(fresh, '_solar_vent_state')
        assert CM.restore_memory(fresh, blob, T_SAVE + 600.0) == ['_solar_vent_state']

    def test_unknown_fields_are_ignored_and_missing_fields_default(self):
        blob = {'ts': T_SAVE, '_solar_vent_state': {'sun_on': True, 'gone_field': 1},
                '_heat_state': 'not a dict'}
        o = SimpleNamespace()
        assert CM.restore_memory(o, blob, T_SAVE) == ['_solar_vent_state']
        assert o._solar_vent_state == SV.SolarVentState(sun_on=True, on=False)

    def test_latch_dicts_keep_only_known_keys(self):
        o = SimpleNamespace(_constraint_breach_state={'T_max': False, 'fog_RH': False})
        CM.restore_memory(o, {'ts': T_SAVE, '_constraint_breach_state':
                              {'T_max': True, 'retired': True}}, T_SAVE)
        assert o._constraint_breach_state == {'T_max': True, 'fog_RH': False}

    def test_no_timestamp_no_restore(self):
        o = SimpleNamespace()
        assert CM.restore_memory(o, {'_solar_vent_state': {'sun_on': True}}, T_SAVE) == []
        assert CM.restore_memory(o, None, T_SAVE) == []


class TestCalibrationUntouched:

    def test_a_row_with_only_the_memory_does_not_freeze_calibration_off(
            self, runtime_db, monkeypatch):
        before = _coord()
        before._solar_vent_state = SV.SolarVentState(sun_on=True)
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE)
        before._save_runtime_state()
        after = _restart(monkeypatch, T_FIRST)
        # 레지스트리 상태가 없던 행 — 옵션 기본값으로 만들어지게 둔다.
        assert not hasattr(after, '_cal_registry_inst')
        after.calibration_enabled = True
        assert after._cal_registry.enabled

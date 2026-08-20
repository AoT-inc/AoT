# coding=utf-8
"""Unit tests for env_coordinator cycle-summary and related plumbing.

Covers:
  1. CycleMixin._build_cycle_summary  (_cycle_mixin.py)
  2. Alembic revision chain integrity
  3. FunctionRuntimeState.summary_json column presence
"""
import json
import types
import unittest.mock

import pytest

# ---------------------------------------------------------------------------
# 1. CycleMixin._build_cycle_summary
# ---------------------------------------------------------------------------

from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import HelpersMixin


def _make_profile(actuator_id, kind, area_m2, slot_key):
    return types.SimpleNamespace(
        actuator_id=actuator_id,
        kind=kind,
        area_m2=area_m2,
        slot_key=slot_key,
    )


def _make_ff_signal(valid=True, reason="cold_front", T_bias=-1.0, RH_bias=5.0,
                    wind_inhibit=False, rain_expected=True):
    return types.SimpleNamespace(
        valid=valid,
        reason=reason,
        T_bias=T_bias,
        RH_bias=RH_bias,
        wind_inhibit=wind_inhibit,
        rain_expected=rain_expected,
    )


def _make_dummy_self(profiles, last_ff_signal):
    """Build a minimal dummy instance for unbound CycleMixin method calls."""
    obj = types.SimpleNamespace()
    obj._profiles = profiles
    obj._last_ff_signal = last_ff_signal
    obj.logger = unittest.mock.Mock()
    # Inherit class-level caps from CycleMixin
    obj._SUMMARY_MAX_COMMANDS = CycleMixin._SUMMARY_MAX_COMMANDS
    obj._SUMMARY_MAX_TEXT = CycleMixin._SUMMARY_MAX_TEXT
    # 구동주기 요약(actuation) 계산에 필요한 최소 상태 — HelpersMixin 에서 실제
    # 구현을 빌려온다(중복 로직 방지).
    obj._dispatch_moved = {}
    obj.actuation_profile = 'standard'
    obj.actuation_period_sec = 0.0
    obj.emergency_period_sec = 60.0
    obj._emergency_now = False
    obj._emergency_reason = ''
    obj._ACTUATION_PROFILE_SEC = HelpersMixin._ACTUATION_PROFILE_SEC
    obj._MOTOR_MIN_MOVE_SEC = HelpersMixin._MOTOR_MIN_MOVE_SEC
    obj._actuation_params = HelpersMixin._actuation_params.__get__(obj)
    obj._build_actuation_summary = CycleMixin._build_actuation_summary.__get__(obj)
    # 목표·작물 상수는 **구획의 프로그램**에서 온다(2026-08-19). 요약이 그것을
    # 읽으므로 스텁도 같은 표면을 가져야 한다 — DB 없이 도는 테스트라 빈 값으로.
    obj._plot_targets = lambda: {'vpd': {'value': None, 'method_id': None},
                                 'co2': {'value': None, 'method_id': None},
                                 'dli': None, 'gdd_daily': None, 'T_base': None,
                                 'model': {}, 'started_on': None,
                                 'plot_name': None, 'stage': None,
                                 'reason': 'none'}
    obj._crop_params = HelpersMixin._crop_params.__get__(obj)
    obj._STRAIN_KINDS = CycleMixin._STRAIN_KINDS
    obj._STRAIN_SATURATED_PCT = CycleMixin._STRAIN_SATURATED_PCT
    obj._STRAIN_MIN_SEC = CycleMixin._STRAIN_MIN_SEC
    obj._assess_strain = CycleMixin._assess_strain.__get__(obj)
    return obj


def _make_situation(context=None, modes=None, limiting_factor="humidity",
                    deviation_native=None):
    return types.SimpleNamespace(
        context=context or {"T_trend": 0.02, "RH_trend": -0.1, "CO2_trend": 1.0},
        modes=modes or ["dehumidify"],
        limiting_factor=limiting_factor,
        deviation_native=deviation_native or {"temperature": 1.5, "humidity": -3.0},
    )


def _make_env_target():
    return {
        "temperature": types.SimpleNamespace(value=21.0),
        "humidity":    types.SimpleNamespace(value=65.0),
    }


def _make_gate_result(triggered=False, description=""):
    return types.SimpleNamespace(triggered=triggered, description=description)


# --- fixtures ---------------------------------------------------------------

@pytest.fixture
def two_profile_setup():
    """Two profiles: one opening, one fan."""
    profiles = [
        _make_profile("aid1", "opening", area_m2=2.5, slot_key="north_vent"),
        _make_profile("aid2", "fan",     area_m2=None, slot_key="fan_east"),
    ]
    ff = _make_ff_signal()
    dummy = _make_dummy_self(profiles, ff)
    situation = _make_situation()
    env_target = _make_env_target()
    # final_cmds: dict cmd for aid1, object cmd for aid2
    final_cmds = {
        "aid1": {"value": 45.0},
        "aid2": types.SimpleNamespace(value=100.0),
    }
    commands = {
        "aid1": types.SimpleNamespace(reason=1, var_source="humidity"),
    }
    gate_result = _make_gate_result()
    return dummy, situation, env_target, final_cmds, commands, gate_result


# --- core correctness -------------------------------------------------------

def test_build_cycle_summary_returns_dict(two_profile_setup):
    dummy, situation, env_target, final_cmds, commands, gate_result = two_profile_setup
    result = CycleMixin._build_cycle_summary(
        dummy,
        now_ts=1_700_000_000.0,
        situation=situation,
        env_target=env_target,
        final_cmds=final_cmds,
        commands=commands,
        gate_result=gate_result,
    )
    assert isinstance(result, dict)


def test_build_cycle_summary_json_serializable(two_profile_setup):
    dummy, situation, env_target, final_cmds, commands, gate_result = two_profile_setup
    result = CycleMixin._build_cycle_summary(
        dummy,
        now_ts=1_700_000_000.0,
        situation=situation,
        env_target=env_target,
        final_cmds=final_cmds,
        commands=commands,
        gate_result=gate_result,
    )
    dumped = json.dumps(result)
    assert isinstance(dumped, str)
    assert len(dumped) > 0


def test_vent_effective_area(two_profile_setup):
    """vent.effective_area_m2 = area_m2 * pct/100 for 'opening' profiles."""
    dummy, situation, env_target, final_cmds, commands, gate_result = two_profile_setup
    # aid1 is opening, area=2.5, pct=45 -> eff = 2.5 * 45/100 = 1.125
    result = CycleMixin._build_cycle_summary(
        dummy,
        now_ts=0.0,
        situation=situation,
        env_target=env_target,
        final_cmds=final_cmds,
        commands=commands,
        gate_result=gate_result,
    )
    vent = result["vent"]
    assert vent["total_area_m2"] == pytest.approx(2.5, abs=0.01)
    assert vent["effective_area_m2"] == pytest.approx(1.125, abs=0.01)


def test_open_ratio_pct(two_profile_setup):
    """open_ratio_pct = effective / total * 100."""
    dummy, situation, env_target, final_cmds, commands, gate_result = two_profile_setup
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation, env_target=env_target,
        final_cmds=final_cmds, commands=commands, gate_result=gate_result,
    )
    # 1.125 / 2.5 * 100 = 45.0
    assert result["vent"]["open_ratio_pct"] == pytest.approx(45.0, abs=0.1)


def test_outputs_by_kind_averages(two_profile_setup):
    """outputs_by_kind holds per-kind average pct."""
    dummy, situation, env_target, final_cmds, commands, gate_result = two_profile_setup
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation, env_target=env_target,
        final_cmds=final_cmds, commands=commands, gate_result=gate_result,
    )
    obk = result["outputs_by_kind"]
    assert "opening" in obk
    assert obk["opening"] == pytest.approx(45.0, abs=0.1)
    assert "fan" in obk
    assert obk["fan"] == pytest.approx(100.0, abs=0.1)


def test_commands_list_entries(two_profile_setup):
    """Each entry in commands list has slot_key, kind, pct, reason, var."""
    dummy, situation, env_target, final_cmds, commands, gate_result = two_profile_setup
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation, env_target=env_target,
        final_cmds=final_cmds, commands=commands, gate_result=gate_result,
    )
    cmd_list = result["commands"]
    assert len(cmd_list) == 2

    # find aid1 entry
    aid1_entry = next(e for e in cmd_list if e["slot_key"] == "north_vent")
    assert aid1_entry["kind"] == "opening"
    assert aid1_entry["pct"] == pytest.approx(45.0, abs=0.1)
    assert aid1_entry["reason"] == 1
    assert aid1_entry["var"] == "humidity"

    # aid2 has no commands entry -> reason/var are None
    aid2_entry = next(e for e in cmd_list if e["slot_key"] == "fan_east")
    assert aid2_entry["kind"] == "fan"
    assert aid2_entry["pct"] == pytest.approx(100.0, abs=0.1)
    assert aid2_entry["reason"] is None
    assert aid2_entry["var"] is None


def test_feedforward_active(two_profile_setup):
    """Feedforward dict is active when ff.valid and reason != '정상 범위'."""
    dummy, situation, env_target, final_cmds, commands, gate_result = two_profile_setup
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation, env_target=env_target,
        final_cmds=final_cmds, commands=commands, gate_result=gate_result,
    )
    ff = result["feedforward"]
    assert ff["active"] is True
    assert ff["reason"] == "cold_front"
    assert ff["T_bias"] == pytest.approx(-1.0, abs=0.01)
    assert ff["RH_bias"] == pytest.approx(5.0, abs=0.01)
    assert ff["wind_inhibit"] is False
    assert ff["rain_expected"] is True


def test_feedforward_inactive_when_normal_range():
    """feedforward.active is False when reason == '정상 범위'."""
    profiles = [_make_profile("a1", "fan", None, "fan1")]
    ff = _make_ff_signal(valid=True, reason="정상 범위")
    dummy = _make_dummy_self(profiles, ff)
    situation = _make_situation()
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation,
        env_target=_make_env_target(),
        final_cmds={"a1": {"value": 50.0}},
        commands={},
        gate_result=_make_gate_result(),
    )
    assert result["feedforward"]["active"] is False


def test_feedforward_inactive_when_invalid():
    """feedforward.active is False when ff.valid is False."""
    profiles = [_make_profile("a1", "fan", None, "fan1")]
    ff = _make_ff_signal(valid=False, reason="some_reason")
    dummy = _make_dummy_self(profiles, ff)
    situation = _make_situation()
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation,
        env_target=_make_env_target(),
        final_cmds={"a1": {"value": 50.0}},
        commands={},
        gate_result=_make_gate_result(),
    )
    assert result["feedforward"]["active"] is False


def test_deviation_rounded():
    """Deviation values are rounded to 2 decimal places."""
    profiles = []
    ff = _make_ff_signal(valid=False, reason="")
    dummy = _make_dummy_self(profiles, ff)
    situation = _make_situation(deviation_native={"temperature": 1.555555, "humidity": -3.0})
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation,
        env_target={},
        final_cmds={},
        commands={},
        gate_result=_make_gate_result(),
    )
    assert result["deviation"]["temperature"] == pytest.approx(1.56, abs=0.001)


def test_modes_and_limiting_factor():
    """modes and limiting_factor pass through correctly."""
    profiles = []
    ff = _make_ff_signal(valid=False, reason="")
    dummy = _make_dummy_self(profiles, ff)
    situation = _make_situation(modes=["dehumidify", "cool"], limiting_factor="humidity")
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation,
        env_target={},
        final_cmds={},
        commands={},
        gate_result=_make_gate_result(),
    )
    assert result["modes"] == ["dehumidify", "cool"]
    assert result["limiting_factor"] == "humidity"


def test_gate_fields():
    """gate dict reflects gate_result.triggered and .description."""
    profiles = []
    ff = _make_ff_signal(valid=False, reason="")
    dummy = _make_dummy_self(profiles, ff)
    situation = _make_situation()
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation,
        env_target={},
        final_cmds={},
        commands={},
        gate_result=_make_gate_result(triggered=True, description="wind gate"),
    )
    assert result["gate"]["triggered"] is True
    assert result["gate"]["description"] == "wind gate"


def test_vent_no_opening_profiles():
    """When no 'opening' profiles exist, open_ratio_pct is None."""
    profiles = [_make_profile("f1", "fan", None, "fan1")]
    ff = _make_ff_signal(valid=False, reason="")
    dummy = _make_dummy_self(profiles, ff)
    situation = _make_situation()
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation,
        env_target={},
        final_cmds={"f1": {"value": 80.0}},
        commands={},
        gate_result=_make_gate_result(),
    )
    assert result["vent"]["open_ratio_pct"] is None
    assert result["vent"]["total_area_m2"] == pytest.approx(0.0, abs=0.01)


# --- cap tests --------------------------------------------------------------

def test_commands_list_capped_at_32():
    """When more than 32 profiles have commands, list is capped at 32."""
    n = 40
    profiles = [
        _make_profile(f"aid{i}", "fan", None, f"fan{i}") for i in range(n)
    ]
    ff = _make_ff_signal(valid=False, reason="")
    dummy = _make_dummy_self(profiles, ff)
    situation = _make_situation()
    # All profiles have commands
    final_cmds = {f"aid{i}": {"value": float(i)} for i in range(n)}
    commands = {}
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation,
        env_target={},
        final_cmds=final_cmds,
        commands=commands,
        gate_result=_make_gate_result(),
    )
    assert len(result["commands"]) == 32


def test_ff_reason_truncated_at_200():
    """Feedforward reason longer than 200 chars is truncated."""
    long_reason = "x" * 300
    profiles = []
    ff = _make_ff_signal(valid=True, reason=long_reason)
    dummy = _make_dummy_self(profiles, ff)
    situation = _make_situation()
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation,
        env_target={},
        final_cmds={},
        commands={},
        gate_result=_make_gate_result(),
    )
    assert len(result["feedforward"]["reason"]) == 200


def test_gate_description_truncated_at_200():
    """gate.description longer than 200 chars is truncated."""
    long_desc = "y" * 300
    profiles = []
    ff = _make_ff_signal(valid=False, reason="")
    dummy = _make_dummy_self(profiles, ff)
    situation = _make_situation()
    result = CycleMixin._build_cycle_summary(
        dummy, now_ts=0.0, situation=situation,
        env_target={},
        final_cmds={},
        commands={},
        gate_result=_make_gate_result(description=long_desc),
    )
    assert len(result["gate"]["description"]) == 200


# ---------------------------------------------------------------------------
# 2. Alembic revision chain integrity
# ---------------------------------------------------------------------------
#
# This section used to pin one file (p5_19_add_runtime_summary.py) and assert
# its revision/down_revision. That file was folded into the single baseline
# p6_00_rebaseline_20260720 when the 115-revision chain was collapsed, so the
# assertions decayed into "a deleted file still exists". What is worth guarding
# is the property that made them useful: the chain still forms one unbroken
# line. The column those migrations added is covered by section 3, which reads
# the model — the source of truth for new installs, since they run
# db.create_all() and stamp the head rather than walking the chain.
#
# The checks themselves now live in aot/scripts/check_alembic_head.py so the
# pre-commit hook and CI can run them too. That relocation is the point: this
# section already asserted ALEMBIC_VERSION == chain head, and the constant
# still shipped one revision behind in v26.08.2 — a suite that only runs when
# someone remembers to run it does not guard a release. These tests stay as the
# `pytest` entry point into that one implementation; do not re-inline the logic.

from aot.scripts import check_alembic_head as _alembic_check


def _findings_of(kind):
    findings, _chain, _heads = _alembic_check.run_checks()
    return [f for f in findings if f["kind"] == kind]


def test_revision_chain_is_not_empty():
    chain, problems = _alembic_check.revision_chain()
    assert not problems, f"unparsable migration files: {problems}"
    assert chain, f"no migration files under {_alembic_check.VERSIONS_DIR}"


def test_revision_chain_has_single_root():
    assert not _findings_of("single-root")


def test_revision_chain_has_no_dangling_parent():
    assert not _findings_of("no-dangling")


def test_revision_chain_has_single_head():
    assert not _findings_of("single-head")


def test_alembic_version_constant_matches_chain_head():
    """config.ALEMBIC_VERSION is the upgrade target, not 'head'.

    alembic_upgrade_db() passes this constant to `update-alembic` explicitly
    (plain 'head' fails while the retired p5 lineage is still around as a
    second head). So a new migration whose author forgets to bump the constant
    is never applied on upgrade, and the mismatch is silent.
    """
    findings = _findings_of("constant-matches")
    assert not findings, findings[0]["message"] if findings else ""


# ---------------------------------------------------------------------------
# 3. FunctionRuntimeState.summary_json column
# ---------------------------------------------------------------------------

def test_function_runtime_state_has_summary_json_column():
    from aot.databases.models.function import FunctionRuntimeState
    col_names = list(FunctionRuntimeState.__table__.columns.keys())
    assert "summary_json" in col_names, (
        f"summary_json not in columns: {col_names}"
    )


def test_function_runtime_state_summary_json_nullable():
    from aot.databases.models.function import FunctionRuntimeState
    col = FunctionRuntimeState.__table__.columns["summary_json"]
    assert col.nullable is True

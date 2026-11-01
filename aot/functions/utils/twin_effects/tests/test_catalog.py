# coding=utf-8
"""효과 목록표 완전성 — 새 종류를 더하고 표를 안 고치면 여기서 깨진다(조용히 빼지 않기)."""
import subprocess
import sys

from aot.functions.utils.twin_effects import catalog as C


def test_every_env_control_kind_has_a_row():
    from aot.functions.utils.env_control.greybox.channels import KIND_TO_CHANNEL, UNMODELED_KINDS
    from aot.functions.utils.env_control.types import ACTUATOR_KINDS
    known = C.all_kinds(C.FACILITY)
    missing = (set(ACTUATOR_KINDS) | set(KIND_TO_CHANNEL) | set(UNMODELED_KINDS)) - known
    assert not missing, "효과 목록표에 없는 장치 종류: %s" % sorted(missing)


def test_channel_agrees_with_env_control_kind_to_channel():
    from aot.functions.utils.env_control.greybox.channels import KIND_TO_CHANNEL, UNMODELED_KINDS
    for kind, ch in KIND_TO_CHANNEL.items():
        assert C.row_for(kind).channel == ch, kind
    for kind in UNMODELED_KINDS:
        row = C.row_for(kind)
        if kind in ('shade', 'curtain'):               # env_control 은 입력 채널로 따로 다룬다(미모델 표에는 이름만)
            assert row.channel == kind
        else:
            assert row.status == C.UNMODELED, kind


def test_unknown_kind_is_explicit_unmodeled_not_dropped():
    r = C.row_for("some_new_gadget")
    assert r.status == C.UNMODELED and "unknown_kind" in r.unmodeled_effects
    s = C.summarize(["heater", "some_new_gadget", "lighting"])
    assert s["modeled"] == 1 and s["unmodeled"] == 2
    assert s["unmodeled_kinds"] == ["some_new_gadget", "lighting"]


def test_status_derivation():
    assert C.row_for("heater").status == C.MODELED
    assert C.row_for("fogger").status == C.PARTIAL        # 잎 젖음 미반영
    assert C.row_for("lighting").status == C.UNMODELED
    assert C.row_for("irrigation_sprinkler", C.FIELD).status == C.PARTIAL
    assert C.row_for("frost_fan", C.FIELD).status == C.UNMODELED


def test_field_air_effects_listed_with_slot():
    r = C.row_for("irrigation_sprinkler", C.FIELD)
    assert "air_RH_near_surface" in r.unmodeled_effects and "air_T_near_surface" in r.unmodeled_effects
    assert "env_twin_field_h" in r.slot


def test_every_row_kind_belongs_to_one_row_per_domain():
    seen = {}
    for r in C.rows():
        for k in r.kinds:
            assert (r.domain, k) not in seen, k
            seen[(r.domain, k)] = r.name


def test_import_is_node_safe():
    code = ("import sys, aot.functions.utils.twin_effects.catalog\n"
            "bad=[m for m in sys.modules if m.startswith(('flask','sqlalchemy','influxdb','aot.databases','aot.functions.utils.env_control'))]\n"
            "print(bad)\nsys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

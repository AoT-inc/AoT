# coding=utf-8
"""시설 부품의 `options.effects` — 장치 계열을 효과 목록표로 채널에 합친다(설계서 2026-10-25 E1)."""
import numpy as np

from aot.twin.types import Provenance, SeriesRef, Status
from .test_facility_greybox import GP, M, V, _data, _run, _spec

W = {"id": "w1", "kind": "opening", "ratings": {"area_m2": 10.0}}
H = {"id": "h1", "kind": "heater", "ratings": {"rated_kW_thermal": 30.0}}


def _dev_spec(devices, prov=M, extra_ctl=None, **opts):
    """장치 id 로 키를 단 controls. 데이터는 채널 시험과 같은 vent/heat 계열을 장치 하나씩에 쓴다."""
    s = _spec(controls=False, effects={"devices": devices}, **opts)
    ctl = {"w1": SeriesRef("act", "vent", 0, prov), "h1": SeriesRef("act", "heat", 1, prov)}
    ctl.update(extra_ctl or {})
    s.controls = ctl
    return s


def test_single_devices_equal_hand_wired_channels():
    now, data = _data()
    ref = _run(_spec(), data, now + 60)
    got = _run(_dev_spec([W, H]), data, now + 60)
    assert got.status == ref.status and got.reason == ref.reason
    assert np.isclose(got.info["lead1h_T"], ref.info["lead1h_T"], atol=1e-9)
    assert got.info["effects"]["members"] == {"vent": ["w1"], "heat": ["h1"]}
    assert got.info["effects"]["unmodeled"] == []


def test_unmodeled_device_is_reported_and_degrades():
    now, data = _data()
    data[("act", "light", 2)] = list(data[("act", "vent", 0)])
    dev = [W, H, {"id": "l1", "kind": "lighting", "ratings": {"rated_kW": 5.0}}]
    r = _run(_dev_spec(dev, extra_ctl={"l1": SeriesRef("act", "light", 2, M)}), data, now + 60)
    assert r.status == Status.DEGRADED
    assert "효과 미반영" in r.reason and "lighting" in r.reason
    assert [u["actuator_id"] for u in r.info["effects"]["unmodeled"]] == ["l1"]


def test_unwired_device_is_listed_not_counted_as_zero():
    now, data = _data()
    dev = [W, H, {"id": "h2", "kind": "heater", "ratings": {"rated_kW_thermal": 30.0}}]     # 계열 연결 안 함
    r = _run(_dev_spec(dev), data, now + 60)
    assert r.info["effects"]["unwired"] == ["h2"]
    assert "상태 계열 없는 장치" in r.reason


def test_device_series_provenance_label_is_not_a_gate():
    now, data = _data()
    r = _run(_dev_spec([W, H], prov=V), data, now + 60)
    assert r.status != Status.NOT_TWINNABLE and "실측이 아님" not in r.reason


def test_no_wired_device_is_not_twinnable():
    now, data = _data()
    s = _dev_spec([W, H])
    s.controls = {}
    r = _run(s, data, now + 60)
    assert r.status == Status.NOT_TWINNABLE


def test_explicit_greybox_value_wins_over_rating_prior():
    now, data = _data()
    ref = _run(_spec(), data, now + 60)
    r = _run(_dev_spec([W, {"id": "h1", "kind": "heater", "ratings": {"rated_kW_thermal": 999.0}}]), data, now + 60)
    assert np.isclose(r.info["lead1h_T"], ref.info["lead1h_T"], atol=1e-9)        # options.greybox.Q_heat 가 이긴다


def test_rating_sum_fills_q_heat_when_not_given():
    now, data = _data()
    ref = _run(_spec(), data, now + 60)
    gb = {k: v for k, v in GP.to_dict().items() if k != "Q_heat"}
    kw = GP.Q_heat / 1000.0
    r = _run(_dev_spec([W, {"id": "h1", "kind": "heater", "ratings": {"rated_kW_thermal": kw}}], greybox=gb), data, now + 60)
    assert np.isclose(r.info["lead1h_T"], ref.info["lead1h_T"], atol=1e-9)        # 정격 합이 Q_heat 로 들어가 손배선과 같다
    no_prior = _run(_dev_spec([W, {"id": "h1", "kind": "heater", "ratings": {}}], greybox=gb), data, now + 60)
    info = getattr(no_prior, "info", None) or {}
    # 정격을 모르면 기본값(5 kW)이라 같지 않다(일치도가 나빠져 아예 발행되지 않을 수도 있다)
    assert "lead1h_T" not in info or not np.isclose(info["lead1h_T"], ref.info["lead1h_T"], atol=1e-6)


# ── 상태 출처(basis): command 는 추정 — 동기화에서 빼고 예측 입력에만 (설계 결정 4) ──────────────────────────
def test_basis_duty_log_and_actual_sync_exactly_like_no_basis():
    now, data = _data()
    ref = _run(_dev_spec([W, H]), data, now + 60)
    for b in ("duty_log", "actual"):
        r = _run(_dev_spec([W, dict(H, basis=b)]), data, now + 60)
        assert np.isclose(r.info["lead1h_T"], ref.info["lead1h_T"], atol=1e-12), b
        assert "추정" not in r.reason


def test_command_basis_is_left_out_of_sync_and_flagged_estimated():
    now, data = _data()
    ref = _run(_dev_spec([W, H]), data, now + 60)
    r = _run(_dev_spec([W, dict(H, basis="command")]), data, now + 60)
    assert "추정" in r.reason and "h1" in r.reason and "동기화 제외" in r.reason
    if r.status == Status.UNSYNCED:                    # 난방을 모르고는 일치도가 안 나오면 발행하지 않는다 — 그것도 '뺐다'는 증거
        return
    assert r.status == Status.DEGRADED                 # 추정이 섞였으니 최대 degraded
    assert not np.isclose(r.info["lead1h_T"], ref.info["lead1h_T"], atol=1e-9)    # 필터가 난방 입력을 못 봤다
    assert r.info["effects"]["members"]["heat"] == ["h1"]                         # 예측 입력 쪽 채널에는 남는다

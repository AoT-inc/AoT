# coding=utf-8
"""배포형 서비스(S2): 플래그 꺼짐·잠금·하트비트·대지 자동 포함·예보 사다리 자동·대지별 분산."""
import json
import sys
import types

import pytest

from aot.inputs.open_meteo_daily_forecast import measurements_dict as OM_DAILY
from aot.twin import forecast as FC
from aot.twin import gate as G
from aot.twin.discovery import PlotInfo, SiteInfo, build_plan, load_overrides, site_config
from aot.twin.service import ServiceSettings, TwinService, shifted_run_at, stagger_minutes
from aot.twin.settings import SettingsError
from aot.twin.types import Series, Status, TargetKind, WriteResult

T0 = 1_792_000_000.0          # 2026-10-14 근처 (UTC)
THETA = {"unique_id": "soil-1", "unit": "percent", "channel": 2, "provenance": "measured"}
RAIN = {"unique_id": "kma-1", "unit": "mm", "channel": 6, "provenance": "measured"}


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class MemChannel:
    """대지 하나의 내장 통로 흉내: 읽기는 빈 계열, 쓰기는 모은다."""

    def __init__(self, plan, sink_error=None):
        self.plan, self.points, self.sink_error = plan, [], sink_error

    def ping(self):
        return True

    def list_targets(self):
        return list(self.plan.targets)

    def read_series(self, ref, window_s, now):
        return Series()

    def write(self, points):
        if self.sink_error:
            return WriteResult(error=self.sink_error)
        self.points.extend(points)
        return WriteResult(written=len(points))


def _om_channels(disabled=(), unit_override=None):
    out = []
    for ch, m in OM_DAILY.items():
        unit = unit_override.get(m["measurement"], m["unit"]) if unit_override else m["unit"]
        out.append({"channel": ch, "measurement": m["measurement"], "unit": unit, "enabled": ch not in disabled,
                    "lead_d": m["forecast_lead_d"], "daily_stat": m["daily_stat"]})
    return out


def _sites():
    return [SiteInfo("site-A", "김제 A", "Asia/Seoul", [
                PlotInfo("plot-1", "들깨 1구", "2026-06-20", 35.86, 126.88),
                PlotInfo("plot-2", "들깨 2구", "2026-06-21", 35.861, 126.881)]),
            SiteInfo("site-B", "영양 B", "Asia/Seoul", [PlotInfo("plot-9", "고추", "2026-05-01", 36.6, 129.1)])]


def _overrides(**site_a):
    return {"sites": {"site-A": {"enabled": True, "inputs": {"rain": RAIN},
                                 "options": {"rain": {"agg": "hourly_mean_sum", "scale": 4}},
                                 "forecast": {"input": "om-1"}, **site_a}},
            "plots": {"plot-1": {"inputs": {"theta": THETA}}, "plot-2": {"enabled": False}}}


def _service(gate, overrides=None, sites=_sites, channels=None, settings=None, clock=None):
    made = channels if channels is not None else []

    def factory(plan):
        ch = MemChannel(plan)
        made.append(ch)
        return ch, ch

    svc = TwinService(gate, sites, lambda uid: _om_channels(), lambda: overrides or _overrides(),
                      version="test", settings=settings or ServiceSettings(force_tier="light"),
                      channel_factory=factory, clock=clock or Clock())
    return svc, made


# ── 예보 사다리 자동 ─────────────────────────────────────────────────────────────

def test_ladder_from_real_input_meta_matches_hand_written_example():
    cfg, notes = FC.ladder_from_channels("om-1", _om_channels())
    assert notes == []
    assert cfg["rain"] == {"unique_id": "om-1", "unit": "mm", "channels": list(range(0, 8))}
    assert cfg["et0"]["channels"] == list(range(8, 16))
    assert cfg["t_max"]["channels"] == list(range(16, 24)) and cfg["t_min"]["channels"] == list(range(24, 32))
    assert "pop" not in cfg                                          # 강수확률(최대·%)은 모델 입력이 아니다
    assert FC.parse({"forecast": cfg}).keys() == {"rain", "et0", "t_max", "t_min"}


def test_ladder_disabled_channel_leaves_gap_and_extra_overrides_apply():
    cfg, _ = FC.ladder_from_channels("om-1", _om_channels(disabled={3}),
                                     extra={"max_age_h": 24, "rain": {"log_sd": 0.5, "channels": [99]}})
    assert cfg["rain"]["channels"][3] is None and cfg["rain"]["channels"][4] == 4
    assert cfg["rain"]["log_sd"] == 0.5 and cfg["max_age_h"] == 24
    assert 99 not in cfg["rain"]["channels"]                          # 채널은 메타가 정한다(덮어쓰기 불가)
    g = FC.parse({"forecast": cfg})["rain"]
    assert 3 not in g.refs and g.refs[4].channel == 4


def test_ladder_skips_converted_units_and_reports_missing_rain():
    cfg, notes = FC.ladder_from_channels("om-1", _om_channels(unit_override={"rain": "inch"}))
    assert "rain" not in cfg and cfg["et0"]["unit"] == "mm"
    assert any("inch" in n for n in notes) and any("비" in n for n in notes)
    cfg2, notes2 = FC.ladder_from_channels("x", [{"channel": 0, "measurement": "rain", "unit": "mm"}])
    assert cfg2 is None and notes2                                     # 리드 메타가 없는 입력 → 사다리 없음


# ── 대상 자동 포함 ───────────────────────────────────────────────────────────────

def test_build_plan_includes_only_enabled_sites_and_auto_fills_options():
    plans = build_plan(_sites(), _overrides(), lambda uid: _om_channels())
    assert [p.site_id for p in plans] == ["site-A"]                    # 영양 B 는 켜지지 않았다
    p = plans[0]
    assert [t.target_id for t in p.targets] == ["plot-1"]              # plot-2 는 덮어쓰기로 뺐다
    t = p.targets[0]
    assert t.kind == TargetKind.FIELD and t.server_id == "local"
    assert t.options["planted_on"] == "2026-06-20" and t.options["timezone"] == "Asia/Seoul"
    assert t.options["lat"] == pytest.approx(35.86)
    assert t.options["rain"]["scale"] == 4                             # 대지 설정을 상속
    # 앞날 예보는 대지 예보 계열(지도 날씨·AI 와 같은 출처) — 입력은 대지의 예보 출처 지정이 정한다
    assert t.options["forecast_series"] == {"site": "site-A"}
    assert "forecast" not in t.options
    assert any("forecast.input" in n for n in p.notes)                 # 옛 설정 값은 쓰지 않는다고 알린다
    assert set(t.inputs) == {"rain", "theta"} and t.inputs["theta"].channel == 2


def test_build_plan_star_default_plot_override_wins_and_bad_wiring_drops_one_plot():
    ov = {"sites": {"*": {"enabled": True}, "site-B": {"enabled": False}},
          "plots": {"plot-1": {"options": {"planted_on": "2026-07-01", "timezone": "UTC"}},
                    "plot-2": {"inputs": {"theta": {"unit": "percent"}}}}}       # unique_id 없음 → 이 구획만 뺌
    plans = build_plan(_sites(), ov, lambda uid: [])
    assert [p.site_id for p in plans] == ["site-A"]
    p = plans[0]
    assert [t.target_id for t in p.targets] == ["plot-1"]
    assert p.targets[0].options["planted_on"] == "2026-07-01" and p.targets[0].options["timezone"] == "UTC"
    assert any("들깨 2구" in n for n in p.notes)
    assert site_config(ov, "site-A") == {"enabled": True}


def test_build_plan_hand_written_ladder_stays_for_dev_json():
    ladder = {"rain": {"unique_id": "om-1", "unit": "mm", "channels": [0, 1]}}
    plans = build_plan(_sites(), _overrides(forecast=ladder), lambda uid: [])
    t = plans[0].targets[0]
    assert t.options["forecast"] == ladder                              # 개발용 JSON 의 손 사다리는 그대로(명시하면 이긴다)
    assert t.options["forecast_series"] == {"site": "site-A"}


def test_load_overrides_missing_file_is_empty_and_bad_shape_raises(tmp_path):
    assert load_overrides(str(tmp_path / "none.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"sites": []}))
    with pytest.raises(SettingsError):
        load_overrides(str(bad))


# ── 분산 ─────────────────────────────────────────────────────────────────────────

def test_stagger_is_stable_and_bounded_and_shift_wraps_midnight():
    m = stagger_minutes("site-A", 20)
    assert m == stagger_minutes("site-A", 20) and 0 <= m < 20
    assert len({stagger_minutes(f"s{i}", 20) for i in range(30)}) > 5     # 30 대지가 한 시각에 몰리지 않는다
    assert stagger_minutes("x", 1) == 0
    assert shifted_run_at(["06:10", "23:55"], 10) == ((0, 5), (6, 20))


# ── 서비스: 꺼짐·잠금·하트비트 ───────────────────────────────────────────────────

def test_flag_off_does_no_work_and_only_polls_flag():
    clock = Clock()
    gate = G.FakeGate(is_enabled=False)
    sites_called = []
    svc, made = _service(gate, sites=lambda: sites_called.append(1) or _sites(), clock=clock)
    assert svc.start()
    assert svc.step() == svc.step() == 60.0                             # 플래그·하트비트 1 분마다
    assert not made and not sites_called and not svc.reports            # 계획도 실행도 없다
    assert [b["status"] for b in gate.beats] == ["idle"]                # 같은 상태는 heartbeat_s 마다
    clock.t += 61
    svc.step()
    assert len(gate.beats) == 2 and gate.beats[-1]["status"] == "idle"
    assert gate.calls["enabled"] == 3


def test_locked_at_start_never_reads_flag_or_db():
    gate = G.FakeGate(is_supported=False, locked_reason="HARDWARE_PROFILE=LOW", is_enabled=True)
    svc, made = _service(gate, sites=lambda: pytest.fail("잠긴 기기에서 DB 를 읽었다"))
    assert svc.start() is False
    for _ in range(3):
        assert svc.step() == svc.s.heartbeat_s
    assert "enabled" not in gate.calls and not made
    hb = gate.beats[-1]
    assert hb["status"] == G.HB_LOCKED and hb["locked_reason"] == "HARDWARE_PROFILE=LOW"
    assert svc.run_all_once() == []


def _service_with_prewarm(gate, prewarm):
    svc = TwinService(gate, _sites, lambda uid: _om_channels(), _overrides, version="test",
                      settings=ServiceSettings(force_tier="light"),
                      channel_factory=lambda plan: (MemChannel(plan),) * 2, clock=Clock(), prewarm=prewarm)
    return svc


def test_prewarm_runs_each_step_while_enabled_and_survives_a_failure():
    calls = []

    def prewarm():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")                                 # 실패해도 걸음은 계속된다
    gate = G.FakeGate(is_enabled=True)
    svc = _service_with_prewarm(gate, prewarm)
    svc.start()
    svc.step()
    svc.step()
    assert len(calls) == 2


def test_prewarm_never_runs_when_disabled_or_locked():
    off = G.FakeGate(is_enabled=False)
    svc = _service_with_prewarm(off, lambda: pytest.fail("꺼진 트윈이 미리 채웠다"))
    svc.start()
    svc.step()
    locked = G.FakeGate(is_supported=False, locked_reason="HARDWARE_PROFILE=LOW", is_enabled=True)
    svc = _service_with_prewarm(locked, lambda: pytest.fail("잠긴 기기가 미리 채웠다"))
    assert svc.start() is False
    svc.step()


def test_heartbeat_fields_after_a_run():
    clock = Clock()
    gate = G.FakeGate(is_enabled=True)
    svc, made = _service(gate, settings=ServiceSettings(force_tier="light", run_on_enable=True), clock=clock)
    svc.start()
    svc.step()                                       # 계획 → 따라잡기 시각(분산/4 분 뒤)
    clock.t += 3600
    svc.step()
    hb = gate.beats[-1]
    assert set(hb) == {"at", "status", "version", "sites", "plots", "last_run_at", "failures", "locked_reason"}
    assert hb["status"] == "running" and hb["version"] == "test"       # 켜짐·대기 = running(S1 어휘)
    assert hb["sites"] == 1 and hb["plots"] == 1 and hb["failures"] == 0
    assert hb["last_run_at"] == clock.t and hb["locked_reason"] is None
    assert any(b["status"] == G.HB_RUNNING for b in gate.beats)
    # plot-1: 비·토양수분은 배선됐지만 계열이 비어 동기화 불가 — 머리말만(정상 결과, 재시도 없음)
    rep = svc.reports[0]
    assert rep.status in (Status.UNSYNCED, Status.NOT_TWINNABLE) and rep.error is None
    assert made and all(p.measurement.startswith("env_twin") for p in made[0].points)


def test_run_on_enable_staggered_then_daily_schedule():
    clock = Clock()
    gate = G.FakeGate(is_enabled=True, times=["06:10"])
    svc, _ = _service(gate, clock=clock)
    svc.start()
    svc.step()
    st = svc.state["site-A"]
    first = st.next_at
    assert T0 <= first <= T0 + 60 * 20 / 4.0
    clock.t = first
    svc.step()
    st = svc.state["site-A"]
    assert st.last_run_at == first
    import datetime
    from zoneinfo import ZoneInfo
    nxt = datetime.datetime.fromtimestamp(st.next_at, ZoneInfo("Asia/Seoul"))
    h, m = divmod(6 * 60 + 10 + stagger_minutes("site-A", 20), 60)
    assert (nxt.hour, nxt.minute) == (h, m) and st.next_at > clock.t


def test_sink_failure_retries_then_gives_up_until_next_slot():
    clock = Clock()
    gate = G.FakeGate(is_enabled=True)

    def factory(plan):
        ch = MemChannel(plan, sink_error="influx down")
        return ch, ch

    svc = TwinService(gate, _sites, lambda uid: _om_channels(), _overrides, version="t",
                      settings=ServiceSettings(force_tier="light", retry_s=900, max_retries=2),
                      channel_factory=factory, clock=clock)
    svc.start()
    svc.step()
    for _ in range(3):
        clock.t = svc.state["site-A"].next_at
        svc.step()
    st = svc.state["site-A"]
    assert st.retries == 0 and st.failures == 1                         # 2 번 다시 하고 포기 → 다음 예약 시각
    assert gate.beats[-1]["status"] == G.HB_ERROR and gate.beats[-1]["failures"] == 1


def test_turning_off_mid_life_stops_work_and_keeps_polling():
    clock = Clock()
    gate = G.FakeGate(is_enabled=True)
    svc, made = _service(gate, clock=clock)
    svc.start()
    svc.step()
    gate.is_enabled = False
    clock.t = svc.state["site-A"].next_at
    assert svc.step() == svc.s.poll_s
    assert not svc.reports and not svc.state and gate.beats[-1]["status"] == G.HB_DISABLED


def test_run_times_change_replans():
    clock = Clock()
    gate = G.FakeGate(is_enabled=True, times=["06:10"])
    svc, _ = _service(gate, clock=clock, settings=ServiceSettings(force_tier="light", run_on_enable=False))
    svc.start()
    svc.step()
    before = svc.state["site-A"].run_at
    gate.times = ["05:00", "17:00"]
    svc.step()
    assert svc.state["site-A"].run_at != before and len(svc.state["site-A"].run_at) == 2


# ── DbGate 계약(S1 의 twin_gate) ─────────────────────────────────────────────────

def test_parse_run_times_accepts_csv_json_list_and_falls_back():
    assert G.parse_run_times("18:10, 06:10") == ["06:10", "18:10"]
    assert G.parse_run_times('["07:00"]') == ["07:00"]
    assert G.parse_run_times(["7:05"]) == ["07:05"]
    assert G.parse_run_times("") == list(G.DEFAULT_RUN_TIMES)
    assert G.parse_run_times("25:00") == list(G.DEFAULT_RUN_TIMES)


def test_db_gate_without_twin_gate_is_off_and_locked(monkeypatch):
    import aot.utils as pkg
    monkeypatch.setitem(sys.modules, "aot.utils.twin_gate", None)       # import 실패 흉내
    monkeypatch.delattr(pkg, "twin_gate", raising=False)
    g = G.DbGate(G.LazyApp(lambda: pytest.fail("앱을 만들었다")))
    assert g.enabled() is False
    assert g.supported() == (False, "twin_gate_missing")


def test_db_gate_uses_real_twin_gate_contract(monkeypatch):
    """S1 의 aot.utils.twin_gate 그대로 — Misc 읽기·쓰기 두 지점만 갈아끼운다."""
    from aot.utils import twin_gate as TG
    stored = []
    misc = types.SimpleNamespace(twin_enabled=True, twin_run_times="18:10,6:10", twin_heartbeat=None)
    monkeypatch.setattr(TG, "_load_misc", lambda: misc)
    monkeypatch.setattr(TG, "_store_heartbeat", lambda data: stored.append(data) or True)
    monkeypatch.setattr(TG, "twin_supported", lambda: (True, ""))
    g = G.DbGate(G.LazyApp(lambda: pytest.fail("앱을 만들었다")))
    assert g.supported() == (True, None)
    assert g.enabled() is True
    assert g.run_times() == ["06:10", "18:10"]
    g.write_heartbeat(G.heartbeat("idle", "v1", sites=2, plots=5, last_run_at=T0, failures=1, now=T0 + 30))
    hb = stored[-1]
    assert hb == {"at": "2026-10-14T17:47:10Z", "status": "idle", "version": "v1", "sites": 2, "plots": 5,
                  "last_run_at": "2026-10-14T17:46:40Z", "failures": 1, "locked_reason": None}
    misc.twin_heartbeat = hb
    assert TG.read_heartbeat() == hb
    assert TG.heartbeat_stale(heartbeat=hb, now=TG._parse_ts(hb["at"])) is False
    monkeypatch.setattr(TG, "twin_supported", lambda: (False, TG.REASON_LOW_MEMORY))
    assert g.supported() == (False, "low_memory") and g.enabled() is False    # 플래그가 켜져도 잠금이 이긴다


def test_service_heartbeat_statuses_are_s1_vocabulary():
    assert {G.HB_STARTING, G.HB_LOCKED, G.HB_DISABLED, G.HB_IDLE, G.HB_RUNNING, G.HB_ERROR} <= \
        {"running", "idle", "locked", "error"}


def test_db_gate_retries_twin_gate_inside_app_context(monkeypatch):
    class App:
        entered = 0

        def app_context(self):
            import contextlib
            App.entered += 1
            state["ctx"] = True

            @contextlib.contextmanager
            def cm():
                yield
            return cm()

    state = {"ctx": False}

    def twin_enabled(misc=None):
        if not state["ctx"]:
            raise RuntimeError("Working outside of application context.")
        return True

    tg = types.ModuleType("aot.utils.twin_gate")
    tg.twin_enabled = twin_enabled
    monkeypatch.setitem(sys.modules, "aot.utils.twin_gate", tg)
    import aot.utils as pkg
    monkeypatch.setattr(pkg, "twin_gate", tg, raising=False)
    assert G.DbGate(G.LazyApp(App)).enabled() is True and App.entered == 1

# coding=utf-8
"""폐루프 시뮬레이터 시설 모델(sim/plant.py) — 물리 상식 시험.

제어기를 시험하는 도구가 틀리면 그 위의 모든 판정이 틀린다. 여기서는 시설이 "온실처럼"
움직이는지만 본다: 분무는 식히고 적시되 습구온도 밑으로 못 내리고, 포화 근처에서는 거의
안 먹고, 더운 외기 환기는 덥히고, 팬 환기 횟수는 풍량/체적이고, 차광은 일사 유입을,
보온커튼은 밤 열손실을 줄이고, 정상상태에서 열수지가 닫힌다.
"""
import json
import sqlite3

import pytest

from aot.utils import psychro as ps
from aot.functions.utils.env_control.sim.plant import (
    ActuatorSpec, Plant, PlantParams, facility_from_db)

T0 = 1_800_000_000.0


def _const(**kw):
    w = {'T': 25.0, 'RH': 60.0, 'solar': 0.0, 'wind': 0.0, 'wind_dir': 0.0,
         'rain': 0.0, 'co2': 420.0, 'cloud': 1.0}
    w.update(kw)
    return lambda t: dict(w)


def _quiet_params(**kw):
    """열 출입을 끈 시설 — 한 장치의 효과만 보이게."""
    p = PlantParams(U_cover=0.0, h_mass=0.0, h_ground=0.0, h_sky_mass=0.0,
                    leak_ach=0.0, leak_ach_wind=0.0, crop_cover=0.0,
                    transp_k_rad=0.0, transp_k_vpd=0.0, h_cover_in=0.0)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


FOG = ActuatorSpec('fog', 'fogger', flow_kg_s=0.05, nozzles=60, eta=0.9)
WIN = ActuatorSpec('win', 'opening', area_m2=60.0)
FAN_IN = ActuatorSpec('fin', 'intake_fan', rated_m3h=40000.0)
FAN_EX = ActuatorSpec('fex', 'exhaust_fan', rated_m3h=40000.0)


class TestFog:
    def test_cools_and_humidifies_but_not_below_wet_bulb(self):
        # 골조 열용량(air_cap_mult)을 빼야 공기만의 단열 과정이 된다.
        p = _quiet_params(air_cap_mult=1.0)
        pl = Plant(p, [FOG], T0, T=35.0, RH=30.0)
        w0 = pl.observe()['w']
        t_wb = ps.adiabatic_saturation_temperature(35.0, w0)
        pl.set_command('fog', 'value', 100.0, T0)
        pl.advance(T0 + 4 * 3600, _const(T=35.0, RH=30.0))
        o = pl.observe()
        assert o['T'] < 33.0, '분무가 식히지 않았다'
        assert o['w'] > w0 + 0.002, '분무가 적시지 않았다'
        assert min(pl.fine['T']) >= t_wb - 0.1, '습구온도 밑으로 내려갔다'
        # 같은 증발량이 냉각과 가습을 함께 만든다 — 엔탈피가 거의 보존된다.
        h0 = ps.enthalpy(35.0, w0)
        h1 = ps.enthalpy(o['T'], o['w'])
        assert abs(h1 - h0) < 0.03 * h0

    def test_near_saturation_does_almost_nothing(self):
        def evap(rh):
            pl = Plant(_quiet_params(), [FOG], T0, T=25.0, RH=rh)
            pl.set_command('fog', 'value', 100.0, T0)
            return pl.energy_terms(_const(T=25.0, RH=rh)(T0))['E_fog']
        assert evap(99.5) < 0.05 * evap(40.0)

    def test_unevaporated_water_wets_crop(self):
        wet = ActuatorSpec('fog', 'fogger', flow_kg_s=0.6, nozzles=56, eta=0.35, wetting=True)
        pl = Plant(PlantParams(), [wet], T0, T=30.0, RH=60.0)
        pl.set_command('fog', 'sec', 20.0, T0)
        pl.advance(T0 + 600, _const(T=30.0, RH=60.0))
        a = pl.acc
        assert a['fog_water_kg'] == pytest.approx(0.6 * 20.0, rel=1e-3)
        assert a['fog_unevap_kg'] > 0.6 * a['fog_water_kg']
        assert a['fog_evap_kg'] + a['fog_unevap_kg'] == pytest.approx(a['fog_water_kg'], rel=1e-3)

    def test_no_water_no_effect(self):
        p = _quiet_params(water_available=False)
        pl = Plant(p, [FOG], T0, T=35.0, RH=30.0)
        pl.set_command('fog', 'value', 100.0, T0)
        pl.advance(T0 + 3600, _const(T=35.0, RH=30.0))
        assert pl.observe()['T'] == pytest.approx(35.0, abs=0.01)
        assert pl.acc['fog_water_kg'] == 0.0


class TestVentilation:
    def test_hot_outdoor_air_heats(self):
        pl = Plant(_quiet_params(), [WIN], T0, T=25.0, RH=50.0)
        pl.set_command('win', 'value', 100.0, T0)
        pl.advance(T0 + 1800, _const(T=35.0, RH=40.0, wind=2.0))
        assert pl.observe()['T'] > 33.0

    def test_closed_window_with_no_leak_does_nothing(self):
        pl = Plant(_quiet_params(), [WIN], T0, T=25.0, RH=50.0)
        pl.advance(T0 + 1800, _const(T=35.0, RH=40.0, wind=2.0))
        assert pl.observe()['T'] == pytest.approx(25.0, abs=0.01)

    def test_balanced_fans_ach_is_flow_over_volume(self):
        p = _quiet_params()
        pl = Plant(p, [FAN_IN, FAN_EX], T0, T=25.0, RH=50.0)
        pl.set_command('fin', 'value', 100.0, T0)
        pl.set_command('fex', 'value', 100.0, T0)
        u = pl._inputs(T0, 1.0, _const()(T0))
        G, parts = pl.exchange(25.0, u)
        assert G == pytest.approx(40000.0 / 3600.0, rel=1e-6)
        ach = G * 3600.0 / p.volume_m3
        assert ach == pytest.approx(40000.0 / p.volume_m3, rel=1e-6)

    def test_exhaust_only_into_sealed_house_is_starved(self):
        p = _quiet_params(leak_area_m2=1.0)
        pl = Plant(p, [FAN_EX, WIN], T0, T=25.0, RH=50.0)
        pl.set_command('fex', 'value', 100.0, T0)
        u = pl._inputs(T0, 1.0, _const()(T0))
        G_closed, _ = pl.exchange(25.0, u)
        pl.set_command('win', 'value', 100.0, T0)
        u = pl._inputs(T0, 1.0, _const()(T0))
        _, parts = pl.exchange(25.0, u)
        assert G_closed < 0.6 * 40000.0 / 3600.0, '보충 개구가 없는데 정격 풍량이 나왔다'
        # 창을 열면 정압이 풀려 팬 원풍량은 회복되지만 일부는 창으로 단락된다.
        assert parts['fan_unb'] > G_closed
        assert parts['fan_unb'] < 40000.0 / 3600.0

    def test_rain_with_open_window_is_recorded(self):
        pl = Plant(_quiet_params(), [WIN], T0, T=25.0, RH=50.0)
        pl.set_command('win', 'value', 50.0, T0)
        pl.advance(T0 + 600, _const(rain=5.0))
        assert pl.acc['rain_open_s'] == pytest.approx(600.0)


class TestScreens:
    def test_shade_lowers_solar_gain(self):
        sh = ActuatorSpec('sh', 'shade')
        pl = Plant(PlantParams(), [sh], T0, T=25.0, RH=50.0)
        pl.set_position('sh', 100.0)
        open_ = pl.energy_terms(_const(solar=800.0, cloud=0.0)(T0))
        pl.set_position('sh', 0.0)
        closed = pl.energy_terms(_const(solar=800.0, cloud=0.0)(T0))
        assert closed['Q']['sol_air'] < 0.6 * open_['Q']['sol_air']
        assert closed['E_tr'] < open_['E_tr']

    def test_curtain_lowers_night_heat_loss(self):
        cu = ActuatorSpec('cu', 'curtain')

        def night(pos):
            pl = Plant(PlantParams(), [cu], T0, T=12.0, RH=70.0, Tm=12.0)
            pl.set_position('cu', pos)
            pl.advance(T0 + 6 * 3600, _const(T=-3.0, RH=80.0, cloud=0.0, wind=2.0))
            return pl.observe()['T']
        assert night(0.0) > night(100.0) + 1.0


class TestDevicesAndFaults:
    def test_heater_heats_and_dead_heater_does_not(self):
        h = ActuatorSpec('h', 'heater', rated_kw=50.0)
        pl = Plant(PlantParams(), [h], T0, T=10.0, RH=60.0, Tm=10.0)
        pl.set_command('h', 'value', 100.0, T0)
        pl.advance(T0 + 3600, _const(T=0.0, RH=70.0))
        warm = pl.observe()['T']
        pl2 = Plant(PlantParams(), [h], T0, T=10.0, RH=60.0, Tm=10.0)
        pl2.set_fault('h', dead=True)
        pl2.set_command('h', 'value', 100.0, T0)
        pl2.advance(T0 + 3600, _const(T=0.0, RH=70.0))
        assert warm > pl2.observe()['T'] + 3.0
        assert pl2.believed_position('h') == 100.0       # 드라이버는 켰다고 믿는다

    def test_motor_travel_and_stuck_vent(self):
        w = ActuatorSpec('w', 'opening', area_m2=50.0, travel_open_s=90.0, travel_close_s=90.0)
        pl = Plant(PlantParams(), [w], T0)
        pl.set_command('w', 'value', 100.0, T0)
        pl.advance(T0 + 45.0, _const(), dt=5.0)
        assert pl.physical_position('w') == pytest.approx(50.0, abs=0.5)
        pl.advance(T0 + 120.0, _const(), dt=5.0)
        assert pl.physical_position('w') == pytest.approx(100.0)
        pl.set_fault('w', stuck=0.0)
        pl.set_command('w', 'value', 60.0, T0 + 120.0)
        pl.advance(T0 + 400.0, _const(), dt=5.0)
        assert pl.physical_position('w') == 0.0
        assert pl.believed_position('w') == 60.0

    def test_pulse_on_seconds(self):
        f = ActuatorSpec('f', 'intake_fan', rated_m3h=36000.0)
        pl = Plant(PlantParams(), [f], T0)
        pl.set_command('f', 'sec', 120.0, T0)
        pl.advance(T0 + 600.0, _const(), dt=10.0)
        # 120 s × 10 m³/s × fan_kw_per_m3h …: 켬 시간만큼만 전력을 쓴다.
        kwh = 36000.0 * PlantParams().fan_kw_per_m3h * 120.0 / 3600.0
        assert pl.acc['fan_kwh'] == pytest.approx(kwh, rel=1e-3)

    def test_co2_injection_raises_co2(self):
        c = ActuatorSpec('c', 'co2_injector', co2_kg_h=3.0)
        pl = Plant(_quiet_params(), [c], T0, CO2=420.0)
        pl.set_command('c', 'value', 100.0, T0)
        pl.advance(T0 + 1800, _const())
        assert pl.observe()['CO2'] > 1000.0


class TestBalance:
    def test_steady_state_heat_balance_closes(self):
        pl = Plant(PlantParams(), [], T0, T=20.0, RH=60.0)
        wx = _const(T=15.0, RH=70.0, solar=300.0, cloud=0.5, wind=1.0)
        pl.advance(T0 + 72 * 3600, wx, dt=30.0)
        dg = pl.energy_terms(wx(T0))
        q = dg['Q']
        air = (q['sol_air'] + q['mass_to_air'] + q['env'] + q['vent'] + q['heat']
               + q['cool'] + q['fog'] + q['cond'] + q['light'])
        mass = (q['sol_mass'] - q['mass_to_air'] + q['latent_mass'] + q['ground']
                + q['sky_mass'] + q['water_sens'])
        scale = max(abs(v) for v in q.values())
        assert abs(air) < 0.01 * scale
        assert abs(mass) < 0.01 * scale
        o = pl.observe()
        assert 15.0 < o['T'] < 45.0, '정상상태 실내 온도가 그럴듯하지 않다'

    def test_closed_house_overheats_in_summer_sun(self):
        pl = Plant(PlantParams(), [], T0, T=30.0, RH=60.0)
        pl.advance(T0 + 12 * 3600, _const(T=35.0, RH=40.0, solar=850.0, cloud=0.0, wind=1.0),
                   dt=30.0)
        assert pl.observe()['T'] > 45.0


def _mini_db(path):
    db = sqlite3.connect(path)
    db.executescript('''
      create table geo_facility (unique_id text, name text, geometry_3d text, envelope text,
        fittings text, actuators text, bay_count int);
      create table output (unique_id text, name text);
      create table output_channel (output_id text, channel int, custom_options text);
    ''')
    geom = {'span_width_m': 8, 'eave_height_m': 2, 'ridge_height_m': 4, 'length_m': 50,
            'roof_type': 'arch', 'orientation_deg': 0}
    env = {'layers': [{'cover': 'vinyl_single', 'type': 'full'}],
           'side_vent': {'outer': {'stages': [{'height_m': 1.0}]}}}
    fittings = [
        {'kind': 'side_window', 'actuator_id': 'W', 'source': 'envelope',
         'size': {'w': 48, 'h': 1.9}, 'surface_normal': [1, 0, 0]},
        {'kind': 'irrigation_valve', 'actuator_id': 'V', 'layer_id': 'L'},
        {'kind': 'irrigation_device', 'layer_id': 'L', 'flow_lph': 40, 'orientation': 'down',
         'sub_type': 'sprinkler'},
        {'kind': 'irrigation_device', 'layer_id': 'L', 'flow_lph': 40, 'orientation': 'down',
         'sub_type': 'sprinkler'},
        {'kind': 'fan', 'actuator_id': 'F', 'fan_role': 'exhaust_fan',
         'surface_normal': [0, 0, 1]},
    ]
    acts = [{'kind': 'exhaust_fan', 'device_uuid': 'F', 'specs': {'airflow_cmh': 45000}}]
    db.execute('insert into geo_facility values (?,?,?,?,?,?,?)',
               ('FAC', '시험', json.dumps(geom), json.dumps(env), json.dumps(fittings),
                json.dumps(acts), 1))
    for oid, nm in (('W', '측창'), ('V', '분무'), ('F', '배기팬')):
        db.execute('insert into output values (?,?)', (oid, nm))
    db.execute('insert into output_channel values (?,?,?)',
               ('W', 0, json.dumps({'travel_time_open_sec': 90, 'travel_time_close_sec': 80,
                                    'last_position_pct': 0})))
    db.commit()
    db.close()


def test_facility_from_db(tmp_path):
    path = str(tmp_path / 'f.db')
    _mini_db(path)
    p, acts, info = facility_from_db(path, 'FAC')
    assert p.floor_m2 == pytest.approx(400.0)
    assert p.volume_m3 == pytest.approx(50 * (8 * 2 + 2 / 3 * 8 * 2), rel=1e-3)
    by = {a.actuator_id: a for a in acts}
    assert by['W'].kind == 'opening'
    assert by['W'].area_m2 == pytest.approx(48.0)          # 감는 높이 1.0 m — 골조 1.9 m 아님
    assert by['W'].travel_open_s == 90.0
    assert by['V'].kind == 'fogger' and by['V'].wetting
    assert by['V'].flow_kg_s == pytest.approx(80.0 / 3600.0)
    assert by['F'].kind == 'exhaust_fan' and by['F'].rated_m3h == 45000.0


CIRC = ActuatorSpec('circ', 'circulation_fan', rated_m3h=10200.0)   # 340 m² × 30 m³/h/m² = 기준 풍량


class TestCirculationFanLeafWetness:
    """순환팬이 잎 둘레 공기를 움직인다 (2026-10-12) — 젖은 잎이 더 빨리 마르고 밤에 덜 식는다.
    팬이 없으면 종전과 비트 단위로 같아야 한다(A/B 의 '팬 없는 시설 무변화')."""

    @staticmethod
    def _night(specs, hours=6.0, pool0=0.0, T=26.0, RH=92.0, **wx):
        pl = Plant(PlantParams(), specs, T0, T=T, RH=RH, Tm=T)
        pl.x[4] = pool0
        for s in specs:
            if s.kind == 'circulation_fan':
                pl.set_command(s.actuator_id, 'value', 100.0, T0)
        w = dict(T=26.0, RH=92.0, cloud=0.0, wind=0.5)
        w.update(wx)
        pl.advance(T0 + hours * 3600.0, _const(**w))
        return pl

    def test_fraction_scales_with_rated_flow_and_command(self):
        pl = Plant(PlantParams(), [CIRC], T0)
        pl.set_command('circ', 'value', 100.0, T0)
        assert pl.circ_frac(pl._inputs(T0, 1.0, _const()(T0))) == pytest.approx(1.0)
        pl.set_command('circ', 'value', 50.0, T0)
        assert pl.circ_frac(pl._inputs(T0, 1.0, _const()(T0))) == pytest.approx(0.5)
        pl.set_command('circ', 'off', None, T0)
        assert pl.circ_frac(pl._inputs(T0, 1.0, _const()(T0))) == 0.0
        big = ActuatorSpec('circ', 'circulation_fan', rated_m3h=100000.0)
        pl = Plant(PlantParams(), [big], T0)
        pl.set_command('circ', 'value', 100.0, T0)
        assert pl.circ_frac(pl._inputs(T0, 1.0, _const()(T0))) == 1.0      # 포화

    def test_no_fan_is_bit_identical_to_no_effect_parameters(self):
        a = self._night([WIN], pool0=5.0)
        p0 = PlantParams(circ_coupling=0.0, circ_leaf_g=0.0)
        b = Plant(p0, [WIN], T0, T=26.0, RH=92.0, Tm=26.0)
        b.x[4] = 5.0
        b.advance(T0 + 6 * 3600.0, _const(T=26.0, RH=92.0, cloud=0.0, wind=0.5))
        assert a.x == b.x
        assert a.acc == b.acc

    def test_wet_crop_dries_faster_with_the_fan(self):
        base = self._night([], hours=3.0, pool0=20.0, RH=60.0, T=25.0)
        fan = self._night([CIRC], hours=3.0, pool0=20.0, RH=60.0, T=25.0)
        assert base.x[4] > 0.0
        assert fan.x[4] < base.x[4], '팬이 젖은 잎을 더 빨리 말리지 않았다'
        assert fan.acc['surf_evap_kg'] > base.acc['surf_evap_kg']

    def test_fan_does_not_cool_a_mass_warmer_than_the_air(self):
        """Tm 은 잎 하나가 아니라 바닥·트레이 덩어리다 — 공기보다 따뜻한 덩어리를 팬이 식히지 않는다(덩어리 모델의 인공물 방지)."""
        def run(specs):
            pl = Plant(PlantParams(), specs, T0, T=8.0, RH=90.0, Tm=11.0)
            for s in specs:
                pl.set_command(s.actuator_id, 'value', 100.0, T0)
            pl.advance(T0 + 1800.0, _const(T=8.0, RH=90.0, cloud=1.0))
            return pl
        base, fan = run([]), run([CIRC])
        assert fan.x[3] == pytest.approx(base.x[3], abs=1e-9)
        assert fan.x[0] == pytest.approx(base.x[0], abs=1e-9)

    def test_fan_costs_power_and_only_when_running(self):
        base = self._night([], hours=1.0)
        fan = self._night([CIRC], hours=1.0)
        assert base.acc['fan_kwh'] == 0.0
        assert fan.acc['fan_kwh'] == pytest.approx(10200.0 * 3.3e-5, rel=0.05)

    def test_clear_humid_night_leaves_stay_less_wet_with_the_fan(self):
        base = self._night([], hours=8.0)
        fan = self._night([CIRC], hours=8.0)
        # 모의 수치(8 h): 젖음 28.4 → 20.9 kg · 이슬 21.4 → 11.7 kg · 젖은 분 332 → 296 — 크지 않게 잡았다.
        assert fan.acc['leaf_wet_s'] < base.acc['leaf_wet_s']
        assert fan.x[4] < 0.9 * base.x[4]
        assert fan.acc['dew_kg'] < base.acc['dew_kg']
        assert fan.x[3] > base.x[3], '팬이 잎(질량) 온도를 공기 쪽으로 끌어오지 않았다'

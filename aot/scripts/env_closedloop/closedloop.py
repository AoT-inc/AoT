# coding=utf-8
"""통합환경제어 폐루프 하네스 — 진짜 `CustomModule` 을 가짜 온실(시설 참값 모델)에 물린다.

`env-replay/gimje/replay_gimje.py`(개루프 리플레이)와 같은 원칙이다: **제어 로직은 한 줄도
다시 쓰지 않는다.** 갈아끼우는 곳은 셋뿐이다.

  1. 측정 읽기(`aot.utils.influx.get_last_measurement`, `facility_sensors` 의 같은 이름)
     — 실내 측정은 시설 상태에서, 실외 측정은 시나리오 외기에서 낸다. 센서 고장은 여기서.
  2. 데몬 RPC(`coord.control`) — `output_on/off` 가 시설 장치 위치를 바꾼다. `_dispatch`
     (어댑터·모터 게이트·불감대)는 진짜로 돈다. 장치 고장은 시설에서(명령은 받되 무효).
  3. 시계 — time.time/sleep, timekit.utc_now/now_utc, 모듈 수준 utc_now 사본,
     `_helpers_mixin.datetime.now`(시간대 미해결 폴백), `aot.utils.method.datetime.now`
     (곡선 목표의 주차).

또 influx 쓰기·`log_channels._safe_write` 는 막는다(쓸 곳이 없다).

사이클: 시각 t 에서 코디네이터가 시설 상태를 읽고 명령을 낸다 → 시설을 t+period 까지
작은 스텝(기본 10 s, 펄스 끝에서 끊음)으로 적분 → 반복. period 는 코디네이터의
`update_period`(김제 600 s).

시설 모델·시나리오·지표는 **하네스 판**을 쓴다(`run.sh` 가 `envsim/` 으로 옆에 복사한다).
시험 대상 코드 디렉터리(/app)가 바뀌어도 시설이 같아야 A/B 비교가 성립하기 때문이다.

환경변수:
  SIM_SCENARIO  시나리오 이름(필수)      SIM_VARIANT  DB 이름표(orig|fans …)
  SIM_OUT_DIR   결과 폴더(/out)          SIM_COORD    코디네이터 unique_id 앞부분
  SIM_SITE      현장 폴더(/site, 실측 외기 timeseries.json)
  SIM_HOURS     길이 덮어쓰기(h)         SIM_PERIOD   update_period 덮어쓰기(s)
  SIM_DT        시설 적분 스텝(s, 기본 10) SIM_WARMUP_H 지표에서 뺄 앞부분(h, 기본 1)
  SIM_VERIFY=1  프로필만 적재해 출력하고 끝(가상 팬 결선 확인용)
  SIM_CODE_REV  추적에 남길 코드 판 표시
  SIM_KEEP_FOREIGN=1  시설 밖 actuator_paired 출력을 떼지 않는다(기본은 뗀다 — 아래 주석)
  SIM_DLI_TARGET  구획 DLI 목표(mol/m²/d)를 준다(스냅숏에 목표가 없을 때 — 차광 '빛 지킴' 시험)
  (시나리오가 정하면) 실외 측정 가공: params.wind_avg_s / rain_accum_s, 추가 실외 센서 extra_sensors,
                  고장 outdoor_stale — 자세한 것은 README '극한 기상 시나리오'.
  SIM_VPD_BASIS   air|leaf — 가상 엽온 센서(시설 열질량 온도 Tm)를 코디네이터의 `leaf_temp_signal`
                  에 묶고 `vpd_target_basis` 를 이 값으로 둔다(`leaf_vpd`). 비우면 묶지 않는다.
"""
import datetime as _dt
import json
import os
import sys
import time as _time_mod
import traceback
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from envsim import metrics as M      # noqa: E402
from envsim import plant as P        # noqa: E402
from envsim import scenarios as S    # noqa: E402


class Clock:
    now = 0.0


_real_time = _time_mod.time


def _patched_time():
    return Clock.now if Clock.now else _real_time()


class _FakeDatetimeMeta(type(_dt.datetime)):
    """진짜 datetime 도 이 가짜의 인스턴스로 친다 — `isinstance(x, datetime.datetime)`
    검사를 쓰는 모듈(`aot.utils.method`)이 진짜 값을 받아도 분기가 어긋나지 않게."""

    def __instancecheck__(cls, inst):
        return isinstance(inst, _dt.datetime)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, _dt.datetime)


class _FakeDatetime(_dt.datetime, metaclass=_FakeDatetimeMeta):
    @classmethod
    def now(cls, tz=None):
        return _dt.datetime.fromtimestamp(Clock.now or _real_time(), tz)

    @classmethod
    def utcnow(cls):
        return _dt.datetime.utcfromtimestamp(Clock.now or _real_time())


# 측정 이름(DeviceMeasurements.measurement) → 시설/외기 키
_MEAS_KEY = {
    'temperature': 'T', 'humidity': 'RH', 'vapor_pressure_deficit': 'VPD',
    'co2': 'CO2', 'dewpoint': 'dewpoint', 'direction': 'wind_dir', 'speed': 'wind',
    'pressure': 'pressure', 'visibility': 'visibility', 'snowfall': 'snow',
    'light': 'solar', 'radiation': 'solar', 'solar_radiation': 'solar',
    'illuminance': 'lux', 'electrical_conductivity': None,
}


def _meas_key(measurement: str, unit: str):
    m = (measurement or '').lower()
    if m == 'precipitation':
        return 'rain15' if (unit or '').lower() in ('mm', 'millimeter') else 'precip_flag'
    return _MEAS_KEY.get(m)


_SIM_LEAF_DEV = 'sim-leaf-temp'   # 가상 엽온 센서(SIM_VPD_BASIS)


def _attach_extra_sensors(db_file, facility, extras):
    """시나리오가 요구한 실외 센서(예보 모델 입력 등)를 **컨테이너 DB 사본**에 붙인다.

    Input 한 행 + DeviceMeasurements 채널 + 시설 센서 피팅(실외, 순위 primary|backup)을 넣는다. 틀은
    시설의 첫 실외 센서(기상청) 행이다. 코디네이터가 이 DB 를 읽기 전에 불러야 한다. → {(장치, 채널): 키}.
    """
    import sqlite3
    import uuid
    ns = uuid.UUID('6f1d2c3a-5b4e-4f00-9a7c-0e5c1a2b3c4e')
    db = sqlite3.connect(db_file)
    db.row_factory = sqlite3.Row
    made = {}
    try:
        fac = db.execute('select fittings from geo_facility where unique_id = ?',
                         (facility,)).fetchone()
        fittings = json.loads(fac['fittings'] or '[]') or []
        tmpl = next((f for f in fittings if f.get('kind') == 'sensor'
                     and f.get('sensor_role') == 'outdoor' and f.get('input_id')), None)
        if tmpl is None:
            sys.exit('실외 센서 피팅이 없어 시나리오의 추가 센서를 붙일 수 없다')
        tin = db.execute('select * from input where unique_id = ?', (tmpl['input_id'],)).fetchone()
        tdm = db.execute('select * from device_measurements where device_id = ? '
                         'order by channel desc limit 1', (tmpl['input_id'],)).fetchone()
        icols = [c for c in tin.keys() if c != 'id']
        dcols = [c for c in tdm.keys() if c != 'id']
        for e in extras:
            tier = e.get('tier') or 'primary'
            dev = str(uuid.uuid5(ns, f"storm-{facility}-{e['device']}-{tier}"))
            row = {c: tin[c] for c in icols}
            row.update(unique_id=dev, device=e['device'], name=e.get('name') or e['device'],
                       period=600.0, max_age_s=None, custom_options='{}', is_activated=1,
                       position_y=(tin['position_y'] or 0) + 80)
            db.execute(f'insert into input ({",".join(icols)}) values ({",".join("?" * len(icols))})',
                       [row[c] for c in icols])
            chans = []
            for i, ch in enumerate(e['channels']):
                mid = str(uuid.uuid5(ns, f"{dev}-{ch['key']}"))
                r = {c: tdm[c] for c in dcols}
                r.update(unique_id=mid, name=ch.get('name') or ch['measurement'], device_id=dev,
                         measurement=ch['measurement'], unit=ch['unit'], channel=i,
                         is_enabled=1, rescaled_measurement='', rescaled_unit='',
                         conversion_id='', measurement_type='')
                db.execute(f'insert into device_measurements ({",".join(dcols)}) '
                           f'values ({",".join("?" * len(dcols))})', [r[c] for c in dcols])
                chans.append({'measurement_id': mid, 'measurement_type': ch.get('type')})
                made[(dev, mid)] = ch['key']
            fit = {'actuator_id': None, 'channel_measurements': chans,
                   'id': 'Fsim' + dev[:8], 'input_id': dev, 'kind': 'sensor',
                   'measurement_id': chans[0]['measurement_id'],
                   'measurement_type': chans[0]['measurement_type'],
                   'name': e.get('name') or e['device'], 'position': tmpl.get('position'),
                   'rotation_deg': 0, 'sensor_role': 'outdoor', 'size': tmpl.get('size'),
                   'surface_normal': None}
            if tier == 'backup':
                fit['sensor_priority'] = 'backup'
            fittings.append(fit)
        db.execute('update geo_facility set fittings = ? where unique_id = ?',
                   (json.dumps(fittings, ensure_ascii=False), facility))
        db.commit()
    finally:
        db.close()
    return made


def _iso(ts: float) -> str:
    return _dt.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def main():
    scen_name = os.environ['SIM_SCENARIO']
    variant = os.environ.get('SIM_VARIANT', 'orig')
    out_dir = os.environ.get('SIM_OUT_DIR', '/out')
    site = os.environ.get('SIM_SITE', '/site')
    coord_prefix = os.environ.get('SIM_COORD', '5a853a0c')
    plant_dt = float(os.environ.get('SIM_DT') or 10.0)
    warmup_s = float(os.environ.get('SIM_WARMUP_H') or 1.0) * 3600.0
    verify_only = os.environ.get('SIM_VERIFY') == '1'

    sc = S.get(scen_name, recorded_path=os.path.join(site, 'timeseries.json'))
    if os.environ.get('SIM_HOURS'):
        sc.hours = float(os.environ['SIM_HOURS'])
    weather = sc.weather()

    # ── 시계 고정(앱 import 전) ─────────────────────────────────────────────
    Clock.now = sc.t0
    _time_mod.time = _patched_time
    _time_mod.sleep = lambda _s: None
    import aot.utils.timekit as tk
    _orig_utc_now = tk.utc_now

    def _fake_utc_now():
        return _dt.datetime.fromtimestamp(Clock.now, _dt.timezone.utc)
    tk.utc_now = _fake_utc_now
    tk.now_utc = _fake_utc_now

    from aot.aot_flask.app import create_app
    app = create_app()
    for _m in list(sys.modules.values()):
        try:
            if getattr(_m, 'utc_now', None) is _orig_utc_now:
                _m.utc_now = _fake_utc_now
        except Exception:
            pass
    import aot.functions.custom_functions.env_coordinator_impl._helpers_mixin as hm
    hm.datetime = _FakeDatetime
    # `aot.utils.method.weeks_elapsed_at(when=None)` 이 `datetime.datetime.now(utc)` 로 '지금'
    # 을 읽는다(VPD·온도 곡선 'method' 목표의 주차). 안 고정하면 실행마다 목표가 시각만큼 흐른다.
    import types as _types
    import aot.utils.method as method_mod
    _dt_shim = _types.ModuleType('datetime')
    _dt_shim.__dict__.update({k: v for k, v in vars(_dt).items() if not k.startswith('__')})
    _dt_shim.datetime = _FakeDatetime
    method_mod.datetime = _dt_shim

    import aot.utils.influx as influx_mod
    import aot.aot_flask.geo.facility_sensors as fs_mod
    influx_mod.write_influxdb_value = lambda *a, **k: None
    influx_mod.add_measurements_influxdb = lambda *a, **k: None
    influx_mod.add_measurements_influxdb_flux = lambda *a, **k: None
    import aot.functions.utils.env_control.log_channels as lc
    lc._safe_write = lambda *a, **k: None

    from aot.config import AOT_DB_PATH

    with app.app_context():
        from aot.databases.models import CustomController, OutputChannel
        from aot.databases.models.measurement import DeviceMeasurements
        from aot.databases.utils import session_scope
        from aot.functions.custom_functions.env_coordinator import CustomModule
        from aot.aot_flask.geo.facility_integration import get_facility_integration

        func = CustomController.query.filter(
            CustomController.unique_id.like(coord_prefix + '%')).first()
        if func is None:
            sys.exit(f'코디네이터 없음: {coord_prefix}')
        COORD = func.unique_id
        facility = json.loads(func.custom_options or '{}').get('geo_facility_id')

        # ── 시설 ────────────────────────────────────────────────────────────
        db_file = AOT_DB_PATH.split('sqlite:///', 1)[-1]
        params, specs, finfo = P.facility_from_db(db_file, facility)
        pd = params.to_dict()
        pd.update(sc.plant_overrides)
        params = P.PlantParams(**pd)
        # ── 시설 밖 paired 출력 떼기(컨테이너 DB 사본에서만) ──────────────────
        # 예전 코디네이터의 actuator_paired 자동 발견은 DB 전체에서 임자 없는 paired 출력을
        # 데려왔다(개발서버 스냅숏에는 TEST 측창 등 6개). 시설에 없는 장치라 시설
        # 모델이 반응하지 않는다. 지금 코드는 시설 범위로 걸러(`_paired_outside_facility_scope`)
        # 이 떼기가 필요 없지만, 수정 전 코드 판과 A/B 를 맞추려고 기본값은 그대로 둔다.
        # 수정이 먹는지 보려면 SIM_KEEP_FOREIGN=1.
        detached = []
        if os.environ.get('SIM_KEEP_FOREIGN') != '1':
            import sqlite3 as _sq
            _db = _sq.connect(db_file)
            try:
                for oid, nm, ot in _db.execute(
                        "select unique_id, name, output_type from output "
                        "where output_type like 'actuator_paired%'").fetchall():
                    if oid not in {sp.actuator_id for sp in specs}:
                        _db.execute("update output set output_type = 'virtual_on_off_single' "
                                    "where unique_id = ?", (oid,))
                        detached.append({'id': oid, 'name': nm, 'type': ot})
                _db.commit()
            finally:
                _db.close()
            if detached:
                print(f'[폐루프] 시설 밖 paired 출력 {len(detached)}개를 사본에서 뗐다: '
                      + ', '.join(d['name'] for d in detached))
        extra_keys = {}
        if sc.extra_sensors:
            extra_keys = _attach_extra_sensors(db_file, facility, sc.extra_sensors)
            print('[폐루프] 추가 실외 센서: '
                  + ', '.join(f"{e['name']}({e.get('tier')})" for e in sc.extra_sensors))
        wx0 = weather(sc.t0)
        T0 = float(sc.init.get('T', wx0['T'] + 1.0))
        RH0 = float(sc.init.get('RH', min(95.0, wx0['RH'])))
        plant = P.Plant(params, specs, sc.t0, T=T0, RH=RH0,
                        CO2=float(sc.init.get('CO2', 450.0)))
        for sp in specs:
            plant.set_position(sp.actuator_id,
                               100.0 if sp.kind in ('shade', 'curtain') else 0.0)
        kinds_present = {sp.kind for sp in specs}

        # 장치 위치를 DB 에 싣는 대상(actuator_paired 처럼 last_position_pct 를 갖는 것)
        paired = set()
        with session_scope(AOT_DB_PATH) as sess:
            for ch in sess.query(OutputChannel).filter(OutputChannel.channel == 0).all():
                if ch.output_id in plant.specs:
                    try:
                        o = json.loads(ch.custom_options or '{}')
                    except Exception:
                        o = {}
                    if 'last_position_pct' in o:
                        paired.add(ch.output_id)
        last_written = {}

        def write_positions():
            todo = {aid: round(plant.believed_position(aid), 2) for aid in paired}
            todo = {a: v for a, v in todo.items() if last_written.get(a) != v}
            if not todo:
                return
            with session_scope(AOT_DB_PATH) as sess:
                for row in sess.query(OutputChannel).filter(
                        OutputChannel.output_id.in_(list(todo)),
                        OutputChannel.channel == 0).all():
                    try:
                        o = json.loads(row.custom_options or '{}')
                    except Exception:
                        o = {}
                    o['last_position_pct'] = todo[row.output_id]
                    o['last_target_pct'] = todo[row.output_id]
                    row.custom_options = json.dumps(o)
            last_written.update(todo)

        write_positions()

        # ── 측정 지도: 실내/실외 장치의 모든 채널 ─────────────────────────────
        integ, integ_err = get_facility_integration(facility, bypass_cache=True)
        if integ_err:
            sys.exit(f'시설 통합 적재 실패: {integ_err}')
        roles = {}
        for s in integ.get('sensors_resolved') or []:
            roles[s.get('input_uuid')] = 'indoor'
        for s in integ.get('sensors_outdoor') or []:
            roles[s.get('input_uuid')] = 'outdoor'
        meas_map = {}
        for dev, role in roles.items():
            if not dev:
                continue
            for dm in DeviceMeasurements.query.filter(DeviceMeasurements.device_id == dev).all():
                k = _meas_key(dm.measurement, dm.unit)
                if k:
                    meas_map[(dev, dm.unique_id)] = (role, k)
        for (_dev, _mid), _key in extra_keys.items():
            meas_map[(_dev, _mid)] = ('outdoor', _key)

        # ── 측정 읽기(센서 고장 포함) ─────────────────────────────────────────
        missing = defaultdict(int)
        served = {}
        frozen = {}
        stale_cache = {}

        def _fault(kind_prefix):
            for f in sc.faults:
                if f.kind.startswith(kind_prefix) and f.active(Clock.now, sc.t0):
                    return f
            return None

        def indoor_value(key, obs):
            if key == 'T':
                return obs['T']
            if key == 'RH':
                return obs['RH']
            if key == 'VPD':
                return obs['VPD']
            if key == 'CO2':
                return obs['CO2']
            if key == 'dewpoint':
                return obs['Td']
            if key == 'solar':
                return plant_light()
            return None

        def plant_light():
            w = weather(Clock.now)
            return max(0.0, w.get('solar', 0.0)) * params.tau_cover

        # 시나리오가 정하면 제어기에 나가는 실외 측정을 측정기답게 가공한다(없으면 예전 그대로).
        wind_avg = float(sc.params.get('wind_avg_s') or 0.0)
        rain_acc = float(sc.params.get('rain_accum_s') or 0.0)
        gust_max = float(sc.params.get('gust_max_s') or 0.0)

        def ext_at(ts):
            w = dict(weather(ts))
            if wind_avg > 0:       # AWS 풍속은 직전 N 초 평균이다(시설이 겪는 순간 풍속이 아니다)
                n = max(1, int(wind_avg // 60))
                w['wind'] = sum(weather(ts - 60.0 * k)['wind'] for k in range(n)) / n
            if rain_acc > 0:       # '강수15분' 은 직전 15 분 누적 mm 다
                n = max(1, int(rain_acc // 60))
                w['rain15_acc'] = (sum(weather(ts - 60.0 * k)['rain'] for k in range(n)) / n
                                   * (rain_acc / 3600.0))
            if gust_max > 0:       # 돌풍계 — 직전 N 초 동안의 1 분 돌풍 최댓값(최대순간풍속)
                n = max(1, int(gust_max // 60))
                w['gust_max'] = max(weather(ts - 60.0 * k).get('gust', 0.0) for k in range(n))
            return w

        def outdoor_value(key, w):
            if key.startswith('fc_'):
                return w.get(key)              # 예보 모델 입력 — 시설 물리와 무관한 값
            if key == 'gust':
                return w.get('gust_max', w.get('gust'))
            if key in ('T', 'RH', 'wind', 'wind_dir', 'pressure'):
                return w.get(key)
            if key == 'VPD':
                return P.ps.vpd(w['T'], P.ps.vapor_pressure(w['T'], w['RH']))
            if key == 'dewpoint':
                return P.ps.dewpoint(P.ps.vapor_pressure(w['T'], w['RH']))
            if key == 'rain15':
                if 'rain15_acc' in w:
                    return round(w['rain15_acc'], 2)
                return round(w.get('rain', 0.0) / 4.0, 2)
            if key == 'precip_flag':
                return 1.0 if w.get('rain', 0.0) > 0 else 0.0
            if key == 'visibility':
                if w.get('visibility') is not None:
                    return w['visibility']
                return 3.0 if w.get('rain', 0.0) > 0 else 20.0
            if key == 'snow':
                return 0.0
            if key == 'solar':
                return w.get('solar')
            if key == 'CO2':
                return w.get('co2')
            return None

        def fake_reader(device_id, measurement_id, max_age=None):
            if device_id == _SIM_LEAF_DEV:
                # 가상 엽온 센서 — 시설의 바닥·작물 열질량 온도(Tm). 실내 측정과 같은 시각.
                return (_iso(Clock.now - 10.0), float(plant.observe()['Tm']))
            role_key = meas_map.get((device_id, measurement_id))
            if role_key is None:
                missing[(device_id, measurement_id)] += 1
                return (None, None)
            role, key = role_key
            now = Clock.now
            if role == 'indoor':
                obs = plant.observe()
                val = indoor_value(key, obs)
                ts = now - 10.0
                f = _fault('indoor_')
                if f is not None:
                    if f.kind == 'indoor_missing':
                        return (None, None)
                    if f.kind in ('indoor_stale', 'indoor_frozen'):
                        if key not in frozen:
                            frozen[key] = (val, ts)
                        val = frozen[key][0]
                        if f.kind == 'indoor_stale':
                            ts = frozen[key][1]
                    elif f.kind == 'indoor_oor':
                        if key == (f.target or 'RH'):
                            val = float(f.value)
                        elif key == 'VPD':
                            t_ = obs['T'] if f.target != 'T' else float(f.value)
                            rh_ = obs['RH'] if f.target != 'RH' else float(f.value)
                            val = max(0.0, P.ps.svp(t_) * (1.0 - rh_ / 100.0))
                else:
                    frozen.clear()
            else:
                if _fault('outdoor_missing') is not None:
                    return (None, None)
                sf = _fault('outdoor_stale')
                if sf is not None and (not sf.target
                                       or key in {x.strip() for x in sf.target.split(',')}):
                    # 관측소 두절 — 두절 직전 표본이 값도 시각도 그대로 굳는다.
                    c = stale_cache.setdefault(id(sf), {})
                    if key not in c:
                        ts_f = ((sc.t0 + sf.start_h * 3600.0) // 300.0) * 300.0
                        c[key] = (outdoor_value(key, ext_at(ts_f)), ts_f)
                    val, ts = c[key]
                else:
                    ts = (now // 300.0) * 300.0
                    val = outdoor_value(key, ext_at(ts))
            if val is None:
                return (None, None)
            if max_age is not None and (now - ts) > float(max_age):
                return (None, None)
            served[(role, key)] = val
            return (_iso(ts), float(val))

        influx_mod.get_last_measurement = fake_reader
        fs_mod.get_last_measurement = fake_reader
        # 코디네이터 자신의 `self.get_last_measurement`(옵션으로 묶은 신호 — 엽온·물 공급·냉난방 연동)
        # 는 기반 컨트롤러 모듈이 import 해 둔 이름을 부른다 — 그것도 갈아끼운다.
        import aot.controllers.abstract_base_controller as abc_mod
        abc_mod.get_last_measurement = fake_reader

        # ── 데몬 RPC ────────────────────────────────────────────────────────
        dispatched = []

        class FakeControl:
            def output_on(self, output_id=None, output_type=None, amount=None,
                          output_channel=0, **kw):
                dispatched.append({'t': Clock.now, 'aid': output_id,
                                   'type': output_type or 'value', 'amount': amount})
                plant.set_command(output_id, output_type or 'value', amount, Clock.now)
                return 0, 'ok'

            def output_off(self, output_id=None, output_channel=0, **kw):
                dispatched.append({'t': Clock.now, 'aid': output_id,
                                   'type': 'off', 'amount': 0.0})
                plant.set_command(output_id, 'off', 0.0, Clock.now)
                return 0, 'ok'

            def __getattr__(self, item):
                return lambda *a, **k: None

        # ── 코디네이터 ─────────────────────────────────────────────────────
        Clock.now = sc.t0 - 60.0
        coord = CustomModule(func, testing=False)
        coord.control = FakeControl()
        coord._load_runtime_state()
        coord._coord_state.integral = {}
        coord._reload_profiles()
        if os.environ.get('SIM_DLI_TARGET'):
            # 시나리오 조건: 구획 프로그램의 DLI 목표(mol/m²/d). 김제 스냅숏에는 목표가 없어
            # 차광막의 '빛 지킴' 이 서지 않는다 — A/B 양쪽에 같은 값을 준다.
            _dli = float(os.environ['SIM_DLI_TARGET'])
            _orig_lpt = coord._load_plot_targets

            def _with_dli(_f=_orig_lpt):
                d = dict(_f() or {})
                d['dli'] = _dli
                return d
            coord._load_plot_targets = _with_dli
        vpd_basis = (os.environ.get('SIM_VPD_BASIS') or '').strip()
        if vpd_basis:
            # 옛 코드 판에는 이 속성이 없다 — 붙여도 읽는 곳이 없어 무해하다(A/B 기준선).
            coord.vpd_target_basis = vpd_basis
            coord.leaf_temp_signal_device_id = _SIM_LEAF_DEV
            coord.leaf_temp_signal_measurement_id = _SIM_LEAF_DEV + '-T'
        period = float(os.environ.get('SIM_PERIOD') or coord.update_period or 60.0)
        coord.update_period = period

        prof_rows = []
        adapters = getattr(coord, '_adapter_by_id', {}) or {}
        for p in coord._profiles:
            prof_rows.append({
                'actuator_id': p.actuator_id, 'kind': p.kind,
                'name': (getattr(coord, '_actuator_names', {}) or {}).get(p.actuator_id),
                'rated_m3h': (p.capacity_meta or {}).get('rated_m3h'),
                'area_m2': p.area_m2, 'azimuth_deg': getattr(p, 'azimuth_deg', None),
                'adapter': repr(adapters.get(p.actuator_id)),
                'in_plant': p.actuator_id in plant.specs})
        print('[폐루프] 코디네이터 프로필:')
        for r in prof_rows:
            print(f"  {r['kind']:14s} {str(r['name'] or '')[:20]:20s} rated_m3h={r['rated_m3h']} "
                  f"area={r['area_m2']} az={r['azimuth_deg']} adapter={r['adapter']} plant={r['in_plant']}")
        print('[폐루프] 시설 장치:')
        for sp in specs:
            print(f'  {sp.kind:14s} {sp.name[:20]:20s} area={sp.area_m2:.1f} '
                  f'rated={sp.rated_m3h:.0f} flow={sp.flow_kg_s:.3f}kg/s')
        if verify_only:
            return

        # ── 계측 ────────────────────────────────────────────────────────────
        import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cm
        rec = {}
        real_wfc = cm.write_final_commands

        def traced_wfc(uid, final_cmds, idxmap):
            fin = {}
            for aid, c in final_cmds.items():
                v = c.get('value') if isinstance(c, dict) else getattr(c, 'value', None)
                r = c.get('reason') if isinstance(c, dict) else getattr(c, 'reason', None)
                fin[aid] = [None if v is None else round(float(v), 2), r]
            rec['finals'] = fin
            return real_wfc(uid, final_cmds, idxmap)
        cm.write_final_commands = traced_wfc

        real_assess = cm.assess

        def traced_assess(*a, **k):
            res = real_assess(*a, **k)
            if k.get('trend_state') is getattr(coord, '_trend_state', None):
                sit = res[0]
                tg = sit.target or {}

                def _v(key):
                    tv = tg.get(key)
                    return (None, None) if tv is None else (tv.value, tv.tolerance)
                T_, T_tol = _v('temperature')
                RH_, RH_tol = _v('humidity')
                V_, V_tol = _v('vpd')
                rec['target'] = {'T': T_, 'T_tol': T_tol, 'RH': RH_, 'RH_tol': RH_tol,
                                 'VPD': V_, 'VPD_tol': V_tol}
                rec['modes'] = list(getattr(sit, 'modes', []) or [])
            return res
        cm.assess = traced_assess

        def wrap_instance(c):
            real_cls = c._classify_emergency

            def traced_cls(gate_result, situation):
                r = real_cls(gate_result, situation)
                rec['emergency'] = list(r) if isinstance(r, (tuple, list)) else [r, None]
                return r
            c._classify_emergency = traced_cls
            real_eval = c._pre_gate.evaluate

            def traced_eval(env, profiles, unique_id=''):
                g = real_eval(env, profiles, unique_id)
                rec['gate_mask'] = getattr(g, 'gate_mask', 0)
                rec['gate_desc'] = getattr(g, 'description', '')
                rec['gate_forced'] = {aid: (fc or {}).get('value')
                                      for aid, fc in (g.forced_commands or {}).items()}
                return g
            c._pre_gate.evaluate = traced_eval
        wrap_instance(coord)

        # ── 고장(장치) ──────────────────────────────────────────────────────
        def apply_actuator_faults():
            for f in sc.faults:
                act = f.active(Clock.now, sc.t0)
                if f.kind == 'water_off':
                    plant.p.water_available = not act
                elif f.kind in ('actuator_dead', 'actuator_stuck'):
                    cand = sorted([sp for sp in specs if sp.kind == f.target
                                   or sp.actuator_id.startswith(f.target or '~')],
                                  key=lambda s: s.name)
                    if f.kind == 'actuator_dead':
                        for sp in cand:
                            plant.set_fault(sp.actuator_id, dead=act)
                    elif cand and f.index < len(cand):
                        aid = cand[f.index].actuator_id
                        if act:
                            if plant.st[aid].stuck is None:
                                plant.set_fault(aid, stuck=f.value if f.value is not None
                                                else plant.physical_position(aid))
                        else:
                            plant.set_fault(aid, clear_stuck=True)

        # ── 루프 ────────────────────────────────────────────────────────────
        cycles = []
        n = 0
        t = sc.t0
        t_wall = _real_time()
        while t < sc.t_end - 1e-6:
            Clock.now = t
            apply_actuator_faults()
            write_positions()
            rec.clear()
            served.clear()
            exc = None
            try:
                coord._run_cycle(period)
            except Exception as e:
                exc = f'{type(e).__name__}: {e}'
                print(f'  사이클 예외 {t}: {exc}')
                traceback.print_exc()
            truth = plant.observe()
            w = weather(t)
            _vb = getattr(coord, '_last_vpd_target_basis', None)
            g = getattr(coord, '_last_guide_range', None)
            cycles.append({
                't': t,
                'sensor': {'T': served.get(('indoor', 'T')), 'RH': served.get(('indoor', 'RH')),
                           'VPD': served.get(('indoor', 'VPD'))},
                'truth': {k: round(truth[k], 3) for k in ('T', 'RH', 'VPD', 'CO2', 'Tm')},
                'ext': {k: w.get(k) for k in ('T', 'RH', 'solar', 'wind', 'gust', 'rain')},
                # 제어기가 이번 사이클에 실제로 받은 실외 값(가공·두절 반영) — 없으면 None
                'seen': {k: served.get(('outdoor', k)) for k in (
                    'T', 'RH', 'wind', 'wind_dir', 'rain15', 'precip_flag', 'solar', 'fc_rain',
                    'gust')},
                'target': rec.get('target'),
                # 사람이 정한 VPD 목표(잎 기준이면 옮기기 전)와 이번 사이클의 기준 상태.
                'vpd_set': (getattr(_vb, 'target', None) if _vb is not None
                            else (rec.get('target') or {}).get('VPD')),
                'vpd_basis': ({0: 'air', 1: 'leaf', 2: 'leaf_fallback'}.get(
                    getattr(_vb, 'state', None)) if _vb is not None else None),
                'guide': ({'T_min': g[0], 'T_max': g[1], 'RH_min': g[2], 'RH_max': g[3]}
                          if g else None),
                'finals': rec.get('finals') or {},
                'emergency': rec.get('emergency'),
                'gate_mask': rec.get('gate_mask'),
                'gate_desc': rec.get('gate_desc'),
                'gate_forced': rec.get('gate_forced'),
                'modes': rec.get('modes'),
                'believed': {aid: round(plant.believed_position(aid), 1) for aid in plant.specs},
                'phys': {aid: round(plant.physical_position(aid), 1) for aid in plant.specs},
                'acc': dict(plant.acc),
                'exc': exc,
            })
            t_next = min(t + period, sc.t_end)
            plant.advance(t_next, weather, dt=plant_dt)
            t = t_next
            n += 1
            if n % 50 == 0:
                print(f'  … {n}사이클 ({_real_time() - t_wall:.0f}s)  T={truth["T"]:.1f}')

        try:
            dli_target = (coord._plot_targets() or {}).get('dli')
        except Exception:
            dli_target = None
        meta = {
            'scenario': sc.name, 'variant': variant, 'coord': COORD, 'facility': facility,
            'dli_target': dli_target,
            'code_rev': os.environ.get('SIM_CODE_REV', ''), 't0': sc.t0, 't_end': sc.t_end,
            'warmup_s': warmup_s, 'period': period, 'plant_dt': plant_dt,
            'fine_step_s': P.Plant.TRACE_EVERY,
            'scenario_meta': sc.meta(), 'plant_params': params.to_dict(),
            'facility_info': finfo, 'actuators': [sp.to_dict() for sp in specs],
            'profiles': prof_rows, 'kinds_present': sorted(kinds_present),
            'not_applicable': [k for k in sc.requires if k not in kinds_present],
            'tz': str(getattr(coord, '_cached_tz', None)),
            'detached_outputs': detached,
            'missing': {f'{k[0][:8]}/{k[1][:8]}': v for k, v in missing.items()},
            'wall_s': round(_real_time() - t_wall, 1),
        }
        trace = {'meta': meta, 'cycles': cycles, 'fine': plant.fine,
                 'fine_pos': plant.fine_pos, 'dispatched': dispatched, 'acc': plant.acc,
                 'weather': weather.to_dict()}
        summ = M.summarize(trace)
        summ['not_applicable'] = meta['not_applicable']
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.join(out_dir, f'{sc.name}__{variant}')
        with open(base + '.trace.json', 'w') as fh:
            json.dump(trace, fh, default=str)
        with open(base + '.summary.json', 'w') as fh:
            json.dump(summ, fh, default=str, ensure_ascii=False, indent=1)
        print(f'[폐루프] {sc.name}/{variant}: {n}사이클, dispatch {len(dispatched)}건, '
              f'Tmax={summ.get("T_max")} → {base}.summary.json')
        if missing:
            print('[경고] 지도에 없는 측정 조회:', dict(list(meta['missing'].items())[:8]))


if __name__ == '__main__':
    main()

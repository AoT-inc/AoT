# coding=utf-8
"""
env_control/sim/scenarios.py — 폐루프 시뮬레이터의 외기 시나리오와 고장 주입.

시나리오 하나 = 외기 시계열(시간 격자 위 T·RH·일사·풍속·풍향·강우·CO₂·운량) +
고장 목록 + 시설 파라미터 덮어쓰기. 같은 이름·같은 씨앗이면 **언제나 같은 값**이
나온다(A/B 비교의 전제). 난수는 `random.Random(seed)` 하나만 쓴다.

시각은 KST(UTC+9) 로 적는다. 합성 시나리오는 **2027 년** 날짜를 쓴다 — 김제 DB 스냅숏
(2026-10-08)에 저장된 런타임 상태의 시각보다 뒤여야 시계가 거꾸로 가지 않는다(태양
위치는 연도와 무관하다). `recorded` 만 실측 날짜(2026-10)다. 일사는 위도·경도에서 맑은 하늘 전천일사(Haurwitz)를
구하고 운량으로 깎는다 — 제어기가 쓰는 `aot.utils.solar` 를 쓰지 않는다(독립성).

## 고장 종류 (`Fault.kind`)

센서(하네스의 측정 읽기에서 적용):
  indoor_missing   실내 값 없음 (None, None)
  indoor_stale     시작 시점 값·시각 그대로(새 점이 안 들어옴 — 나이 판정에 걸린다)
  indoor_frozen    시작 시점 값 그대로, 시각은 계속 새것(거울 장치가 멈춘 값을 되풀이)
  indoor_oor       target 채널('T'|'RH')을 value 로 바꿔 보고(예: RH 130)
  outdoor_missing  실외 값 없음
  outdoor_stale    실외 값이 시작 직전 표본 그대로 **시각도 멈춘다**(관측소 두절 — 새 점이 안 들어옴).
                   `max_age` 를 주고 읽는 경로는 값 없음으로 보고, 안 주고 읽는 경로는 낡은 값을
                   그대로 받는다(둘의 차이를 보려는 고장). target = 쉼표로 쓴 채널 키
                   ('wind,rain15,precip_flag,wind_dir' …), 비우면 실외 전부.
장치(하네스 FakeControl·시설에서 적용 — 명령은 받아들여지지만 물리 효과가 없다):
  actuator_dead    target = kind(예 'exhaust_fan') 또는 actuator_id 앞부분
  actuator_stuck   target 장치를 value % 에 고정(index 로 몇 번째인지)
  water_off        분무 물 공급 끊김
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import random
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

KST = _dt.timezone(_dt.timedelta(hours=9))
DEFAULT_LAT = 35.86
DEFAULT_LON = 126.88
GRID_S = 300.0


# ─────────────────────────────────────────────────────────────────────────────
# 태양
# ─────────────────────────────────────────────────────────────────────────────

def sun_sin_elevation(t_epoch: float, lat: float = DEFAULT_LAT,
                      lon: float = DEFAULT_LON) -> float:
    d = _dt.datetime.fromtimestamp(t_epoch, _dt.timezone.utc)
    doy = d.timetuple().tm_yday
    decl = math.radians(23.45 * math.sin(2 * math.pi * (284 + doy) / 365.0))
    B = 2 * math.pi * (doy - 81) / 364.0
    eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
    utc_h = d.hour + d.minute / 60.0 + d.second / 3600.0
    solar_time = utc_h + lon / 15.0 + eot / 60.0
    H = math.radians(15.0 * (solar_time - 12.0))
    la = math.radians(lat)
    return math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(H)


def clear_sky_ghi(t_epoch: float, lat: float = DEFAULT_LAT,
                  lon: float = DEFAULT_LON) -> float:
    """맑은 하늘 수평 전천일사 [W/m²] (Haurwitz)."""
    s = sun_sin_elevation(t_epoch, lat, lon)
    if s <= 0.0:
        return 0.0
    return 1098.0 * s * math.exp(-0.057 / s)


def cloud_factor(cloud: float) -> float:
    """운량 → 일사 감쇠(Kasten–Czeplak)."""
    c = max(0.0, min(1.0, cloud))
    return 1.0 - 0.75 * c ** 3.4


# ─────────────────────────────────────────────────────────────────────────────
# 시계열
# ─────────────────────────────────────────────────────────────────────────────

WX_KEYS = ('T', 'RH', 'solar', 'wind', 'wind_dir', 'rain', 'co2', 'cloud', 'pressure')


class WeatherSeries:
    """시간 격자 위 외기. 호출하면 선형 보간(풍향·강우는 직전 표본)."""

    def __init__(self, t: List[float], data: Dict[str, List[float]]):
        self.t = list(t)
        self.data = {k: list(v) for k, v in data.items()}

    def __call__(self, t: float) -> Dict[str, float]:
        ts = self.t
        if t <= ts[0]:
            i, f = 0, 0.0
        elif t >= ts[-1]:
            i, f = len(ts) - 2, 1.0
        else:
            lo, hi = 0, len(ts) - 1
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if ts[mid] <= t:
                    lo = mid
                else:
                    hi = mid
            i = lo
            f = (t - ts[i]) / (ts[i + 1] - ts[i])
        out = {}
        for k, v in self.data.items():
            if k in ('wind_dir', 'rain'):
                out[k] = v[i] if f < 1.0 else v[i + 1]
            else:
                out[k] = v[i] + (v[i + 1] - v[i]) * f
        return out

    def to_dict(self) -> dict:
        return {'t': self.t, **self.data}


@dataclass
class Fault:
    kind: str
    start_h: float = 0.0
    end_h: Optional[float] = None
    target: Optional[str] = None
    value: Optional[float] = None
    index: int = 0

    def active(self, t: float, t0: float) -> bool:
        h = (t - t0) / 3600.0
        return h >= self.start_h and (self.end_h is None or h < self.end_h)


@dataclass
class Scenario:
    name: str
    description: str
    start: str                                  # 'YYYY-MM-DD HH:MM' KST
    hours: float
    build: Callable[['Scenario'], WeatherSeries] = field(repr=False, default=None)
    faults: List[Fault] = field(default_factory=list)
    plant_overrides: Dict[str, float] = field(default_factory=dict)
    init: Dict[str, float] = field(default_factory=dict)   # 실내 초기 T·RH·CO2
    requires: List[str] = field(default_factory=list)      # 의미가 있으려면 필요한 kind
    seed: int = 1
    lat: float = DEFAULT_LAT
    lon: float = DEFAULT_LON
    params: Dict[str, object] = field(default_factory=dict)
    # 시설에 덧붙이는 실외 센서(하네스가 컨테이너 DB 사본에 넣는다) — 예보 모델 입력 같은 것.
    # 항목: {'device': 'OPEN_METEO_FORECAST', 'name': …, 'tier': 'primary'|'backup',
    #        'channels': [{'measurement': 'rain', 'unit': 'mm', 'key': 'fc_rain', 'type': 'rain'}]}
    extra_sensors: List[Dict[str, object]] = field(default_factory=list)

    @property
    def t0(self) -> float:
        d = _dt.datetime.strptime(self.start, '%Y-%m-%d %H:%M').replace(tzinfo=KST)
        return d.timestamp()

    @property
    def t_end(self) -> float:
        return self.t0 + self.hours * 3600.0

    def weather(self) -> WeatherSeries:
        return self.build(self)

    def meta(self) -> dict:
        return {'name': self.name, 'description': self.description, 'start': self.start,
                'hours': self.hours, 'faults': [asdict(f) for f in self.faults],
                'plant_overrides': dict(self.plant_overrides), 'init': dict(self.init),
                'requires': list(self.requires), 'seed': self.seed,
                'extra_sensors': [dict(e) for e in self.extra_sensors],
                'params': {k: v for k, v in self.params.items()
                           if isinstance(v, (int, float, str, list, tuple, dict))}}


# ─────────────────────────────────────────────────────────────────────────────
# 합성 외기 생성기
# ─────────────────────────────────────────────────────────────────────────────

def _diurnal_frac(local_h: float, h_min: float = 5.5, h_max: float = 14.5) -> float:
    """0(최저) ~ 1(최고). 최저 h_min, 최고 h_max 인 비대칭 코사인."""
    h = local_h % 24.0
    if h_min <= h <= h_max:
        return 0.5 * (1.0 - math.cos(math.pi * (h - h_min) / (h_max - h_min)))
    span = 24.0 - (h_max - h_min)
    k = (h - h_max) % 24.0
    return 0.5 * (1.0 + math.cos(math.pi * k / span))


def synth(sc: Scenario) -> WeatherSeries:
    """`sc.params` 로 하루 주기 외기를 만든다.

    params:
      T_min, T_max          °C (리스트면 날짜별)
      RH_day, RH_night      %  (최고·최저 기온 때의 RH)
      cloud                 0..1 (리스트면 날짜별)
      wind_day, wind_night  m/s,  wind_dir deg,  gust (난류 세기 m/s)
      rain                  [(시작h, 끝h, mm/h), ...] — 시나리오 시작 기준
      rain_cooling          강우 중 기온 하강 K
      co2                   ppm
    """
    p = sc.params
    rnd = random.Random(sc.seed)
    t0 = sc.t0
    n = int(sc.hours * 3600.0 / GRID_S) + 1
    ts = [t0 + i * GRID_S for i in range(n)]
    data = {k: [] for k in WX_KEYS}

    def _day(v, day):
        if isinstance(v, (list, tuple)):
            return v[min(day, len(v) - 1)]
        return v

    d0 = _dt.datetime.fromtimestamp(t0, KST).date()
    gust = 0.0
    wdir = float(p.get('wind_dir', 225.0))
    rains = list(p.get('rain', []))
    for t in ts:
        local = _dt.datetime.fromtimestamp(t, KST)
        h_rel = (t - t0) / 3600.0
        day = (local.date() - d0).days
        lh = local.hour + local.minute / 60.0
        fr = _diurnal_frac(lh)
        Tmin = float(_day(p.get('T_min', 10.0), day))
        Tmax = float(_day(p.get('T_max', 22.0), day))
        T = Tmin + (Tmax - Tmin) * fr
        RH = float(p.get('RH_night', 85.0)) + (float(p.get('RH_day', 45.0))
                                               - float(p.get('RH_night', 85.0))) * fr
        cloud = float(_day(p.get('cloud', 0.2), day))
        rain = 0.0
        for (a, b, mmh) in rains:
            if a <= h_rel < b:
                rain = float(mmh)
        if rain > 0:
            cloud = max(cloud, 0.95)
            T -= float(p.get('rain_cooling', 2.0))
            RH = max(RH, 92.0)
        gust = 0.85 * gust + rnd.gauss(0.0, float(p.get('gust', 0.4)))
        wind = float(p.get('wind_night', 1.0)) + (float(p.get('wind_day', 3.0))
                                                  - float(p.get('wind_night', 1.0))) * fr
        wind = max(0.0, wind + gust)
        wdir = (wdir + rnd.gauss(0.0, 4.0)) % 360.0
        solar = clear_sky_ghi(t, sc.lat, sc.lon) * cloud_factor(cloud)
        data['T'].append(round(T, 3))
        data['RH'].append(round(max(5.0, min(100.0, RH)), 2))
        data['solar'].append(round(solar, 1))
        data['wind'].append(round(wind, 2))
        data['wind_dir'].append(round(wdir, 1))
        data['rain'].append(rain)
        data['co2'].append(float(p.get('co2', 420.0)))
        data['cloud'].append(cloud)
        data['pressure'].append(1010.0)
    return WeatherSeries(ts, data)


def recorded(sc: Scenario) -> WeatherSeries:
    """김제 기상청(KMA) 실측 외기(`env-replay/gimje/timeseries.json`).

    일사 채널이 없어 맑은 하늘 일사 × 운량으로 만든다. 운량은 강수가 있으면 0.95,
    아니면 습도에서 어림(RH 90 % 이상 0.8, 그 밖 0.3). 강우는 '강수15분'(mm/15분)
    → mm/h(×4).
    """
    path = sc.params.get('path')
    raw = json.load(open(path))
    by_meas = {}
    for s in raw['series']:
        if s.get('role') != 'outdoor':
            continue
        by_meas[s['measurement_id'][:8]] = sorted(s.get('points') or [])
    chan = sc.params.get('channels') or {
        'T': 'f9b6779d', 'RH': 'd5584725', 'wind_dir': '36bc6b74',
        'wind': '8b035f93', 'rain15': '22dfd1eb', 'pressure': '79641066'}
    n = int(sc.hours * 3600.0 / GRID_S) + 1
    ts = [sc.t0 + i * GRID_S for i in range(n)]

    def at(key, t, default):
        pts = by_meas.get(chan.get(key, ''), [])
        if not pts:
            return default
        lo, hi = 0, len(pts) - 1
        if t <= pts[0][0]:
            return pts[0][1]
        if t >= pts[-1][0]:
            return pts[-1][1]
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if pts[mid][0] <= t:
                lo = mid
            else:
                hi = mid
        if key in ('wind_dir', 'rain15'):
            return pts[lo][1]
        a, b = pts[lo], pts[hi]
        return a[1] + (b[1] - a[1]) * (t - a[0]) / max(1e-9, b[0] - a[0])

    data = {k: [] for k in WX_KEYS}
    for t in ts:
        T = float(at('T', t, 15.0))
        RH = float(at('RH', t, 70.0))
        r15 = float(at('rain15', t, 0.0) or 0.0)
        rain = r15 * 4.0
        cloud = 0.95 if rain > 0 else (0.8 if RH >= 90 else 0.3)
        data['T'].append(round(T, 2))
        data['RH'].append(round(RH, 1))
        data['solar'].append(round(clear_sky_ghi(t, sc.lat, sc.lon) * cloud_factor(cloud), 1))
        data['wind'].append(float(at('wind', t, 1.0) or 0.0))
        data['wind_dir'].append(float(at('wind_dir', t, 0.0) or 0.0))
        data['rain'].append(rain)
        data['co2'].append(420.0)
        data['cloud'].append(cloud)
        data['pressure'].append(float(at('pressure', t, 1010.0) or 1010.0))
    return WeatherSeries(ts, data)


# ─────────────────────────────────────────────────────────────────────────────
# 등록부
# ─────────────────────────────────────────────────────────────────────────────

_BASES = {
    'normal': dict(start='2027-04-20 04:00', hours=48, params=dict(
        T_min=8.0, T_max=22.0, RH_day=40.0, RH_night=88.0, cloud=0.2,
        wind_day=3.0, wind_night=1.0, wind_dir=250.0)),
    'warm': dict(start='2027-05-20 04:00', hours=30, params=dict(
        T_min=16.0, T_max=29.0, RH_day=40.0, RH_night=85.0, cloud=0.15,
        wind_day=2.5, wind_night=0.8, wind_dir=230.0)),
    'hot_dry': dict(start='2027-07-25 04:00', hours=48, params=dict(
        T_min=26.0, T_max=35.0, RH_day=32.0, RH_night=58.0, cloud=0.05,
        wind_day=2.5, wind_night=0.8, wind_dir=200.0)),
    'hot_humid': dict(start='2027-08-05 04:00', hours=48, params=dict(
        T_min=26.0, T_max=32.0, RH_day=78.0, RH_night=95.0, cloud=0.4,
        wind_day=2.0, wind_night=0.6, wind_dir=180.0)),
    'extreme': dict(start='2027-08-10 04:00', hours=36, params=dict(
        T_min=28.0, T_max=36.0, RH_day=38.0, RH_night=65.0, cloud=0.0,
        wind_day=1.2, wind_night=0.4, wind_dir=200.0, gust=0.2)),
    'humid_night': dict(start='2027-10-15 12:00', hours=36, params=dict(
        T_min=9.0, T_max=21.0, RH_day=60.0, RH_night=97.0, cloud=0.0,
        wind_day=1.5, wind_night=0.2, wind_dir=20.0, gust=0.15)),
    # 김제 2026-10-13 낮의 꼴(과습 열림 시험, 2026-10-14): 닫혀 있던 집이 RH 90 % 대로 시작하고(init), 외기는
    # 실내와 거의 같은 온도(19~22 °C)에 이슬점이 3~4 °C 낮다 — 열면 습기가 빠지는 조건.
    'humid_mild_day': dict(start='2027-10-15 11:00', hours=8, params=dict(
        T_min=17.0, T_max=21.5, RH_day=70.0, RH_night=85.0, cloud=0.9,
        wind_day=1.5, wind_night=0.4, wind_dir=20.0)),
    'cold_night': dict(start='2027-01-15 12:00', hours=36, params=dict(
        T_min=-5.0, T_max=2.0, RH_day=45.0, RH_night=80.0, cloud=0.0,
        wind_day=3.0, wind_night=1.5, wind_dir=320.0)),
    # 맑은 겨울 새벽 — 밤새 친 보온커튼을 일출에 어떻게 걷는가(아침 램프)와 밤 결로(커튼 틈).
    'cold_humid_dawn': dict(start='2027-02-10 16:00', hours=26, params=dict(
        T_min=-2.0, T_max=8.0, RH_day=60.0, RH_night=95.0, cloud=0.0,
        wind_day=1.5, wind_night=0.5, wind_dir=320.0, gust=0.2)),
    'rain_heat': dict(start='2027-07-20 04:00', hours=48, params=dict(
        T_min=27.0, T_max=35.0, RH_day=55.0, RH_night=85.0, cloud=0.2,
        wind_day=3.0, wind_night=1.0, wind_dir=220.0,
        rain=[(9.0, 11.0, 6.0), (31.0, 33.5, 8.0)], rain_cooling=1.0)),
    # 폭염 게이트(외기 ≥ 45 °C) 를 일부러 세운다 — 비 + 폭염 동시 경로 시험용(합성).
    # 맑고 건조한 가을(2026-10-14 김제 꼴) — 실내 센서 두절 시험의 바탕.
    'clear_dry_autumn': dict(start='2027-10-14 04:00', hours=24, params=dict(
        T_min=7.0, T_max=20.0, RH_day=25.0, RH_night=80.0, cloud=0.05,
        wind_day=2.0, wind_night=0.6, wind_dir=320.0)),
    'rain_heat_gate': dict(start='2027-07-20 04:00', hours=30, params=dict(
        T_min=33.0, T_max=47.0, RH_day=30.0, RH_night=60.0, cloud=0.1,
        wind_day=3.0, wind_night=1.0, wind_dir=220.0,
        rain=[(9.0, 11.0, 6.0)], rain_cooling=0.0)),
}


def _mk(name, base, desc, faults=None, overrides=None, requires=None, **kw):
    b = _BASES[base]
    params = dict(b['params'])
    params.update(kw.pop('params', {}))
    return Scenario(name=name, description=desc, start=kw.pop('start', b['start']),
                    hours=kw.pop('hours', b['hours']), build=synth,
                    faults=list(faults or []), plant_overrides=dict(overrides or {}),
                    requires=list(requires or []), params=params, **kw)


def _registry(recorded_path: Optional[str] = None) -> Dict[str, Scenario]:
    S = {}
    S['normal'] = _mk('normal', 'normal', '봄날(8~22 °C, 맑음) 이틀')
    S['hot_dry'] = _mk('hot_dry', 'hot_dry', '고온건조(외기 26~35 °C, 낮 RH 30~40 %)')
    S['hot_humid'] = _mk('hot_humid', 'hot_humid', '고온다습(외기 26~32 °C, RH 78~95 %)')
    # 운량 0.85 → 맑은 하늘의 약 0.57(Kasten–Czeplak) — "구름 0.6" 은 투과 비율로 읽었다.
    # 더운데 빛이 모자라는 날: 차광막은 빛을 지켜야 한다(DLI).
    S['hot_dry_overcast'] = _mk('hot_dry_overcast', 'hot_dry',
                                '고온건조 + 흐림(운량 0.85 — 일사 맑은 날의 약 0.57)',
                                params={'cloud': 0.85})
    S['extreme_tunnel'] = _mk(
        'extreme_tunnel', 'extreme',
        '극한 고온(외기 ~36 °C, 강일사, 약풍) + 작은 개구 능력(유효 면적 10 %) — '
        '조치 없으면 실내 50 °C 이상', overrides={'opening_area_scale': 0.1})
    S['extreme_tunnel_nowater'] = _mk(
        'extreme_tunnel_nowater', 'extreme', 'extreme_tunnel + 분무 물 공급 끊김',
        faults=[Fault('water_off')], overrides={'opening_area_scale': 0.1})
    S['humid_night'] = _mk('humid_night', 'humid_night',
                           '가을 습한 밤(맑은 밤 복사냉각, RH 97 %) — 결로 위험')
    S['humid_mild_day'] = _mk('humid_mild_day', 'humid_mild_day',
                              '흐리고 온화한 습한 낮(19~22 °C, RH 70 %)에 RH 91 % 로 닫혀 있던 집 — 외기가 실내와 거의 '
                              '같은 온도이고 이슬점이 3~4 °C 낮다(김제 2026-10-13 꼴)',
                              init={'T': 21.0, 'RH': 91.0}, overrides={'opening_area_scale': 3.0})
    S['cold_night'] = _mk('cold_night', 'cold_night', '한파 밤(−5~+2 °C)',
                          overrides={'T_ground': 8.0}, init={'T': 10.0, 'RH': 70.0})
    # 밤 결로 틈을 실제로 세우는 밤: 따뜻하고 습한 저녁 뒤 흐리고 바람 없는 밤. 맑은 밤은 이 시설
    # 모델에서 피복이 하늘로 식어 결로가 실내 습기를 빼 이슬점 여유가 2 °C 아래로 안 내려간다
    # (humid_night 최저 2.25 °C) — 흐린 밤이라야 여유가 0.5 °C 대까지 간다.
    S['humid_gap_night'] = _mk('humid_gap_night', 'humid_night',
                               '따뜻·습한 저녁 + 흐리고 고요한 밤(16~24 °C, 밤 RH 99 %, 운량 0.7) — '
                               '닫힌 보온커튼 아래 이슬점 여유 2 °C 미만',
                               params={'T_min': 16.0, 'T_max': 24.0, 'RH_day': 90.0,
                                       'RH_night': 99.0, 'cloud': 0.7, 'wind_night': 0.2},
                               init={'T': 22.0, 'RH': 92.0}, hours=30)
    S['cold_humid_dawn'] = _mk('cold_humid_dawn', 'cold_humid_dawn',
                               '맑은 겨울 새벽(−2~8 °C, 밤 RH 95 %) — 밤 결로와 일출의 커튼 걷기',
                               overrides={'T_ground': 8.0}, init={'T': 12.0, 'RH': 80.0})
    S['rain_heat'] = _mk('rain_heat', 'rain_heat',
                         '폭염 중 소나기(외기 27~35 °C, 강우 6~8 mm/h 두 번)')
    S['rain_heat_gate'] = _mk(
        'rain_heat_gate', 'rain_heat_gate',
        '합성: 외기 47 °C(폭염 게이트 발동) 중 강우 — safety_gates HEAT 가 RAIN 폐쇄를 '
        '덮어쓰는지 시험')
    # 센서 고장 — 따뜻한 날 낮(10~16시)에 건다.
    S['sensor_indoor_missing'] = _mk(
        'sensor_indoor_missing', 'warm', '실내 센서 값 없음 10~16시',
        faults=[Fault('indoor_missing', 6.0, 12.0)])
    S['sensor_indoor_stale'] = _mk(
        'sensor_indoor_stale', 'warm', '실내 센서 새 값 끊김(시각도 멈춤) 10~16시',
        faults=[Fault('indoor_stale', 6.0, 12.0)])
    S['sensor_indoor_frozen'] = _mk(
        'sensor_indoor_frozen', 'warm', '실내 센서 값이 멈춘 채 새 시각으로 계속 옴 10~16시',
        faults=[Fault('indoor_frozen', 6.0, 12.0)])
    S['sensor_indoor_oor'] = _mk(
        'sensor_indoor_oor', 'warm', '실내 습도 130 % 보고 10~16시',
        faults=[Fault('indoor_oor', 6.0, 12.0, target='RH', value=130.0)])
    S['sensor_outdoor_missing'] = _mk(
        'sensor_outdoor_missing', 'warm', '실외 기상 값 없음 09~17시',
        faults=[Fault('outdoor_missing', 5.0, 13.0)])
    # 맑고 건조한 가을 낮 실내 두절(2026-10-14 김제 육묘장3 꼴: 07:29 실내 미러가 모두 끊겼고 09~13시 맑음·외기 19 °C·
    # RH 25 % 인데 측창 0 %, 근거 21). 밤에 닫힌 창을 '제자리' 가 낮까지 끌고 가는가 · 해를 보고 정한 작은 하한(근거 60)이
    # 서는가. 고장은 미러가 멈춘 꼴(`indoor_stale` — 새 점이 안 들어온다).
    S['sensor_indoor_blind_day'] = _mk(
        'sensor_indoor_blind_day', 'clear_dry_autumn',
        '맑고 건조한 가을 낮(7~20 °C, 낮 RH 25 %) 실내 센서 두절 08~13시',
        faults=[Fault('indoor_stale', 4.0, 9.0)])
    # 같은 날 두절이 해 질 녘을 넘는다(13~21시) — 해가 진 뒤 그 하한만큼 열린 창을 단계로 닫는가.
    S['sensor_indoor_blind_dusk'] = _mk(
        'sensor_indoor_blind_dusk', 'clear_dry_autumn',
        '맑고 건조한 가을 낮(7~20 °C, 낮 RH 25 %) 실내 센서 두절 13~21시(해 질 녘을 넘김)',
        faults=[Fault('indoor_stale', 9.0, 17.0)])
    # 장치 고장 — 명령은 받지만 효과 없음.
    S['act_fan_dead'] = _mk('act_fan_dead', 'hot_dry', '배기팬 고장(명령 수락, 무효)',
                            faults=[Fault('actuator_dead', 0.0, None, target='exhaust_fan')],
                            requires=['exhaust_fan'], hours=30)
    S['act_fog_dead'] = _mk('act_fog_dead', 'hot_dry', '분무기 고장(명령 수락, 무효)',
                            faults=[Fault('actuator_dead', 0.0, None, target='fogger')],
                            requires=['fogger'], hours=30)
    S['act_vent_stuck'] = _mk('act_vent_stuck', 'hot_dry', '측창 하나가 닫힌 채 고착(08시~)',
                              faults=[Fault('actuator_stuck', 4.0, None, target='opening',
                                            value=0.0, index=0)],
                              requires=['opening'], hours=30)
    S['act_heater_dead'] = _mk('act_heater_dead', 'cold_night', '난방기 고장(명령 수락, 무효)',
                               faults=[Fault('actuator_dead', 0.0, None, target='heater')],
                               requires=['heater'], init={'T': 10.0, 'RH': 70.0},
                               overrides={'T_ground': 8.0})
    S['act_cooler_dead'] = _mk('act_cooler_dead', 'hot_dry', '냉방기 고장(명령 수락, 무효)',
                               faults=[Fault('actuator_dead', 0.0, None, target='cooler')],
                               requires=['cooler'], hours=30)
    _storm_registry(S)
    rp = recorded_path or '/site/timeseries.json'
    S['recorded'] = Scenario(
        name='recorded', description='김제 기상청 실측 외기 10-05 23시 ~ 10-08 22시 (70.5 h)',
        start='2026-10-05 23:15', hours=70.5, build=recorded, params={'path': rp})
    return S


# ─────────────────────────────────────────────────────────────────────────────
# 극한 기상 묶음(`storm`) — 외기 시계열 생성은 storm.py
# ─────────────────────────────────────────────────────────────────────────────

# 하네스가 제어기에 내는 측정을 측정기답게 가공하는 설정(기존 시나리오에는 없다 — 결과가 안 바뀐다).
#   wind_avg_s     풍속을 직전 N 초 평균으로(KMA AWS 는 10 분 평균)
#   rain_accum_s   `강수15분` 을 직전 N 초 누적으로(mm)
_METER = {'wind_avg_s': 600, 'rain_accum_s': 900}

STORM = ['typhoon', 'squall_heat', 'heatwave_tropical_night', 'foehn_dry_wind',
         'cold_snap_frost', 'fog_morning_overcast', 'rain_gauge_vs_forecast',
         'rain_gauge_vs_forecast_primary', 'sensor_storm_outage', 'sensor_outage_night']


def _storm_registry(S: Dict[str, Scenario]) -> None:
    from . import storm as W        # 늦게 읽는다 — storm 이 이 모듈을 import 한다
    S['typhoon'] = Scenario(
        name='typhoon', start='2027-09-05 14:00', hours=48, build=W.build_typhoon, seed=11,
        description='태풍 통과 48 h(서해안, 위험반원): 기압 1004→958 hPa, 풍속 4→26 m/s(돌풍 ~34), '
                    '풍향 동→남동→남→남서→서→북서로 회전, 호우 띠 10~50 mm/h, RH ~95~99 %, 일사 3~10 %; '
                    '9/7 아침 개어 덥고 습한 맑은 날(33 °C)',
        params=dict(_METER), init={'T': 29.0, 'RH': 70.0})
    S['squall_heat'] = Scenario(
        name='squall_heat', start='2027-08-02 06:00', hours=34, build=W.build_squall, seed=12,
        description='폭염 오후(34.8 °C) 16:10 열대류 스콜: 돌풍전선(풍속 1→16 m/s, 풍향 SW→NNW), '
                    '20 분에 15 K 하강, 30 분 호우(최대 ~60 mm/h), 17:30 이후 다시 해; 이튿날 맑고 덥다',
        params=dict(_METER, wind_avg_s=300), init={'T': 26.0, 'RH': 80.0})
    S['heatwave_tropical_night'] = Scenario(
        name='heatwave_tropical_night', start='2027-08-06 04:00', hours=72,
        build=W.build_heatwave, seed=13,
        description='폭염 3 일(최고 36→37.5→38 °C) + 열대야(밤 최저 27.2~28.4 °C, 밤 RH 90 % 이상), 약풍',
        params=dict(_METER), init={'T': 29.0, 'RH': 85.0})
    S['foehn_dry_wind'] = Scenario(
        name='foehn_dry_wind', start='2027-06-02 06:00', hours=36, build=W.build_foehn, seed=14,
        description='푄(높새) 건조열풍: 시작 2.5 h 에 자리잡아 낮 30 °C·RH 15~20 %·풍속 ~10 m/s 정속(ENE), '
                    '강일사, 밤에도 24 °C·RH 20 %대',
        params=dict(_METER), init={'T': 22.0, 'RH': 60.0})
    S['cold_snap_frost'] = Scenario(
        name='cold_snap_frost', start='2027-04-10 08:00', hours=36, build=W.build_frost, seed=15,
        description='늦서리: 맑은 낮 18 °C → 바람 없는 맑은 밤 복사냉각으로 −4 °C(새벽) → 이튿날 아침 쾌청',
        params=dict(_METER), plant_overrides={'T_ground': 10.0}, init={'T': 11.0, 'RH': 55.0})
    S['fog_morning_overcast'] = Scenario(
        name='fog_morning_overcast', start='2027-10-18 21:00', hours=30, build=W.build_fog, seed=16,
        description='짙은 아침 안개: 02시에 끼어 11시까지 RH 100 %·일사 맑은 날의 10 %·시정 120 m, '
                    '11시에 갑자기 걷혀 강한 햇볕(낮 21 °C)',
        params=dict(_METER), init={'T': 15.0, 'RH': 70.0})
    # 예보 모델 입력(Open-Meteo)이 실외 센서로 묶여 있고, 실측 강우계(KMA)는 0 을 낸다.
    _fc = {'device': 'OPEN_METEO_FORECAST', 'name': 'Open-Meteo 예보(시뮬)',
           'channels': [{'measurement': 'rain', 'unit': 'mm', 'key': 'fc_rain', 'type': 'rain'}]}
    S['rain_gauge_vs_forecast'] = Scenario(
        name='rain_gauge_vs_forecast', start='2027-08-14 05:00', hours=30,
        build=W.build_forecast_rain, seed=17,
        description='덥고 맑은 날(34.5 °C). 실측 강우계 0 mm, 예보 모델(백업 순위 센서)이 낮 12~17시 '
                    '0.5~1.8 mm/h 를 낸다 — 제어기가 모델 강수를 비로 읽으면 한낮에 창을 닫는다',
        params=dict(_METER), init={'T': 27.0, 'RH': 75.0},
        extra_sensors=[dict(_fc, tier='backup')])
    S['rain_gauge_vs_forecast_primary'] = Scenario(
        name='rain_gauge_vs_forecast_primary', start='2027-08-14 05:00', hours=30,
        build=W.build_forecast_rain, seed=17,
        description='위와 같되 예보 모델 센서를 순위 표시 없이(= 메인) 묶은 설치 — 강우계 0 과 모델 값이 '
                    '같은 순위라 평균된다',
        params=dict(_METER), init={'T': 27.0, 'RH': 75.0},
        extra_sensors=[dict(_fc, tier='primary')])
    # 태풍 + 실외 관측소 두절. 첫 두절(h 4~6, 18~20시)은 직전 값이 온화한 채로(풍속 ~6 m/s·비 없음) 굳고
    # 그 사이 첫 강우 띠(최대 8 mm/h)가 들어온다 → 오래된 '평온' 은 여는 근거가 아니다(그리고 열려 있던
    # 창을 닫을 근거도 없다). 둘째 두절(h 19~21)은 최대풍 한복판 — 오래된 '위험' 은 닫는 근거로 남아야
    # 한다(규칙 A).
    S['sensor_storm_outage'] = Scenario(
        name='sensor_storm_outage', start='2027-09-05 14:00', hours=48, build=W.build_typhoon,
        seed=11,
        description='typhoon + 실외 관측소가 두 번 끊김: h 4~6(비 막 시작·직전 값 온화, 창 열려 있음) 와 h 19~21'
                    '(최대풍 한복판) 각 2 시간 — 규칙 A(낡은 강우·풍속은 닫는 근거로는 쓰고 여는 근거로는 안 쓴다)',
        params=dict(_METER), init={'T': 29.0, 'RH': 70.0},
        faults=[Fault('outdoor_stale', 4.0, 6.0), Fault('outdoor_stale', 19.0, 21.0)])
    # 습한 밤 + 관측소 두절 + 자정 이슬비(2026-10-12 최종 회귀 §5-4, 김제 10/10 22:30~01:30). 하드 습도 상한이 야간 파킹을
    # 풀어 연 창을 두절 30 분 뒤부터 단계로 닫는가(근거 58) — 비(00:00~)는 두절 중이라 제어기가 볼 수 없다.
    S['sensor_outage_night'] = Scenario(
        name='sensor_outage_night', start='2027-10-10 12:00', hours=24,
        build=W.build_humid_outage_night, seed=18,
        description='흐리고 고요한 습한 가을 밤(바깥 16~23 °C, RH 80~93 %) — 닫힌 집 RH 90~95 % 로 습도 상한이 '
                    '야간 파킹을 풀어 창이 열린 채 22:30~01:30 실외 관측소 두절, 00:00 부터 이슬비 0.6~1.5 mm/h',
        params=dict(_METER), init={'T': 21.0, 'RH': 88.0},
        faults=[Fault('outdoor_stale', W.NO_OUTAGE_H[0], W.NO_OUTAGE_H[1])])
    # 돌풍 채널이 있는 설치(2026-10-10) — 같은 외기에 실외 돌풍 센서(measurement 'gust', 종류 'wind_gust')를
    # 하나 더 묶는다. 값은 직전 `gust_max_s` 초의 1 분 돌풍 최댓값(AWS '최대순간풍속' 꼴). 강풍 게이트의
    # 돌풍 단계(`safety_gates.classify_wind`)를 시험한다 — 돌풍을 모르는 옛 코드 판은 이 채널을 읽지 않는다.
    _gust = {'device': 'SENSECAP_WEATHER', 'name': '돌풍계(시뮬)',
             'channels': [{'measurement': 'gust', 'unit': 'm_s', 'key': 'gust',
                           'type': 'wind_gust'}]}
    for base in ('foehn_dry_wind', 'squall_heat'):
        b = S[base]
        S[base + '_gust'] = Scenario(
            name=base + '_gust', start=b.start, hours=b.hours, build=b.build, seed=b.seed,
            description=b.description + ' — 돌풍계(10 분 최대 돌풍)를 실외 센서로 더 묶음',
            params=dict(b.params, gust_max_s=600), init=dict(b.init),
            extra_sensors=[dict(_gust, tier='primary')])


# 시나리오 묶음 이름 → 목록. run.sh 는 첫 인자부터 이 이름이면 펼친다.
GROUP_NAMES = ('baseline', 'storm', 'all')


def group(name: str, recorded_path: Optional[str] = None) -> List[str]:
    if name == 'baseline':
        return list(BASELINE)
    if name == 'storm':
        return list(STORM)
    if name == 'all':
        return names(recorded_path)
    raise KeyError(f'unknown group {name!r}; one of {list(GROUP_NAMES)}')


def names(recorded_path: Optional[str] = None) -> List[str]:
    return list(_registry(recorded_path).keys())


def get(name: str, recorded_path: Optional[str] = None) -> Scenario:
    reg = _registry(recorded_path)
    if name not in reg:
        raise KeyError(f'unknown scenario {name!r}; one of {sorted(reg)}')
    return reg[name]


# 기본 묶음 — 김제(개구부 2 + 분무 1, ±가상 팬)에서 의미 있는 것.
BASELINE = [
    'normal', 'hot_dry', 'hot_humid', 'extreme_tunnel', 'extreme_tunnel_nowater',
    'humid_night', 'cold_night', 'rain_heat', 'rain_heat_gate', 'recorded',
    'sensor_indoor_missing', 'sensor_indoor_stale', 'sensor_indoor_frozen',
    'sensor_indoor_oor', 'sensor_outdoor_missing',
    'sensor_indoor_blind_day', 'sensor_indoor_blind_dusk',
    'act_fan_dead', 'act_fog_dead', 'act_vent_stuck',
]

__all__ = ['Scenario', 'Fault', 'WeatherSeries', 'synth', 'recorded', 'get', 'names', 'group',
           'BASELINE', 'STORM', 'GROUP_NAMES', 'clear_sky_ghi', 'sun_sin_elevation', 'KST']

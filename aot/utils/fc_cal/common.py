# coding=utf-8
"""예보 현장 보정 — 공통 상수·매개변수·시각 도우미·물리식 (예보·트윈 데이터 관리 D4).

설계: AoT_dev/plans/2026-10-25_twin_data_management_design.md §4. 이 모듈은 DB·Influx·Flask 를 모른다
(순수 계산). 보정이 다루는 변수는 두 종류다.

- 시간별(`kind='h'`): T 기온 · RH 습도 · WS 풍속 · SOL 일사 · RAIN 강수 (L0 `fc_hourly` 의 중립 변수 이름)
- 일별(`kind='d'`): TMAX · TMIN · RAIN (L0 `fc_daily`)

풍향·운량·강수확률·ET0 는 비교할 현장 관측이 없거나(POP·운량) 보정이 뜻이 없어(풍향) 다루지 않는다.
"""
import math
from collections import namedtuple
from dataclasses import dataclass, replace
from datetime import datetime, timezone

KIND_H, KIND_D = 'h', 'd'
HOURLY_VARS = ('T', 'RH', 'WS', 'SOL', 'RAIN')
DAILY_VARS = ('TMAX', 'TMIN', 'RAIN')
VARS = {KIND_H: HOURLY_VARS, KIND_D: DAILY_VARS}

# 리드대: 층 하나가 채택·되돌림의 단위다(설계 §4.1·§4.3).
BANDS_H = ('0-6', '6-12', '12-24', '24-48')
BANDS_D = ('0', '1', '2-3', '4-7')
BANDS = {KIND_H: BANDS_H, KIND_D: BANDS_D}

# 상태 — `fc_calibration.status`
ST_ADOPTED = 'adopted'          # 규칙을 통과해 기본값으로 쓴다
ST_FORCED = 'forced'            # 대지 설정이 '항상 켬' — 성적과 무관하게 쓴다
ST_REVERTED = 'reverted'        # 채택했다가 최근 성적이 나빠져 원본으로 되돌렸다
ST_CANDIDATE = 'candidate'      # 계수는 있으나 아직 원본보다 낫다는 근거가 모자라다(원본 사용)
ST_FEW = 'few_samples'          # 표본·기간이 모자라 계수도 못 만든다(원본 사용)
ST_NO_OBS = 'no_obs'            # 비교할 현장 관측이 없다(원본 사용)
ST_NO_FC = 'no_forecast'        # 대지에 지정된 예보 출처가 없거나 L0 발표본이 없다
ST_OFF = 'off'                  # 대지 설정이 '끔'
ST_DEFERRED = 'deferred'        # 시간 제한을 넘겨 오늘은 건너뛰었다(이전 상태 유지)
USED_STATES = (ST_ADOPTED, ST_FORCED)
STATUS_CODE = {ST_ADOPTED: 1, ST_FORCED: 2, ST_REVERTED: 3, ST_CANDIDATE: 4, ST_FEW: 5, ST_NO_OBS: 6,
               ST_NO_FC: 7, ST_OFF: 8, ST_DEFERRED: 9}

DAY_S = 86400.0
HOUR_S = 3600.0

# fc_cal_score 채널 번호(번호는 바꾸지 않고 추가만 한다)
SCORE_CHANNELS = ('n', 'mae_raw', 'mae_cal', 'rmse_raw', 'rmse_cal', 'bias_raw', 'bias_cal',
                  'brier_raw', 'brier_cal', 'pod', 'far', 'skill', 'status', 'ci_lo', 'ci_hi',
                  'recent_skill', 'days')


@dataclass(frozen=True)
class Params:
    """보정·검증 매개변수. 기본값이 설계 §4 의 값이다. 저사양은 `reduced()` 로 줄인다."""
    half_life_days: float = 14.0        # 지수 가중 평균 반감기
    shrink_k: float = 10.0              # 0 쪽 수축 n_eff/(n_eff+k)
    rain_shrink_k: float = 30.0         # 비 양 비율은 더 강하게 수축
    min_n_h: int = 30                   # 층(시간대·계절) 최소 표본
    min_n_d: int = 10                   # 일별은 하루 한 점이라 낮다
    min_days: int = 14                  # 채택에 필요한 평가 일수
    min_eval_n_h: int = 100             # 채택에 필요한 평가 표본(전진 검증에서 맞힌 쌍)
    min_eval_n_d: int = 14
    train_min_days: int = 7             # 첫 검증 시점 전에 필요한 학습 일수
    step_days: int = 1                  # 검증 시점 간격(일)
    window_days: int = 60               # 읽는 이력 창
    bootstrap: int = 300                # 일 단위 블록 부트스트랩 횟수. 0 이면 표준오차 방식
    z_strict: float = 2.33              # 부트스트랩이 없을 때 하한 z(더 엄격)
    ci_pct: float = 5.0                 # 부트스트랩 하한 백분위(한쪽 95 %)
    revert_days: int = 14               # 되돌림을 판단하는 최근 기간
    cooldown_days: int = 7              # 되돌린 뒤 다시 채택하기까지
    min_rain_events_h: int = 20         # 비는 사건 수가 모자라면 판정하지 않는다(시간별: 비 온 시간)
    min_rain_events_d: int = 8          # (일별: 비 온 날)
    rain_thr_h: float = 0.1             # 발생 문턱(mm/h)
    rain_thr_d: float = 1.0             # (mm/day)
    rain_event_mm: float = 1.0          # POD·FAR 문턱
    rain_p_cut: float = 0.15            # 보정 발생 확률이 이보다 낮은 예보 비는 0 으로 둔다
    rain_wet_min: int = 30              # 양 분위 맞춤에 필요한 비 온 쌍 수
    time_budget_s: float = 60.0         # 대지·변수마다 시간 제한
    reduced_mode: bool = False

    def min_n(self, kind):
        return self.min_n_d if kind == KIND_D else self.min_n_h

    def min_eval_n(self, kind):
        return self.min_eval_n_d if kind == KIND_D else self.min_eval_n_h

    def rain_thr(self, kind):
        return self.rain_thr_d if kind == KIND_D else self.rain_thr_h

    def min_rain_events(self, kind):
        return self.min_rain_events_d if kind == KIND_D else self.min_rain_events_h

    def reduced(self):
        """저사양(파이): 창 30일, 부트스트랩 없음(단순 표준오차 + 더 엄격한 문턱), 이틀에 한 번 검증 시점."""
        return replace(self, window_days=30, bootstrap=0, step_days=2, reduced_mode=True)


# 한 쌍 — t: 대상 시각(시간별은 정시 epoch, 일별은 대상일 00:00 UTC epoch), lead: 시간(시)/일,
# fc·ob: 예보값과 관측값, aux: 변수별 곁가지(RH: (예보 기온, 관측 기온) · RAIN: 강수확률 0~1 또는 None).
Pair = namedtuple('Pair', 't lead fc ob aux')


def band_of(kind, lead):
    lead = int(lead)
    if kind == KIND_D:
        return '0' if lead <= 0 else '1' if lead == 1 else '2-3' if lead <= 3 else '4-7'
    return '0-6' if lead < 6 else '6-12' if lead < 12 else '12-24' if lead < 24 else '24-48'


def season_of(month):
    return 'DJF' if month in (12, 1, 2) else 'MAM' if month in (3, 4, 5) else 'JJA' if month in (6, 7, 8) else 'SON'


def tod_of(hour):
    return 'day' if 6 <= hour < 18 else 'night'


class Ctx:
    """대지 맥락 — 시간대·위치와 현지 시각 계산(메모)."""

    def __init__(self, tz='UTC', lat=None, lon=None):
        self.tz_name = tz or 'UTC'
        self.lat, self.lon = lat, lon
        try:
            from zoneinfo import ZoneInfo
            self._tz = ZoneInfo(self.tz_name)
        except Exception:                                   # noqa: BLE001
            self._tz = timezone.utc
        self._memo = {}

    def local(self, t):
        """시간별 대상 시각 → (현지 날짜 번호, 현지 시, 월). 날짜 번호 = 현지 날짜의 date.toordinal()."""
        key = int(t // HOUR_S)
        got = self._memo.get(key)
        if got is None:
            d = datetime.fromtimestamp(key * HOUR_S, timezone.utc).astimezone(self._tz)
            got = (d.date().toordinal(), d.hour, d.month)
            self._memo[key] = got
        return got

    def local_end(self, t):
        """창이 끝나는 정시 `t` 의 창이 속한 현지 시간(= `t` 직전 1초) — 일 집계용."""
        return self.local(t - 1.0)

    @staticmethod
    def day_of(t):
        """일별 대상일(00:00 UTC epoch) → (날짜 번호, 월)."""
        d = datetime.fromtimestamp(t, timezone.utc)
        return d.date().toordinal(), d.month

    def stratum(self, kind, t):
        """한 쌍의 층 열쇠들 — 가장 잘게 → 거칠게. 시간별 `tod|계절` → `tod` → ''. 일별 `계절` → ''."""
        if kind == KIND_D:
            _o, month = self.day_of(t)
            return [season_of(month), '']
        _o, hour, month = self.local(t)
        tod = tod_of(hour)
        return ['%s|%s' % (tod, season_of(month)), tod, '']

    def day_key(self, kind, t):
        """일 단위 블록(부트스트랩·최근 기간) 열쇠 = 현지 날짜 번호."""
        return self.day_of(t)[0] if kind == KIND_D else self.local(t)[0]


# ── 물리식 ────────────────────────────────────────────────────────────────

def dew_point_c(t_c, rh):
    """이슬점(°C, Magnus). RH 는 1~100 으로 제한한다."""
    rh = min(100.0, max(1.0, float(rh)))
    g = math.log(rh / 100.0) + 17.62 * t_c / (243.12 + t_c)
    return 243.12 * g / (17.62 - g)


def rh_from_dew(t_c, td_c):
    """기온·이슬점 → 상대습도(%, 0~100)."""
    es = lambda x: math.exp(17.62 * x / (243.12 + x))
    return min(100.0, max(0.0, 100.0 * es(td_c) / es(t_c)))


def solar_elevation_deg(lat, lon, epoch):
    """태양 고도(°) — NOAA 근사. 맑은 하늘 일사의 재료다."""
    d = datetime.fromtimestamp(epoch, timezone.utc)
    n = d.timetuple().tm_yday + (d.hour + d.minute / 60.0) / 24.0
    b = math.radians(360.0 / 364.0 * (n - 81.0))
    eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)         # 분
    decl = math.radians(23.45) * math.sin(math.radians(360.0 / 365.0 * (284.0 + n)))
    solar_h = d.hour + d.minute / 60.0 + d.second / 3600.0 + lon / 15.0 + eot / 60.0
    ha = math.radians(15.0 * (solar_h - 12.0))
    la = math.radians(lat)
    s = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def clear_sky_ghi(lat, lon, epoch):
    """맑은 하늘 전천 일사(W/m², Haurwitz). 고도가 0 이하면 0."""
    cosz = math.sin(math.radians(solar_elevation_deg(lat, lon, epoch)))
    if cosz <= 0.0:
        return 0.0
    return 1098.0 * cosz * math.exp(-0.059 / cosz)


def age_weight(now, t, half_life_days):
    """지수 가중 — 반감기마다 절반."""
    age_d = max(0.0, (now - t) / DAY_S)
    return 0.5 ** (age_d / half_life_days)

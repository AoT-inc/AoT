# coding=utf-8
"""device_link_status.py — 장치의 통신 품질·배터리 상태 해석.

지도 위젯의 장치 모달(입력/출력/장치 마커)이 배터리 아이콘과 신호 막대를 그리기
위해 쓰는 단일 진입점이다. 세 가지를 한다:

1. **출처 해석** — 어떤 장치의 어느 채널이 이 장치의 배터리/RSSI/SNR 인가.
   Input 은 보통 자기 자신이지만, LoRaWAN Output(`on_off_chirpstack`)은 배터리도
   RSSI 도 갖고 있지 않다 — 같은 DevEUI 를 가진 하트비트 Input
   (`chirpstack_rak3172_valve_hb`) 또는 Function(`lorawan_mode_manager`)이 그
   값을 들고 있다. 그래서 EUI 로 짝을 찾는다.
2. **환산** — 배터리는 장치마다 %/전압(V)/전압(mV)/bool 로 제각각 들어온다.
   화면에 숫자 하나를 찍으려면 % 로 정규화해야 한다.
3. **등급** — RSSI/SNR 을 막대 0~3 단계로 합친다.

판정 기준(전압 곡선·신호 등급)은 아래 "판정 기준" 구획 한 곳에 모여 있다.
숫자를 고칠 일이 생기면 거기만 보면 되고, 왜 그 값인지도 거기 적혀 있다.
"""

import logging
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# 링크/배터리 측정의 최대 유효 수명(초).
# 환경 센서용 DEFAULT_MAX_AGE_S(300초)를 그대로 쓰면 안 된다 — LoRaWAN 하트비트는
# 주기가 길게는 30~60분이라 정상 노드가 상시 stale 로 보인다. 초과해도 값은 주되
# stale 플래그를 세워 배지를 흐리게 그린다.
LINK_MAX_AGE_S: int = 3600

# custom_options 에서 EUI 를 담고 있는 키들. 드라이버마다 이름이 다르다:
#   on_off_chirpstack(Output)            → dev_eui
#   chirpstack_rak3172_valve_hb(Input)   → device_eui
#   chirpstack_MQTT_jmespath(Input)      → device_euis (쉼표 구분 복수)
#   lorawan_mode_manager(Function)       → dev_eui
_EUI_OPTION_KEYS = ('dev_eui', 'device_eui', 'device_euis')

# ═══════════════════════════════════════════════════════════════════════════
# 판정 기준 — **보수적으로** 잡는다
#
# 이 숫자들의 목적은 계측이 아니라 **환기**다. 다만 환기와 불안 조장은 다르다 —
# 멀쩡히 돌아가는 장치가 늘 "20%", "약함" 으로 보이면 사용자는 배지를 곧 무시하게
# 되고, 그때부터 배지는 아무 일도 못 한다. 그래서 세 가지 원칙을 따른다:
#
#   ① **이론 범위가 아니라 실사용 범위.** 1S 리튬 데이터시트는 3.0~4.2V 지만
#      실제 운용 구간은 훨씬 좁다. 태양광 충전 노드는 3.9V 를 넘기면 사실상
#      만충으로 봐도 되고(4.2V 는 부하 없는 순간에만 잠깐 닿는다), 3.5V 아래로
#      떨어지면 송신이 불안해진다. 그 **실측 구간**을 0~100 에 매핑한다.
#   ② **정상은 정상으로 보여야 한다.** 현장에서 가장 신호가 약한 노드조차
#      "설치된 것들 중 낮은 편"일 뿐 고장이 아닌 경우가 대부분이다. 최저 등급
#      (1막대)은 실제로 여유가 바닥난 링크에만 준다 — 남발하면 경고가 아니라
#      배경 소음이 된다.
#   ③ **배터리는 정책보다 먼저 운다.** lorawan_mode_manager 의
#      vbat_critical(11.40) / vbat_low(11.70)은 데몬이 **행동**하는 지점이다.
#      배지가 그 지점에서야 0% 가 되면 예고가 아니라 통보다. 배터리 곡선의 0% 는
#      그보다 위에 둔다. (초안은 두 값을 같은 점에 놓았다가 이 이유로 분리했다.)
#      링크에는 이 원칙을 적용하지 않는다 — ②가 우선이고, 정책의 link_rssi_min /
#      link_snr_min 은 vbat 을 모를 때만 쓰이는 좁은 보조 경로다.
#
# 조정할 일이 생기면 **여기만** 고치면 된다. 테스트가 이 원칙들을 값이 아니라
# 관계로 검증하므로(정책 상수를 직접 읽어 대조), 정책 쪽이 바뀌면 여기가 깨진다.
# ═══════════════════════════════════════════════════════════════════════════

# ── 신호 등급 임계값 ────────────────────────────────────────────────────────
# SNR 이 함께 오면 LoRaWAN 으로 본다. SNR 없이 dBm 만 오는 장치(WiFi 플러그 등)는
# 같은 숫자라도 의미가 전혀 다르다 — -90 dBm 은 LoRa 에선 멀쩡하고 WiFi 에선 불통
# 직전이다. 그래서 표를 나눈다.
#
# 1막대는 **실제로 여유가 바닥난** 링크에만 준다(원칙 ②).
# 하한 근거는 복조 한계다: LoRa 는 SF12 에서 SNR -20 dB, SF7 에서 -7.5 dB 까지
# 복조된다. SNR -13 은 아직 SF 여유가 남은 축이고, 그 아래부터 재전송이 는다.
#
# 구분점은 **koat 김제 현장 24개 노드 실측**(2026-08-04)으로 잡았다:
#   AoT-C 밸브 10대   RSSI -61~-90,  SNR  8.5~13.75   (전부 여유 있음)
#   온습도 9대        RSSI -89~-114, SNR -8.75~13.5
#   토양온습도 5대    RSSI -73~-98,  SNR  8.5~13.5
# 현장 최약체는 온습도_1(-114 dBm / -8.75 dB) 하나뿐이고, 나머지 23대는 전부
# 여유가 있다. 그 하나만 2막대로 떨어지고 **1막대는 아무도 없게** 잡았다 —
# 사용자 판단대로 "설치된 것 중 낮은 편"이지 고장이 아니기 때문이다.
# 다음으로 약한 온습도_2(-106 dBm / +8 dB)는 SNR 이 넉넉하므로 3막대로 둔다.
_LORA_RSSI_STRONG, _LORA_SNR_STRONG = -110.0, -5.0   # 정상 — 손댈 것 없음
_LORA_RSSI_OK,     _LORA_SNR_OK     = -120.0, -13.0  # 동작하나 여유가 줄었음
# WiFi 는 -70 dBm 부터 재전송이 늘고 -85 근처에서 사실상 끊긴다.
_WIFI_RSSI_STRONG, _WIFI_RSSI_OK    = -67.0, -82.0

# ── 배터리 환산 곡선 (전압 → %), 화학 종류별 ────────────────────────────────
# 전부 구간선형이다. 어느 화학이든 방전 곡선의 중간 구간은 평평해서 전압으로 잔량을
# 정확히 맞히는 것 자체가 불가능하다 — 맞히려 들지 말고 "찼다/쓸 만하다/비었다"를
# 틀리지 않게 하는 데 집중한다. 종류는 device_measurements.battery_type 으로 지정.
#
# **전압만으로는 화학을 알 수 없다.** 납산 12V 와 인산철 4S 는 운용 전압대가 겹치는데
# 곡선 모양은 사실상 반대다:
#     납산    12.70=100 / 12.00=50 / 11.40=0
#     인산철  13.40=100 / 13.00=20 / 12.00=0   ← 13V 대가 거의 평평
# 하나로 처리하면 한쪽이 크게 틀린다(납산 곡선에 인산철을 넣으면 실사용 구간이 전부
# 100% 로 뭉개지고, 반대면 납산 만충이 40% 로 보인다). 전압 이력으로 자동 추정하는
# 안도 검토했으나 인산철이 깊게 방전되면 납산 구간과 겹친다 — **정확도가 가장 필요한
# 순간에 정확히 틀린다.** 그래서 사람이 지정하게 한다(2026-08-04 사용자 결정).
BATTERY_TYPES: Dict[str, Tuple[Tuple[float, float], ...]] = {
    # 1S 리튬이온 — 실사용 3.00~3.90V (0.9V 창). 창을 좁히면 안 되는 이유는
    # 측정 자체의 오차 때문이다(이 dict 아래 주석 참조).
    'liion_1s':   ((3.00, 0.0), (3.90, 100.0)),
    # 인산철(LiFePO4) 4S — 12.00V 방전 종지, 13.40V 만충.
    # 12.80V 무릎을 명시적으로 꺾는다. 이걸 빼고 12.00~13.00 을 한 직선으로 두면
    # 12.80(≈10%)이 20% 로 읽혀, 데몬이 절전(13.00)→초절전(12.80)으로 두 단계
    # 내려가는 동안 배지는 25%→20% 로 5%p 밖에 안 움직인다 — 화면이 상황이
    # 나빠지는 것을 못 보여준다. 무릎 아래는 실제로 전압이 급락하는 구간이다.
    'lifepo4_4s': ((12.00, 0.0), (12.80, 10.0), (13.00, 25.0),
                   (13.20, 70.0), (13.40, 100.0)),
    # 납산 12V — 무부하 기준. 50% 이하 상시 운용은 수명을 급격히 깎으므로
    # 11.40(=lorawan_mode_manager vbat_critical) 을 0 으로 둔다.
    'lead_12v':   ((11.40, 0.0), (11.80, 25.0), (12.00, 50.0), (12.70, 100.0)),
}

# 1S 리튬 곡선의 창(3.00~3.90V)이 넓은 이유 — **측정 오차가 창보다 컸기 때문이다.**
#   상한 3.90: 실제로 충전해 보면 3.9V 를 넘어서면 사실상 만충이다. 4.10~4.20 은
#     충전 직후 무부하 순간에만 잠깐 닿는 값이라, 그걸 100% 로 잡으면 정상 만충
#     노드가 늘 80% 대로 보인다 — 없는 문제를 만든다.
#   하한 3.00: 리튬의 방전 종지(이 아래는 과방전이라 실제로 손대야 하는 지점).
#     3.50 으로 좁게 잡았다가 넓혔다. RAK3172 EVB 는 배터리를 PB3 ADC 로 직접 읽고
#     `BAT_MV_PER_COUNT` 가 **개체별 1점 보정** 값이다(보정한 개체에서 게인오차
#     1.9% 관측). 3.7V 에서 ±2~3% 면 ±70~110mV 인데, 창이 0.4V(3.5~3.9)면 오차
#     하나로 표시가 수십 %p 흔들린다. 실제로 koat 현장 9대가 3.43~3.79V 로 흩어져
#     있었고, 그중 상당 부분은 잔량 차이가 아니라 미보정 게인차로 보인다.

# 자동 추정 — battery_type 이 비어 있을 때 전압 범위로 종류를 고른다.
# 12V 대는 화학을 알 수 없으므로 **납산**으로 가정한다: 인산철을 납산 곡선에 넣으면
# 실사용 구간(12.8~13.4V)이 전부 100% 로 뭉개져 배지가 아무 정보도 못 주지만,
# 반대(납산을 인산철 곡선에)면 멀쩡한 만충 배터리가 40% 로 보여 없는 문제를 만든다.
# 둘 다 틀리는 길이라면 **거짓 경보를 내지 않는 쪽**으로 틀린다.
_AUTO_RANGES: Tuple[Tuple[float, float, str], ...] = (
    (2.8, 4.4, 'liion_1s'),
    (9.0, 15.5, 'lead_12v'),
)


# ─────────────────────────────────────────────────────────────────────────────
# 환산 / 등급 (순수 함수 — DB·Influx 접근 없음, 테스트 대상)
# ─────────────────────────────────────────────────────────────────────────────
def battery_percent(value: Optional[float], unit: Optional[str],
                    battery_type: Optional[str] = None) -> Optional[float]:
    """배터리 측정값을 0~100 % 로 환산한다. 환산 불가면 None.

    battery_type 은 `device_measurements.battery_type`(BATTERY_TYPES 의 키).
    비어 있거나 모르는 값이면 전압 범위로 자동 추정한다(_AUTO_RANGES).

    None 을 돌려주는 것은 실패가 아니라 "이 값은 퍼센트로 말할 수 없다"는 정직한
    답이다 — 호출부는 숫자 없이 아이콘만 그리고 원값을 툴팁에 넣는다. 모르는 것을
    억지로 0~100 에 욱여넣으면 화면이 조용히 거짓말을 한다.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None

    u = (unit or '').strip().lower()

    if u in ('percent', '%'):
        return max(0.0, min(100.0, v))
    if u == 'decimal':
        return max(0.0, min(100.0, v * 100.0))
    if u == 'bool':
        return 100.0 if v else 0.0
    if u == 'mv':
        v = v / 1000.0
        u = 'v'
    if u != 'v':
        return None

    # 지정된 종류가 있으면 전압 범위를 따지지 않는다 — 사람이 아는 것이 추정보다 낫다.
    points = BATTERY_TYPES.get((battery_type or '').strip())
    if points:
        return _interpolate(v, points)

    for lo, hi, type_key in _AUTO_RANGES:
        if lo <= v <= hi:
            return _interpolate(v, BATTERY_TYPES[type_key])
    return None


def _interpolate(v: float, points: Tuple[Tuple[float, float], ...]) -> float:
    """(x, y) 오름차순 꺾은점 위에서 구간선형 보간. 양 끝은 clamp."""
    if v <= points[0][0]:
        return points[0][1]
    if v >= points[-1][0]:
        return points[-1][1]
    for i in range(1, len(points)):
        x0, y0 = points[i - 1]
        x1, y1 = points[i]
        if v <= x1:
            span = x1 - x0
            return y0 if span <= 0 else y0 + (y1 - y0) * (v - x0) / span
    return points[-1][1]


def link_level(rssi: Optional[float], snr: Optional[float],
               comm_fault: bool = False, stale: bool = False) -> int:
    """RSSI/SNR → 막대 수 0~3 (0=무응답/판정불가, 1=약함, 2=중간, 3=강함).

    두 값이 서로 다른 등급을 가리키면 **낮은 쪽**을 쓴다 — 링크는 둘 다 좋아야
    좋은 것이지, 하나만 좋으면 되는 게 아니다.
    """
    if comm_fault or stale:
        return 0
    if rssi is None and snr is None:
        return 0

    levels: List[int] = []
    if snr is not None:
        # SNR 이 있으면 LoRaWAN 으로 본다.
        if rssi is not None:
            if rssi >= _LORA_RSSI_STRONG:
                levels.append(3)
            elif rssi >= _LORA_RSSI_OK:
                levels.append(2)
            else:
                levels.append(1)
        if snr >= _LORA_SNR_STRONG:
            levels.append(3)
        elif snr >= _LORA_SNR_OK:
            levels.append(2)
        else:
            levels.append(1)
    elif rssi is not None:
        if rssi >= _WIFI_RSSI_STRONG:
            levels.append(3)
        elif rssi >= _WIFI_RSSI_OK:
            levels.append(2)
        else:
            levels.append(1)

    return min(levels) if levels else 0


# ─────────────────────────────────────────────────────────────────────────────
# 출처 해석
# ─────────────────────────────────────────────────────────────────────────────
def normalize_eui(raw) -> str:
    """DevEUI 표기 흔들림을 흡수한다(대소문자, ':'/'-' 구분자, 공백)."""
    return (str(raw or '').strip().lower()
            .replace(':', '').replace('-', '').replace(' ', ''))


def _device_euis(unique_id: str) -> Set[str]:
    """장치(Input/Output/Function)의 custom_options 에서 EUI 집합을 뽑는다."""
    from aot.databases.models import Input, Output
    from aot.databases.models.controller import CustomController
    from aot.utils.system_pi import parse_custom_option_values

    row = None
    for model in (Input, Output, CustomController):
        try:
            row = model.query.filter(model.unique_id == unique_id).first()
        except Exception:
            row = None
        if row is not None:
            break
    if row is None:
        return set()

    try:
        opts = parse_custom_option_values(row) or {}
    except Exception as exc:
        logger.debug('[LinkStatus] custom_options 파싱 실패 %s: %s', unique_id, exc)
        return set()
    # parse_custom_option_values 는 단일 controller 를 넘겨도 {uuid: {...}} 로 감싼다.
    if unique_id in opts and isinstance(opts.get(unique_id), dict):
        opts = opts[unique_id]

    euis: Set[str] = set()
    for key in _EUI_OPTION_KEYS:
        raw = opts.get(key)
        if not raw:
            continue
        for part in str(raw).split(','):
            norm = normalize_eui(part)
            if norm:
                euis.add(norm)
    return euis


def _meta_channels(unique_id: str) -> Dict[str, dict]:
    """장치가 가진 메타 채널을 {key: {measurement_id, unit}} 로 반환한다.

    key 판정은 라벨·그래프와 **같은** 함수(channel_label_meta)를 쓴다. 여기서
    별도 판정을 하면 같은 채널이 배지에선 배터리인데 그래프에선 아닌 상태가 된다.
    """
    from aot.aot_flask.geo.facility_sensors import (META_CHANNEL_KEYS,
                                                    channel_meta_for_dm)
    from aot.databases.models.measurement import DeviceMeasurements

    found: Dict[str, dict] = {}
    try:
        rows = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == unique_id).all()
    except Exception as exc:
        logger.debug('[LinkStatus] 측정 조회 실패 %s: %s', unique_id, exc)
        return found

    for dm in rows:
        # channel_meta_for_dm 은 conversion 이 걸린 채널의 **변환 단위**를 준다.
        # 원 단위를 쓰면 mV 를 V 로 읽는 식의 1000배 오차가 난다.
        meta = channel_meta_for_dm(dm)
        key = meta.get('key')
        if key in META_CHANNEL_KEYS and key not in found:
            found[key] = {'measurement_id': meta.get('measurement_id') or dm.unique_id,
                          'unit': meta.get('unit') or '',
                          # 배터리 화학 종류(사용자 지정). ''(빈 값)=자동 추정.
                          'battery_type': (getattr(dm, 'battery_type', '') or '')}
    return found


def resolve_link_source(unique_id: str) -> Tuple[Optional[str], Dict[str, dict]]:
    """(값을 실제로 들고 있는 장치 uuid, 메타 채널 dict) 를 반환한다.

    1. 자기 자신에게 메타 채널이 있으면 그대로 쓴다(Input, mode-manager Function).
    2. 없으면 같은 DevEUI 를 가진 장치를 찾는다(LoRaWAN Output → 하트비트 Input).
    3. 그래도 없으면 (None, {}) — 호출부는 배지를 **아예 그리지 않는다.**
       빈 아이콘을 그리면 "배터리 정보 없음"이 "배터리 0%"처럼 보인다.
    """
    own = _meta_channels(unique_id)
    if own:
        return unique_id, own

    euis = _device_euis(unique_id)
    if not euis:
        return None, {}

    for cand_id in _meta_channel_device_ids():
        if cand_id == unique_id:
            continue
        if euis & _device_euis(cand_id):
            chans = _meta_channels(cand_id)
            if chans:
                return cand_id, chans
    return None, {}


def _meta_channel_device_ids() -> List[str]:
    """메타 채널을 가질 **가능성이 있는** 장치 uuid 목록(후보 축소용).

    전 장치를 EUI 파싱하면 장치 수만큼 custom_options 를 파싱하게 된다. 먼저
    measurement 값으로 후보를 좁힌다.
    """
    from aot.databases.models.measurement import DeviceMeasurements

    try:
        rows = DeviceMeasurements.query.with_entities(
            DeviceMeasurements.device_id
        ).filter(
            DeviceMeasurements.measurement.in_(
                ['rssi', 'snr', 'battery', 'electrical_potential'])
        ).distinct().all()
    except Exception as exc:
        logger.debug('[LinkStatus] 후보 조회 실패: %s', exc)
        return []
    return [r[0] for r in rows if r and r[0]]


# ─────────────────────────────────────────────────────────────────────────────
# 조회
# ─────────────────────────────────────────────────────────────────────────────
def _read_channel(device_id: str, measurement_id: str, max_age: int):
    """(ts, value, stale) — max_age 초과분은 값은 주되 stale 로 표시한다."""
    from aot.utils.influx import get_last_measurement
    try:
        ts, val = get_last_measurement(device_id, measurement_id, max_age=max_age)
        if ts is not None and val is not None:
            return ts, float(val), False
        ts, val = get_last_measurement(device_id, measurement_id, max_age=None)
        if ts is not None and val is not None:
            return ts, float(val), True
    except Exception as exc:
        logger.debug('[LinkStatus] %s/%s 조회 실패: %s', device_id, measurement_id, exc)
    return None, None, False


def _stale_value(device_id: str, measurement_id: str):
    """창 없이 마지막 값 — `_read_channel` 의 2차 조회와 같다.

    **이것만은 배치로 묶지 않는다.** 단일 계열의 무제한 조회는 Influx 가 색인
    으로 끝내 빠르지만(실측 장치당 20ms 안팎), 같은 창을 여러 계열로 묶으면
    보존 기간 전체를 훑어 **21계열에 11초**가 걸렸다(창을 30일로 좁혀도 같다 —
    비용은 계열 수가 아니라 창이 만든다). 배치가 이득인 것은 창이 좁을 때뿐이다.
    """
    from aot.utils.influx import get_last_measurement
    try:
        ts, val = get_last_measurement(device_id, measurement_id, max_age=None)
        if ts is not None and val is not None:
            return ts, float(val), True
    except Exception as exc:
        logger.debug('[LinkStatus] %s/%s 이력 조회 실패: %s',
                     device_id, measurement_id, exc)
    return None, None, False


def _prefetch_channels(specs, max_age: int) -> Dict[tuple, tuple]:
    """`(device_id, measurement_id) → (ts, value, stale)` 를 **한 번에** 읽는다.

    `_read_channel` 은 채널마다 Influx 를 치고, 신선한 값이 없으면 전 이력을
    한 번 더 훑는다 — 장치당 최대 6회다. 필지 요약 하나가 그것을 장치 수만큼
    반복해 실측 27회였고, 값이 없는 설치(갓 만든 서버)에서는 **전부 2회째까지**
    가므로 가장 느린 경우가 가장 흔한 경우가 된다.

    Returns:
        키가 있으면 그것이 답이다. 없으면 사전 조회하지 못한 것이므로 호출부가
        `_read_channel` 로 되돌아간다 — 실패해도 배지가 사라지지 않는다.
    """
    from aot.databases.models import Conversion, DeviceMeasurements
    from aot.utils.influx import bulk_key, query_last_values_bulk_status
    from aot.utils.system_pi import return_measurement_info

    out: Dict[tuple, tuple] = {}
    specs = [(d, m) for d, m in (specs or ()) if d and m]
    if not specs:
        return out

    try:
        rows = {r.unique_id: r for r in DeviceMeasurements.query.filter(
            DeviceMeasurements.unique_id.in_([m for _d, m in specs])).all()}
        conv_ids = {r.conversion_id for r in rows.values() if r.conversion_id}
        conversions = {}
        if conv_ids:
            conversions = {c.unique_id: c for c in Conversion.query.filter(
                Conversion.unique_id.in_(list(conv_ids))).all()}
    except Exception as exc:
        logger.debug('[LinkStatus] 채널 메타 조회 실패: %s', exc)
        return out

    series = {}
    for device_id, measurement_id in specs:
        row = rows.get(measurement_id)
        if row is None:
            continue
        channel, unit, measure = return_measurement_info(
            row, conversions.get(row.conversion_id))
        if not unit:
            continue
        series[(device_id, measurement_id)] = (unit, device_id, channel, measure)
    if not series:
        return out

    try:
        fresh, ok = query_last_values_bulk_status(
            list(series.values()), past_sec=max_age)
    except Exception as exc:
        logger.debug('[LinkStatus] 배치 조회 실패: %s', exc)
        return out
    if not ok:
        return out

    missing = {}
    for key, spec in series.items():
        hit = fresh.get(bulk_key(*spec))
        if hit is None:
            missing[key] = spec
            continue
        try:
            out[key] = (hit[0], float(hit[1]), False)
        except (TypeError, ValueError):
            out[key] = (None, None, False)

    # 신선한 값이 없는 채널만 개별로 한 번 더 — 창이 무제한이라 묶으면 오히려
    # 느려진다(`_stale_value` 주석). 못 찾아도 결과를 **적어 둔다**: 비워 두면
    # 호출부가 `_read_channel` 로 되돌아가 신선 조회부터 다시 하므로, 값이 없는
    # 장치일수록 왕복이 늘어나는 원래 문제로 되돌아간다.
    for device_id, measurement_id in missing:
        out[(device_id, measurement_id)] = _stale_value(device_id, measurement_id)
    return out


def _iso(ts) -> Optional[str]:
    if ts is None:
        return None
    if hasattr(ts, 'isoformat'):
        return ts.isoformat()
    return str(ts)


def read_link_status(unique_id: str, max_age: int = LINK_MAX_AGE_S,
                     comm_fault: bool = False,
                     resolved: Optional[Tuple[Optional[str], Dict[str, dict]]] = None,
                     prefetched: Optional[Dict[tuple, tuple]] = None) -> dict:
    """장치 하나의 배터리/통신 상태를 배지용 형태로 반환한다.

    반환:
        {
          'source_id': str | None,     # 값을 실제로 들고 있는 장치(짝일 수 있음)
          'battery':   {'percent', 'raw', 'unit', 'stale', 'ts'} | None,
          'link':      {'level', 'rssi', 'snr', 'stale', 'ts'} | None,
          'comm_fault': bool,
        }
    battery / link 이 None 이면 근거 채널이 아예 없다는 뜻이다.

    `resolved`·`prefetched` 는 여러 장치를 도는 호출부(`read_link_status_batch`)가
    출처 해석과 값 조회를 **한 번에** 끝내 놓고 넘겨주는 것이다. 없으면 예전처럼
    자기가 조회한다 — 장치 하나만 보는 호출부는 그대로 쓰면 된다.
    """
    result: dict = {'source_id': None, 'battery': None, 'link': None,
                    'comm_fault': bool(comm_fault)}

    source_id, chans = (resolved if resolved is not None
                        else resolve_link_source(unique_id))
    if not source_id:
        return result
    result['source_id'] = source_id

    def _channel(measurement_id):
        if prefetched is not None:
            hit = prefetched.get((source_id, measurement_id))
            if hit is not None:
                return hit
        return _read_channel(source_id, measurement_id, max_age)

    if 'battery' in chans:
        ch = chans['battery']
        ts, val, stale = _channel(ch['measurement_id'])
        if val is not None:
            result['battery'] = {
                'percent': battery_percent(val, ch.get('unit'), ch.get('battery_type')),
                'raw':     val,
                'unit':    ch.get('unit') or '',
                'type':    ch.get('battery_type') or '',
                'stale':   stale,
                'ts':      _iso(ts),
            }

    rssi = snr = None
    link_stale = False
    link_ts = None
    for key in ('rssi', 'snr'):
        if key not in chans:
            continue
        ts, val, stale = _channel(chans[key]['measurement_id'])
        if val is None:
            continue
        if key == 'rssi':
            rssi = val
        else:
            snr = val
        link_stale = link_stale or stale
        if link_ts is None or (ts is not None and str(ts) > str(link_ts)):
            link_ts = ts

    if rssi is not None or snr is not None:
        result['link'] = {
            'level': link_level(rssi, snr, comm_fault=bool(comm_fault), stale=link_stale),
            'rssi':  rssi,
            'snr':   snr,
            'stale': link_stale,
            'ts':    _iso(link_ts),
        }
    elif comm_fault:
        # 근거 채널은 없지만 데몬이 두절이라 말하는 경우 — 0막대로 그 사실을 알린다.
        result['link'] = {'level': 0, 'rssi': None, 'snr': None,
                          'stale': False, 'ts': None}

    return result


def read_link_status_batch(unique_ids: List[str],
                           max_age: int = LINK_MAX_AGE_S) -> Dict[str, dict]:
    """여러 장치를 한 번에. comm_fault 는 /inputstate 와 같은 daemon 값을 쓴다.

    **이름만 배치였던 자리다.** 예전에는 장치마다 `read_link_status` 를 부르고
    그것이 채널마다 Influx 를 쳐서, 필지 요약 하나가 27회를 왕복했다. 출처
    해석과 값 조회를 각각 한 번으로 접는다 — 해석을 먼저 끝내야 무엇을 읽을지
    알 수 있으므로 순서가 뒤집히지 않는다.
    """
    faults = _comm_faults(unique_ids)

    resolved = {}
    for uid in unique_ids:
        try:
            resolved[uid] = resolve_link_source(uid)
        except Exception as exc:
            logger.debug('[LinkStatus] 출처 해석 실패(%s): %s', uid, exc)
            resolved[uid] = (None, {})

    specs = set()
    for source_id, chans in resolved.values():
        if not source_id:
            continue
        for key in ('battery', 'rssi', 'snr'):
            ch = chans.get(key) or {}
            if ch.get('measurement_id'):
                specs.add((source_id, ch['measurement_id']))

    try:
        prefetched = _prefetch_channels(specs, max_age)
    except Exception as exc:
        logger.warning('[LinkStatus] 값 사전 조회 실패: %s', exc)
        prefetched = {}

    return {uid: read_link_status(uid, max_age=max_age,
                                  comm_fault=faults.get(uid, False),
                                  resolved=resolved.get(uid),
                                  prefetched=prefetched)
            for uid in unique_ids}


def _comm_faults(unique_ids: List[str]) -> Dict[str, bool]:
    """daemon 의 comm_is_fault 를 한 번에 읽는다(Input 만 해당).

    Output 의 두절은 `output_state()` 가 이미 'fault' 로 내보내고 지도 팝업이 그걸
    쓰고 있다(io_link_health_infra_plan 6절). 여기서 다시 판정하지 않는다.
    """
    faults: Dict[str, bool] = {}
    try:
        from aot.aot_client import DaemonControl
        status = DaemonControl().input_status_all() or {}
        for uid in unique_ids:
            entry = status.get(uid) or {}
            faults[uid] = bool(entry.get('comm_is_fault'))
    except Exception as exc:
        logger.debug('[LinkStatus] input_status_all 실패: %s', exc)
    return faults

# coding=utf-8
"""Unit tests — 장치 배터리/통신품질 배지의 환산·등급·채널 분류.

DB·InfluxDB 를 타지 않는 순수 함수만 본다(라이브 DB 대상 테스트 금지 규칙).

이 숫자들은 잔량·전파세기를 **맞히는** 것이 목적이 아니라 사용자가 손쓸 시간이
있을 때 **환기**하는 것이 목적이다. 환기와 불안 조장은 다르다 — 멀쩡한 장치가 늘
낮게 보이면 사용자는 배지를 곧 무시하고, 그때부터 배지는 아무 일도 못 한다.
그래서 세 가지를 고정해 검증한다:
① 이론 범위가 아니라 **실사용 범위**를 0~100 에 매핑하는가,
② 정상인 것이 정상으로 보이는가(만충은 100%, 현장 최약체 노드도 최저 등급 아님),
③ 배터리는 lorawan_mode_manager 가 **행동하기 전에** 0% 에 닿는가.
②③은 정책 상수(ModeOpts)와 실측 기준값을 직접 읽어 대조하므로, 어느 쪽이
바뀌어도 여기가 먼저 깨진다.
"""
import pytest

from aot.aot_flask.geo.device_link_status import battery_percent, link_level
from aot.aot_flask.geo.facility_sensors import META_CHANNEL_KEYS, channel_label_meta


# ── 배터리 환산 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize('value,unit,expected', [
    (95, 'percent', 95.0),
    (140, 'percent', 100.0),      # clamp
    (-5, 'percent', 0.0),
    (0.42, 'decimal', 42.0),
    (1, 'bool', 100.0),
    (0, 'bool', 0.0),
    ('87', '%', 87.0),            # 문자열 입력도 받는다
])
def test_battery_percent_direct_units(value, unit, expected):
    assert battery_percent(value, unit) == pytest.approx(expected)


@pytest.mark.parametrize('volts,expected', [
    (2.90, 0.0),      # 방전 종지 아래 → clamp
    (3.00, 0.0),      # 실사용 하한 = 과방전 경계
    (3.45, 50.0),
    (3.90, 100.0),    # 실사용 만충
    (4.20, 100.0),    # 무부하 피크 → clamp
])
def test_battery_percent_1s_lithium(volts, expected):
    assert battery_percent(volts, 'V') == pytest.approx(expected)


# koat 김제 온습도/토양온습도 노드 배터리 실측 (2026-08-04).
_KOAT_FIELD_BATTERY_V = [3.43, 3.47, 3.69, 3.70, 3.71, 3.71, 3.72, 3.73, 3.79,
                         3.85, 3.87, 3.89, 3.90, 3.95]


def test_no_working_field_node_reads_empty():
    """정상 가동 중인 노드가 0%(빨간 빈 배터리)로 보이면 안 된다.

    하한을 3.50V 로 좁게 잡았을 때 3.43V/3.47V 노드 둘이 0% 가 됐다. 둘 다 링크는
    멀쩡하고(SNR 8~9) 업링크도 정상이었다 — 잔량이 아니라 **측정 오차**일 공산이
    크다. RAK3172 EVB 의 `BAT_MV_PER_COUNT` 는 개체별 1점 보정 값이고 보정한
    개체에서도 게인오차가 1.9% 였다. 3.7V 에서 ±2~3% 면 ±70~110mV 라, 0.4V 짜리
    창에서는 오차 하나가 표시를 수십 %p 흔든다. 창을 0.9V(3.0~3.9)로 넓혀
    측정 오차보다 크게 만든 이유다.
    """
    for v in _KOAT_FIELD_BATTERY_V:
        assert battery_percent(v, 'V') > 0.0, f'{v}V 가 0% 로 표시됨'


def test_over_discharged_cell_still_reads_low():
    """넓혔다고 진짜 위험한 전압까지 무뎌지면 안 된다."""
    assert battery_percent(3.10, 'V') < 15.0
    assert battery_percent(3.00, 'V') == 0.0


def test_full_battery_must_read_full():
    """실사용 만충 노드가 100% 로 읽혀야 한다 — 없는 문제를 만들지 않기 위해.

    데이터시트 만충(4.20V)을 100% 로 잡으면, 실제로 다 충전된 태양광 노드가 늘
    80% 대로 보인다. 사용자는 매일 "덜 찼네" 를 보게 되고 곧 배지를 무시한다.
    현장 충전 실측 기준 3.9V 이상은 만충으로 본다(2026-08-04 사용자 확인).
    """
    assert battery_percent(3.90, 'V') == 100.0
    assert battery_percent(4.05, 'V') == 100.0
    assert battery_percent(4.20, 'V') == 100.0
    # 12V 계열도 각 화학의 만충에서 100 — 충전 중 전압(13~15V)은 당연히 clamp.
    assert battery_percent(12.70, 'V', 'lead_12v') == 100.0
    assert battery_percent(13.40, 'V', 'lifepo4_4s') == 100.0
    assert battery_percent(14.40, 'V', 'lifepo4_4s') == 100.0


@pytest.mark.parametrize('volts,expected', [
    (11.30, 0.0),     # 방전 한계 아래 → clamp
    (11.40, 0.0),
    (11.80, 25.0),
    (12.00, 50.0),
    (12.70, 100.0),   # 무부하 만충
    (13.80, 100.0),   # 충전 중 → clamp
])
def test_battery_percent_lead_acid_12v(volts, expected):
    assert battery_percent(volts, 'V', 'lead_12v') == pytest.approx(expected)


@pytest.mark.parametrize('volts,expected', [
    (11.90, 0.0),     # 방전 종지 아래 → clamp
    (12.00, 0.0),
    (12.80, 10.0),    # 무릎 — 아래로는 전압이 급락한다
    (13.00, 25.0),
    (13.20, 70.0),
    (13.40, 100.0),
    (15.20, 100.0),   # 충전 중 → clamp
])
def test_battery_percent_lifepo4_4s(volts, expected):
    assert battery_percent(volts, 'V', 'lifepo4_4s') == pytest.approx(expected)


def test_chemistry_cannot_be_guessed_from_voltage():
    """같은 전압이 화학에 따라 정반대로 읽힌다 — 그래서 설정이 필요하다.

    12.7V 는 납산에겐 만충이고 인산철에겐 거의 빈 상태다. 자동 추정은 12V 대를
    납산으로 가정하므로, 인산철 팩은 실사용 구간(12.8~13.4V)이 전부 100% 로
    뭉개진다 — 그 상태가 바로 battery_type 을 지정해야 한다는 신호다.
    """
    assert battery_percent(12.70, 'V', 'lead_12v') == 100.0
    assert battery_percent(12.70, 'V', 'lifepo4_4s') < 25.0
    # 자동(미지정) 12V 대 = 납산 가정
    assert battery_percent(12.70, 'V') == battery_percent(12.70, 'V', 'lead_12v')
    # 알 수 없는 종류 문자열은 조용히 자동으로 떨어진다(저장 단계에서 걸러지지만
    # 옛 데이터가 남아 있어도 배지가 사라지지 않게).
    assert battery_percent(12.70, 'V', 'nonsense') == battery_percent(12.70, 'V')


def test_koat_aot_c_pack_reads_full_when_typed():
    """AoT-C(인산철) 실측 13.41~15.17V 는 만충 구간이다 — 종류를 지정해도 100%.

    지정 여부와 무관하게 100% 인 이유는 이 팩들이 실제로 충전 상태이기 때문이고,
    방전이 진행되면(13.2V 이하) 그때부터 지정 여부가 표시를 가른다.
    """
    for v in (13.41, 13.57, 14.39, 15.17):
        assert battery_percent(v, 'V', 'lifepo4_4s') == 100.0
    assert battery_percent(13.10, 'V', 'lifepo4_4s') < 60.0   # 방전되면 갈린다
    assert battery_percent(13.10, 'V', 'lead_12v') == 100.0


def test_battery_badge_warns_before_the_daemon_acts():
    """배지는 정책이 **행동하기 전에** 0% 에 닿아야 한다.

    lorawan_mode_manager 는 vbat_low_v 에서 절전, vbat_critical_v 에서 초절전으로
    내린다. 배지가 그 지점에서야 0 이 되면 예고가 아니라 통보다 — 사용자가 손쓸
    구간이 남지 않는다. 그래서 두 임계값 **위**에서 이미 0 이어야 한다.
    (초안은 두 값을 같은 점에 놓았다가 이 이유로 분리했다.)
    """
    from aot.functions.lorawan_mode_manager import ModeOpts
    o = ModeOpts()
    # 기본값은 4S 인산철 기준(2026-08-04 이관). 납산 팩은 사용자가 12.00/11.70/11.40
    # 으로 되돌리며, 그 경우도 아래 관계가 성립한다(두 곡선 모두 검증).
    assert (o.vbat_critical_v, o.vbat_low_v, o.vbat_recover_v) == (12.80, 13.00, 13.20)

    for chem, (crit, low_v, rec) in {
        'lifepo4_4s': (o.vbat_critical_v, o.vbat_low_v, o.vbat_recover_v),
        'lead_12v':   (11.40, 11.70, 12.00),
    }.items():
        # 절전으로 내리는 지점에서는 이미 "곧 바닥" 이 보여야 한다. 0 을 요구하지는
        # 않는다 — 그 전압들은 실제로 10~25% 가 남은 상태이고, 빈 배터리로 그리면
        # 원칙 ②(정상은 정상으로)를 어긴다.
        assert battery_percent(low_v, 'V', chem) <= 25.0, chem
        # 초절전(더 낮은 지점)은 절전보다 낮게 보여야 한다.
        assert battery_percent(crit, 'V', chem) < battery_percent(low_v, 'V', chem), chem
        # 정책이 "성능 모드 가능" 이라 부르는 전압은 절반 이상으로 보여야 한다 —
        # 데몬이 여유롭다고 판단한 상태를 화면이 경고로 그리면 서로 어긋난다.
        assert battery_percent(rec, 'V', chem) >= 50.0, chem


def test_battery_percent_mv_is_scaled_not_treated_as_volts():
    """lorawan_mode_manager 는 배터리를 mV 로 기록한다 — 1000배 오차 방지."""
    assert battery_percent(3700, 'mV') == pytest.approx(battery_percent(3.70, 'V'))


@pytest.mark.parametrize('value,unit', [
    (24.0, 'V'),      # 어느 곡선에도 없는 전압대
    (7.0, 'V'),       # 1S 와 12V 사이 공백
    (3.9, ''),        # 단위 없음
    (3.9, 'ppm'),     # 엉뚱한 단위
    (None, 'V'),
    ('abc', 'V'),
])
def test_battery_percent_unknown_returns_none(value, unit):
    """모르는 것은 None 으로 답한다 — 억지로 0~100 에 넣으면 화면이 거짓말한다."""
    assert battery_percent(value, unit) is None


# ── 통신 등급 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('rssi,snr,expected', [
    (-88, 5, 3),        # 여유 있음
    (-110, -5, 3),      # 경계 포함
    (-111, -5, 2),
    (-110, -6, 2),      # SNR 이 낮은 쪽 → 낮은 등급 채택
    (-120, -13, 2),     # 경계 포함
    (-121, -13, 1),
    (-120, -14, 1),
    (-130, -25, 1),     # 아무리 나빠도 수신은 됐으므로 1
])
def test_link_level_lorawan(rssi, snr, expected):
    assert link_level(rssi, snr) == expected


# koat 김제 현장 24개 노드 실측 (2026-08-04). 기준을 바꾸면 실제 화면이 어떻게
# 보이는지가 여기서 바로 드러난다 — 숫자만 고치고 현장 그림을 상상하지 않게.
_KOAT_FIELD_NODES = [
    # (이름, RSSI, SNR, 기대 막대)
    ('AoT-C-s-006', -61, 10.00, 3),
    ('AoT-C-s-010', -90, 9.50, 3),
    ('토양온습도_3', -98, 12.25, 3),
    ('온습도_3', -100, 9.25, 3),
    ('온습도_7', -103, 9.50, 3),
    ('온습도_2', -106, 8.00, 3),    # RSSI 는 낮지만 SNR 이 넉넉 → 정상
    ('온습도_1', -114, -8.75, 2),   # 현장 최약체 — 낮을 뿐 고장은 아니다
]


@pytest.mark.parametrize('name,rssi,snr,expected', _KOAT_FIELD_NODES)
def test_koat_field_nodes_render_as_expected(name, rssi, snr, expected):
    """실제 현장 24대 중 2막대는 최약체 하나뿐, 1막대는 없어야 한다.

    사용자 지적(2026-08-04): 온습도_1 이 설치된 장비들 중 신호가 가장 낮지만
    그건 상대적으로 낮은 것이지 문제 있는 수준이 아니다. 정상 설비가 상시
    경고 상태로 보이면 사용자는 배지를 통째로 무시하게 된다.
    """
    assert link_level(rssi, snr) == expected, f'{name}({rssi}dBm/{snr}dB)'


def test_no_field_node_is_painted_as_weak():
    """1막대는 복조 여유가 실제로 바닥난 링크에만 — 현장엔 아직 하나도 없다."""
    assert all(link_level(r, s) >= 2 for _n, r, s, _e in _KOAT_FIELD_NODES)
    # 반대로 여유가 없는 구간은 확실히 1막대로 떨어져야 한다.
    assert link_level(-125, -18) == 1


@pytest.mark.parametrize('rssi,expected', [
    (-55, 3), (-67, 3), (-68, 2), (-82, 2), (-83, 1),
])
def test_link_level_wifi_when_no_snr(rssi, expected):
    """SNR 이 없으면 WiFi 표를 쓴다 — -90dBm 은 LoRa 에선 멀쩡, WiFi 에선 불통."""
    assert link_level(rssi, None) == expected


def test_link_level_snr_only():
    assert link_level(None, 5) == 3
    assert link_level(None, -15) == 1


@pytest.mark.parametrize('kwargs', [
    {'comm_fault': True},
    {'stale': True},
])
def test_link_level_zero_when_unreachable(kwargs):
    """두절/오래된 값은 아무리 숫자가 좋아도 0막대다."""
    assert link_level(-50, 10, **kwargs) == 0


def test_link_level_zero_without_any_input():
    assert link_level(None, None) == 0


# ── 채널 분류 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('name,measurement,expected_key', [
    ('RSSI', 'rssi', 'rssi'),
    ('SNR', 'snr', 'snr'),
    ('Battery', 'battery', 'battery'),
    ('Battery Voltage', 'electrical_potential', 'battery'),
    ('배터리 전압', 'electrical_potential', 'battery'),
    # koat 현장 실제 채널명(chirpstack_mqtt_jmespath 입력, 2026-08-04 확인)
    ('배터리', 'electrical_potential', 'battery'),
])
def test_meta_channels_get_language_independent_keys(name, measurement, expected_key):
    """key 가 없으면 표시명(번역됨)이 key 가 되어, 클라이언트가 언어에 따라
    이 채널을 못 골라낸다 — 배지/그래프 제외가 통째로 무너진다."""
    key, _unit = channel_label_meta(None, name, '', measurement)
    assert key == expected_key
    assert key in META_CHANNEL_KEYS


@pytest.mark.parametrize('name', ['Panel Voltage', 'Solar V', 'EC probe'])
def test_non_battery_voltage_is_not_promoted(name):
    """전압 채널을 전부 배터리로 보면 태양광 전압까지 배터리 배지가 된다."""
    key, _unit = channel_label_meta(None, name, 'V', 'electrical_potential')
    assert key not in META_CHANNEL_KEYS

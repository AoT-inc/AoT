# coding=utf-8
"""env_coordinator 건강 점검 — 결정 로그를 읽어 사람이 볼 한 화면으로 낸다.

제어 변경은 **하루를 살아 봐야** 안다. 개구부가 떨리는지, 난방과 냉방이
맞물리는지, 야간 파킹이 아침에 풀리는지는 합성 테스트로 나오지 않는다.
그렇다고 사흘 내내 사람이 InfluxDB 를 뒤질 수는 없어서, 코디네이터가 이미
남기고 있는 결정 로그를 세어 준다.

**읽기 전용이다** — 운영 서버에 그대로 돌려도 된다.

    python3 -m aot.scripts.check_env_coordinator_health
    python3 -m aot.scripts.check_env_coordinator_health --hours 72
    python3 -m aot.scripts.check_env_coordinator_health --function <uuid>
    python3 -m aot.scripts.check_env_coordinator_health --json

종료 0=이상 없음, 1=볼 것 있음, 2=검사 실패.

────────────────────────────────────────────────────────────────────────────
읽는 곳이 둘이고 **가용성이 다르다**

    coord_actuator_<id8>_command / _reason   항상 기록된다
    env_control (모드·편차·목표·제한인자)     log_level_debug 가 켜져 있을 때만

그래서 디버그가 꺼진 코디네이터는 액추에이터 축만 나온다. 없는 것을 0 으로
보고하지 않고 **"기록 없음"** 이라고 말한다 — 0 회 진동과 측정 안 됨은 다르다.

────────────────────────────────────────────────────────────────────────────
왜 이 항목들인가

진동          같은 장치가 방향을 뒤집는 횟수. 제어가 목표 주위에서 떠는 것은
              합성 테스트가 못 잡고 현장에서는 모터 수명으로 나타난다.
상반 가동     난방과 냉방(또는 가습 분무)이 같은 사이클에 함께 켜진 것.
              Post-Gate 가 막게 되어 있으므로 **0 이 아니면 그 자체가 결함**이다.
안전 후보정   Post-Gate 가 실제로 고친 횟수(gate=-1). 위 항목의 상류 신호다.
근거 쏠림     한 장치가 창 내내 같은 근거로만 산 경우. 무구배·야간파킹·맞선짝은
              정상 사유이지만 **24시간 100%** 면 그 장치는 사실상 죽어 있다.
긴급 사이클   emergency 모드 비율. 드물어야 정상이다.
의심 액추에이터 (CH93, 근거 42)  전송 실패가 이어졌거나 오래 세게 명령했는데 반응이 없어 코디네이터가
              부하 분담에서 빼고 제자리에 둔 장치. 있으면 그 장치를 점검해야 한다. 의심이 있을 때만 기록된다.
분무용 물 공급 (CH92)  옵션을 켠 코디네이터만. 물이 없거나 신호가 끊겨 분무기가 멈춘 분.
              0 이 아니면 사람이 탱크·수압·신호를 봐야 한다(설계된 보호이지만 끝내는 것은 사람).
극한 고온 보호 단계(CH75)·플래그(CH76) — 활성 분, 단계 전환 횟수와 시각, 보호 중
              무엇이 막혔나(바깥이 더 더움·증발 여력·물). debug 와 무관하게 늘
              기록된다. 전환이 시간당 1회를 넘으면 문턱 근처의 들락거림이다.
설정 점검     오늘 실제로 밟은 지뢰들 — 종료일 임박, 유도/하드 역전,
              신선도 상한이 센서 주기보다 짧아 값이 늘 만료되는 경우,
              차광막을 닫으면 광량 하한 아래로 떨어지는 모순 설정,
              센서·장치 조합이 제어로 이어지지 않는 경우(`_check_combinations`).
"""

import argparse
import json
import logging
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

# `start_flask_ui` 를 import 하는 것만으로 기동 로그 여섯 줄이 stdout 으로
# 쏟아져 보고서 머리를 덮는다. INFO 만 끈다 — 경고·오류는 그대로 보여야 한다.
# **CLI 로 돌 때만** 끈다. `logging.disable` 은 프로세스 전역이라 모듈 머리에서
# 무조건 걸면, 이 모듈을 import 하는 테스트가 pytest 프로세스 전체의 INFO 이하를
# 꺼 버려 뒤에 도는 assertLogs/caplog 검사가 순서에 따라 실패한다(PR #88 실측).
# 아래 app import 보다 위에 있어야 기동 로그가 막힌다.
if __name__ == '__main__':
    logging.disable(logging.INFO)

from aot.start_flask_ui import app
from aot.databases.models import CustomController, Input, Output
from aot.functions.utils.env_control import log_channels as LC
from aot.functions.utils.env_control import heat_protect as HP
from aot.utils import sensor_status as SS
from aot.functions.utils.env_control import water_supply as WS
from aot.functions.utils.env_control import leaf_vpd as LV
from aot.functions.utils.env_control import humid_regime as HR
from aot.functions.utils.env_control.types import ACTUATOR_DOMAIN, DEFAULT_DOMAIN
from aot.utils.timekit import FARM, today_at, utc_now


# ── 코드 → 사람 말 ──────────────────────────────────────────────────────────
# 상수를 **참조**한다. 숫자를 베껴 적으면 renumber 가 조용히 오라벨을 만든다.
REASON_LABEL = {
    LC.REASON_IDLE:             '쉼',
    LC.REASON_PRIMARY:          '주작용',
    LC.REASON_SECONDARY:        '보조',
    LC.REASON_WRONG_DIRECTION:  '방향 불일치',
    LC.REASON_SIDE_EFFECT:      '부작용 충돌',
    LC.REASON_SAFETY_PRE_GATE:  '안전 강제',
    LC.REASON_UNAVAILABLE:      '통신 실패',
    LC.REASON_SAFETY_POST_GATE: '안전 보정',
    LC.REASON_NO_GRADIENT:      '무구배',
    LC.REASON_NO_OUTDOOR_DATA:  '실외 값 없음',
    LC.REASON_OPPOSING_PARKED:  '맞선 짝 대기',
    LC.REASON_DEADZONE_BACKOFF: '데드존 후퇴',
    LC.REASON_NIGHT_PARKED:     '야간 파킹',
    LC.REASON_MANUAL_OVERRIDE:  '수동 잠금',
    LC.REASON_NO_MEASUREMENT:   '실내 값 없음',
    LC.REASON_CURTAIN_DAY_OPEN: '낮 걷음',
    LC.REASON_DIRECTION_UNSETTLED: '방향 확정 대기',
    LC.REASON_HUMID_NO_RELIEF:  '과습·환기 무익',
    LC.REASON_HUMID_CAPPED:     '과습·열림 제한',
    LC.REASON_HUMID_COLD:       '과습·실외 너무 참',
    LC.REASON_NO_RESPONSE:      '열어도 반응 없음',
    LC.REASON_HEAT_VENT_HOT_OUTSIDE: '폭염·바깥이 더 더움',
    LC.REASON_HEAT_FOG_BLOCKED: '폭염·분무 불가',
    # 임계 오버라이드 계열 — coordinate() 가 아니라
    # `apply_threshold_and_gate_overrides` 가 붙이는 근거다. 최종 명령
    # 로그(CH100 계열)에만 나타난다.
    LC.REASON_LIMIT_LIGHT_MAX:      '광량 상한',
    LC.REASON_LIMIT_LIGHT_MIN:      '광량 하한',
    LC.REASON_LIMIT_TEMP_MAX:       '온도 상한',
    LC.REASON_LIMIT_TEMP_MIN:       '온도 하한',
    LC.REASON_LIMIT_HUMID_MAX:      '습도 상한',
    LC.REASON_LIMIT_HUMID_MIN:      '습도 하한',
    LC.REASON_FOG_DERATE:           '분무 감쇠',
    LC.REASON_FOG_HUMIDITY_CEILING: '분무 습도 상한',
    LC.REASON_NO_ACTUATOR:          '장치 없음',
    LC.REASON_HEAT_PROTECT:         '극한 고온 보호',
    LC.REASON_NO_WATER:             '분무용 물 없음',
    LC.REASON_ACTUATOR_SUSPECT:     '의심 장치 보류',
    # 스크린 판단(`screen_policy`) — 차광막을 열·VPD 에 씀 / 빛을 지키려 걷어 둠.
    LC.REASON_SHADE_HEAT:           '차광·열부하',
    LC.REASON_SHADE_LIGHT_KEEP:     '차광·빛 지킴',
    LC.REASON_SCREEN_HOLD:          '차광·왕복 방지',
    LC.REASON_CURTAIN_GAP:          '커튼·결로 틈',
    LC.REASON_CURTAIN_RAMP:         '커튼·아침 단계 걷기',
    LC.REASON_PREPARK_HOLD:         '파킹 직전·더 안 엶',
    LC.REASON_CURTAIN_NIGHT_CLOSE:  '커튼·밤 보온 닫음',
    LC.REASON_SOLAR_VENT_FLOOR:     '일사 부하·환기 하한',
    LC.REASON_RAIN_RESTRICT:        '강우 단계 제한(천창 닫음·측창 상한)',
    LC.REASON_WIND_RESTRICT:        '강풍 1단계(풍상측·천창 닫음·상한)',
    LC.REASON_WETTING_FOG_DUSK:     '분무 해 질 녘 제한',
    LC.REASON_MORNING_PURGE:        '아침 습기 빼기·환기 하한',
    LC.REASON_FROST_PROTECT:        '서리 주의·보호(닫음·난방·유동팬)',
    LC.REASON_EXTREME_PULSE_FOG:    '극한 고온·건조 짧은 펄스 분무',
    LC.REASON_OUTAGE_CLOSE:         '실외 값 없음·밤 닫음',
    LC.REASON_NIGHT_DEW_FAN:        '밤 이슬·순환팬',
    LC.REASON_BLIND_SUN_VENT:       '실내 값 없음·해 보고 작은 환기',
    LC.REASON_UNKNOWN:              '근거 미상',
}

# 창 내내 이것 하나로만 살았다면 그 장치는 사실상 참여하지 않은 것이다.
IDLE_REASONS = frozenset({
    LC.REASON_IDLE, LC.REASON_NO_GRADIENT, LC.REASON_NO_OUTDOOR_DATA,
    LC.REASON_OPPOSING_PARKED, LC.REASON_NIGHT_PARKED,
    LC.REASON_OUTAGE_CLOSE,         # 실외 값 없이 밤에 닫아 둔 창 — 쉬는 이유가 설명돼 있다
    LC.REASON_WRONG_DIRECTION, LC.REASON_NO_MEASUREMENT,
    LC.REASON_CURTAIN_DAY_OPEN,
    # 과습에서 환기가 소용없다고 판단했거나, 열어도 반응이 없어 멈춘 것 — 설명이 끝난 쉼이다.
    LC.REASON_HUMID_NO_RELIEF, LC.REASON_NO_RESPONSE, LC.REASON_HUMID_COLD,
    # 극한 고온 보호 — 바깥이 더 더워 닫은 창, 증발 여력·물이 없어 쉬는 분무.
    LC.REASON_HEAT_VENT_HOT_OUTSIDE, LC.REASON_HEAT_FOG_BLOCKED,
    # 분무용 물이 없어 쉬는 분무기 — 쉬는 이유는 설명이 끝났다(물 공급 자체는 아래 `water` 에서 센다).
    LC.REASON_NO_WATER,
    # 빛을 지키려 걷어 둔 차광막 — 쉬는 이유가 설명돼 있다.
    LC.REASON_SHADE_LIGHT_KEEP,
})

# 코디네이터의 요청을 **일부러** 0 으로 만드는 보호 장치의 근거들. 최종 명령의
# 근거(`_final_reason`)가 이것이면 "요청이 게이트에 버려졌다" 가 아니라 "보호가
# 설계대로 작동했다" 다. 이 둘을 한 줄로 묶어 경고하면 사람은 경고에 익숙해지고,
# 정말 버려진 요청(2026-08-30 영양: 가습이 필요한 31 사이클 전부에서 분무 요청이
# 게이트에 버려졌다)이 그 사이에 묻힌다 — 2026-09-30 로컬 3포장이 정확히 그랬다:
# 육묘 일소 방지 잠금이 107번 분무를 막았고 검사기는 그것을 고장처럼 보고했다.
GUARD_REASONS = frozenset({
    LC.REASON_SAFETY_PRE_GATE, LC.REASON_SAFETY_POST_GATE,
    LC.REASON_LIMIT_LIGHT_MAX, LC.REASON_LIMIT_LIGHT_MIN,
    LC.REASON_LIMIT_TEMP_MAX, LC.REASON_LIMIT_TEMP_MIN,
    LC.REASON_LIMIT_HUMID_MAX, LC.REASON_LIMIT_HUMID_MIN,
    LC.REASON_FOG_DERATE, LC.REASON_FOG_HUMIDITY_CEILING,
    LC.REASON_HEAT_PROTECT, LC.REASON_NO_WATER,
    # 해 질 녘 습윤형 분무 제한 — 잎을 젖은 채 밤에 들이지 않으려는 설계된 0 이다.
    LC.REASON_WETTING_FOG_DUSK,
    # 서리 — 분무·CO₂·냉방·개구부를 0 으로, 난방·유동팬을 100 으로 몬다. 설계된 강제다.
    LC.REASON_FROST_PROTECT,
})

# 스크린(보온커튼·차광막)은 0/100 두 자리뿐이라 명령이 문턱(닫혀 있다 걷으려면 60,
# 걷혀 있다 닫으려면 40)을 못 넘으면 제자리로 스냅된다. 그러므로 스크린의 최종 0 은
# "안 나갔다" 가 아니라 **닫힘이라는 위치**다 — 요청 12% → 최종 0% 는 커튼을 닫으라는
# 명령이 그대로 나간 것이고, 이것을 억제로 세면 저녁마다 오경보가 난다.
SCREEN_KINDS = frozenset({'curtain', 'shade'})

MODE_LABEL = {
    1: '냉방', 2: '난방', 3: '가습', 4: '제습',
    5: 'CO₂ 시비', 6: '폭염 보호', 0: '보존', 99: '긴급',
}
LIMIT_LABEL = {0: '없음', 1: '광량', 2: 'CO₂', 3: '온도', 4: '수분'}

GATE_LABEL = [
    (LC.GATE_BIT_RAIN,        '강우'),
    (LC.GATE_BIT_WIND,        '강풍'),
    (LC.GATE_BIT_EXT_EXP,     '실외 비·바람 끊김'),
    (LC.GATE_BIT_INT_EXP,     '실내 값 끊김'),
    (LC.GATE_BIT_HEAT,        '고온'),
    (LC.GATE_BIT_COLD,        '저온'),
    (LC.GATE_BIT_FOG_SUNBURN, '일소 방지 분무 잠금'),
    (LC.GATE_BIT_RAIN_LIGHT,  '강우 단계 제한(예보·약한 비)'),
    (LC.GATE_BIT_WIND_LIGHT,  '강풍 1단계(풍상측 닫음·상한)'),
    (LC.GATE_BIT_FROST_WATCH, '서리 주의'),
    (LC.GATE_BIT_FROST,       '서리 보호'),
]

# 극한 고온 보호 플래그(CH76) — 상수를 **참조**한다(근거 라벨과 같은 이유).
HP_FLAG_LABEL = [
    (HP.HP_FLAG_VENT_OPEN_OK,    '환기 가능'),
    (HP.HP_FLAG_HOT_OUTSIDE,     '바깥이 더 더움'),
    (HP.HP_FLAG_FOG_ALLOWED,     '분무 허용'),
    (HP.HP_FLAG_FOG_WETBULB,     '증발 여력 부족'),
    (HP.HP_FLAG_FOG_HUMID,       '습도로 분무 차단'),
    (HP.HP_FLAG_NO_WATER,        '물 없음'),
    (HP.HP_FLAG_SHADE_DEPLOY,    '차광 전개'),
    (HP.HP_FLAG_LIGHT_MIN_YIELD, '광량 하한에 차광 양보'),
    (HP.HP_FLAG_INDOOR_STALE,    '실내 값 끊김'),
]
# 보호가 이보다 자주 켜졌다 꺼졌다 하면 사람이 본다 — 진입 지연·해제 여유·최소 유지가
# 막아야 할 30 °C 근처의 들락거림이다(설계 §6).
HP_MAX_TRANSITIONS_PER_H = 1.0

# 밤 이슬·서리 노출(2026-10-12) — 시설 문제를 코디네이터 결함과 섞지 않으려고 따로 센다.
# 밤 이슬 분 = 해 진 뒤 실내 RH ≥ 95 % 이거나 이슬점 여유 < 1 °C 인 분. 잎은 복사로 공기보다 1~3 °C 식으므로
# 공기 쪽 여유가 1 °C 아래면 잎은 이미 이슬점 아래다(밤 이슬 순환팬의 진입선은 2 °C, `night_dew`).
NIGHT_DEW_RH_PCT = 95.0
NIGHT_DEW_MARGIN_C = 1.0
EXPOSURE_STEP_S = 300.0            # 센서 표본을 이 격자로 평균해 센다(센서 주기가 달라도 같은 잣대)
EXPOSURE_DEW_MIN = 60.0            # 이만큼 넘고
EXPOSURE_DEW_SHARE = 0.25          # 밤의 이 몫 이상이면 시설 권고를 낸다
EXPOSURE_FROST_MIN = 15.0          # 실내 0 °C 이하가 이만큼 넘거나
EXPOSURE_FROST_PROTECT_MIN = 60.0  # 서리 보호(게이트)가 이만큼 넘으면 권고

# 상반 쌍 — `apply_hvac_opposition_interlock` 이 보는 것과 **같은 두 종류**다.
# 분무(fogger)를 여기 넣으면 안 된다: VPD 를 목표로 하면 난방과 가습이 함께
# 도는 것이 정상이라, 넣는 순간 정상 동작이 26% 결함으로 보고된다(실측).
WARMING_KINDS = frozenset({'heater'})
COOLING_KINDS = frozenset({'cooler'})
HUMIDIFY_KINDS = frozenset({'fogger'})
VENT_KINDS = frozenset(k for k, d in ACTUATOR_DOMAIN.items() if d == 'vent')


# ── InfluxDB ────────────────────────────────────────────────────────────────

def _fetch_series(uid, hours):
    """이 Function 이 남긴 결정 로그 전량을 한 번에 읽는다.

    측정값마다 질의하면 액추에이터 수만큼 왕복이 는다. 한 번에 받아서
    파이썬에서 가른다 — 24시간 300초 주기라도 수만 행 수준이다.
    """
    from aot.utils.influx import _influx_connection_params
    from influxdb_client import InfluxDBClient

    params = _influx_connection_params()
    if not params:
        raise RuntimeError('측정 DB 설정을 읽지 못했습니다')
    url, token, bucket, _version = params

    flux = (
        f'from(bucket: "{bucket}")'
        # ⚠ **`int(hours)h` 로 쓰지 말 것.** `--hours 0.2` 가 `-0h` 가 되어
        #   InfluxDB 가 "cannot query an empty range" 로 거절한다. 재시작
        #   직후를 들여다볼 때 정확히 그 값을 쓰게 된다.
        f' |> range(start: -{max(int(hours * 3600), 60)}s)'
        f' |> filter(fn: (r) => r["device_id"] == "{uid}")'
        f' |> filter(fn: (r) => r["_field"] == "value")'
        f' |> keep(columns: ["_time", "_measurement", "channel", "_value"])'
    )

    rows = []
    with InfluxDBClient(url=url, token=token, org='aot', timeout=60000) as client:
        for table in client.query_api().query(flux):
            for rec in table.records:
                rows.append((
                    rec.get_time(),
                    rec.values.get('_measurement') or '',
                    rec.values.get('channel'),
                    rec.get_value(),
                ))
    rows.sort(key=lambda r: r[0])
    return rows


# ── 액추에이터 신원 ─────────────────────────────────────────────────────────

def _actuator_directory(facility_uuid):
    """`id[:8]` → (이름, kind). 코디네이터가 쓰는 것과 **같은 출처**를 쓴다."""
    directory = {}
    if facility_uuid:
        try:
            from aot.space.facility_integration import get_facility_integration
            data, err = get_facility_integration(facility_uuid)
            if not err and isinstance(data, dict):
                for act in data.get('actuators_resolved') or []:
                    uid = act.get('output_uuid') or ''
                    if uid:
                        directory[uid[:8]] = (
                            act.get('output_name') or uid[:8],
                            act.get('kind') or '',
                        )
        except Exception:                                    # noqa: BLE001
            pass                # 시설을 못 읽어도 이름 없이 계속 센다
    return directory


def _name_from_db(prefix):
    """도면에 없는 액추에이터 — Output 이름만이라도 붙인다."""
    row = Output.query.filter(Output.unique_id.like(f'{prefix}%')).first()
    return (row.name if row else prefix), ''


# ── 계산 ────────────────────────────────────────────────────────────────────

def _cluster_cycles(stamps, epsilon_s=5.0):
    """같은 사이클의 기록을 하나로 접는다.

    사이클 안의 쓰기들은 서로 밀리초 차이라, 5초를 넘으면 다음 사이클로 본다.
    가장 짧은 실제 주기(update_period 하한)보다 훨씬 작아 오접합 위험이 없다.
    """
    cycles = []
    for ts in stamps:
        if not cycles or (ts - cycles[-1]).total_seconds() > epsilon_s:
            cycles.append(ts)
    return cycles


def _cycle_index(cycle_starts, ts):
    """이 기록이 속한 사이클. 클러스터 시작 시각들에 대해 이분 탐색한다."""
    import bisect
    i = bisect.bisect_right(cycle_starts, ts) - 1
    return max(i, 0)


def _activity_flags(values, reason_counter):
    """이 장치가 창 내내 무엇을 했는지 두 축으로 가른다.

    한 축으로는 갈리지 않는다. 쿠마모토 냉방기가 24시간 **전부 0%** 인데 근거의
    68% 가 `주작용` 이었다 — 냉방 모드가 한 번도 없었으니 0% 가 맞는 동작이고,
    근거는 "이 방향의 대표 장치" 라는 뜻이라 그것도 맞다. 그런데 표에 나란히
    찍히면 "일하고 있다는데 0%" 라는 모순으로 읽힌다.

    그래서 **"안 움직였다" 와 "왜 안 움직였다" 를 따로** 낸다. 근거가 전부 대기
    계열이면 설명이 끝난 것이고, 주작용을 달고도 0 이면 사람이 볼 자리다 —
    수요가 정말 0 이었을 수도 있고, min-ON 문턱을 영영 못 넘는 교착일 수도
    있는데 로그만으로는 둘이 같아 보인다.
    """
    never_ran = bool(values) and max(values) <= 0.0
    explained = bool(reason_counter) and set(reason_counter) <= IDLE_REASONS
    # ⚠ **한 번이라도 아니라 대부분일 때만** 수상하다. 보호 장치가 창의 대부분을 막은
    #   장치(로컬 3포장 분무: 습도 상한 46 · 안전 강제 43 · 주작용 11 %)는 주작용이
    #   조금 섞였다는 이유로 "설명이 안 된다" 가 아니다 — 89 % 는 이미 설명됐다.
    work = sum(n for c, n in reason_counter.items()
               if c in (LC.REASON_PRIMARY, LC.REASON_SECONDARY))
    claimed_work = bool(reason_counter) and work * 2 > sum(reason_counter.values())
    return {
        'never_ran': never_ran,
        'always_idle': explained,
        'idle_while_claiming_work': never_ran and claimed_work,
    }


def _suppressed_pairs(requested, final):
    """코디네이터가 켜라고 했는데 실제로는 0 이 나간 사이클들 `[(시각, 요청값)]`.

    이 목록이 이 검사기의 존재 이유다. 요청만 보면 "평균 23% 로 돌고 있다"
    이고 최종만 보면 "0% 로 쉰다"인데, 둘 다 참이면서 서로 다른 곳을
    가리킨다 — 전자는 코디네이터가 정상이라는 뜻이고 후자는 그 판단이
    게이트에 버려졌다는 뜻이다. 그 간극을 세지 않으면 사람이 둘 중 어디를
    봐야 하는지 알 수 없다(2026-08-30 영양: 가습이 필요한 31 사이클 전부에서
    분무 요청이 게이트에 버려졌고, 검사기는 "작동 중"이라고 보고했다).

    ⚠ **타임스탬프로 짝짓지 않는다.** 요청과 최종은 같은 사이클 안에서도
    수백 ms 떨어져 기록되므로 정확히 같은 시각이 아니다. 사이클 경계로
    묶는 대신 5 초 안의 가장 가까운 최종값을 그 요청의 짝으로 본다.
    """
    if not requested or not final:
        return []
    finals = sorted(final)
    out = []
    for ts, want in requested:
        if want <= 0.0:
            continue
        nearest = min(finals, key=lambda fv: abs((fv[0] - ts).total_seconds()))
        if abs((nearest[0] - ts).total_seconds()) > 5.0:
            continue
        if nearest[1] <= 0.0:
            out.append((ts, want))
    return out


def _count_suppressed(requested, final):
    """`_suppressed_pairs` 의 개수."""
    return len(_suppressed_pairs(requested, final))


def _split_suppressed(pairs, final_reasons, guard_codes):
    """버려진 사이클을 **보호 장치가 막은 것**과 **설명 없이 버려진 것**으로 가른다.

    반환 `(guarded, unexplained_pairs)` — 앞은 `Counter{근거 코드: 횟수}`, 뒤는
    보호 근거가 없는 `[(시각, 요청값)]`. 그 사이클의 최종 근거(`_final_reason`)를
    5 초 안에서 찾고, 그것이 `guard_codes` 에 있으면 보호가 막은 것이다. 최종 근거
    기록이 없는 옛 구간은 **설명이 없는 쪽**으로 둔다 — 모르는 것을 정상으로
    접으면 이 검사가 존재하는 이유가 사라진다.
    """
    from collections import Counter
    guarded = Counter()
    unexplained = []
    frs = sorted(final_reasons or [])
    for ts, want in pairs:
        code = None
        if frs:
            near = min(frs, key=lambda fr: abs((fr[0] - ts).total_seconds()))
            if abs((near[0] - ts).total_seconds()) <= 5.0:
                code = near[1]
        if code in guard_codes:
            guarded[code] += 1
        else:
            unexplained.append((ts, want))
    return guarded, unexplained


def _heat_protect_summary(tiers, flags, flag_labels, hours):
    """극한 고온 보호(CH75·76) → 활성 분·단계 전환·플래그 분포. 기록이 없으면 None.

    `tiers`/`flags` 는 [(ts, 값)]. 활성 시간은 **사이클 간격**으로 센다 — 보호 단계는
    매 사이클 남으므로 표본 하나가 그 간격만큼의 상태다. 간격이 중앙값의 3배를 넘으면
    (사이클이 빠졌다) 중앙값만큼만 센다 — 멈춘 시간을 보호 중으로 부풀리지 않는다.
    """
    if not tiers:
        return None
    tiers = sorted(tiers)
    gaps = [(b[0] - a[0]).total_seconds() for a, b in zip(tiers, tiers[1:])]
    med = sorted(gaps)[len(gaps) // 2] if gaps else 0.0
    active_s = tier2_s = 0.0
    for i, (ts, tier) in enumerate(tiers):
        g = gaps[i] if i < len(gaps) else med
        if med and g > med * 3:
            g = med
        if tier >= 1:
            active_s += g
        if tier >= 2:
            tier2_s += g
    transitions = []
    for (_t0, a), (t1, b) in zip(tiers, tiers[1:]):
        if int(a) != int(b):
            transitions.append((t1, int(a), int(b)))
    counts = {}
    for _ts, v in flags or []:
        mask = int(v)
        for bit, label in flag_labels:
            if mask & bit:
                counts[label] = counts.get(label, 0) + 1
    span_h = hours if hours else 1
    return {
        'samples': len(tiers),
        'active_min': active_s / 60.0,
        'tier2_min': tier2_s / 60.0,
        'transitions': len(transitions),
        'transitions_per_h': len(transitions) / span_h,
        'transition_times': [(t.isoformat(), a, b) for t, a, b in transitions[:12]],
        'flags': counts,
    }


def _frost_summary(gate_events, median_gap_s):
    """안전 게이트 마스크의 서리 비트 → 주의·보호 분과 진입 횟수. 서리가 한 번도 없었으면 None.

    서리 단계는 따로 채널을 두지 않는다 — 단계가 서 있는 사이클은 게이트가 마스크를 남기므로
    (`GATE_BIT_FROST_WATCH`·`GATE_BIT_FROST`, 둘은 함께 서지 않는다) 표본 하나가 사이클 간격만큼의
    상태다. 서 있지 않은 사이클은 기록이 없다. 사이클 간격 3배 넘게 비면 다른 진입으로 센다.
    """
    ev = sorted((ts, int(v)) for ts, v in gate_events if v >= 0)
    gap = float(median_gap_s or 0.0)
    watch_s = protect_s = 0.0
    entries = []
    last_ts = None
    last_lv = 0
    for ts, mask in ev:
        lv = 2 if mask & LC.GATE_BIT_FROST else (1 if mask & LC.GATE_BIT_FROST_WATCH else 0)
        if not lv:
            last_lv = 0
            continue
        if lv == 2:
            protect_s += gap
        else:
            watch_s += gap
        fresh = (last_ts is None or not gap
                 or (ts - last_ts).total_seconds() > gap * 3)
        if lv == 2 and (fresh or last_lv < 2):
            entries.append(ts)
        last_ts, last_lv = ts, lv
    if not (watch_s or protect_s):
        return None
    return {'watch_min': watch_s / 60.0, 'protect_min': protect_s / 60.0,
            'protect_entries': len(entries),
            'protect_times': [t.isoformat() for t in entries[:6]]}


def _bucket_means(series, step_s):
    """[(epoch, 값)] → {격자 시작 epoch: 평균}. 값이 숫자가 아닌 표본은 건너뛴다."""
    acc = {}
    for ts, v in series or []:
        try:
            ts, v = float(ts), float(v)
        except (TypeError, ValueError):
            continue
        if v != v:                                   # NaN
            continue
        b = int(ts // step_s) * step_s
        tot, n = acc.get(b, (0.0, 0))
        acc[b] = (tot + v, n + 1)
    return {b: tot / n for b, (tot, n) in acc.items()}


def _merge_sensors(series_list, step_s):
    """센서 여럿 → 격자마다 센서별 평균의 평균(센서가 많은 쪽이 표본 수로 이기지 않게)."""
    per = [_bucket_means(s, step_s) for s in series_list or []]
    out = {}
    for b in sorted(set().union(*per) if per else ()):
        vals = [m[b] for m in per if b in m]
        out[b] = sum(vals) / len(vals)
    return out


def _exposure_summary(t_series, rh_series, is_night, step_s=EXPOSURE_STEP_S):
    """실내 온·습도 → 밤 이슬 분·서리 분. 온도와 습도가 **함께** 있는 격자만 센다. 기록이 없으면 None.

    `t_series`/`rh_series` 는 센서별 [(epoch, 값)] 의 목록, `is_night(epoch)` 는 True/False/None(모름).
    밤을 모르는 격자(좌표 없음)는 밤으로 세지 않는다 — `night_known` 이 False 면 밤 이슬 분은 0 이 아니라 "못 셈" 이다.
    서리 분(실내 ≤ 0 °C)은 낮밤을 가리지 않는다.
    """
    T = _merge_sensors(t_series, step_s)
    RH = _merge_sensors(rh_series, step_s)
    both = sorted(set(T) & set(RH))
    if not both:
        return None
    night_n = dew_n = frost_n = known_n = 0
    t_min = None
    for b in both:
        t, rh = T[b], RH[b]
        t_min = t if t_min is None else min(t_min, t)
        if t <= 0.0:
            frost_n += 1
        night = is_night(b + step_s / 2.0)
        if night is None:
            continue
        known_n += 1
        if not night:
            continue
        night_n += 1
        td = HR.dewpoint_c(t, rh)
        if rh >= NIGHT_DEW_RH_PCT or (td is not None and t - td < NIGHT_DEW_MARGIN_C):
            dew_n += 1
    k = step_s / 60.0
    return {'covered_min': len(both) * k, 'night_min': night_n * k,
            'night_dew_min': dew_n * k, 'frost_min': frost_n * k,
            'indoor_T_min': t_min, 'night_known': bool(known_n)}


def _exposure_advice(summary, kinds, frost=None):
    """노출이 크면 시설 권고 문장들 → [str]. 코디네이터 결함이 아니라 시설 몫이라 '볼 것' 으로 세지 않는다.

    `kinds` 는 이 코디네이터 장치 종류의 집합(순환팬·난방기 유무로 문장을 바꾼다),
    `frost` 는 `_frost_summary` 결과(서리 보호 분)."""
    out = []
    if not summary:
        return out
    kinds = set(kinds or ())
    night = summary['night_min']
    dew = summary['night_dew_min']
    if dew >= EXPOSURE_DEW_MIN and night and dew >= EXPOSURE_DEW_SHARE * night:
        line = (f'밤 이슬 위험이 큽니다 — 밤 {night:.0f}분 중 {dew:.0f}분({dew * 100.0 / night:.0f}%)이'
                f' 실내 습도 {NIGHT_DEW_RH_PCT:.0f}% 이상이거나 이슬점 여유 {NIGHT_DEW_MARGIN_C:g} °C 미만 —'
                ' 제습기·보온커튼·난방 검토')
        if 'circulation_fan' not in kinds:
            line += ' (순환팬이 없습니다 — 공기를 움직이면 잎이 젖어 있는 시간이 줄어듭니다)'
        out.append(line)
    fr_min = summary['frost_min']
    prot = (frost or {}).get('protect_min', 0.0)
    if fr_min >= EXPOSURE_FROST_MIN or prot >= EXPOSURE_FROST_PROTECT_MIN:
        line = (f'서리 위험 — 실내 0 °C 이하 {fr_min:.0f}분(최저 {summary["indoor_T_min"]:.1f} °C)'
                + (f' · 서리 보호 {prot:.0f}분' if prot else '') + ' — 보온커튼·난방 검토')
        if 'heater' not in kinds:
            line += ' (난방기가 없어 보호는 닫기만 합니다)'
        out.append(line)
    return out


def _night_checker(target_id):
    """epoch → 그 시각 시설 위치가 밤인가(True/False), 모르면 None. 같은 10분 격자는 한 번만 묻는다."""
    cache = {}

    def check(epoch):
        key = int(epoch // 600)
        if key not in cache:
            try:
                from aot.utils.solar import is_daytime
                day = is_daytime(target_id=target_id,
                                 at=datetime.fromtimestamp(epoch, timezone.utc))
                cache[key] = None if day is None else (not day)
            except Exception:                                # noqa: BLE001
                cache[key] = None
        return cache[key]
    return check


def _fetch_indoor_series(facility_uuid, hours):
    """시설의 실내 온도·습도 센서 이력 → (온도 시계열 목록, 습도 시계열 목록). 못 읽으면 ([], [])."""
    if not facility_uuid:
        return [], []
    try:
        from aot.space.facility_integration import get_facility_integration
        from aot.utils.influx import get_past_measurements
        data, err = get_facility_integration(facility_uuid)
        if err or not isinstance(data, dict):
            return [], []
        out = {'temperature': [], 'humidity': []}
        seen = set()
        for sensor in data.get('sensors_resolved') or []:
            mtype = sensor.get('measurement_type')
            iid, mid = sensor.get('input_uuid'), sensor.get('measurement_id')
            if mtype not in out or not iid or not mid or (iid, mid) in seen:
                continue
            seen.add((iid, mid))
            rows = get_past_measurements(iid, mid, max_age=int(hours * 3600)) or []
            if rows:
                out[mtype].append(rows)
        return out['temperature'], out['humidity']
    except Exception:                                        # noqa: BLE001
        return [], []


STATUS_NAME = {code: name for name, code in SS.STATUS_CODES.items()}
VPD_SOURCE_NAME = {code: name for name, code in SS.VPD_SOURCE_CODES.items()}


def _summarize_sensor_status(by_channel):
    """`sensor_status` 측정(CH80~91)을 축별 상태 분포로 접는다.

    반환 `None` = 기록이 없다. **0 으로 보고하지 않는다** — 디버그 로깅이 꺼진
    코디네이터는 이 값을 쓰지 않으므로, 기록 없음과 "전부 valid" 는 다르다.
    `axes` 는 valid 가 아닌 상태가 한 번이라도 있던 축만 담는다(valid 만 있는 축은
    조용하다). out_of_range·frozen 은 제어에서 빠진 값이라 `problem` 으로 올린다.
    """
    if not by_channel:
        return None
    axes = {}
    records = 0
    for axis in LC.SENSOR_STATUS_AXES:
        values = by_channel.get(LC.ch_sensor_status(axis)) or []
        records = max(records, len(values))
        counts = Counter(STATUS_NAME.get(int(v), f'코드 {int(v)}') for _t, v in values)
        if any(name != SS.VALID for name in counts):
            axes[axis] = dict(counts)
    src = Counter(VPD_SOURCE_NAME.get(int(v), f'코드 {int(v)}')
                  for _t, v in by_channel.get(LC.CH_VPD_SOURCE) or [])
    diffs = [v for _t, v in by_channel.get(LC.CH_VPD_DEVICE_DIFF) or []]
    return {
        'records': records,
        'axes': axes,
        'out_of_range': {a: c[SS.OUT_OF_RANGE] for a, c in axes.items()
                         if c.get(SS.OUT_OF_RANGE)},
        'frozen': {a: c[SS.FROZEN] for a, c in axes.items() if c.get(SS.FROZEN)},
        'vpd_source': dict(src),
        'vpd_device_diff_mean': (sum(diffs) / len(diffs)) if diffs else None,
        'vpd_device_diff_max_abs': max((abs(v) for v in diffs), default=None),
    }


def _state_minutes(series):
    """매 사이클 남는 상태 채널(CH92·93) → {값: 분}. 기록이 없으면 None.

    `_heat_protect_summary` 와 같은 규칙이다 — 표본 하나가 다음 표본까지의 간격만큼의
    상태이고, 중앙값의 3배를 넘는 공백(재시작)은 중앙값만큼만 센다(멈춘 시간을 그 상태로
    부풀리지 않는다). 0 분과 "기록 없음" 을 섞지 않으려고 빈 입력은 None 이다.
    """
    if not series:
        return None
    series = sorted(series)
    gaps = [(b[0] - a[0]).total_seconds() for a, b in zip(series, series[1:])]
    med = sorted(gaps)[len(gaps) // 2] if gaps else 0.0
    out = {}
    for i, (_ts, v) in enumerate(series):
        g = gaps[i] if i < len(gaps) else med
        if med and g > med * 3:
            g = med
        out[int(v)] = out.get(int(v), 0.0) + g / 60.0
    return out


def _water_summary(series):
    """분무용 물 공급(CH92) → 상태별 분. 옵션을 켜지 않은 코디네이터는 None(기록이 없다)."""
    mins = _state_minutes(series)
    if mins is None:
        return None
    return {
        'ok_min': mins.get(WS.WATER_OK, 0.0),
        'low_min': mins.get(WS.WATER_LOW, 0.0),
        'stale_min': mins.get(WS.WATER_STALE, 0.0),
    }


def _vpd_basis_summary(series):
    """VPD 목표 기준(CH94) → 상태별 분. 엽온을 묶지 않은 공기 기준은 None(기록이 없다).

    `leaf_fallback_min` 은 **잎 기준으로 정했는데 엽온을 못 써 공기 기준으로 돈** 시간이다 —
    목표의 뜻이 그동안 달랐다(잎 목표 숫자를 공기 VPD 로 좇았다).
    """
    mins = _state_minutes(series)
    if mins is None:
        return None
    return {
        'air_min': mins.get(LV.TARGET_AIR, 0.0),
        'leaf_min': mins.get(LV.TARGET_LEAF, 0.0),
        'leaf_fallback_min': mins.get(LV.TARGET_LEAF_FALLBACK, 0.0),
    }


def _suspect_summary(series):
    """의심 액추에이터 보류(CH93) → 보류 분·최대 대수. 한 번도 없으면 None.

    CH93 은 의심이 있는 동안과 끝난 사이클(0 표식)에만 남는다 — 기록이 없다는 것은 의심이
    없었다는 뜻이다(`_state_minutes` 와 달리 '기록 없음' 이 곧 0 이다). 그래서 None 이 정상이다.
    """
    if not series:
        return None
    mins = _state_minutes([(t, 1.0 if v > 0 else 0.0) for t, v in series])
    return {'held_min': (mins or {}).get(1, 0.0),
            'max_count': int(max(v for _t, v in series))}


def _count_reversals(samples, min_delta):
    """방향을 뒤집은 횟수. 잔물결은 `min_delta` 로 걸러 낸다.

    작은 흔들림까지 세면 PWM 이나 반올림이 진동으로 보인다. 사람이 "떤다"고
    말하는 것은 눈에 보이는 크기의 왕복이라, 그 크기를 인자로 받는다.
    """
    reversals = 0
    direction = 0
    last = None
    for _ts, value in samples:
        if last is None:
            last = value
            continue
        delta = value - last
        if abs(delta) < min_delta:
            continue
        sign = 1 if delta > 0 else -1
        if direction and sign != direction:
            reversals += 1
        direction = sign
        last = value
    return reversals


def analyse(row, hours, min_delta):
    """코디네이터 하나를 훑는다. 반환은 화면·JSON 이 함께 쓰는 dict."""
    opts = json.loads(row.custom_options or '{}')
    facility_uuid = opts.get('geo_facility_id') or ''
    directory = _actuator_directory(facility_uuid)

    rows = _fetch_series(row.unique_id, hours)

    cmd_by_act = defaultdict(list)          # 코디네이터가 **요청한** 값 (CH40+)
    reason_by_act = defaultdict(list)
    final_by_act = defaultdict(list)        # 게이트까지 지난 **최종** 값 (CH100+)
    final_reason_by_act = defaultdict(list)
    env_by_channel = defaultdict(list)
    status_by_channel = defaultdict(list)   # measurement 'sensor_status' (CH80~91)
    gb_by_channel = Counter()               # 그림자 기록 수(채널별)
    gate_events = []
    dispatch_fail = []
    clean_flags = []
    mismatch = []
    heat_tiers = []                         # 극한 고온 보호 단계 (CH75, 매 사이클)
    heat_flags = []                         # 극한 고온 보호 플래그 (CH76)
    water_state = []                        # 분무용 물 공급 (CH92, 옵션을 켠 코디네이터만)
    suspect_state = []                      # 제어에서 뺀 의심 액추에이터 수 (CH93, 있을 때만)
    vpd_basis_state = []                    # VPD 목표 기준 (CH94, 엽온을 묶었거나 잎 기준일 때만)

    for ts, measurement, channel, value in rows:
        if measurement.startswith('coord_actuator_'):
            body = measurement[len('coord_actuator_'):]
            # ⚠ 순서 주의 — '_final_reason' 은 '_reason' 으로도 끝난다.
            # 긴 접미사를 먼저 보지 않으면 최종 근거가 요청 근거로 섞여 들어간다.
            if body.endswith('_final_reason'):
                final_reason_by_act[body[:-len('_final_reason')]].append(
                    (ts, int(value)))
            elif body.endswith('_final'):
                final_by_act[body[:-len('_final')]].append((ts, float(value)))
            elif body.endswith('_command'):
                cmd_by_act[body[:-len('_command')]].append((ts, float(value)))
            elif body.endswith('_reason'):
                reason_by_act[body[:-len('_reason')]].append((ts, int(value)))
        elif measurement == 'env_greybox':
            # 그림자(물리 모델)가 남기는 것. 채널 0~5 는 1스텝 예측·오차,
            # 6~13 은 MPC 그림자, 14~15 는 일사 선행이다 — **출처가 달라**
            # 하나가 죽어도 나머지는 계속 쌓인다(그래서 따로 센다).
            try:
                gb_by_channel[int(channel)] += 1
            except (TypeError, ValueError):
                pass
        elif measurement == 'env_control':
            try:
                env_by_channel[int(channel)].append((ts, float(value)))
            except (TypeError, ValueError):
                pass
        elif measurement == LC.MEAS_SENSOR_STATUS:
            try:
                status_by_channel[int(channel)].append((ts, float(value)))
            except (TypeError, ValueError):
                pass
        elif measurement == 'safety_gate_active':
            gate_events.append((ts, float(value)))
        elif measurement == 'dispatch_fail_count':
            dispatch_fail.append((ts, float(value)))
        elif measurement == 'clean_for_learning':
            clean_flags.append((ts, float(value)))
        elif measurement == 'actuator_mismatch_count':
            mismatch.append((ts, float(value)))
        elif measurement == 'heat_protect_tier':
            heat_tiers.append((ts, float(value)))
        elif measurement == 'heat_protect_flags':
            heat_flags.append((ts, float(value)))
        elif measurement == 'water_supply_state':
            water_state.append((ts, float(value)))
        elif measurement == 'actuator_suspect_count':
            suspect_state.append((ts, float(value)))
        elif measurement == 'vpd_target_basis':
            vpd_basis_state.append((ts, float(value)))

    # ── 사이클 리듬 ────────────────────────────────────────────────────────
    # ⚠ **`safety_gate_active` 도 사이클 신호에 넣는다** (2026-09-03). 안전
    #   게이트가 걸리면 `_cycle_mixin.py` 가 L1~L3 전에 조기 반환해
    #   `coord_actuator_*` 를 한 줄도 안 쓴다 — 그 전에는 여기서 `cmd_by_act`
    #   만 봤으므로, 강우가 몇 시간 이어지면 코디네이터가 **실제로는 매
    #   사이클 정상 실행 중**인데도 "결정 로그가 없다"(cycles=0) 로 보였다.
    #   실측: 쿠마모토가 강우 게이트로 5시간 동안 이 상태였고, 그동안 이
    #   스크립트와 데몬 로그만 보면 "코디네이터가 멈췄다"와 구분되지 않았다
    #   (반면 `get_control_state` 의 실시간 요약은 `_write_gate_only_summary`
    #   덕에 이미 최신이었다 — 2026-08-26에 화면 쪽만 먼저 고쳐졌었다).
    #   `safety_gate_active` 는 게이트가 걸린 사이클에만 쓰이고 정상 사이클과
    #   겹치지 않으므로(트리거되면 그 자리에서 반환, `coord_actuator_*` 는
    #   안 쓴다) 합쳐도 사이클이 중복 세어지지 않는다.
    #
    # 한 사이클은 액추에이터 수만큼 행을 남기고 그것들이 거의 같은 순간에
    # 몰린다. 타임스탬프를 그대로 세면 **사이클 수가 액추에이터 배로 부풀고
    # 중앙 간격이 0 초가 된다**(첫 실행에서 실제로 그렇게 나왔다).
    cmd_stamps = sorted(ts for series in cmd_by_act.values() for ts, _ in series)
    gate_stamps = sorted(ts for ts, _ in gate_events)
    stamps = _cluster_cycles(cmd_stamps + gate_stamps)
    gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]
    median_gap = statistics.median(gaps) if gaps else 0.0
    # 중앙값의 3배를 넘는 간격 = 사이클이 통째로 빠진 것. 재시작·정지·멈춤.
    long_gaps = [g for g in gaps if median_gap and g > median_gap * 3]

    # ── 액추에이터 축 ──────────────────────────────────────────────────────
    span_h = hours if hours else 1
    actuators = []
    kind_by_prefix = {}
    for prefix in sorted(set(cmd_by_act) | set(final_by_act)):
        requested = cmd_by_act.get(prefix, [])
        final = final_by_act.get(prefix, [])
        name, kind = directory.get(prefix) or _name_from_db(prefix)
        kind_by_prefix[prefix] = kind

        # **통계는 최종값 기준이다.** 요청값(CH40)은 게이트·감쇠·인터록을 지나기
        # 전이라 "요청했다"이지 "작동했다"가 아니다. 최종값이 없는 구간(이 기록을
        # 넣기 전에 돈 코디네이터)만 요청값으로 되돌아가고, 그 사실을 함께 낸다 —
        # 조용히 폴백하면 옛 데이터와 새 데이터가 같은 뜻으로 보인다.
        samples = final or requested
        source = 'final' if final else 'requested'
        values = [v for _t, v in samples]
        rsrc = final_reason_by_act.get(prefix) if final else None
        reasons = Counter(code for _t, code in
                          (rsrc if rsrc else reason_by_act.get(prefix, [])))
        total_reasons = sum(reasons.values()) or 1
        top = [(REASON_LABEL.get(c, f'코드 {c}'), n * 100.0 / total_reasons)
               for c, n in reasons.most_common(3)]
        flags = _activity_flags(values, reasons)
        # 의심 장치로 보류된 사이클 수 — 이 근거가 보이면 코디네이터가 그 장치를 부하 분담에서 빼고
        # 제자리에 둔 것이다(전송도 하지 않았다). 설계된 보호이지만 사람이 장치를 점검해야 끝난다.
        suspect_cycles = reasons.get(LC.REASON_ACTUATOR_SUSPECT, 0)
        req_values = [v for _t, v in requested]
        # 스크린은 0 이 위치(닫힘)라 억제로 세지 않는다(SCREEN_KINDS 주석).
        if kind in SCREEN_KINDS:
            pairs = []
        else:
            pairs = _suppressed_pairs(requested, final)
        guarded, unexplained = _split_suppressed(
            pairs, final_reason_by_act.get(prefix), GUARD_REASONS)
        actuators.append({
            'prefix': prefix,
            'name': name,
            'kind': kind,
            'domain': ACTUATOR_DOMAIN.get(kind, DEFAULT_DOMAIN),
            'samples': len(values),
            'source': source,
            'mean': sum(values) / len(values) if values else 0.0,
            'max': max(values) if values else 0.0,
            'requested_mean': (sum(req_values) / len(req_values)
                               if req_values else 0.0),
            'requested_max': max(req_values) if req_values else 0.0,
            'suspect_cycles': suspect_cycles,
            'suppressed': len(unexplained),
            'suppressed_max': max((w for _t, w in unexplained), default=0.0),
            'guarded': {REASON_LABEL.get(c, f'코드 {c}'): n
                        for c, n in guarded.most_common()},
            'reversals': _count_reversals(samples, min_delta),
            'reversals_per_h': _count_reversals(samples, min_delta) / span_h,
            'top_reasons': top,
            **flags,
        })

    # ── 상반 가동 ──────────────────────────────────────────────────────────
    # 고정폭 버킷은 경계에 걸친 사이클을 둘로 쪼갠다. 위에서 이미 실제 사이클
    # 시작 시각을 뽑아 두었으니 그것에 붙인다 — 판정이 주기 설정과 무관해진다.
    active = defaultdict(set)               # 사이클 인덱스 → {kind}
    for prefix, samples in cmd_by_act.items():
        kind = kind_by_prefix.get(prefix) or ''
        if not kind:
            continue
        for ts, value in samples:
            if value > 0:
                active[_cycle_index(stamps, ts)].add(kind)
    conflicts = sum(1 for kinds in active.values()
                    if (kinds & WARMING_KINDS) and (kinds & COOLING_KINDS))
    heat_while_vent = sum(1 for kinds in active.values()
                          if (kinds & WARMING_KINDS) and (kinds & VENT_KINDS))
    heat_while_fog = sum(1 for kinds in active.values()
                         if (kinds & WARMING_KINDS) and (kinds & HUMIDIFY_KINDS))
    cycles_seen = len(active) or 1

    # ── 모드·제한인자·안전 (디버그 로깅이 켜져 있을 때만 존재) ────────────
    modes = Counter(int(v) for _t, v in env_by_channel.get(72, []))
    limits = Counter(int(v) for _t, v in env_by_channel.get(71, []))
    have_env = bool(modes or limits)

    gate_bits = Counter()
    post_gate_corrections = 0
    for _ts, value in gate_events:
        if value < 0:
            post_gate_corrections += 1
            continue
        mask = int(value)
        for bit, label in GATE_LABEL:
            if mask & bit:
                gate_bits[label] += 1

    clean_ratio = (sum(1 for _t, v in clean_flags if v >= 0.5) * 100.0
                   / len(clean_flags)) if clean_flags else None

    # 클러스터된 사이클 중 `coord_actuator_*` 가 하나도 없는 것 = 게이트만
    # 남긴 사이클. `cycles` 에는 포함시키되(방금 위에서 그렇게 했다) 몇 회가
    # 그런 것인지는 따로 말한다 — 안 그러면 "5시간째 게이트로 쉬는 중"과
    # "정상적으로 5시간 잘 돌았다"가 숫자만 봐서는 구분되지 않는다.
    cmd_cycles = set(_cluster_cycles(cmd_stamps))
    gate_only_cycles = sum(
        1 for g in _cluster_cycles(gate_stamps)
        if not any(abs((g - c).total_seconds()) < 5.0 for c in cmd_cycles))

    # ── 밤 이슬·서리 노출(시설 몫 — 코디네이터 결함과 섞지 않는다) ─────────────
    t_series, rh_series = _fetch_indoor_series(facility_uuid, hours)
    exposure = _exposure_summary(t_series, rh_series, _night_checker(row.unique_id))
    frost_sum = _frost_summary(gate_events, median_gap)
    exposure_advice = _exposure_advice(
        exposure, {a['kind'] for a in actuators if a.get('kind')}, frost_sum)

    return {
        'uuid': row.unique_id,
        'name': row.name,
        'facility_uuid': facility_uuid,
        'debug_logging': bool(row.log_level_debug),
        'cycles': len(stamps),
        'gate_only_cycles': gate_only_cycles,
        'median_gap_s': median_gap,
        'long_gaps': len(long_gaps),
        'first': stamps[0].isoformat() if stamps else None,
        'last': stamps[-1].isoformat() if stamps else None,
        'actuators': actuators,
        'opposing_cycles': conflicts,
        'opposing_pct': conflicts * 100.0 / cycles_seen,
        'heat_while_vent_cycles': heat_while_vent,
        'heat_while_fog_cycles': heat_while_fog,
        'post_gate_corrections': post_gate_corrections,
        'have_env_metrics': have_env,
        'modes': {MODE_LABEL.get(c, f'코드 {c}'): n for c, n in modes.most_common()},
        'emergency_pct': (modes.get(99, 0) * 100.0 / sum(modes.values())
                          if modes else None),
        'limits': {LIMIT_LABEL.get(c, f'코드 {c}'): n for c, n in limits.most_common()},
        'gates': dict(gate_bits),
        'frost': frost_sum,
        'exposure': exposure,
        'exposure_advice': exposure_advice,
        'dispatch_fail_total': int(sum(v for _t, v in dispatch_fail)),
        'actuator_mismatch_max': int(max((v for _t, v in mismatch), default=0)),
        'clean_ratio': clean_ratio,
        'greybox_records': dict(gb_by_channel),
        'heat_protect': _heat_protect_summary(heat_tiers, heat_flags,
                                              HP_FLAG_LABEL, hours),
        'sensor_status': _summarize_sensor_status(status_by_channel),
        'water_supply': _water_summary(water_state),
        'suspected': _suspect_summary(suspect_state),
        'vpd_basis': _vpd_basis_summary(vpd_basis_state),
        'settings': (_check_settings(opts, facility_uuid, row)
                     + _check_shadow_alive(opts, gb_by_channel, len(stamps))),
    }


# ── 설정 점검 ───────────────────────────────────────────────────────────────

def _check_settings(opts, facility_uuid, row=None):
    """오늘 실제로 밟은 지뢰들만 본다. 추측으로 항목을 늘리지 않는다."""
    findings = []

    # `schedule_end_time`(코디네이터 자기 종료일)은 2026-09-01 부로 없다 —
    # 구획을 새로 심어도 사람이 그 날짜를 다시 고치기 전까지 계속 멈춰
    # 있던 것이 실제 사고였다(영양·쿠마모토, 구획을 갈아 심었는데도 8월
    # 31일 종료로 굳어 있었다). 대신 구획의 `expected_end_on`(진행 중인
    # 구획의 예상 종료 — 실제로 끝난 것이 아니라 아직 임박 여부만 알린다)
    # 이 임박했는지만 본다. `ended_on` 이 지난 구획은 R2 가 이미 걷어내
    # 여기까지 올라오지 않으므로 '지나서 제어가 멈춘다' 는 경우 자체가 없다.
    if row is not None:
        try:
            from aot.aot_flask.geo import coordinator_plot
            expected = coordinator_plot.control_targets(row).get('expected_end_on')
        except Exception:                                     # noqa: BLE001
            expected = None
        if expected:
            left = (expected - today_at(FARM)).days
            if 0 <= left <= 7:
                findings.append(('warn',
                    f'구획 예상 종료일 {expected} 까지 {left}일 남았습니다 — '
                    f'제어는 멈추지 않고 다음 구획/guide 범위로 넘어갑니다'))

    # 유도 범위가 하드 임계 밖이면 매 사이클 ERROR 를 찍는다. 슬라이더 한 번이면
    # 풀리는데, 로그만 보면 제어 결함처럼 읽힌다.
    pairs = (('guide_T_min', 'guide_T_max', 'temp_min', 'temp_max', '온도'),
             ('guide_RH_min', 'guide_RH_max', None, None, '습도'))
    for g_lo_k, g_hi_k, h_lo_k, h_hi_k, label in pairs:
        if not h_lo_k:
            continue
        g_lo, g_hi = opts.get(g_lo_k), opts.get(g_hi_k)
        h_lo, h_hi = opts.get(h_lo_k), opts.get(h_hi_k)
        if None in (g_lo, g_hi, h_lo, h_hi):
            continue
        if g_lo < h_lo or g_hi > h_hi:
            findings.append((
                'warn',
                f'{label} 유도 범위({g_lo:g}~{g_hi:g})가 하드 임계'
                f'({h_lo:g}~{h_hi:g}) 밖입니다 — 매 사이클 경고가 납니다'))

    findings.extend(_check_sensor_freshness(opts, facility_uuid))
    findings.extend(_check_light_band(opts, facility_uuid))
    findings.extend(_check_combinations(opts, facility_uuid, row))
    findings.extend(_check_shared_actuators(facility_uuid, row))
    findings.extend(_check_vent_azimuth(facility_uuid))
    return findings


# @manual ai/env-control#safety-gates
def _check_vent_azimuth(facility_uuid):
    """풍향 센서는 있는데 개구부 방위각이 없으면 강풍 1단계가 풍향별로 못 가른다 (2026-10-10).

    강풍 1단계(`safety_gates.classify_wind`, 근거 55)는 풍상측 개구부만 닫고 풍하측은 상한까지
    쓴다. 방위각을 모르면 풍상측인지 알 수 없어 **천창은 닫고 측창은 상한(50 %)만** 건다 —
    바람 받는 측창이 반쯤 열린 채 남을 수 있다. 김제 측창 둘이 그 상태였는데 화면도 로그도
    조용했다(폭풍 시뮬 `foehn_dry_wind`). 방위각은 개구부 장치를 지도 도형(GeoShape)에 묶으면
    도형에서 나온다(`facility_geo_helpers.shape_azimuth_area`).

    풍향 채널이 없으면 방위각이 있어도 쓸 데가 없으므로 보고하지 않는다.
    """
    if not facility_uuid:
        return []
    try:
        from aot.space.facility_integration import get_facility_integration
        from aot.space.device_binding import shapes_for_devices
        from aot.space.facility_geo_helpers import shape_azimuth_area
        data, err = get_facility_integration(facility_uuid)
        if err or not isinstance(data, dict):
            return []
        outdoor = {(x.get('measurement_type') or '').strip()
                   for x in (data.get('sensors_outdoor') or []) if x.get('input_uuid')}
        if 'wind_direction' not in outdoor:
            return []
        openings = {a.get('output_uuid'): a.get('output_name')
                    for a in (data.get('actuators_resolved') or [])
                    if a.get('kind') == 'opening' and a.get('output_uuid')}
        if not openings:
            return []
        shapes = shapes_for_devices(list(openings))
        missing = []
        for oid, name in sorted(openings.items(), key=lambda kv: kv[1] or kv[0]):
            rows = shapes.get(oid) or []
            az = None
            if rows and getattr(rows[0], 'feature', None):
                az, _area = shape_azimuth_area(rows[0].feature)
            if az is None:
                missing.append(name or oid[:8])
    except Exception:                                        # noqa: BLE001
        return []
    if not missing:
        return []
    return [('warn',
             f'측창 방위각 미설정 — 풍향별 닫기를 못 함: {", ".join(missing)}. '
             f'강풍 1단계(10분 평균 ≥ 문턱의 0.6 배)에서 풍상측을 가르지 못해 천창은 닫고 '
             f'측창은 상한만 겁니다. 개구부 장치를 지도 도형에 묶으면 방위각이 생깁니다')]


def _check_shadow_alive(opts, gb_by_channel, n_cycles):
    """그림자를 켜 뒀는데 **예측 기록이 없으면** 말한다.

    ⚠ 이 항목이 있는 이유: 2026-08-04 리팩터가 사이클 길이를 넘기지 않아 그림자
    단계가 매 사이클 NameError 로 죽었는데, 예외가 debug 로 삼켜져 **8주 동안**
    아무도 몰랐다. 그동안 예측·학습·검증 기록이 통째로 비어, 물리 제어로 전환할
    근거가 쌓일 수 없었다. 화면도 로그도 조용했다 — 기록이 **없다는 사실**만이
    유일한 신호였다(2026-09-28).

    MPC 그림자(6~13)는 다른 자리에서 기록하므로, 그것만 있고 0~5 가 없으면
    "예측 단계만 죽었다" 는 뜻이라 따로 말한다.
    """
    engine = (opts.get('effect_engine') or 'legacy').lower()
    if engine not in ('shadow', 'greybox') or n_cycles <= 0:
        return []
    pred = sum(gb_by_channel.get(c, 0) for c in range(0, 6))
    mpc = sum(gb_by_channel.get(c, 0) for c in range(6, 14))
    if pred > 0:
        return []
    if mpc > 0:
        return [('error',
                 '효과 엔진이 %s 인데 **1스텝 예측 기록이 한 건도 없습니다**'
                 '(MPC 그림자는 %d건). 예측·학습·검증이 멈춰 있어 물리 제어로 '
                 '전환할 근거가 쌓이지 않습니다 — 데몬 로그에서 "greybox 그림자" '
                 '실패를 확인하세요' % (engine, mpc))]
    return [('error',
             '효과 엔진이 %s 인데 그림자 기록이 한 건도 없습니다(%d사이클). '
             '모델이 나란히 돌지 않고 있습니다 — 데몬 로그를 확인하세요'
             % (engine, n_cycles))]


def _check_shared_actuators(facility_uuid, row=None):
    """이 코디네이터의 장치를 **다른 시설의 활성 코디네이터도** 제어하는가.

    두 코디네이터가 같은 장치를 잡으면 서로의 명령을 덮어쓴다. 양쪽 결정
    로그에는 각자 정상 근거만 남아서 **근거 분포만 봐서는 절대 안 보인다** —
    실측(2026-09-25 로컬): 쿠마모토가 육묘장3 의 측창을 19일간 함께 제어해
    10분 주기 톱니가 났는데, 이 점검기 출력에는 두 코디네이터 모두 멀쩡했다.

    같은 시설의 코디네이터끼리는 보지 않는다(구역 분할이 정상 구성).
    """
    if not facility_uuid:
        return []
    try:
        from aot.space.facility_integration import get_facility_integration
        mine_integ, err = get_facility_integration(facility_uuid)
        if err or not isinstance(mine_integ, dict):
            return []
        mine = {a.get('output_uuid'): a.get('output_name')
                for a in (mine_integ.get('actuators_resolved') or [])
                if a.get('output_uuid') and a.get('kind')}
        shared = {}
        for other in CustomController.query.filter_by(device='env_coordinator').all():
            if (row is not None and other.unique_id == row.unique_id) \
                    or not other.is_activated:
                continue
            try:
                o = json.loads(other.custom_options or '{}')
            except (TypeError, ValueError):
                continue
            linked = o.get('geo_facility_id') or o.get('geo_facility_id_device_id') or ''
            if not linked or linked == facility_uuid:
                continue
            integ, err = get_facility_integration(linked)
            if err or not isinstance(integ, dict):
                continue
            for a in (integ.get('actuators_resolved') or []):
                oid = a.get('output_uuid')
                if oid in mine and a.get('kind'):
                    shared.setdefault(oid, []).append(other.name)
    except Exception:                                        # noqa: BLE001
        return []
    return [('severe',
             f'장치 "{mine.get(oid) or oid[:8]}" 를 다른 시설의 코디네이터'
             f'({", ".join(sorted(names))})도 제어 중입니다 — 서로의 명령을 '
             f'덮어써 개도가 톱니처럼 오갑니다. 시설 편집기에서 한쪽 연결을 정리하세요')
            for oid, names in sorted(shared.items())]


# ── 센서·장치 조합 ──────────────────────────────────────────────────────────
# 축 → 그 축을 잴 수 있는 measurement_type. 시설 편집기가 쓰는 어휘 그대로다
# (`facility_sensors._MTYPE_KEY`). VPD 채널은 온도·습도를 대신하지 못한다 —
# 제어가 T/RH 로 폴백할 때 필요한 것은 그 둘 자체다.
_AXIS_MTYPE = {'T': 'temperature', 'RH': 'humidity',
               'CO2': 'co2', 'Light': 'light'}
_AXIS_LABEL = {'T': '온도', 'RH': '습도', 'CO2': 'CO₂', 'Light': '광량'}


def _axes_of_kind(kind):
    """이 종류가 실제로 미는 축 {'T','RH',…}. **정본은 authority 표 하나다** —
    여기 표를 한 벌 더 적으면 새 종류가 생길 때 조용히 갈라진다."""
    from aot.functions.utils.env_control.authority import _KIND_AUTHORITY
    return {k.rsplit('_', 1)[0] for k in _KIND_AUTHORITY.get(kind, {})}


def _has_ext_collector():
    """실외 컨텍스트 수집기가 하나라도 활성인가."""
    try:
        return bool(CustomController.query.filter(
            CustomController.device == 'ext_context_collector',
            CustomController.is_activated.is_(True)).first())
    except Exception:                                        # noqa: BLE001
        return False


# @manual ai/env-control#actuators-missing
def _check_combinations(opts, facility_uuid, row=None):
    """센서와 장치의 **조합**이 제어로 이어지는가 (2026-09-20).

    시설마다 장치 구성이 다르고, 측정만 있고 제어가 없는 축(참고값)이나 그
    반대가 정상이다. 그런데 어긋남 중 셋은 **아무 에러 없이 제어를 통째로
    세운다** — 사람은 동작을 며칠 지켜보다 알게 된다.

    보는 것 셋:
      1. 목표는 있는데 **측정**이 없다 — 편차를 못 재 그 축이 제어에서 빠진다.
      2. 목표는 있는데 **장치**가 없다 — 재기는 하는데 움직일 수단이 없다.
      3. **장치**는 있는데 그 장치가 미는 축을 하나도 못 잰다 — 근거가 없어
         영원히 제자리다(근거 21).

    ⚠ **"측정만 있고 목표·장치가 없다" 는 보고하지 않는다.** 그것이 곧 보조
      값(참고용)이고 정상 구성이다 — 제한이 없는 설치를 영구히 빨간불로 두면
      아무도 안 본다(`check_scope_grants` 와 같은 판단).
    """
    if not facility_uuid:
        return []
    try:
        from aot.space.facility_integration import get_facility_integration
        data, err = get_facility_integration(facility_uuid)
        if err or not isinstance(data, dict):
            return []
    except Exception:                                        # noqa: BLE001
        return []

    def _mtypes(rows):
        return {(x.get('measurement_type') or '').strip()
                for x in (rows or []) if x.get('input_uuid')}

    indoor  = _mtypes(data.get('sensors_resolved'))
    outdoor = _mtypes(data.get('sensors_outdoor'))
    kinds   = {(a.get('kind') or '').strip()
               for a in (data.get('actuators_resolved') or [])}
    kinds.discard('')

    measured = {ax for ax, mt in _AXIS_MTYPE.items() if mt in indoor}
    # 광량만 실외로 대신할 수 있다 — 실내 광센서가 없으면 코디네이터가 실외
    # 일사에 차광막 개도와 피복 투과율을 곱해 막 아래 값을 추정한다
    # (`_cycle_mixin.estimate_indoor_light`). 온습도·CO₂ 에는 그런 경로가 없다.
    #
    # ⚠ 실외 일사의 유입구는 **둘**이다 — 시설 도면의 실외 센서와
    #   `ext_context_collector` 의 공유 컨텍스트(`_compute_light_est` 주석).
    #   뒤를 빠뜨리면 수집기로 일사를 받는 설치가 "광 센서를 다세요" 라는
    #   틀린 안내를 받는다. 수집기가 실제로 일사를 싣는지까지는 여기서 알 수
    #   없으므로, 하나라도 활성이면 **보고하지 않는다** — 없는 문제를 만들어
    #   내는 쪽이 놓치는 쪽보다 나쁘다(사람이 찾을 것이 없다).
    if 'light' in outdoor or _has_ext_collector():
        measured.add('Light')

    controlled = set()
    for k in kinds:
        controlled |= _axes_of_kind(k)

    # ── 이 시설이 실제로 목표를 갖는 축 ──────────────────────────────────────
    # 온습도는 언제나 목표가 있다(guide 범위는 끌 수 없다). CO₂·VPD 는 구획
    # 단계 목표가 있을 때만이고, 광량은 상·하한을 적었을 때만이다.
    targeted = {'T', 'RH'}
    if float(opts.get('light_max') or 0) > 0 or float(opts.get('light_min') or 0) > 0:
        targeted.add('Light')
    tgt = {}
    if row is not None:
        try:
            from aot.aot_flask.geo import coordinator_plot
            tgt = coordinator_plot.control_targets(row) or {}
        except Exception:                                    # noqa: BLE001
            tgt = {}
    co2_t = (tgt.get('co2') or {})
    if co2_t.get('value') or co2_t.get('method_id'):
        targeted.add('CO2')

    findings = []

    # 1. 목표는 있는데 측정이 없다
    for ax in sorted(targeted - measured):
        # 온습도가 빠지면 제어 전체가 선다 — 다른 축과 같은 무게가 아니다.
        level = 'severe' if ax in ('T', 'RH') else 'warn'
        findings.append((level,
            f'{_AXIS_LABEL[ax]} 목표는 있는데 측정이 없습니다 — 편차를 잴 수 '
            f'없어 이 축은 제어에서 빠지고, 이 축을 움직이던 장치는 제자리에 '
            f'섭니다(근거 21). 시설 편집기에서 '
            f'{_AXIS_MTYPE[ax]} 채널을 묶으세요'))

    # 2. 목표는 있는데 장치가 없다
    for ax in sorted((targeted & measured) - controlled):
        findings.append(('warn',
            f'{_AXIS_LABEL[ax]} 목표는 있는데 이 축을 움직일 장치가 '
            f'없습니다 — 값은 보이지만 따라갈 수단이 없습니다'))

    # 3. 장치는 있는데 그 장치가 미는 축을 하나도 못 잰다
    for k in sorted(kinds):
        axes = _axes_of_kind(k)
        if not axes or (axes & measured):
            continue
        findings.append(('warn',
            f"'{k}' 장치가 움직이는 축({'·'.join(_AXIS_LABEL.get(a, a) for a in sorted(axes))})"
            f'을 하나도 잴 수 없습니다 — 이 장치는 근거가 없어 계속 제자리입니다'))

    return findings


def _check_light_band(opts, facility_uuid):
    """차광막을 닫으면 하한 아래로 떨어지는 설정인가 (2026-09-16).

    차광막 아래 광량은 `상한 × 총 투과율`(피복 × 차광막) 까지 떨어진다. 그 값이
    하한보다 낮으면 **어떤 개도로도 두 기준을 함께 만족할 수 없다** — 밝아서
    닫으면 이번엔 어둡다고 한다. 제어는 차광을 우선해 왕복만 막고 있으므로,
    고치는 것은 사람 몫이고 그 사실이 어딘가에는 보여야 한다.

    실측(영양 육묘장): 상한 250 · 피복 0.85 · 차광막 0.5 → 닫으면 106 인데
    하한이 150 이었다.
    """
    lmax = float(opts.get('light_max') or 0.0)
    lmin = float(opts.get('light_min') or 0.0)
    if lmax <= 0.0 or lmin <= 0.0 or not facility_uuid:
        return []            # 한쪽을 껐으면 모순이 성립하지 않는다
    try:
        from aot.space.facility_integration import get_facility_integration
        from aot.space.facility_calc import _shade_tau
        data, err = get_facility_integration(facility_uuid)
        if err or not isinstance(data, dict):
            return []
        cover = float((data.get('capacity_meta') or {}).get('transmittance')
                      or (data.get('computed') or {}).get('transmittance') or 0.0)
        shade = (((data.get('envelope') or {}).get('curtain') or {}).get('shade')
                 or {})
        s_tau = _shade_tau(shade) if shade.get('enabled') else 1.0
    except Exception:                                        # noqa: BLE001
        return []
    tau = cover * s_tau
    if not (0.0 < tau <= 1.0):
        return []
    closed = lmax * tau
    if lmin < closed:
        return []            # 닫아도 하한 위다 — 정상
    return [(
        'warn',
        f'광량 상·하한이 모순입니다 — 상한 {lmax:g} 에서 차광막을 닫으면'
        f' {closed:.0f} W/m² 이라 하한 {lmin:g} 아래입니다(총 투과율 {tau:.2f}).'
        f' 하한을 {closed:.0f} 미만으로 낮추거나 상한을 {lmin / tau:.0f} 이상으로'
        f' 올리세요 — 그때까지 보광·개방 강제는 서지 않습니다')]


def _check_sensor_freshness(opts, facility_uuid):
    """신선도 상한이 센서의 실제 기록 주기보다 짧으면 그 값은 **늘** 만료다.

    제어 경로에서는 코디네이터가 항상 숫자를 넘기므로(안전 결정) 주기로 넓혀
    주지 않는다. 그래서 40분마다 깨는 노드에 20분 상한을 걸면 그 센서는 화면에
    보이는데 제어에서는 통째로 빠진다 — 그리고 아무 에러도 나지 않는다.
    """
    findings = []
    max_age = opts.get('sensor_max_age')
    if not max_age or not facility_uuid:
        return findings

    try:
        from aot.space.facility_integration import get_facility_integration
        data, err = get_facility_integration(facility_uuid)
        if err or not isinstance(data, dict):
            return findings
    except Exception:                                        # noqa: BLE001
        return findings

    # ⚠ **실외를 빠뜨리지 말 것.** `sensors_resolved` 에는 실내만 들어간다 —
    # 실외 바인딩은 `sensors_outdoor` 라는 별도 목록이다. 처음에 앞의 것만 보다가
    # 정작 망가진 쪽을 통째로 못 봤다(육묘장3: 기상청 주기 300초에 상한 120초라
    # 실외값이 늘 만료였고, 개구부가 24시간 내내 '실외 값 없음' 으로 멈춰 있었다).
    # 실외는 개구부·안전 게이트의 유일한 근거라 오히려 이쪽이 더 중요하다.
    buckets = (('실내', data.get('sensors_resolved') or []),
               ('실외', data.get('sensors_outdoor') or []))

    seen = set()
    for role, sensors in buckets:
        for sensor in sensors:
            input_uuid = sensor.get('input_uuid') or sensor.get('device_uuid') or ''
            if not input_uuid or input_uuid in seen:
                continue
            seen.add(input_uuid)
            inp = Input.query.filter(Input.unique_id == input_uuid).first()
            if not inp or not inp.period:
                continue
            # 장치가 스스로 상한을 들고 있으면 그것이 이긴다 — 그때는 코디네이터
            # 값과 비교할 일이 없다.
            if getattr(inp, 'max_age_s', None):
                continue
            if inp.period > max_age:
                findings.append((
                    'severe',
                    f'{role} 센서 "{inp.name}" 주기 {inp.period:g}초 >'
                    f' 신선도 상한 {max_age:g}초 — 제어에서 늘 만료로 걸립니다'))
    return findings


# ── 출력 ────────────────────────────────────────────────────────────────────

def _fmt_gap(seconds):
    if not seconds:
        return '—'
    if seconds >= 60:
        return f'{seconds / 60:.0f}분'
    return f'{seconds:.0f}초'


def report(results, hours, min_delta):
    problems = 0
    print(f'env_coordinator 건강 점검 — 최근 {hours}시간'
          f' (진동 판정 {min_delta:g}%p 이상)')
    print('=' * 72)

    if not results:
        print('활성 코디네이터가 없습니다.')
        return 0

    for r in results:
        print()
        print(f'■ {r["name"]}')
        if not r['cycles']:
            print('   결정 로그가 없습니다 — 이 창에서 한 사이클도 돌지 않았습니다.')
            problems += 1
            continue

        gate_only = (f' · 게이트로만 {r["gate_only_cycles"]}회'
                    if r['gate_only_cycles'] else '')
        print(f'   사이클      {r["cycles"]}회 · 중앙 간격 {_fmt_gap(r["median_gap_s"])}'
              f' · 긴 공백 {r["long_gaps"]}회{gate_only}')

        if r['have_env_metrics']:
            modes = ' · '.join(f'{k} {v}' for k, v in list(r['modes'].items())[:4])
            print(f'   운전 모드   {modes or "—"}')
            if r['emergency_pct']:
                print(f'   긴급 사이클 {r["emergency_pct"]:.1f}%')
            limits = ' · '.join(f'{k} {v}' for k, v in list(r['limits'].items())[:3])
            if limits:
                print(f'   제한 인자   {limits}')
        elif not r['debug_logging']:
            print('   운전 모드   기록 없음 (디버그 로깅 꺼짐 — 액추에이터 축만 봅니다)')

        print()
        print(f'   {"액추에이터":<26}{"평균":>7}{"최대":>7}{"진동/h":>8}   근거')
        for a in r['actuators']:
            kind = f' ({a["kind"]})' if a['kind'] else ''
            label = (a['name'] + kind)[:26]
            reasons = ' · '.join(f'{lbl} {pct:.0f}%' for lbl, pct in a['top_reasons'])
            mark = ' !' if (a['always_idle'] or a['idle_while_claiming_work']) else ''
            print(f'   {label:<26}{a["mean"]:>6.1f}%{a["max"]:>6.0f}%'
                  f'{a["reversals_per_h"]:>8.1f}   {reasons}{mark}')

        # ── 요청은 했는데 나가지 않은 것 ──────────────────────────────────
        # 이 표의 숫자는 **최종값**(게이트까지 지난 값)이다. 코디네이터가
        # 켜라고 한 것이 게이트에 막혔다면 그 사실을 여기서 말해야 한다 —
        # 안 그러면 "이 장치는 쉬고 있다"로만 읽혀 원인이 코디네이터에
        # 있는 것처럼 보인다(정작 봐야 할 곳은 게이트다).
        blocked = [a for a in r['actuators'] if a.get('suppressed')]
        for a in sorted(blocked, key=lambda x: -x['suppressed']):
            problems += 1
            print(f'   ! {a["name"]} 은 {a["suppressed"]}개 사이클에서 코디네이터가'
                  f' 최대 {a["suppressed_max"]:.0f}% 를 요청했으나 실제로는 0% 가'
                  f' 나갔습니다 — 게이트·감쇠·인터록을 확인하세요')

        # 보호 장치가 설계대로 막은 것은 문제가 아니다 — 다만 **숨기지는 않는다.**
        # 같은 보호가 갑자기 늘면 그것이 신호이므로 횟수와 근거는 남긴다.
        for a in r['actuators']:
            if a.get('guarded'):
                why = ' · '.join(f'{lbl} {n}' for lbl, n in a['guarded'].items())
                print(f'   · {a["name"]}: 요청이 보호 장치에 막힌 사이클 '
                      f'{sum(a["guarded"].values())}개 ({why}) — 설계된 동작입니다')

        stale = [a['name'] for a in r['actuators']
                 if a.get('source') == 'requested']
        if stale:
            print(f'   · 최종값 기록이 없어 요청값으로 표시한 장치:'
                  f' {", ".join(stale)} (이 값은 실제 작동이 아닙니다)')

        idle = [a['name'] for a in r['actuators'] if a['always_idle']]
        if idle:
            problems += 1
            print(f'   ! 창 내내 참여하지 않은 장치: {", ".join(idle)}')

        # 0% 인데 근거는 '일하고 있다' — 수요가 0 이었을 수도, min-ON 문턱을
        # 못 넘는 교착일 수도 있다. 로그만으로는 갈리지 않으니 사람에게 넘긴다.
        puzzling = [a for a in r['actuators'] if a['idle_while_claiming_work']]
        for a in puzzling:
            problems += 1
            top = a['top_reasons'][0] if a['top_reasons'] else ('—', 0.0)
            print(f'   ! {a["name"]} 은 창 내내 0% 인데 근거는 '
                  f'"{top[0]}" {top[1]:.0f}% 입니다 — 수요가 없었는지'
                  f' 문턱을 못 넘었는지 확인하세요')

        # ── 센서 상태 (기록 전용 — out_of_range·frozen 만 제어에서 빠진다) ───
        sst = r.get('sensor_status')
        if sst is None:
            if not r['debug_logging']:
                print('   센서 상태   기록 없음 (디버그 로깅 꺼짐)')
        else:
            if sst['out_of_range']:
                problems += 1
                oor = ' · '.join(f'{a} {n}회' for a, n in sst['out_of_range'].items())
                print(f'   ! 물리적으로 불가능한 센서 값이 제어에서 빠졌습니다: {oor}'
                      f' — 센서·단위 변환을 확인하세요')
            if sst['frozen']:
                problems += 1
                frz = ' · '.join(f'{a} {n}회' for a, n in sst['frozen'].items())
                print(f'   ! 값이 멈춘 센서가 제어에서 빠졌습니다: {frz}'
                      f' — 시각은 새것인데 값이 그대로입니다. 센서·거울 장치를 확인하세요')
            others = {a: {k: n for k, n in c.items()
                          if k not in (SS.VALID, SS.OUT_OF_RANGE, SS.FROZEN)}
                      for a, c in sst['axes'].items()}
            others = {a: c for a, c in others.items() if c}
            if others:
                text = ' · '.join(
                    a + ' ' + '/'.join(f'{k} {n}' for k, n in c.items())
                    for a, c in others.items())
                print(f'   · 센서 상태 (기록 {sst["records"]}회): {text}')
            src = sst['vpd_source']
            if src:
                diff = ''
                if sst['vpd_device_diff_mean'] is not None:
                    diff = (f' · 장치 VPD 와 평균 {sst["vpd_device_diff_mean"]:+.2f} kPa'
                            f' (최대 {sst["vpd_device_diff_max_abs"]:.2f})')
                print('   · VPD 출처  ' + ' · '.join(
                    f'{k} {n}' for k, n in src.items()) + diff)

        flagged = []
        if r['opposing_cycles']:
            problems += 1
            flagged.append(f'⚠ 난방·냉방 동시 가동 {r["opposing_cycles"]}회'
                           f' ({r["opposing_pct"]:.1f}%) — 인터락이 막았어야 합니다')
        if r['post_gate_corrections']:
            flagged.append(f'· 안전 후보정 {r["post_gate_corrections"]}회')
        if r['heat_while_vent_cycles']:
            flagged.append(f'· 난방 중 환기 {r["heat_while_vent_cycles"]}회')
        if r['heat_while_fog_cycles']:
            flagged.append(f'· 난방 중 가습 {r["heat_while_fog_cycles"]}회 (VPD 목표면 정상)')
        if r['gates']:
            flagged.append('· 안전 게이트 ' +
                           ' · '.join(f'{k} {v}' for k, v in r['gates'].items()))
        if r['dispatch_fail_total']:
            problems += 1
            flagged.append(f'⚠ 전송 실패 누계 {r["dispatch_fail_total"]}')
        if r['actuator_mismatch_max']:
            # 신뢰도(trust_score) 기반 — 학습 가중치용 로그 수치다. 제어에서 뺀 '고장 의심' 장치와 다르다.
            flagged.append(f'· 신뢰도 낮은 액추에이터 최대 {r["actuator_mismatch_max"]}대 (학습 가중치용)')
        if r['clean_ratio'] is not None:
            flagged.append(f'· 학습 가능 사이클 {r["clean_ratio"]:.0f}%')
        hp = r.get('heat_protect')
        if hp and (hp['active_min'] or hp['transitions']):
            when = ', '.join(f'{t[11:16]} {a}→{b}' for t, a, b in hp['transition_times'][:6])
            flagged.append(
                f'· 극한 고온 보호 활성 {hp["active_min"]:.0f}분'
                f' (단계 2 {hp["tier2_min"]:.0f}분) · 단계 전환 {hp["transitions"]}회'
                + (f' ({when})' if when else ''))
            if hp['flags']:
                flagged.append('  보호 중 ' + ' · '.join(
                    f'{k} {v}' for k, v in sorted(hp['flags'].items(),
                                                   key=lambda kv: -kv[1])[:5]))
            if hp['transitions_per_h'] > HP_MAX_TRANSITIONS_PER_H:
                problems += 1
                flagged.append(
                    f'⚠ 극한 고온 보호가 시간당 {hp["transitions_per_h"]:.1f}회 켜졌다 '
                    f'꺼졌습니다 — 문턱 근처의 들락거림입니다(해제 여유·최소 유지 확인)')
        fr = r.get('frost')
        if fr:
            # 서리 주의·보호에 있던 시간 — 설계된 보호이지만 **작물이 위험했던 시간**이다. 보호가
            # 섰는데 난방기가 없으면(닫기만 한다) 사람이 해야 할 일이 남는다.
            when = ', '.join(t[11:16] for t in fr['protect_times'])
            flagged.append(
                f'· 서리 주의 {fr["watch_min"]:.0f}분 · 보호 {fr["protect_min"]:.0f}분'
                f' (보호 진입 {fr["protect_entries"]}회'
                + (f': {when}' if when else '') + ')')
        ex = r.get('exposure')
        if ex:
            # 시설 몫이다 — 코디네이터가 고칠 일이 아니라 '볼 것' 으로 세지 않는다. 설비 권고만 말한다.
            night = (f'밤 이슬 {ex["night_dew_min"]:.0f}분 / 밤 {ex["night_min"]:.0f}분'
                     if ex['night_known'] else '밤 이슬 계산 불가(시설 좌표 없음)')
            flagged.append(
                f'· {night} · 실내 0 °C 이하 {ex["frost_min"]:.0f}분'
                f' (최저 {ex["indoor_T_min"]:.1f} °C · 온습도 모두 잰 {ex["covered_min"]:.0f}분 기준)')
        else:
            flagged.append('· 밤 이슬·서리 노출 기록 없음 (실내 온도·습도 센서 값을 읽지 못했습니다)')
        for line in r.get('exposure_advice') or []:
            flagged.append(f'→ {line}')
        sp = r.get('suspected')
        if sp and sp['max_count']:
            # 제어에서 뺀 장치 — 설계된 보호이지만 끝내는 것은 사람이다(점검·수리).
            problems += 1
            names = [f'{a["name"]}({a["kind"]}) {a["suspect_cycles"]}사이클'
                     for a in r['actuators'] if a.get('suspect_cycles')]
            flagged.append(
                f'⚠ 고장 의심 액추에이터를 제어에서 뺐습니다 — 최대 {sp["max_count"]}대, '
                f'보류 {sp["held_min"]:.0f}분'
                + (f' ({", ".join(names)})' if names else '')
                + ' — 전송 실패가 이어졌거나 오래 세게 명령했는데 반응이 없었습니다. '
                  '장치를 점검하세요(30분 뒤 자동으로 다시 시도합니다)')
        ws = r.get('water_supply')
        if ws and (ws['low_min'] or ws['stale_min']):
            # 물이 없어 분무기가 멈춘 시간 — 설계된 보호이지만 **사람이 물을 채워야** 끝난다.
            problems += 1
            flagged.append(
                f'⚠ 분무용 물 공급 부족 {ws["low_min"]:.0f}분 · 신호 끊김 '
                f'{ws["stale_min"]:.0f}분 (정상 {ws["ok_min"]:.0f}분) — '
                f'그동안 분무기는 모두 멈췄습니다. 탱크·수압·신호를 확인하세요')
        elif ws:
            flagged.append(f'· 분무용 물 공급 정상 {ws["ok_min"]:.0f}분')
        vb = r.get('vpd_basis')
        if vb and vb['leaf_fallback_min']:
            # 잎 목표 숫자를 공기 VPD 로 좇은 시간 — 엽온 센서를 사람이 봐야 끝난다.
            problems += 1
            flagged.append(
                f'⚠ VPD 목표를 잎 기준으로 정했는데 엽온을 못 써 공기 기준으로 돈 시간 '
                f'{vb["leaf_fallback_min"]:.0f}분 (잎 기준 {vb["leaf_min"]:.0f}분) — '
                f'엽온 센서의 신호·만료·멈춤·설치 방향(잎을 보고 있는가)을 확인하세요')
        elif vb and vb['leaf_min']:
            flagged.append(f'· VPD 목표 잎 기준 {vb["leaf_min"]:.0f}분')
        if flagged:
            print()
            for line in flagged:
                print(f'   {line}')

        if r['settings']:
            print()
            print('   설정 점검')
            for level, text in r['settings']:
                problems += 1
                print(f'   {"⚠" if level == "severe" else "·"} {text}')

    print()
    print('=' * 72)
    if problems:
        print(f'볼 것 {problems}건. 위 항목을 확인하세요.')
        return 1
    print('이상 없음.')
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--hours', type=float, default=24.0, metavar='H',
                    help='검사 창, 시간 단위 (기본 24)')
    ap.add_argument('--function', dest='function_uuid', metavar='UUID',
                    help='코디네이터 하나만 (기본: 활성 전체)')
    ap.add_argument('--min-delta', type=float, default=5.0, metavar='PCT',
                    help='진동으로 셀 최소 변화폭, %%p (기본 5)')
    ap.add_argument('--all', action='store_true',
                    help='비활성 코디네이터도 포함')
    ap.add_argument('--json', action='store_true', help='JSON 으로 출력')
    args = ap.parse_args()

    with app.app_context():
        query = CustomController.query.filter(
            CustomController.device == 'env_coordinator')
        if args.function_uuid:
            query = query.filter(CustomController.unique_id == args.function_uuid)
        elif not args.all:
            query = query.filter(CustomController.is_activated.is_(True))

        results = []
        try:
            for row in query.all():
                results.append(analyse(row, args.hours, args.min_delta))
        except Exception as exc:                             # noqa: BLE001
            print(f'ERROR: 검사 실패 — {exc}', file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps({
            'generated_at': utc_now().isoformat(),
            'hours': args.hours,
            'coordinators': results,
        }, ensure_ascii=False, indent=2))
        return 1 if any(
            r['opposing_cycles'] or r['settings'] or not r['cycles']
            or (r.get('suspected') or {}).get('max_count')
            or (r.get('water_supply') or {}).get('low_min')
            or (r.get('water_supply') or {}).get('stale_min')
            or (r.get('vpd_basis') or {}).get('leaf_fallback_min')
            for r in results) else 0

    return report(results, args.hours, args.min_delta)


if __name__ == '__main__':
    sys.exit(main())

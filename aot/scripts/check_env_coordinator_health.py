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
설정 점검     오늘 실제로 밟은 지뢰들 — 종료일 임박, 유도/하드 역전,
              신선도 상한이 센서 주기보다 짧아 값이 늘 만료되는 경우.
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
logging.disable(logging.INFO)

from aot.start_flask_ui import app
from aot.databases.models import CustomController, Input, Output
from aot.functions.utils.env_control import log_channels as LC
from aot.functions.utils.env_control.types import ACTUATOR_DOMAIN, DEFAULT_DOMAIN


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
    LC.REASON_UNKNOWN:              '근거 미상',
}

# 창 내내 이것 하나로만 살았다면 그 장치는 사실상 참여하지 않은 것이다.
IDLE_REASONS = frozenset({
    LC.REASON_IDLE, LC.REASON_NO_GRADIENT, LC.REASON_NO_OUTDOOR_DATA,
    LC.REASON_OPPOSING_PARKED, LC.REASON_NIGHT_PARKED,
    LC.REASON_WRONG_DIRECTION,
})

MODE_LABEL = {
    1: '냉방', 2: '난방', 3: '가습', 4: '제습',
    5: 'CO₂ 시비', 0: '보존', 99: '긴급',
}
LIMIT_LABEL = {0: '없음', 1: '광량', 2: 'CO₂', 3: '온도', 4: '수분'}

GATE_LABEL = [
    (LC.GATE_BIT_RAIN,        '강우'),
    (LC.GATE_BIT_WIND,        '강풍'),
    (LC.GATE_BIT_EXT_EXP,     '외기 극한'),
    (LC.GATE_BIT_INT_EXP,     '내부 극한'),
    (LC.GATE_BIT_HEAT,        '고온'),
    (LC.GATE_BIT_COLD,        '저온'),
    (LC.GATE_BIT_FOG_SUNBURN, '일소 방지 분무 잠금'),
]

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
            from aot.aot_flask.geo.facility_integration import get_facility_integration
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
    claimed_work = bool({LC.REASON_PRIMARY, LC.REASON_SECONDARY} & set(reason_counter))
    return {
        'never_ran': never_ran,
        'always_idle': explained,
        'idle_while_claiming_work': never_ran and claimed_work,
    }


def _count_suppressed(requested, final):
    """코디네이터가 켜라고 했는데 실제로는 0 이 나간 사이클 수.

    이 숫자가 이 검사기의 존재 이유다. 요청만 보면 "평균 23% 로 돌고 있다"
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
        return 0
    finals = sorted(final)
    n = 0
    for ts, want in requested:
        if want <= 0.0:
            continue
        nearest = min(finals, key=lambda fv: abs((fv[0] - ts).total_seconds()))
        if abs((nearest[0] - ts).total_seconds()) > 5.0:
            continue
        if nearest[1] <= 0.0:
            n += 1
    return n


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
    gate_events = []
    dispatch_fail = []
    clean_flags = []
    mismatch = []

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
        elif measurement == 'env_control':
            try:
                env_by_channel[int(channel)].append((ts, float(value)))
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

    # ── 사이클 리듬 ────────────────────────────────────────────────────────
    # 한 사이클은 액추에이터 수만큼 행을 남기고 그것들이 거의 같은 순간에
    # 몰린다. 타임스탬프를 그대로 세면 **사이클 수가 액추에이터 배로 부풀고
    # 중앙 간격이 0 초가 된다**(첫 실행에서 실제로 그렇게 나왔다).
    stamps = _cluster_cycles(
        sorted(ts for series in cmd_by_act.values() for ts, _ in series))
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
        req_values = [v for _t, v in requested]
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
            'suppressed': _count_suppressed(requested, final),
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

    return {
        'uuid': row.unique_id,
        'name': row.name,
        'facility_uuid': facility_uuid,
        'debug_logging': bool(row.log_level_debug),
        'cycles': len(stamps),
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
        'dispatch_fail_total': int(sum(v for _t, v in dispatch_fail)),
        'actuator_mismatch_max': int(max((v for _t, v in mismatch), default=0)),
        'clean_ratio': clean_ratio,
        'settings': _check_settings(opts, facility_uuid, row),
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
            left = (expected - date.today()).days
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
    return findings


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
        from aot.aot_flask.geo.facility_integration import get_facility_integration
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

        print(f'   사이클      {r["cycles"]}회 · 중앙 간격 {_fmt_gap(r["median_gap_s"])}'
              f' · 긴 공백 {r["long_gaps"]}회')

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
                  f' 최대 {a["requested_max"]:.0f}% 를 요청했으나 실제로는 0% 가'
                  f' 나갔습니다 — 게이트·감쇠·인터록을 확인하세요')

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
            flagged.append(f'· 의심 액추에이터 최대 {r["actuator_mismatch_max"]}대')
        if r['clean_ratio'] is not None:
            flagged.append(f'· 학습 가능 사이클 {r["clean_ratio"]:.0f}%')
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
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'hours': args.hours,
            'coordinators': results,
        }, ensure_ascii=False, indent=2))
        return 1 if any(
            r['opposing_cycles'] or r['settings'] or not r['cycles']
            for r in results) else 0

    return report(results, args.hours, args.min_delta)


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
# coding=utf-8
"""env_coordinator 의 결정 로그를 사람이 읽는 형태로 푼다 (읽기 전용).

## 왜 필요한가

코디네이터는 매 사이클 판단 근거를 InfluxDB 에 남긴다 — 변수별 편차, 제한
요인, 액추에이터별 명령과 근거코드. 그런데 **그것을 읽는 화면이 하나도
없다.** 기록은 `device_measurements` 를 거치지 않고 InfluxDB 로 직접 가므로
(`log_channels._safe_write`) 측정값 패널·그래프 위젯의 선택 목록에도 안
나온다. 즉 "그때 왜 그렇게 판단했나" 를 사후에 볼 수단이 없다.

로그도 답이 안 된다 — 컨트롤러 로거는 `log_level_debug` 가 꺼져 있으면
`ERROR` 라(`base_controller.py`) info 가 아무 데도 안 남는다. **"그 로그가
없다 = 그 코드가 안 탔다" 가 아니다.**

그래서 저장된 결정을 직접 읽는다. 제어에 손대지 않는 **읽기 전용**이라
운영 서버에 그대로 돌려도 된다.

## ⚠ 기록된 명령은 **오버라이드 적용 전** 값이다

`coord_actuator_*_command` 는 `coordinator._log_cmd` 가 쓰는데, 그 호출은
`coordinate()` 안 — 즉 `_cycle_mixin` 의 임계 오버라이드·일사 감쇠·습도 상한·
안전 프리게이트가 적용되기 **전**이다. 근거코드(`env_control` ch41+)도
`write_cycle_metrics(commands=...)` 가 `final_cmds` 가 아니라 `commands` 를
받으므로 같은 시점이다.

따라서 **"로그에 40% 라고 있는데 장치는 안 움직였다" 가 정상일 수 있다** —
게이트가 뒤에서 0 으로 끊은 경우다. 실제 전송값은 Output 컨트롤러 쪽 기록을
봐야 한다. 이 도구가 보여주는 것은 "코디네이터가 무엇을 하려 했는가" 이지
"무엇이 실제로 나갔는가" 가 아니다.

## 채널 규약

`aot/functions/utils/env_control/log_channels.py` 가 정본이다. 이 스크립트는
그 상수를 **import 해서** 쓴다 — 번호를 여기 옮겨 적으면 규약이 바뀔 때
조용히 어긋나고, 그러면 엉뚱한 채널을 편차라고 보여준다.

## 쓰는 법

    python3 -m aot.scripts.show_env_decisions                 # 코디네이터 전체, 최근 3시간
    python3 -m aot.scripts.show_env_decisions --hours 24
    python3 -m aot.scripts.show_env_decisions --name 温室環境制御
    python3 -m aot.scripts.show_env_decisions --json

종료 0=정상, 2=조회 실패.
"""
import argparse
import collections
import json
import sys

sys.path.insert(0, '/app') if '/app' not in sys.path else None


def _load():
    """앱 컨텍스트가 필요한 것들을 늦게 부른다 — import 만으로 죽지 않게."""
    from aot.aot_flask.app import create_app
    from aot.databases.models import CustomController, Misc, Output
    from aot.utils.database import db_retrieve_table_daemon
    from aot.utils.influx import resolve_measurement_db_host
    from aot.config import INFLUXDB_PORT
    from aot.functions.utils.env_control import log_channels as LC
    from influxdb_client import InfluxDBClient
    return (create_app, CustomController, Misc, Output, db_retrieve_table_daemon,
            resolve_measurement_db_host, INFLUXDB_PORT, LC, InfluxDBClient)


def _reason_names(LC):
    """근거코드 → 이름. 상수에서 파생하므로 새 코드가 생겨도 따라온다."""
    return {v: k[len('REASON_'):].lower()
            for k, v in vars(LC).items()
            if k.startswith('REASON_') and isinstance(v, int)}


def collect(app, deps, uid, hours):
    (_, _, Misc, Output, db_retrieve_table_daemon,
     resolve_measurement_db_host, INFLUXDB_PORT, LC, InfluxDBClient) = deps
    s = db_retrieve_table_daemon(Misc, entry='first')
    client = InfluxDBClient(
        url='http://%s:%s' % (resolve_measurement_db_host(s.measurement_db_host),
                              INFLUXDB_PORT or s.measurement_db_port),
        token=s.measurement_db_password,
        org=s.measurement_db_user or '-')
    query = ('from(bucket: "%s") |> range(start: -%s)'
             ' |> filter(fn: (r) => r["device_id"] == "%s")'
             % (s.measurement_db_dbname, hours, uid))
    records = []
    for table in client.query_api().query(query, org=s.measurement_db_user or '-'):
        for r in table.records:
            records.append((r.get_time(), r.values.get('_measurement'),
                            str(r.values.get('channel')), r.get_value()))

    # 사이클 단위로 묶는다 — 같은 사이클의 기록이 초 단위로 흩어진다.
    cycles = collections.defaultdict(dict)
    for ts, meas, ch, val in records:
        cycles[ts.replace(second=0, microsecond=0)][(meas, ch)] = val

    # 액추에이터 이름: measurement 이름에 uuid 앞자리가 들어 있다.
    actuators = {}
    for _, meas, ch, _ in records:
        if meas and meas.startswith('coord_actuator_') and meas.endswith('_command'):
            short = meas[len('coord_actuator_'):-len('_command')]
            o = Output.query.filter(Output.unique_id.like(short + '%')).first()
            actuators[meas] = (ch, o.name if o else short)
    return cycles, actuators


def rows(cycles, actuators, LC, limit):
    """`write_cycle_metrics` 의 채널 규약대로 푼다.

    ⚠ **`VAR_INDEX` 로 유추하면 안 된다.** `env_control` measurement 의 채널은
    `CH_SITUATION_DEV_BASE + VAR_INDEX[var]` 가 아니라 아래 고정 배치다
    (`log_channels.write_cycle_metrics` 독스트링). 처음 이 도구를 쓸 때
    ch20~23 을 편차로, ch30 을 제한인자로 읽어 **목표값을 편차라고 보여줬다.**

        20~23  목표값   (VPD, 온도, 습도, CO2)
        24~27  우선순위 (VPD, 온도, 습도, CO2) — 동적 격상 반영
        30~32  편차     (온도, 습도, CO2)
        33     편차     (VPD) — VPD 직접 제어 모드에서만 값이 실린다.
                          이 모드에서는 30/31 이 항상 0(온습도가 제어목표에서
                          빠짐)이라, 실제로 액추에이터를 움직이는 값은 이것뿐이다.
        71     제한 인자 코드
        72     운전 모드 코드

    액추에이터 명령은 `env_control` 이 아니라 별도 measurement
    (`coord_actuator_<uuid8>_command`)에 있다 — 근거코드는 그 +1 채널.
    """
    reasons = _reason_names(LC)
    limits = {v: k for k, v in getattr(LC, 'LIMIT_CODES', {}).items()}
    modes = {v: k for k, v in getattr(LC, 'MODE_CODES', {}).items()}
    out = []
    for ts in sorted(cycles)[-limit:]:
        c = cycles[ts]

        def env(ch):
            return c.get(('env_control', str(ch)))

        target = {'vpd': env(20), 'temp': env(21), 'humi': env(22), 'co2': env(23)}
        prio = {'vpd': env(24), 'temp': env(25), 'humi': env(26), 'co2': env(27)}
        dev = {'temp': env(30), 'humi': env(31), 'co2': env(32), 'vpd': env(33)}
        cmds = []
        for meas, (ch, name) in sorted(actuators.items(), key=lambda x: int(x[1][0])):
            val = c.get((meas, ch))
            if val is None:
                continue
            rv = c.get((meas.replace('_command', '_reason'), str(int(ch) + 1)))
            cmds.append({'name': name, 'pct': val,
                         'reason': reasons.get(int(rv), rv) if rv is not None else None})
        lim, mode = env(71), env(72)
        out.append({
            'ts': ts.isoformat(),
            'target': target,
            'priority': prio,
            'deviation': dev,
            'limiting': limits.get(int(lim), lim) if lim is not None else None,
            'mode': modes.get(int(mode), mode) if mode is not None else None,
            'safety_gate': c.get(('safety_gate_active', str(LC.CH_SAFETY_GATE))),
            'commands': cmds,
        })
    return out


def render(name, data):
    lines = ['■ %s — 결정 로그 %d사이클' % (name, len(data))]
    if not data:
        lines.append('   (기록 없음)')
        return lines
    # ⚠ 마지막 행을 그냥 쓰면 안 된다 — 사이클 기록은 초 단위로 흩어져
    # 조회 순간 **부분만 들어온 행**이 마지막일 수 있고, 그러면 목표가 전부
    # 0(=목표 없음)으로 보인다. 실제로 그렇게 표시된 적이 있다.
    t = next((r['target'] for r in reversed(data)
              if any(v is not None for v in r['target'].values())), {})
    lines.append('   목표  온도 %s · 습도 %s · VPD %s · CO2 %s   (0 = 목표 없음)'
                 % tuple('%.4g' % (t.get(k) or 0) for k in ('temp', 'humi', 'vpd', 'co2')))
    lines.append('')
    lines.append('%-6s  %-30s %-10s %-6s  %s'
                 % ('시각', '편차(측정−목표)', '제한인자', '게이트', '명령 [근거]'))
    for r in data:
        dev = ' '.join('%s%+.2f' % (k, v) for k, v in sorted(r['deviation'].items())
                       if v is not None)
        cmds = '  '.join('%s %.0f%%[%s]' % (c['name'], c['pct'], c['reason'])
                         for c in r['commands'])
        lines.append('%-6s  %-30s %-10s %-6s  %s' % (
            r['ts'][11:16], dev or '-', r['limiting'] or '-',
            '켜짐' if r['safety_gate'] else '-', cmds or '-'))
    lines.append('')
    lines.append('   (시각 UTC · 제한인자/모드는 log_channels 의 코드표)')
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description='env_coordinator 결정 로그 판독 (읽기 전용)')
    ap.add_argument('--hours', default='3h',
                    help="조회 구간 (예: 3h, 24h, 7d). 기본 3h")
    ap.add_argument('--name', default=None, help='코디네이터 이름 (기본: 전부)')
    ap.add_argument('--limit', type=int, default=20, help='표시할 사이클 수 (기본 20)')
    ap.add_argument('--json', action='store_true', help='기계 판독')
    args = ap.parse_args(argv)

    try:
        deps = _load()
    except Exception as exc:                                    # noqa: BLE001
        sys.stderr.write('의존성 로드 실패: %s\n' % exc)
        return 2
    create_app, CustomController = deps[0], deps[1]
    LC = deps[7]

    app = create_app()
    result = {}
    with app.app_context():
        q = CustomController.query.filter(CustomController.device.like('%coordinator%'))
        if args.name:
            q = q.filter(CustomController.name == args.name)
        controllers = q.all()
        if not controllers:
            sys.stderr.write('코디네이터를 찾지 못했다\n')
            return 2
        for cc in controllers:
            try:
                cycles, actuators = collect(app, deps, cc.unique_id, args.hours)
            except Exception as exc:                            # noqa: BLE001
                sys.stderr.write('%s 조회 실패: %s\n' % (cc.name, exc))
                return 2
            # ⚠ **이름으로 키잉하지 말 것.** 이름은 유일하지 않다 —
            #   같은 이름의 코디네이터가 둘이면 뒤엣것이 앞엣것을 덮어써,
            #   살아 있는 코디네이터의 로그가 통째로 사라지고 화면에는
            #   '기록 없음' 만 남는다(2026-08-26 실제로 영양 육묘장이
            #   그랬다 — 비활성 사본이 활성 쪽을 가렸다).
            label = '%s (%s%s)' % (cc.name, cc.unique_id[:8],
                                   '' if cc.is_activated else ', 비활성')
            result[label] = rows(cycles, actuators, LC, args.limit)

    if args.json:
        sys.__stdout__.write(json.dumps(result, ensure_ascii=False, indent=1) + '\n')
        return 0
    for name, data in result.items():
        sys.__stdout__.write('\n'.join(render(name, data)) + '\n\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
# coding=utf-8
"""AI 도구 표면의 비용을 잰다 — 고정비(매니페스트)·응답 페이로드·실사용 분포.

**왜 별도 스크립트인가.** `aot/tests/ai_eval/runner.py` 는 실제 LLM 을 호출해
왕복 수와 답변 품질을 본다(= 동적 비용, API 요금과 DB 사본이 필요하다). 그런데
지금까지 아무도 재지 않던 것은 그 앞에 있는 **고정비**다 — 매니페스트는 질문
내용과 무관하게 매 호출에 실리고, 도구 응답은 매 턴 컨텍스트에 누적된다.
이 둘은 LLM 없이 잴 수 있으므로 여기서 따로 재고, 그래서 CI 에서도 돌릴 수 있다.

`docs/design/ai-tool-architecture.md` Phase 0 의 계측 도구다. 그 문서의 판단
(무엇을 상시 노출할지, 예산을 얼마로 잡을지)은 전부 여기서 나온 수치에 기댄다.

    python3 -m aot.scripts.measure_ai_tool_cost              # 고정비 (DB 불필요)
    python3 -m aot.scripts.measure_ai_tool_cost --payload    # 응답 크기 (앱 컨텍스트 필요)
    python3 -m aot.scripts.measure_ai_tool_cost --usage --db PATH   # 실사용 분포
    python3 -m aot.scripts.measure_ai_tool_cost --json

종료 0=정상, 1=예산 초과, 2=계측 실패.

**읽기 전용이다.** `--usage` 는 sqlite 를 `mode=ro` 로 열고, `--payload` 는
조회 도구만 부른다. 운영 서버에 그대로 돌려도 된다.
"""
import argparse
import json
import os
import sys

# 토큰 근사는 문자수/4 다. 한국어는 이보다 나쁘고 영어 스키마는 이보다 좋아
# 절대값으로는 못 쓴다 — **같은 방식으로 잰 값끼리의 비교**(회귀 감시, 개선
# 전후)에만 쓸 것. 모델별 토크나이저를 붙이면 절대값도 의미를 갖는다.
CHARS_PER_TOKEN = 4


def _tok(obj):
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False,
                                                       default=str)
    return len(text), len(text) // CHARS_PER_TOKEN


# ---------------------------------------------------------------------------
# 고정비 — 매니페스트
# ---------------------------------------------------------------------------

def measure_manifest():
    """매 호출에 실리는 도구 정의의 크기. LLM·DB 없이 잴 수 있다."""
    from aot.ai.services import tool_registry as registry

    agent = registry.manifest_system_tools()
    mcp = registry.virtual_tools()

    def _per_tool(entries, name_key):
        out = []
        for entry in entries:
            chars, tokens = _tok(entry)
            out.append({'tool': entry.get(name_key), 'chars': chars,
                        'tokens': tokens})
        out.sort(key=lambda item: -item['chars'])
        return out

    agent_chars, agent_tokens = _tok(agent)
    mcp_chars, mcp_tokens = _tok(mcp)
    return {
        'agent_manifest': {'count': len(agent), 'chars': agent_chars,
                           'tokens': agent_tokens,
                           'tools': _per_tool(agent, 'tool_name')},
        'mcp_catalog': {'count': len(mcp), 'chars': mcp_chars,
                        'tokens': mcp_tokens,
                        'tools': _per_tool(mcp, 'tool_name')},
    }


# ---------------------------------------------------------------------------
# 응답 페이로드
# ---------------------------------------------------------------------------
# 대표 호출만 잰다. 전 도구를 부르면 쓰기 도구까지 건드리게 되므로, **조회만**
# 고정 목록으로 둔다. 새 조회 도구를 만들면 여기 추가할 것 — 안 그러면 그
# 도구의 응답 크기는 아무도 안 본다.
PAYLOAD_PROBES = [
    ('get_spatial_tree', {}),
    ('list_plantings', {}),
    ('list_plantings(with_sensors)', {'with_sensors': True}),
    ('get_zone_sensor_summary', {'measurement_type': 'volumetric_water_content'}),
    ('search_devices', {'query': '온습도'}),
    ('get_device_list', {}),
]


def measure_payload():
    """실제 조회 응답의 크기. 앱 컨텍스트(DB)가 필요하다."""
    from aot.ai.services.aot_data_tool_service import AoTDataToolService as svc

    handlers = {
        'get_spatial_tree': svc.get_spatial_tree,
        'list_plantings': svc.list_plantings,
        'list_plantings(with_sensors)': svc.list_plantings,
        'get_zone_sensor_summary': getattr(svc, 'get_zone_sensor_summary', None),
        'search_devices': svc.search_devices,
        'get_device_list': getattr(svc, 'get_device_list_tool', None),
    }

    rows = []
    for label, kwargs in PAYLOAD_PROBES:
        fn = handlers.get(label)
        if fn is None:
            rows.append({'tool': label, 'status': 'missing'})
            continue
        try:
            result = fn(**kwargs)
        except Exception as exc:
            rows.append({'tool': label, 'status': 'error',
                         'message': str(exc)[:120]})
            continue
        chars, tokens = _tok(result)
        row = {'tool': label, 'status': 'ok', 'chars': chars, 'tokens': tokens}
        # 원시 시계열이 응답의 몇 %인지 — summary-first 규약의 근거가 되는 수치다.
        raw = _raw_reading_chars(result)
        if raw:
            row['raw_reading_chars'] = raw
            row['raw_reading_pct'] = round(100.0 * raw / chars, 1) if chars else 0
        rows.append(row)
    rows.sort(key=lambda item: -item.get('chars', 0))
    return rows


def _raw_reading_chars(obj):
    """응답 안의 원시 시계열(`readings`) 이 차지하는 문자수."""
    total = 0
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == 'readings' and isinstance(value, list):
                total += _tok(value)[0]
            else:
                total += _raw_reading_chars(value)
    elif isinstance(obj, list):
        for item in obj:
            total += _raw_reading_chars(item)
    return total


# ---------------------------------------------------------------------------
# 실사용 분포
# ---------------------------------------------------------------------------

def measure_usage(db_path, limit=12):
    """`ai_history` 에서 실제 질문과 도구 호출 분포를 읽는다(읽기 전용).

    ⚠ 이 수치를 **도구를 자르는 근거로 쓰지 말 것.** 설계 문서 §단계별 설계
    참조 — 표본이 얇거나 개발 중 만든 대화면 "아직 안 불렸다" 와 "안 쓰인다"
    를 구별할 수 없다. 승격(무엇을 상시 노출할지)의 힌트로만 쓴다.
    """
    import collections
    import sqlite3

    conn = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    try:
        rows = conn.execute(
            'SELECT goal, actions_json FROM ai_history').fetchall()
    finally:
        conn.close()

    calls = collections.Counter()
    goals = 0
    for goal, actions in rows:
        if goal:
            goals += 1
        if not actions:
            continue
        try:
            blob = json.dumps(json.loads(actions), ensure_ascii=False)
        except Exception:
            blob = actions
        for chunk in blob.split('"tool_name": "')[1:]:
            calls[chunk.split('"')[0]] += 1

    return {
        'rows': len(rows),
        'rows_with_goal': goals,
        'distinct_tools_called': len(calls),
        'calls': calls.most_common(limit),
        'total_calls': sum(calls.values()),
        'caveat': ('표본이 얇거나 개발 중 생성된 것이면 강등 근거로 쓸 수 없다 '
                   '— docs/design/ai-tool-architecture.md §단계별 설계'),
    }


# ---------------------------------------------------------------------------

def _print_report(data):
    man = data['manifest']
    print('=== 고정비 — 매 호출에 실리는 도구 정의 ===')
    for key, label in (('agent_manifest', '에이전트 루프 매니페스트'),
                       ('mcp_catalog', 'MCP 카탈로그(tools/list)')):
        block = man[key]
        print('  %-26s 도구 %3d개  %7d자  약 %6d토큰'
              % (label, block['count'], block['chars'], block['tokens']))
    print()
    print('  가장 큰 도구 정의 8개 (MCP 카탈로그 기준):')
    for item in man['mcp_catalog']['tools'][:8]:
        print('    %-30s %5d자' % (item['tool'], item['chars']))

    if data.get('payload'):
        print()
        print('=== 응답 페이로드 — 매 턴 컨텍스트에 누적된다 ===')
        for row in data['payload']:
            if row['status'] != 'ok':
                print('  %-34s (%s)' % (row['tool'], row['status']))
                continue
            extra = ''
            if row.get('raw_reading_pct'):
                extra = '   원시 시계열 %s%%' % row['raw_reading_pct']
            print('  %-34s %7d자  약 %5d토큰%s'
                  % (row['tool'], row['chars'], row['tokens'], extra))

    if data.get('usage'):
        use = data['usage']
        print()
        print('=== 실사용 분포 (%d행, goal 있는 행 %d) ==='
              % (use['rows'], use['rows_with_goal']))
        print('  호출된 도구 %d종 / 총 %d회'
              % (use['distinct_tools_called'], use['total_calls']))
        for name, count in use['calls']:
            print('    %-30s %4d' % (name, count))
        print('  ⚠ %s' % use['caveat'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', action='store_true',
                        help='조회 도구의 응답 크기도 잰다 (앱 컨텍스트 필요)')
    parser.add_argument('--usage', action='store_true',
                        help='ai_history 의 실사용 분포를 읽는다')
    parser.add_argument('--db', help='--usage 가 읽을 sqlite 경로')
    parser.add_argument('--budget-tokens', type=int,
                        help='에이전트 매니페스트 토큰 상한. 넘으면 종료 1')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    data = {}
    try:
        data['manifest'] = measure_manifest()
    except Exception as exc:
        print('매니페스트 계측 실패: %s' % exc, file=sys.stderr)
        return 2

    if args.payload:
        try:
            from aot.start_flask_ui import app
            with app.app_context():
                data['payload'] = measure_payload()
        except Exception as exc:
            print('페이로드 계측 실패(앱 컨텍스트?): %s' % exc, file=sys.stderr)
            data['payload'] = []

    if args.usage:
        db_path = args.db
        if not db_path:
            try:
                from aot.config import SQL_DATABASE_AOT as db_path
            except Exception:
                db_path = None
        if not db_path or not os.path.exists(db_path):
            print('--usage 에는 읽을 수 있는 --db 경로가 필요합니다',
                  file=sys.stderr)
            return 2
        try:
            data['usage'] = measure_usage(db_path)
        except Exception as exc:
            print('사용 분포 계측 실패: %s' % exc, file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_report(data)

    if args.budget_tokens:
        actual = data['manifest']['agent_manifest']['tokens']
        if actual > args.budget_tokens:
            print('\n예산 초과: 매니페스트 %d토큰 > 상한 %d토큰'
                  % (actual, args.budget_tokens), file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

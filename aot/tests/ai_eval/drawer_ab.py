# coding=utf-8
"""서랍(노출 등급) A/B — 같은 요청을 켜기 전/후로 돌려 왕복과 토큰을 비교한다.

핵심 질문 4개(설계 문서 §노출 등급과 서랍)에 숫자로 답하는 것이 목적이다.
    1. 상시 노출에 없는 도구가 필요할 때 `open_drawer` 를 부르는가
    2. 서랍을 한 번에 맞히는가 (도메인 이름으로 묶은 가정이 맞는가)
    3. 왕복이 몇 번 늘어나는가
    4. 답변 품질이 떨어지는가

한 조건(켜짐/꺼짐)이 한 프로세스다. `tiering_enabled()` 는 호출 시점의
os.environ 을 읽지만, 매니페스트가 요청 컨텍스트(flask.g)에 캐시되므로 한
프로세스 안에서 환경변수를 뒤집는 방식은 신뢰할 수 없다. 그래서 조건마다
프로세스를 나누고 결과 JSON 두 개를 --compare 로 합친다.

    AOT_AI_TOOL_TIERING=0 python -m aot.tests.ai_eval.drawer_ab \
        --db-path /copy/aot.db --n 12 --seed 7 --out off.json
    AOT_AI_TOOL_TIERING=1 python -m aot.tests.ai_eval.drawer_ab \
        --db-path /copy/aot.db --n 12 --seed 7 --out on.json
    python -m aot.tests.ai_eval.drawer_ab --compare off.json on.json

SAFETY: 실제 LLM 을 부른다(비용 발생). DB 는 **사본만** 받는다 — runner.py 와
같은 규칙이고, WAL 때문에 cp 가 아니라 sqlite3 backup() 으로 떠야 한다.
"""
import argparse
import json
import os
import sys
import time

# 이 파일은 두 가지로 실행된다: 패키지 모듈(`python -m aot.tests.ai_eval.drawer_ab`)
# 로도, 컨테이너에 형제 파일과 함께 복사한 평평한 스크립트로도. 컨테이너가
# 바인드 마운트하는 것은 메인 체크아웃이라 워크트리의 새 파일이 /app 에 없어서
# 후자가 필요하다. 어느 쪽이든 형제 모듈은 항상 옆에 있다.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import request_sampler          # noqa: E402
import tool_call_probe          # noqa: E402


def _is_quota_error(ai_result, metrics):
    """분당 입력토큰 쿼터(429)에 걸린 턴인지. 이건 서랍과 무관한 실패라
    표본에서 빼거나 다시 돌려야 한다 — 품질 저하로 잘못 세면 안 된다."""
    blob = '%s %s' % ((ai_result or {}).get('message', ''), metrics.get('error', ''))
    return ('429' in blob or 'RESOURCE_EXHAUSTED' in blob
            or 'exceeded your current quota' in blob)


def run_condition(db_path, n, seed, drawer_ratio, out_path, label=None,
                  sleep_s=20.0, retry_on_quota=True):
    if not db_path or not os.path.isfile(db_path):
        raise ValueError('db_path 는 DB **사본** 이어야 합니다 (라이브 금지): %r' % db_path)

    os.environ['ALEMBIC_RUNNING'] = '1'
    from aot.aot_flask.app import create_app
    from aot.config import ProdConfig
    from aot.ai.services import tool_registry as registry

    class _EvalConfig(ProdConfig):
        SQLALCHEMY_DATABASE_URI = 'sqlite:///%s' % db_path
        TESTING = True

    app = create_app(config=_EvalConfig)
    tiering = registry.tiering_enabled()
    samples = request_sampler.sample(n=n, seed=seed, db_path=db_path,
                                     drawer_ratio=drawer_ratio)

    # MCP 예열. AoT MCP 서버는 첫 매니페스트 요청 때 'stopped' 로 건너뛰고 그
    # 뒤에 올라온다 — 예열하지 않으면 **1번 요청만** 도구 20여 개가 없는 상태로
    # 돌아 조건 비교가 오염된다. operate_device·get_sensor_detail 처럼 MCP 표면
    # 에만 있는 도구가 그 차이에 걸린다.
    mcp_n = 0
    for _ in range(6):
        with app.test_request_context():
            from aot.ai.services.ai_action_service import AIActionService
            from aot.databases.models import AIAgent
            _ag = AIAgent.query.filter_by(is_activated=True).first()
            _m = AIActionService.get_action_manifest(
                agent_unique_id=_ag.unique_id if _ag else None, is_slim=True)
            mcp_n = len(_m.get('mcp_tools') or [])
            sys_n = len(_m.get('system_tools') or [])
        if mcp_n:
            break
        time.sleep(5)
    print('예열: tiering=%s  system_tools=%d  mcp_tools=%d' % (tiering, sys_n, mcp_n),
          flush=True)

    results = []
    for i, s in enumerate(samples):
        # 요청마다 새 요청 컨텍스트 — 매니페스트 요청 캐시(flask.g)가 앞 요청의
        # 것을 물고 오지 않게. thread_id 도 매번 새로 두어 대화 이력이 섞이지
        # 않게 한다(후속발화 해소 로직이 끼어들면 왕복 비교가 오염된다).
        for attempt in range(2):
            if i or attempt:
                # 요청 하나가 프롬프트 13만 토큰대라 분당 입력토큰 쿼터에 쉽게
                # 닿는다. 쿼터 실패를 품질 저하로 오독하지 않으려면 쉬어야 한다.
                time.sleep(sleep_s if not attempt else 65.0)
            with app.test_request_context():
                from aot.ai.services.ai_agent_service import AIAgentService
                thread_id = 'drawer-ab-%s-%d-%d' % (
                    'on' if tiering else 'off', seed, i)
                ai_result, metrics = tool_call_probe.probe_scenario(
                    AIAgentService.process_natural_language_command,
                    agent_id='auto', command_text=s['prompt'], thread_id=thread_id)
            if not (retry_on_quota and _is_quota_error(ai_result, metrics)):
                break
            print('    (쿼터 429 — 65초 쉬고 한 번 더)', flush=True)
        row = dict(s)
        row['tiering'] = tiering
        row['metrics'] = metrics
        row['quota_failed'] = _is_quota_error(ai_result, metrics)
        row['status'] = (ai_result or {}).get('status')
        row['insight'] = (ai_result or {}).get('insight', '')
        row['intercept'] = (ai_result or {}).get('_intercept')
        row['proposed'] = [
            (a.get('params') or {}).get('tool_name') or a.get('tool_name')
            or a.get('action_type')
            for a in ((ai_result or {}).get('proposed_actions') or [])]
        results.append(row)
        print('[%2d/%2d] %-3s %-11s %-42s llm=%d tok=%s tools=%d drawer=%s%s' % (
            i + 1, len(samples), 'ON' if tiering else 'OFF',
            s['needs_drawer'] or 'core', s['prompt'][:40],
            metrics['llm_calls'], metrics['prompt_tokens'], metrics['tool_calls'],
            ','.join(metrics['distinct_drawers']) or '-',
            '  !QUOTA' if row['quota_failed'] else ''), flush=True)

    payload = {
        'label': label or ('tiering_on' if tiering else 'tiering_off'),
        'tiering': tiering, 'seed': seed, 'n': n, 'drawer_ratio': drawer_ratio,
        'db_path': db_path, 'at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'warm_system_tools': sys_n, 'warm_mcp_tools': mcp_n,
        'results': results,
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print('\n→ %s' % out_path)
    return payload


# ── 집계 ────────────────────────────────────────────────────────────────
def _agg(rows):
    def mean(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 2) if vals else 0
    return {
        'n': len(rows),
        'llm_calls': mean([r['metrics']['llm_calls'] for r in rows]),
        'tool_calls': mean([r['metrics']['tool_calls'] for r in rows]),
        'prompt_tokens': mean([r['metrics']['prompt_tokens'] for r in rows]),
        'output_tokens': mean([r['metrics']['output_tokens'] for r in rows]),
        'declared_tools': mean([r['metrics']['declared_tools_first_call'] for r in rows]),
        'latency_ms': mean([r['metrics']['latency_ms'] for r in rows]),
        'insight_len': mean([len(r.get('insight') or '') for r in rows]),
        'empty_answers': sum(1 for r in rows if len(r.get('insight') or '') < 10),
    }


def compare(off_path, on_path):
    off = json.load(open(off_path, encoding='utf-8'))
    on = json.load(open(on_path, encoding='utf-8'))
    off_by = {r['id']: r for r in off['results']}
    on_by = {r['id']: r for r in on['results']}
    ids = [i for i in off_by if i in on_by]

    out = {'paired': len(ids), 'overall': {}, 'by_need': {}, 'per_request': []}
    out['overall'] = {'off': _agg([off_by[i] for i in ids]),
                      'on': _agg([on_by[i] for i in ids])}
    for need in ('core', 'drawer'):
        sel = [i for i in ids
               if (off_by[i]['needs_drawer'] is None) == (need == 'core')]
        if sel:
            out['by_need'][need] = {'off': _agg([off_by[i] for i in sel]),
                                    'on': _agg([on_by[i] for i in sel])}

    # 서랍이 필요한 요청에서만 의미 있는 지표 — 질문 1·2 의 답.
    drawer_ids = [i for i in ids if on_by[i]['needs_drawer']]

    def _attempts(m):
        # MCP 경유 열기는 핸들러 후킹이 못 보므로 execute_action 기록으로 보완.
        return max(m.get('drawer_open_count') or 0,
                   m.get('drawer_open_attempts') or 0,
                   (m.get('tool_call_names') or []).count('open_drawer'))

    opened = [i for i in drawer_ids if _attempts(on_by[i]['metrics']) > 0]
    right = [i for i in opened
             if on_by[i]['needs_drawer'] in on_by[i]['metrics']['distinct_drawers']]
    first_try = [i for i in opened
                 if (on_by[i]['metrics']['drawer_opens'] or [{}])[0].get('drawer')
                 == on_by[i]['needs_drawer']]
    out['drawer_behavior'] = {
        'needed': len(drawer_ids),
        'opened_any': len(opened),
        'opened_correct_drawer': len(right),
        'correct_on_first_try': len(first_try),
        'avg_drawers_opened': round(
            sum(_attempts(on_by[i]['metrics']) for i in drawer_ids)
            / len(drawer_ids), 2) if drawer_ids else 0,
        'never_opened': [i for i in drawer_ids if i not in opened],
    }
    out['blocked_writes'] = {i: on_by[i]['metrics']['blocked_writes']
                             for i in ids if on_by[i]['metrics']['blocked_writes']}

    for i in ids:
        o, n_ = off_by[i], on_by[i]
        out['per_request'].append({
            'id': i, 'prompt': o['prompt'], 'needs_drawer': o['needs_drawer'],
            'off': {'llm': o['metrics']['llm_calls'],
                    'tools': tool_call_probe.format_trace(o['metrics']),
                    'ptok': o['metrics']['prompt_tokens'],
                    'len': len(o.get('insight') or '')},
            'on': {'llm': n_['metrics']['llm_calls'],
                   'tools': tool_call_probe.format_trace(n_['metrics']),
                   'ptok': n_['metrics']['prompt_tokens'],
                   'len': len(n_.get('insight') or ''),
                   'drawers': n_['metrics']['distinct_drawers']},
        })
    return out


def _print_compare(cmp_out):
    o, n = cmp_out['overall']['off'], cmp_out['overall']['on']
    print('== 전체 (%d쌍) ==' % cmp_out['paired'])
    hdr = '%-16s %10s %10s %10s' % ('지표', '끔', '켬', '차이')
    print(hdr)
    for k in ('declared_tools', 'prompt_tokens', 'llm_calls', 'tool_calls',
              'output_tokens', 'latency_ms', 'insight_len'):
        diff = round(n[k] - o[k], 2)
        pct = (' (%+.0f%%)' % (100.0 * diff / o[k])) if o[k] else ''
        print('%-16s %10s %10s %10s%s' % (k, o[k], n[k], diff, pct))
    print('\n== 서랍 동작 ==')
    for k, v in cmp_out['drawer_behavior'].items():
        print('  %-24s %s' % (k, v))
    for need, agg in cmp_out['by_need'].items():
        print('\n== %s 요청 ==' % need)
        for k in ('prompt_tokens', 'llm_calls', 'tool_calls', 'insight_len'):
            print('  %-16s 끔 %8s → 켬 %8s' % (k, agg['off'][k], agg['on'][k]))
    if cmp_out['blocked_writes']:
        print('\n!! 승인 게이트 우회 시도(프로브가 막음):', cmp_out['blocked_writes'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db-path', help='DB **사본** 경로 (라이브 금지)')
    p.add_argument('--n', type=int, default=12)
    p.add_argument('--seed', type=int, default=7)
    p.add_argument('--drawer-ratio', type=float, default=0.6)
    p.add_argument('--out', default=None)
    p.add_argument('--label', default=None)
    p.add_argument('--sleep', type=float, default=20.0,
                   help='요청 사이 대기(초) — 분당 입력토큰 쿼터 회피')
    p.add_argument('--compare', nargs=2, metavar=('OFF_JSON', 'ON_JSON'))
    a = p.parse_args()

    if a.compare:
        res = compare(*a.compare)
        _print_compare(res)
        print('\n' + json.dumps(res, ensure_ascii=False, indent=2)[:200] + ' …')
        with open('drawer_ab_compare.json', 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
    else:
        run_condition(a.db_path, a.n, a.seed, a.drawer_ratio,
                      a.out or 'drawer_ab_out.json', a.label, sleep_s=a.sleep)

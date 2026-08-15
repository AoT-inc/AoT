# coding=utf-8
"""
Golden-set runner — AI v3.1 refactor evaluation harness (Phase 0).

Runs GOLDEN_SET scenarios through the CURRENT production dispatch path
(AIAgentService.process_natural_language_command — the exact same call
sequence as aot_flask.routes_ai_api.ai_portal_chat's non-stream branch;
UnifiedOrchestrator/UOC was a separate keyword-heuristic "Tier2" fork removed
in the agent-loop redesign's Phase 3, docs/design/ai-agent-loop.md §11.1)
and records latency/approx-tokens/check results, so later phases can be
compared against this frozen baseline instead of guessing whether they helped.

SAFETY: this makes REAL calls to whatever AIEntry/AIAgent are configured in
the target DB, which costs real API tokens. Per project rule (라이브 DB
테스트 금지), this must be pointed at a COPY of the database, never the live
one. run_golden_set() requires an explicit db_path and refuses to proceed
without it — there is no default fallback to any live path.

MAKING THE COPY — the app runs the DB in WAL mode, so `cp aot.db copy.db`
silently misses any recently-committed row still sitting in `aot.db-wal`
(the main file only reflects data as of the last checkpoint — observed
firsthand: an AIEntry added minutes earlier was absent from a plain-`cp`
copy while the live DB clearly had it). Use a consistent snapshot instead:
    import sqlite3
    src = sqlite3.connect("/path/to/live/aot.db")
    src.backup(sqlite3.connect("/path/to/copy.db"))

Usage (manual, not pytest-collected — filename does not match test_*.py):
    python -m aot.tests.ai_eval.runner --db-path /path/to/copy/of/aot.db \\
        [--save-baseline] [--category simple_query]
"""
import argparse
import json
import os
import time
from datetime import datetime

from aot.tests.ai_eval.golden_set import GOLDEN_SET, looks_like_command_language

REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    '.local', 'reports',
)
BASELINE_PATH = os.path.join(REPORTS_DIR, 'ai_v3_golden_baseline.json')
METRICS_LOG_PATH = os.path.join(REPORTS_DIR, 'ai_v3_phase_metrics.md')


def _seed_recent_control(thread_id, device_name, state=True):
    """Write a synthetic AIHistory row recording a prior operate_device turn on
    this thread, so a `seed_recent_control` scenario can exercise the REAL
    recent-control interceptor (intent_resolver.recent_controlled_devices())
    end-to-end instead of only documenting its no-history fallthrough. Mirrors
    the shape _dispatch_actions writes: actions_json with a tool_name +
    params.device_id AIAgentService._recent_controlled_devices reads back."""
    from aot.databases.models import AIHistory, Output, AIAgent
    dev = Output.query.filter_by(name=device_name).first()
    if not dev:
        return False
    agent = AIAgent.query.filter_by(is_activated=True).first()
    if not agent:
        return False
    row = AIHistory(
        agent_id=agent.unique_id, goal=f"seed: turn {device_name} {'on' if state else 'off'}",
        insight=f"{device_name} {'ON' if state else 'OFF'}",
        actions_json=json.dumps([{
            'tool_name': 'operate_device',
            'params': {'device_id': dev.unique_id, 'state': state,
                       'display_summary': f"{device_name} {'ON' if state else 'OFF'}"},
        }]),
        status='executed', thread_id=thread_id, message_type='ai',
    )
    from aot.aot_flask.extensions import db as _db
    _db.session.add(row)
    _db.session.commit()
    return True


def run_scenario(scenario):
    """Run one scenario through the current production dispatch path:
    AIAgentService.process_natural_language_command — the same call
    ai_portal_chat's non-stream branch makes (Phase 3, UOC removed;
    see docs/design/ai-agent-loop.md §11.1). That function itself routes
    'auto' requests to AgentLoopService once AIGlobalSettings.agent_loop_enabled
    is set, and falls back to the legacy router/planner/synthesizer pipeline
    otherwise — this runner exercises whichever is currently active in the
    target DB, unchanged by which one that is.
    """
    from aot.ai.services.ai_agent_service import AIAgentService

    from aot.tests.ai_eval.tool_call_probe import ToolCallProbe

    result = {'id': scenario['id'], 'category': scenario['category'], 'prompt': scenario['prompt']}
    if scenario.get('seed_recent_control') and scenario.get('thread_id'):
        _seed_recent_control(scenario['thread_id'], scenario['seed_recent_control'])
    start = time.monotonic()
    try:
        # 왕복·도구 호출·실토큰 계측(Phase 0 나머지 절반). 이것 없이는
        # 매니페스트를 줄인 변경이 왕복을 늘려 손해인지 알 수 없다 —
        # approx_tokens 는 최종 답변 글자수일 뿐이다.
        with ToolCallProbe() as probe:
            ai_result = AIAgentService.process_natural_language_command(
                agent_id='auto', command_text=scenario['prompt'],
                thread_id=scenario.get('thread_id'), page_context=scenario.get('page_context'),
            )
        result['tool_metrics'] = probe.summary()
        result['insight'] = ai_result.get('insight', '')
        result['intent'] = ai_result.get('intent')
        result['path'] = ai_result.get('_intercept') or 'legacy_ai_agent_service'
        # Which deterministic interceptor (if any) actually fired — see the
        # `_intercept` tagging added at each branch in
        # AIAgentService.process_natural_language_command. None means the
        # command fell through to the LLM-driven planner/supervisor path.
        result['intercept'] = ai_result.get('_intercept')
        result['proposed_device_names'] = _extract_proposed_device_names(ai_result)
        result['ok'] = True
    except Exception as e:
        result['ok'] = False
        result['error'] = f'{type(e).__name__}: {e}'

    result['latency_ms'] = int((time.monotonic() - start) * 1000)
    # Rough approximation only (chars/4) — kept for continuity with the frozen
    # baseline. `tool_metrics.prompt_tokens` is the REAL number (provider usage
    # metadata, summed over every round trip); prefer it for cost comparisons.
    result['approx_tokens'] = (len(result.get('insight', '')) + len(scenario['prompt'])) // 4

    result['check_passed'], result['check_reasons'] = _run_checks(scenario, result)
    return result


# Canned degradation strings the router/worker path returns when no active,
# credentialed AIAgent/AIEntry is configured — NOT a genuine pass or fail,
# just evidence the scenario was never actually evaluated by a model. Without
# this check, min_insight_len alone would count these as false-positive
# passes (the canned message is long enough to satisfy it).
_DEGRADED_MARKERS = (
    'temporarily unavailable', 'Service is temporarily unavailable',
    '일시적으로 이용', '서비스 이용 불가',
)


def _looks_degraded(insight):
    return any(marker in insight for marker in _DEGRADED_MARKERS)


def _extract_proposed_device_names(ai_result):
    """Pull device display names out of a process_natural_language_command
    result's proposed_actions, so checks can assert on the actual device set
    a deterministic interceptor resolved — not just insight text length.

    Two action shapes exist and both are handled: per-device control actions
    (recent/location/map-scoped control) carry one action per device with
    `params.display_summary`; a batch creation action (e.g.
    create_sequence_function) carries ONE action for N devices, with the
    actual device set as a list of ids under `params.arguments.device_ids` —
    each id is resolved to its real Output/Input name so expect_device_count
    and expect_devices_include/exclude both work against a batch-creation
    action too, not just per-device control proposals. A plain create_function
    action (no device_ids — an empty function shell) correctly contributes NO
    names: its own display_summary describes the FUNCTION being created, not a
    device, so it must NOT be picked up as a fallback here (that previously
    broke the fc_conditional_01 zero-device check)."""
    from aot.databases.models import Input, Output
    names = []
    for act in ai_result.get('proposed_actions') or []:
        act = act or {}
        params = act.get('params') or {}
        arguments = params.get('arguments') or {}
        device_ids = arguments.get('device_ids')
        if device_ids:
            for did in device_ids:
                dev = (Output.query.filter_by(unique_id=did).first()
                       or Input.query.filter_by(unique_id=did).first())
                names.append(dev.name if dev else did)
            continue
        summary = params.get('display_summary') or params.get('name') or ''
        if summary:
            names.append(summary)
    return names


def _run_checks(scenario, result):
    checks = scenario.get('checks', {})
    reasons = []
    insight = result.get('insight', '')

    if not result.get('ok'):
        return False, ['runtime_error']

    if _looks_degraded(insight):
        result['degraded'] = True
        return None, ['no_credentials_degraded_response']

    if 'min_insight_len' in checks and len(insight) < checks['min_insight_len']:
        reasons.append('insight_too_short')

    if checks.get('forbid_command_language') and looks_like_command_language(insight):
        reasons.append('command_language_detected')

    # Which deterministic handler (recent/location/map/function_create/...)
    # was expected to fire. None checks that NOTHING fired (command fell
    # through, e.g. deliberately out of scope for every interceptor).
    if 'expect_intercept' in checks and result.get('intercept') != checks['expect_intercept']:
        reasons.append(f"intercept_mismatch(expected={checks['expect_intercept']!r}, "
                        f"actual={result.get('intercept')!r})")

    proposed = result.get('proposed_device_names') or []
    for name_substr in checks.get('expect_devices_include', ()):
        if not any(name_substr in n for n in proposed):
            reasons.append(f"expected_device_missing({name_substr!r})")

    for name_substr in checks.get('expect_devices_exclude', ()):
        if any(name_substr in n for n in proposed):
            reasons.append(f"unexpected_device_present({name_substr!r})")

    if 'expect_device_count' in checks and len(proposed) != checks['expect_device_count']:
        reasons.append(f"device_count_mismatch(expected={checks['expect_device_count']}, actual={len(proposed)})")

    return (len(reasons) == 0), reasons


def run_golden_set(db_path, category=None, save_baseline=False, label=None):
    """Run the golden set against a COPIED database at db_path.

    Refuses to run without an explicit db_path — never falls back to any
    default/live database location.

    label: optional human-readable note recorded in the metrics log (e.g.
    "no-credential baseline" when the DB copy has no active AIEntry with a
    real API key — see result['degraded'] on individual scenarios).
    """
    if not db_path:
        raise ValueError(
            "db_path is required — point this at a COPY of the database, "
            "never the live one (see project rule: 라이브 DB 테스트 금지)."
        )
    if not os.path.isfile(db_path):
        raise ValueError(f"db_path does not exist: {db_path}")

    os.environ["ALEMBIC_RUNNING"] = "1"
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db as _db
    from aot.config import ProdConfig

    class _EvalConfig(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'
        TESTING = True

    app = create_app(config=_EvalConfig)
    scenarios = GOLDEN_SET if not category else [s for s in GOLDEN_SET if s['category'] == category]

    # test_request_context (not just app_context) — some code on this path
    # (e.g. current_app.config lookups triggered from a request-like flow)
    # expects an active request context, matching how ai_portal_chat() runs
    # it in production.
    with app.test_request_context():
        results = [run_scenario(s) for s in scenarios]

    _write_results(results, save_baseline=save_baseline, label=label)
    return results


def _write_results(results, save_baseline=False, label=None):
    os.makedirs(REPORTS_DIR, exist_ok=True)

    summary = _summarize(results)
    if save_baseline or not os.path.isfile(BASELINE_PATH):
        with open(BASELINE_PATH, 'w', encoding='utf-8') as f:
            json.dump({'results': results, 'summary': summary, 'label': label}, f, ensure_ascii=False, indent=2)

    with open(METRICS_LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(f"\n## Run {datetime.utcnow().isoformat()}Z" + (f" — {label}" if label else "") + "\n\n")
        f.write(f"- scenarios: {summary['total']} · passed: {summary['passed']} · "
                f"failed: {summary['failed']} · skipped(degraded, no credentials): {summary['skipped']} · "
                f"avg_latency_ms: {summary['avg_latency_ms']}\n")
        f.write(f"- per turn: llm_calls={summary['avg_llm_calls']} · "
                f"tool_calls={summary['avg_tool_calls']} · "
                f"prompt_tokens={summary['avg_prompt_tokens']} · "
                f"output_tokens={summary['avg_output_tokens']} · "
                f"declared_tools={summary['avg_declared_tools']} · "
                f"drawer_opens(total)={summary['total_drawer_opens']}\n")
        for cat, stats in summary['by_category'].items():
            f.write(f"  - {cat}: {stats['passed']} passed / {stats['failed']} failed / "
                    f"{stats['skipped']} skipped (of {stats['total']}), avg_latency_ms={stats['avg_latency_ms']}\n")


def _summarize(results):
    total = len(results)
    passed = sum(1 for r in results if r['check_passed'] is True)
    failed = sum(1 for r in results if r['check_passed'] is False)
    skipped = sum(1 for r in results if r['check_passed'] is None)
    avg_latency = int(sum(r['latency_ms'] for r in results) / total) if total else 0

    def _m(key):
        vals = [(r.get('tool_metrics') or {}).get(key) or 0 for r in results]
        return round(sum(vals) / len(vals), 2) if vals else 0

    by_category = {}
    for r in results:
        cat = r['category']
        bucket = by_category.setdefault(cat, {'total': 0, 'passed': 0, 'failed': 0, 'skipped': 0, 'latencies': []})
        bucket['total'] += 1
        if r['check_passed'] is True:
            bucket['passed'] += 1
        elif r['check_passed'] is False:
            bucket['failed'] += 1
        else:
            bucket['skipped'] += 1
        bucket['latencies'].append(r['latency_ms'])
    for stats in by_category.values():
        stats['avg_latency_ms'] = int(sum(stats['latencies']) / len(stats['latencies'])) if stats['latencies'] else 0
        del stats['latencies']

    return {
        'total': total, 'passed': passed, 'failed': failed, 'skipped': skipped,
        'avg_latency_ms': avg_latency, 'by_category': by_category,
        # 턴당 평균 — 매니페스트/컨텍스트를 줄이는 변경의 실제 효과는 여기서 본다.
        'avg_llm_calls': _m('llm_calls'),
        'avg_tool_calls': _m('tool_calls'),
        'avg_prompt_tokens': _m('prompt_tokens'),
        'avg_output_tokens': _m('output_tokens'),
        'avg_declared_tools': _m('declared_tools_first_call'),
        'total_drawer_opens': sum((r.get('tool_metrics') or {}).get('drawer_open_count') or 0
                                  for r in results),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db-path', required=True, help='Path to a COPY of the database (never the live one)')
    parser.add_argument('--category', default=None, help='Run only this category')
    parser.add_argument('--save-baseline', action='store_true')
    parser.add_argument('--label', default=None, help='Human-readable note for the metrics log, e.g. "no-credential baseline"')
    args = parser.parse_args()

    out = run_golden_set(
        db_path=args.db_path, category=args.category,
        save_baseline=args.save_baseline, label=args.label,
    )
    print(json.dumps(_summarize(out), ensure_ascii=False, indent=2))

# coding=utf-8
"""MCP 호출 품질 장부 — 감사 행 한 번 쓰기와 품질 칸, 그리고 지표 계산.

고정하는 것:

  1. 감사 쓰기를 INSERT 한 번으로 합쳐도 **남는 내용이 예전과 같다**(원칙 7).
     예전 2단계 기록(log_call → update_status)을 이 파일 안에 그대로 두고,
     같은 입력으로 두 방식의 행을 칸 단위로 대조한다.
  2. 호출 한 번에 mcp_audit_log 에 대한 쓰기 SQL 은 INSERT 1개뿐이다.
  3. 직렬화가 깨지면 행이 1개, call_state='failed' 로 남고 예외는 그대로 올라간다.
  4. AOT_MCP_QUALITY_LEDGER=0 이면 새 칸이 전부 NULL 이다.
  5. 전송 계층이 transport·세션 열쇠를 제대로 넘긴다(HTTP 헤더 128자 상한 포함).
  6. 지표: 옛 NULL 행 제외, 열쇠 없는 행의 10분 세션, 90초 묶음, 간격 계산.

DB 는 conftest 가 만든 임시 sqlite 다(레포·라이브 DB 를 열지 않는다).
"""
import io
import json
from datetime import datetime, timedelta

import pytest
from flask import Flask

from aot.aot_flask.extensions import db
import aot.databases.models  # noqa: F401  — 모델 등록
from aot.databases.models import MCPAuditLog
from aot.mcp_server import audit, quality
from aot.tools import tool_execution as te
from aot.tools import mcp_safety_gate as gate


# ── 공용 준비 ────────────────────────────────────────────────────────────────

@pytest.fixture()
def app():
    from aot.config import AOT_DB_PATH
    a = Flask(__name__)
    a.config['SQLALCHEMY_DATABASE_URI'] = AOT_DB_PATH
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(a)
    _clear()
    yield a
    _clear()


def _clear():
    from aot.config import AOT_DB_PATH
    from aot.databases.utils import session_scope
    with session_scope(AOT_DB_PATH) as s:
        s.query(MCPAuditLog).delete()
        s.commit()


def _rows():
    from aot.config import AOT_DB_PATH
    from aot.databases.utils import session_scope
    with session_scope(AOT_DB_PATH) as s:
        out = []
        for r in s.query(MCPAuditLog).order_by(MCPAuditLog.id).all():
            out.append({c.name: getattr(r, c.name) for c in MCPAuditLog.__table__.columns})
        return out


_LEGACY_COLS = ('agent_id', 'tool_name', 'params_json', 'reason', 'permission',
                'confirmation_status', 'confirmation_id', 'user_id',
                'result_summary', 'error')
_NEW_COLS = audit.QUALITY_FIELDS


def _legacy_record(tool_name, arguments, agent_id, permission, reason,
                   blocked, result, error_text):
    """변경 전 `_record_audit` 원문 그대로 — 동등성 대조의 기준."""
    try:
        confirmation_id = (blocked or {}).get("confirmation_id")
        uid = audit.log_call(tool_name=tool_name, params=arguments,
                             agent_id=agent_id, permission=permission,
                             reason=reason, confirmation_id=confirmation_id)
        if permission == "read":
            status = "n/a"
        elif blocked is None and tool_name in gate.config_only_tools():
            status = "not_required"
        elif blocked is None:
            status = "approved"
        elif blocked.get("status") == "pending_approval":
            status = "pending"
        else:
            status = "rejected"
        summary = (blocked or {}).get("reason_code") or (
            "" if error_text else str(result.get("status", ""))[:100])
        audit.update_status(uid, status, result_summary=summary, error=error_text)
    except Exception:
        pass


def _patch_exec(monkeypatch, result=None, blocked=None, raises=None):
    """게이트·디스패치를 고정값으로. 스코프 판정은 통과."""
    monkeypatch.setattr(te, '_scope_refusal', lambda *a, **k: None)
    monkeypatch.setattr(gate, 'gate', lambda *a, **k: blocked)

    def _dispatch(name, args):
        if raises:
            raise raises
        return json.loads(json.dumps(result)) if isinstance(result, dict) else result
    monkeypatch.setattr(te, '_dispatch_virtual_tool', _dispatch)


def _config_only_tool():
    names = sorted(gate.config_only_tools())
    return names[0] if names else None


# ── 1. 행 동등성(원칙 7) ────────────────────────────────────────────────────

def _cases():
    cfg = _config_only_tool()
    cases = [
        # (이름, 도구, 결과, blocked, 예외)
        ('read-ok', 'search_devices', {'status': 'success', 'devices': [1, 2]}, None, None),
        ('read-error-key', 'search_devices', {'error': 'nope'}, None, None),
        ('read-not-found', 'search_devices', {'status': 'not_found'}, None, None),
        ('read-raises', 'search_devices', None, None, RuntimeError('boom')),
        ('read-valueerror', 'search_devices', None, None, ValueError('bad arg')),
        ('write-approved', 'operate_device', {'status': 'success'}, None, None),
        ('write-pending', 'operate_device', None,
         {'status': 'pending_approval', 'confirmation_id': 'c-1',
          'reason_code': 'approval_required'}, None),
        ('write-pending-nocode', 'operate_device', None,
         {'status': 'pending_approval', 'confirmation_id': 'c-2'}, None),
        ('write-rejected', 'operate_device', None,
         {'status': 'refused', 'reason_code': 'read_only_role'}, None),
        ('write-long-status', 'operate_device', {'status': 'x' * 300}, None, None),
    ]
    if cfg:
        cases.append(('config-only', cfg, {'status': 'success'}, None, None))
    return cases


@pytest.mark.parametrize('case', _cases(), ids=lambda c: c[0])
def test_single_insert_row_equals_the_two_step_row(app, monkeypatch, case):
    _name, tool, result, blocked, raises = case
    args = {'target': 'x', '_reason': 'because'}
    _patch_exec(monkeypatch, result=result, blocked=blocked, raises=raises)

    te._execute_tool(app, tool, dict(args), agent_id='user:alice/claude')
    new = _rows()
    assert len(new) == 1
    _clear()

    # 예전 방식 — 실행 결과(blocked 면 blocked 가 곧 result)를 그대로 넘긴다.
    permission = gate.classify_permission(tool)
    if raises is not None:
        legacy_result = {'status': 'error', 'message': str(raises)}
        error_text = str(raises)
    else:
        legacy_result = blocked if blocked is not None else dict(result)
        error_text = ''
    _legacy_record(tool, dict(args), 'user:alice/claude', permission, 'because',
                   blocked, legacy_result, error_text)
    old = _rows()
    assert len(old) == 1
    for col in _LEGACY_COLS:
        assert new[0][col] == old[0][col], col


def test_non_dict_result_keeps_the_old_insert_default(app, monkeypatch):
    """결과가 dict 가 아니면 예전에는 UPDATE 가 깨져 INSERT 기본값이 남았다."""
    _patch_exec(monkeypatch, result=['a', 'b'])
    te._execute_tool(app, 'operate_device', {}, agent_id='a')
    row = _rows()[0]
    assert row['confirmation_status'] == 'pending'
    assert row['result_summary'] == ''
    assert row['call_state'] == 'executed'
    assert row['result_items'] is None


# ── 2. 쓰기 횟수 ────────────────────────────────────────────────────────────

def test_one_call_writes_exactly_one_insert(app, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    _patch_exec(monkeypatch, result={'status': 'success', 'items': [1]})
    seen = []

    def _spy(conn, cursor, statement, params, context, executemany):
        low = statement.lower()
        if 'mcp_audit_log' in low and not low.lstrip().startswith('select'):
            seen.append(low.split()[0])

    called = {'log_call': 0, 'update_status': 0}
    monkeypatch.setattr(audit, 'log_call',
                        lambda *a, **k: called.__setitem__('log_call', 1) or '')
    monkeypatch.setattr(audit, 'update_status',
                        lambda *a, **k: called.__setitem__('update_status', 1))
    event.listen(Engine, 'before_cursor_execute', _spy)
    try:
        te._execute_tool(app, 'search_devices', {}, agent_id='a')
    finally:
        event.remove(Engine, 'before_cursor_execute', _spy)
    assert seen == ['insert']
    assert called == {'log_call': 0, 'update_status': 0}


# ── 3. 직렬화 예외 ──────────────────────────────────────────────────────────

def test_serialization_failure_leaves_one_failed_row(app, monkeypatch):
    class _Opaque:
        pass

    monkeypatch.setattr(te, '_scope_refusal', lambda *a, **k: None)
    monkeypatch.setattr(gate, 'gate', lambda *a, **k: None)
    monkeypatch.setattr(te, '_dispatch_virtual_tool',
                        lambda n, a: {'status': 'success', 'thing': _Opaque()})
    with pytest.raises(TypeError):
        te._execute_tool(app, 'search_devices', {}, agent_id='a')
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]['call_state'] == 'failed'
    assert rows[0]['error'].startswith('TypeError(')
    assert rows[0]['response_bytes'] is None
    assert rows[0]['duration_ms'] is not None


def test_base_exception_leaves_one_failed_row_and_propagates(app, monkeypatch):
    class _Stop(BaseException):
        """KeyboardInterrupt·SystemExit 류 — Exception 이 아니다."""

    _patch_exec(monkeypatch, result={'status': 'success', 'devices': [1]})

    def _boom(*a, **k):
        raise _Stop('halt')
    monkeypatch.setattr(te, '_finish_result', _boom)
    with pytest.raises(_Stop):
        te._execute_tool(app, 'search_devices', {}, agent_id='a',
                         transport='mcp_http', session_key='k')
    rows = _rows()
    assert len(rows) == 1                          # finally 가 한 번만 적는다
    assert rows[0]['call_state'] == 'failed'
    assert rows[0]['error'] == repr(_Stop('halt'))
    assert rows[0]['response_bytes'] is None
    assert rows[0]['duration_ms'] is not None


# ── 4. 품질 칸 채우기와 스위치 ────────────────────────────────────────────────

def test_quality_fields_are_filled(app, monkeypatch):
    monkeypatch.delenv('AOT_MCP_QUALITY_LEDGER', raising=False)
    _patch_exec(monkeypatch, result={'status': 'success', 'count': 3,
                                     'devices': [1, 2, 3, 4]})
    out = te._execute_tool(app, 'search_devices', {}, agent_id='a',
                           transport='mcp_http', session_key='sess-abc')
    row = _rows()[0]
    assert row['transport'] == 'mcp_http'
    assert row['via_drawer'] is False
    assert row['call_state'] == 'executed'
    assert row['result_items'] == 3            # count 가 목록 길이보다 먼저
    assert row['truncated'] is False
    assert row['response_bytes'] == len(out[0]['text'].encode('utf-8'))
    assert isinstance(row['response_tokens'], int) and row['response_tokens'] > 0
    assert isinstance(row['duration_ms'], int) and row['duration_ms'] >= 0
    # 세션 열쇠는 해시 16자만 남는다 — 원문은 어디에도 없다.
    assert row['session_key'] == te.session_key_hash('sess-abc')
    assert len(row['session_key']) == 16 and 'sess' not in row['session_key']


def test_use_tool_marks_via_drawer(app, monkeypatch):
    _patch_exec(monkeypatch, result={'status': 'success'})
    te._execute_tool(app, 'use_tool',
                     {'tool_name': 'search_devices', 'arguments': {}},
                     agent_id='a', transport='mcp_stdio', session_key='s')
    rows = _rows()
    assert len(rows) == 1                     # use_tool 자신은 행을 남기지 않는다
    assert rows[0]['tool_name'] == 'search_devices'
    assert rows[0]['via_drawer'] is True
    assert rows[0]['transport'] == 'mcp_stdio'


def test_truncated_response_records_pre_cap_tokens_and_post_cap_bytes(app, monkeypatch):
    monkeypatch.setattr(te, '_MAX_RESPONSE_TOKENS', 300)
    big = {'status': 'success', 'rows': [{'name': 'row-%d' % i, 'v': 'x' * 40}
                                         for i in range(200)]}
    _patch_exec(monkeypatch, result=big)
    out = te._execute_tool(app, 'search_devices', {}, agent_id='a')
    row = _rows()[0]
    assert row['truncated'] is True
    assert row['result_items'] == 200         # 캡 **전** 건수
    sent = out[0]['text']
    assert row['response_bytes'] == len(sent.encode('utf-8'))   # 캡 **후** 크기
    assert row['response_tokens'] > te._estimate_tokens(sent)   # 캡 **전** 추정


def test_flag_off_leaves_new_columns_null(app, monkeypatch):
    monkeypatch.setenv('AOT_MCP_QUALITY_LEDGER', '0')
    _patch_exec(monkeypatch, result={'status': 'success', 'devices': []})
    te._execute_tool(app, 'search_devices', {}, agent_id='a',
                     transport='mcp_http', session_key='k')
    row = _rows()[0]
    for col in _NEW_COLS:
        assert row[col] is None, col
    assert row['confirmation_status'] == 'n/a'   # 감사 행 자체는 그대로


def test_result_items_rule():
    ri = te._result_items
    assert ri({'count': 0, 'items': [1, 2]}) == 0
    assert ri({'total': 5}) == 5
    assert ri({'matched': 2, 'total': 9}) == 9        # count→total→matched 순
    assert ri({'count': True, 'a': [1]}) == 1         # bool 은 정수로 안 친다
    assert ri({'a': [1, 2], 'b': [1, 2, 3]}) is None  # 본 결과가 어느 것인지 모른다
    assert ri({'status': 'ok'}) is None
    assert ri(['x']) is None
    # 곁가지 목록과 `_` 키는 세지 않는다 — 본 결과가 비면 0 이다.
    assert ri({'devices': [], 'warnings': ['w'], 'errors': ['e'],
               'notes': ['n'], 'hints': ['h'], 'see': ['s']}) == 0
    assert ri({'rows': [1, 2], '_content_blocks': [1], 'available_releases': [1, 2, 3],
               'controlling_tools': ['x']}) == 2
    assert ri({'warnings': ['only aux']}) is None
    assert ri({'count': 4, 'a': [1], 'b': [2]}) == 4  # 도구가 센 값이 먼저


def test_cap_stats_reports_the_estimate_it_already_made():
    stats = {}
    te._cap_result({'status': 'ok'}, 't', max_tokens=1000, stats=stats)
    assert stats['original'] == te._estimate_tokens(json.dumps({'status': 'ok'}))
    off = {}
    te._cap_result({'status': 'ok'}, 't', max_tokens=0, stats=off)
    assert off == {}                              # 캡을 끄면 NULL


def test_session_key_hash_bounds():
    assert te.session_key_hash(None) is None
    assert te.session_key_hash('') is None
    assert te.session_key_hash('x' * 129) is None
    assert len(te.session_key_hash('x' * 128)) == 16


# ── 5. 전송 계층 배선 ───────────────────────────────────────────────────────

def _server():
    import importlib
    return importlib.import_module('aot.aot_mcp_server')


def _http_app(monkeypatch, app):
    """_run_http_server 가 만드는 Flask 앱을 serve 직전에 가로챈다."""
    import sys
    import types
    srv = _server()
    captured = {}
    fake = types.ModuleType('waitress')
    fake.serve = lambda http_app, **kw: captured.setdefault('app', http_app)
    monkeypatch.setitem(sys.modules, 'waitress', fake)
    from aot.tools import mcp_auth
    monkeypatch.setattr(mcp_auth, 'authenticate_http',
                        lambda headers, declared=None: (True, 'agent-x', None, None))
    calls = []

    def _fake_exec(a, name, arguments, **kw):
        calls.append(dict(kw, name=name))
        return [{'type': 'text', 'text': '{}'}]
    monkeypatch.setattr(srv, '_execute_tool', _fake_exec)
    srv._run_http_server(app, port=0)
    return captured['app'].test_client(), calls


def _rpc_call(name='search_devices'):
    return {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': name, 'arguments': {}}}


def test_http_session_header_reaches_the_execution_layer(app, monkeypatch):
    client, calls = _http_app(monkeypatch, app)
    r = client.post('/mcp', json=_rpc_call(), headers={'Mcp-Session-Id': 'abc123'})
    assert r.status_code == 200
    assert calls[-1]['transport'] == 'mcp_http'
    assert calls[-1]['session_key'] == 'abc123'

    client.post('/mcp', json=_rpc_call(), headers={'Mcp-Session-Id': 'y' * 129})
    assert calls[-1]['session_key'] is None       # 128자 상한

    client.post('/mcp', json=_rpc_call())
    assert calls[-1]['session_key'] is None


def test_rest_route_is_marked_rest_without_a_session(app, monkeypatch):
    client, calls = _http_app(monkeypatch, app)
    r = client.post('/mcp/tools/call', json={'name': 'search_devices', 'arguments': {}},
                    headers={'Mcp-Session-Id': 'abc'})
    assert r.status_code == 200
    assert calls[-1]['transport'] == 'rest'
    assert calls[-1].get('session_key') is None


def test_stdio_uses_one_process_key(app, monkeypatch):
    srv = _server()
    calls = []
    monkeypatch.setattr(srv, '_execute_tool',
                        lambda a, n, args, **kw: calls.append(kw) or [])
    s = srv.StdioMCPServer(app, out=io.StringIO())
    s._authed = True
    s._initialized = True
    for i in range(2):
        s._handle({'jsonrpc': '2.0', 'id': i, 'method': 'tools/call',
                   'params': {'name': 'search_devices', 'arguments': {}}})
    assert [c['transport'] for c in calls] == ['mcp_stdio', 'mcp_stdio']
    assert calls[0]['session_key'] == calls[1]['session_key']
    assert len(calls[0]['session_key']) == 32


def test_in_app_thread_id_becomes_the_session_key(app, monkeypatch):
    from aot.ai import ai_request_context as ctx
    from aot.ai.services.resolvers import mcp_tool_call_resolver as mod

    got = {}
    monkeypatch.setattr(mod, '_is_builtin_server', lambda sid: True)
    monkeypatch.setattr(te, 'execute_for_agent',
                        lambda *a, **kw: got.update(kw) or {'status': 'success', 'result': {}})
    token = ctx.push(thread_id='thread-42')
    try:
        with app.app_context():
            mod.MCPToolCallResolver().execute(
                'mcp_tool_call', 'srv', {'tool_name': 'search_devices'}, None)
    finally:
        ctx.pop(token)
    assert got['session_key'] == 'thread-42'
    assert ctx.get_thread_id() is None            # pop 이 되돌린다


def test_worker_threads_carry_only_the_thread_id():
    """계획 실행기의 병렬 단계 — 워커는 대화 thread_id 만 이어받는다.
    첨부·깊이·자율은 예전처럼 비어 있어야 한다(인앱 AI 동작 불변)."""
    from concurrent.futures import ThreadPoolExecutor
    from aot.ai import ai_request_context as ctx

    def _peek():
        return (ctx.get_thread_id(), ctx.get_attachments(), ctx.get_depth(),
                ctx.get_autonomy())

    token = ctx.push(attachments=[{'media_type': 'image/png', 'base64_data': 'x'}],
                     depth='deep', autonomy='auto', thread_id='thread-7')
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            bare = pool.submit(_peek).result()
            bound = pool.submit(ctx.bind_thread_id(_peek)).result()
            after = pool.submit(_peek).result()     # 같은 워커 재사용 — 되돌렸는가
    finally:
        ctx.pop(token)
    assert bare == (None, [], None, None)          # 예전 그대로
    assert bound == ('thread-7', [], None, None)   # thread_id 만
    assert after == (None, [], None, None)


def test_planner_submits_steps_with_the_thread_id():
    import inspect
    from aot.ai.services import ai_planning_service as mod
    src = inspect.getsource(mod)
    assert 'pool.submit(_ai_ctx.bind_thread_id(execute_single_step), s)' in src


def test_execute_for_agent_passes_in_app_transport(app, monkeypatch):
    from aot.tools import mcp_auth
    monkeypatch.setattr(mcp_auth, 'ensure_service_account', lambda: None)
    monkeypatch.setattr(mcp_auth, '_role_for', lambda u: None)
    seen = {}

    def _fake(a, name, args, **kw):
        seen.update(kw)
        return [{'type': 'text', 'text': json.dumps({'call_state': 'executed'})}]
    monkeypatch.setattr(te, '_execute_tool', _fake)
    with app.app_context():
        te.execute_for_agent(app, 'search_devices', {}, session_key='t-1',
                             scope_user_uuid='u')
    assert seen['transport'] == 'in_app'
    assert seen['session_key'] == 't-1'


# ── 6. 지표 ─────────────────────────────────────────────────────────────────

T0 = datetime(2026, 9, 1, 12, 0, 0)


def _r(sec, tool='search_devices', key='s1', transport='mcp_http', agent='a',
       dur=100, state='executed', items=1, summary='success', via=False,
       truncated=False, perm='read'):
    return {'timestamp': T0 + timedelta(seconds=sec), 'agent_id': agent,
            'tool_name': tool, 'permission': perm, 'result_summary': summary,
            'duration_ms': dur, 'session_key': key, 'transport': transport,
            'via_drawer': via, 'response_tokens': 10, 'response_bytes': 20,
            'truncated': truncated, 'call_state': state, 'result_items': items}


def _old(sec):
    r = _r(sec)
    for c in _NEW_COLS:
        r[c] = None
    return r


def test_old_null_rows_only_count_toward_the_measured_ratio():
    rows = [_r(0), _r(10), _old(20), _old(30)]
    q = quality.summarize(rows)
    assert q['rows_total'] == 4
    assert q['rows_measured'] == 2
    assert q['measured_ratio'] == 0.5
    assert q['overall']['calls'] == 2


def test_bundles_split_after_ninety_seconds_of_silence():
    # 시작 = timestamp − duration. 두 번째 호출은 91초 뒤 **끝났지만** 5초 걸려
    # 86초 뒤에 시작했다 → 같은 묶음. 세 번째는 앞 끝에서 92초 뒤 시작 → 새 묶음.
    rows = [_r(0, dur=0), _r(91, dur=5000), _r(183, dur=0)]
    o = quality.summarize(rows)['overall']
    assert o['bundles'] == 2
    assert o['gap_p50_ms'] == 86000


def test_keyless_rows_fall_back_to_ten_minute_sessions():
    rows = [_r(0, key=None), _r(60, key=None),
            _r(60 + 601, key=None),                    # 10분 넘게 비었다 → 새 세션
            _r(30, key=None, agent='b')]               # 다른 주체는 다른 세션
    o = quality.summarize(rows)['overall']
    assert o['bundles'] == 3


def test_flow_metrics():
    rows = [
        _r(0, tool='open_drawer'),
        _r(5, tool='get_x', via=True),
        _r(10, tool='get_x', via=True),
        _r(15, tool='get_x', via=True, items=0),
        _r(20, tool='resolve_target', summary='needs_disambiguation'),
        _r(25, tool='operate_device', perm='write', state='pending_approval'),
        _r(30, tool='search_devices', state='failed', truncated=True),
    ]
    q = quality.summarize(rows)
    o = q['overall']
    assert o['bundles'] == 1
    assert o['calls_per_bundle_p50'] == 7
    assert o['discovery_first_rate'] == 1.0
    assert o['drawer_follow_through_rate'] == 1.0
    assert o['longest_same_tool_run'] == 3
    assert o['same_tool_repeat_rate'] == round(2 / 6, 4)
    assert o['empty_rate'] == round(1 / 7, 4)
    assert o['disambiguation_rate'] == round(1 / 7, 4)
    assert o['pending_rate'] == round(1 / 7, 4)
    assert o['error_rate'] == round(1 / 7, 4)
    assert o['truncated_rate'] == round(1 / 7, 4)
    # 지연은 실행된 읽기 호출만(대기·실패 제외) — 5건.
    assert o['latency_samples'] == 5
    assert 'mcp_http' in q['by_transport']
    cats = {c['category'] for c in q['by_category']}
    assert 'drawer' in cats


def test_answered_not_found_and_disambiguation_are_not_errors():
    """대상 없음·되묻기는 도구가 `error` 키를 함께 실어 failed 로 적힌다.
    오류율에서는 빼고 빈 결과·되묻기에만 센다. 지연 표본에는 넣는다."""
    rows = [
        _r(0, tool='add_schedule', state='failed', summary='needs_disambiguation',
           items=None, dur=40),
        _r(5, tool='get_note', state='failed', summary='not_found', items=None, dur=60),
        _r(10, tool='get_note', state='executed', summary='not_found', items=None, dur=70),
        _r(15, tool='search_devices', state='failed', summary='', items=None, dur=900),
        _r(20, tool='search_devices', state='executed', items=2, dur=80),
    ]
    o = quality.summarize(rows)['overall']
    assert o['error_rate'] == round(1 / 5, 4)          # 진짜 실패 하나만
    assert o['disambiguation_rate'] == round(1 / 5, 4)
    assert o['empty_rate'] == round(2 / 5, 4)          # not_found 두 줄
    # 실행 2 + 답한 failed 2 = 4. 진짜 실패(900ms)는 빠진다.
    assert o['latency_samples'] == 4
    assert o['latency_p90_ms'] == 80
    cats = quality.summarize(rows)['by_category']
    assert sum(c['calls'] for c in cats) == 5


def test_header_keyed_sessions_are_also_split_by_agent():
    rows = [_r(0, key='same', agent='a'), _r(5, key='same', agent='b'),
            _r(10, key='same', agent='a')]
    o = quality.summarize(rows)['overall']
    assert o['bundles'] == 2
    assert o['calls_per_bundle_p50'] == 1 and o['calls_per_bundle_p90'] == 2


def test_drawer_open_pairs_with_at_most_one_following_drawer_call():
    # 열기 두 번 뒤 경유 호출 하나 → 전환 1/2.
    rows = [_r(0, tool='open_drawer'), _r(3, tool='get_tool_detail'),
            _r(6, tool='get_x', via=True)]
    assert quality.summarize(rows)['overall']['drawer_follow_through_rate'] == 0.5
    # 열기 하나 뒤 경유 호출 셋 → 1/1(여러 번 세지 않는다).
    rows = [_r(0, tool='open_drawer'), _r(3, tool='get_x', via=True),
            _r(6, tool='get_y', via=True), _r(9, tool='get_z', via=True)]
    assert quality.summarize(rows)['overall']['drawer_follow_through_rate'] == 1.0
    # 열기 → 경유 → 열기 → 경유 → 경유 : 2/2.
    rows = [_r(0, tool='open_drawer'), _r(3, tool='get_x', via=True),
            _r(6, tool='open_drawer'), _r(9, tool='get_y', via=True),
            _r(12, tool='get_z', via=True)]
    assert quality.summarize(rows)['overall']['drawer_follow_through_rate'] == 1.0
    # 다른 묶음의 경유 호출은 짝이 아니다.
    rows = [_r(0, tool='open_drawer'), _r(200, tool='get_x', via=True)]
    assert quality.summarize(rows)['overall']['drawer_follow_through_rate'] == 0.0


def test_summary_carries_no_identity():
    rows = [_r(0, agent='user:alice/claude', key='secret-session-key')]
    text = json.dumps(quality.summarize(rows), default=str)
    assert 'alice' not in text
    assert 'secret-session-key' not in text
    assert 'agent_id' not in text and 'session_key' not in text


def test_compute_quality_reads_the_db_and_caches(app, monkeypatch):
    quality.clear_cache()
    audit.record_call('search_devices', {}, agent_id='a', call_state='executed',
                      transport='mcp_http', duration_ms=12, session_key='k')
    audit.record_call('search_devices', {}, agent_id='a')     # 옛 모양(NULL)
    q = quality.compute_quality(days=7)
    assert q['rows_total'] == 2 and q['rows_measured'] == 1
    assert q['limited'] is False
    audit.record_call('search_devices', {}, agent_id='a', call_state='executed')
    assert quality.compute_quality(days=7)['rows_total'] == 2   # 60초 캐시
    quality.clear_cache()
    assert quality.compute_quality(days=7, max_rows=2)['limited'] is True
    quality.clear_cache()


def test_record_call_rejects_unknown_quality_fields(app):
    assert audit.record_call('t', {}, not_a_column=1) == ''
    assert _rows() == []


# ── 7. 서랍 열기 — 인자 없이 부르면 목록(오류 아님) ─────────────────────────────

def test_open_drawer_without_argument_returns_the_index_without_error(app, monkeypatch):
    index = [{'drawer': 'device', 'description': 'd', 'tools': ['search_devices']}]
    monkeypatch.setattr(te, '_drawer_index', lambda a, role=None: index)
    assert te._open_drawer(app, {}) == {'drawers': index}
    assert te._open_drawer(app, None) == {'drawers': index}
    wrong = te._open_drawer(app, {'drawer': 'nope'})
    assert wrong['error'] == 'unknown drawer: nope'   # 모르는 이름은 여전히 알린다
    assert wrong['drawers'] == index


def test_open_drawer_without_argument_is_recorded_as_executed(app, monkeypatch):
    index = [{'drawer': 'device', 'description': 'd', 'tools': ['search_devices']}]
    monkeypatch.setattr(te, '_drawer_index', lambda a, role=None: index)
    out = te._execute_tool(app, 'open_drawer', {}, agent_id='a', transport='mcp_http')
    body = json.loads(out[0]['text'])
    assert 'error' not in body
    assert body['call_state'] == 'executed'
    assert _rows()[0]['call_state'] == 'executed'

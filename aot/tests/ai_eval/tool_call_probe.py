# coding=utf-8
"""한 턴에서 **LLM 왕복과 도구 호출을 실제로 센다**.

runner.py 의 `approx_tokens` 는 최종 답변 글자수÷4 라서, 서랍 구조가 왕복을
몇 번 늘렸는지·매 호출에 실제로 몇 토큰이 실렸는지를 답하지 못한다. 고정비
−77% 가 순이익인지 아닌지는 그 두 숫자에 달려 있으므로 여기서 센다.

세는 지점 4곳
    1. `requests.post`   — 프로바이더 응답의 usage 메타데이터(진짜 토큰 수),
                            요청 payload 에 실린 **도구 선언 개수**, 응답의
                            functionCall/tool_use 이름. 엔진이 자체 함수호출
                            루프를 도는 경우(gemini 는 요청 1건 안에서 최대 3턴)
                            AgentLoopService 의 step 만 세면 놓친다.
    2. `_safe_api_result` — 모델이 **텍스트 JSON 으로** 낸 actions. 네이티브
                            함수호출을 붙여 놓아도 실제로는 이쪽으로 답하는
                            경우가 많다(로컬 gemini 관측). 1번만 세면 도구
                            호출이 0으로 보인다.
    3. `execute_action`  — 실제로 실행된 도구. 엔진 내부 루프와 AgentLoop 의
                            읽기 도구 실행이 모두 이 지점을 지난다.
    4. `open_drawer`     — 연 서랍 이름과 성공 여부. 모르는 이름은 오류가 아니라
                            목록을 돌려주므로(설계 의도), 그것을 "실패" 가 아니라
                            **다시 고르기** 로 따로 세야 왕복 계산이 맞는다.

안전: 승인이 필요한 도구(물리 제어·변경)는 이 프로브가 **실행 직전에 막는다**.
정상 경로에서는 애초에 승인 큐로 가므로 한 번도 안 걸려야 정상이고, 걸리면
그 자체가 승인 게이트 구멍이라는 발견이다(blocked_writes 에 남는다).
"""
import json
import time

_LLM_HOST_HINTS = (
    'generativelanguage', 'googleapis.com/v1beta', 'api.anthropic.com',
    'api.openai.com', 'api.groq.com', 'api.mistral.ai', 'openai.azure.com',
    ':11434', '/v1/chat/completions', '/v1/messages',
)


def _looks_like_llm(url, payload):
    u = (url or '')
    if any(h in u for h in _LLM_HOST_HINTS):
        return True
    return isinstance(payload, dict) and (
        'contents' in payload or 'messages' in payload)


def _json_len(obj):
    if obj is None:
        return 0
    try:
        return len(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return None


def _count_declared_tools(payload):
    """요청에 실제로 실린 도구 선언 개수 — 고정비의 직접 측정치."""
    if not isinstance(payload, dict):
        return None
    tools = payload.get('tools')
    if isinstance(tools, list):
        if tools and isinstance(tools[0], dict) and 'function_declarations' in tools[0]:
            return sum(len(t.get('function_declarations') or []) for t in tools)
        return len(tools)
    return 0 if tools is None else None


def _extract_usage(data):
    """(prompt_tokens, output_tokens) — 프로바이더별 이름만 다르다."""
    if not isinstance(data, dict):
        return None, None
    um = data.get('usageMetadata')
    if isinstance(um, dict):
        return um.get('promptTokenCount'), um.get('candidatesTokenCount')
    u = data.get('usage')
    if isinstance(u, dict):
        return (u.get('input_tokens') or u.get('prompt_tokens'),
                u.get('output_tokens') or u.get('completion_tokens'))
    return None, None


def _extract_tool_calls(data):
    """응답에서 모델이 부른 도구 이름들(순서 유지)."""
    names = []
    if not isinstance(data, dict):
        return names
    for cand in (data.get('candidates') or []):                 # gemini
        for part in ((cand.get('content') or {}).get('parts') or []):
            fc = part.get('functionCall')
            if isinstance(fc, dict) and fc.get('name'):
                names.append(fc['name'])
    for block in (data.get('content') or []):                   # anthropic
        if isinstance(block, dict) and block.get('type') == 'tool_use':
            names.append(block.get('name'))
    for ch in (data.get('choices') or []):                      # openai 계열
        for tc in ((ch.get('message') or {}).get('tool_calls') or []):
            fn = (tc or {}).get('function') or {}
            if fn.get('name'):
                names.append(fn['name'])
    return [n for n in names if n]


def _classes_defining(attr):
    """`attr` 를 **직접 정의한** 클래스를 전부 찾는다.

    엔진 베이스(AbstractAI)를 sys.modules 로 하나만 잡아 패치하면 놓친다 —
    앱 부팅 과정에서 base_ai 가 다시 실행되면 모듈의 AbstractAI 는 새 객체로
    바뀌는데 이미 정의된 GeminiAI 의 MRO 는 **옛 클래스**를 그대로 붙들고 있다.
    (관측: 패치 후에도 GeminiAI._safe_api_result 가 원본이었다.) 그래서 모듈에
    노출된 클래스들의 MRO 를 훑어 정의 클래스를 모두 모은다.
    """
    import sys
    seen, out = set(), []
    for mod in list(sys.modules.values()):
        try:
            members = list(vars(mod).values())
        except Exception:
            continue
        for obj in members:
            if not isinstance(obj, type):
                continue
            try:
                mro = obj.__mro__
            except Exception:
                continue
            for klass in mro:
                if id(klass) in seen:
                    continue
                seen.add(id(klass))
                if attr in klass.__dict__:
                    out.append(klass)
    return out


def _action_tool_name(action):
    """AgentLoopService._tool_name 과 같은 규칙 — 모양이 여러 가지다."""
    if not isinstance(action, dict):
        return None
    p = action.get('params') or {}
    args = p.get('arguments') if isinstance(p.get('arguments'), dict) else {}
    return (action.get('tool_name') or p.get('tool_name')
            or args.get('tool_name') or action.get('action_type'))


class ToolCallProbe:
    """with 블록 안에서 일어난 LLM 왕복·도구 호출을 기록한다."""

    def __init__(self, block_writes=True):
        self.block_writes = block_writes
        self.reset()

    def reset(self):
        self.llm_calls = []        # [{declared_tools, prompt_tokens, output_tokens, tool_calls}]
        self.tool_calls = []       # 모델이 부른 도구 이름 — 순서대로
        self.executed = []         # 실제로 실행된 도구
        self.drawer_opens = []     # [{drawer, ok}]
        self.blocked_writes = []
        self.http_errors = 0

    # ── 집계 ────────────────────────────────────────────────────────────
    def summary(self):
        return {
            'llm_calls': len(self.llm_calls),
            'tool_calls': len(self.tool_calls),
            'tool_call_names': list(self.tool_calls),
            'executed': list(self.executed),
            'drawer_opens': list(self.drawer_opens),
            'drawer_open_count': len(self.drawer_opens),
            # 서랍 열기가 **MCP 경유**로 나가면 별도 프로세스에서 실행되므로
            # 위의 handler 후킹이 못 본다. 그때도 execute_action 은 지나가므로
            # 이 숫자가 실제 시도 횟수다(어느 서랍인지는 알 수 없다).
            'drawer_open_attempts': self.executed.count('open_drawer'),
            # 왕복별 상세 — 선언 개수·토큰·그 왕복에서 부른 도구.
            'calls': [dict(c) for c in self.llm_calls],
            'drawer_miss_count': sum(1 for d in self.drawer_opens if not d['ok']),
            'distinct_drawers': sorted({d['drawer'] for d in self.drawer_opens
                                        if d['drawer']}),
            'prompt_tokens': sum(c['prompt_tokens'] or 0 for c in self.llm_calls),
            'output_tokens': sum(c['output_tokens'] or 0 for c in self.llm_calls),
            'declared_tools_first_call': (self.llm_calls[0]['declared_tools']
                                          if self.llm_calls else None),
            'payload_chars_first_call': (self.llm_calls[0]['payload_chars']
                                         if self.llm_calls else None),
            'tools_chars_first_call': (self.llm_calls[0]['tools_chars']
                                       if self.llm_calls else None),
            'max_declared_tools': max([c['declared_tools'] or 0
                                       for c in self.llm_calls] or [0]),
            'blocked_writes': list(self.blocked_writes),
            'http_errors': self.http_errors,
        }

    # ── 패치 ────────────────────────────────────────────────────────────
    def __enter__(self):
        import requests
        from aot.ai.services.ai_action_service import AIActionService
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        self._orig_post = requests.post
        self._safe_targets = [(k, k.__dict__['_safe_api_result'])
                              for k in _classes_defining('_safe_api_result')]
        self._orig_exec = AIActionService.execute_action.__func__ \
            if hasattr(AIActionService.execute_action, '__func__') \
            else AIActionService.execute_action
        self._orig_drawer = AoTDataToolService.open_drawer.__func__ \
            if hasattr(AoTDataToolService.open_drawer, '__func__') \
            else AoTDataToolService.open_drawer
        probe = self

        def post(url, *a, **kw):
            payload = kw.get('json')
            resp = probe._orig_post(url, *a, **kw)
            if not _looks_like_llm(url, payload):
                return resp
            record = {
                'declared_tools': _count_declared_tools(payload),
                # 도구 정의가 요청 전체에서 차지하는 비중을 보려고 함께 잰다.
                # 고정비 −77% 가 요청 하나에서 몇 %인지는 이 둘의 비로 나온다.
                'payload_chars': _json_len(payload),
                'tools_chars': _json_len((payload or {}).get('tools')
                                         if isinstance(payload, dict) else None),
                'prompt_tokens': None, 'output_tokens': None, 'tool_calls': [],
                'status': getattr(resp, 'status_code', None),
                'at': time.time(),
            }
            try:
                data = resp.json()
            except Exception:
                data = None
            if getattr(resp, 'status_code', 200) >= 400:
                probe.http_errors += 1
            p, o = _extract_usage(data)
            record['prompt_tokens'], record['output_tokens'] = p, o
            record['tool_calls'] = _extract_tool_calls(data)
            probe.tool_calls.extend(record['tool_calls'])
            probe.llm_calls.append(record)
            return resp

        def execute_action(action_type=None, target_id=None, params=None, **kw):
            params = params or {}
            name = (params.get('tool_name')
                    or (params.get('arguments') or {}).get('tool_name')
                    or action_type)
            probe.executed.append(name)
            if probe.block_writes:
                try:
                    unsafe = AIActionService.requires_approval(name)
                except Exception:
                    unsafe = False
                if unsafe:
                    # 여기 걸리면 승인 게이트를 우회해 실행되려던 것이다.
                    probe.blocked_writes.append(name)
                    return {'status': 'error',
                            'message': 'blocked by eval probe (write/physical tool)'}
            return probe._orig_exec(action_type, target_id, params, **kw)

        def open_drawer(drawer=None, **extra):
            result = probe._orig_drawer(drawer=drawer, **extra)
            probe.drawer_opens.append({
                'drawer': drawer,
                'ok': bool(isinstance(result, dict) and not result.get('error')),
                'count': (result or {}).get('count') if isinstance(result, dict) else None,
            })
            return result

        def _make_safe(orig):
            def safe_api_result(self_engine, raw_text, engine_name):
                result = orig(self_engine, raw_text, engine_name)
                names = [n for n in (_action_tool_name(a)
                                     for a in ((result or {}).get('actions') or [])) if n]
                if names:
                    probe.tool_calls.extend(names)
                    if probe.llm_calls:
                        probe.llm_calls[-1].setdefault('parsed_calls', []).extend(names)
                return result
            return safe_api_result

        requests.post = post
        for klass, orig in self._safe_targets:
            setattr(klass, '_safe_api_result', _make_safe(orig))
        AIActionService.execute_action = staticmethod(execute_action)
        AoTDataToolService.open_drawer = staticmethod(open_drawer)
        return self

    def __exit__(self, *exc):
        import requests
        from aot.ai.services.ai_action_service import AIActionService
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        requests.post = self._orig_post
        for klass, orig in self._safe_targets:
            setattr(klass, '_safe_api_result', orig)
        AIActionService.execute_action = staticmethod(self._orig_exec)
        AoTDataToolService.open_drawer = staticmethod(self._orig_drawer)
        return False


def probe_scenario(fn, *args, **kwargs):
    """fn 을 프로브 안에서 실행하고 (결과, 계측) 을 돌려준다."""
    with ToolCallProbe() as p:
        started = time.monotonic()
        try:
            result = fn(*args, **kwargs)
            err = None
        except Exception as e:
            result, err = None, '%s: %s' % (type(e).__name__, e)
        elapsed = int((time.monotonic() - started) * 1000)
    metrics = p.summary()
    metrics['latency_ms'] = elapsed
    if err:
        metrics['error'] = err
    return result, metrics


def format_trace(metrics):
    """도구 호출 순서를 한 줄로 — 보고서에 그대로 붙일 수 있게."""
    names = metrics.get('tool_call_names') or []
    return ' → '.join(names) if names else '(도구 호출 없음)'


if __name__ == '__main__':
    print(json.dumps({'note': 'import 용 모듈입니다. drawer_ab.py 를 실행하세요.'},
                     ensure_ascii=False))

# coding=utf-8
"""설정 모달(`?*_type=options`) 요청 구간별 계측.

- options 요청에는 항상 `Server-Timing: app;dur=<뷰 시간>` 헤더를 붙인다(개발자도구 Timing 탭, `?modal_trace=1` 토스트).
- 자세한 계측은 `AOT_TRACE_MODAL=1` 이거나, 요청을 낸 페이지 주소(Referer)에 `modal_trace=1` 이 있을 때만 켠다.
  한 요청에서 전체 시간·CPU 시간·DB 질의 수/시간·응답 크기를 한 줄로 `[modal-trace]` 로 남긴다.
  전체 - CPU 가 크면 파이썬이 일하지 않고 **기다린 시간**(GIL·DB 락·다른 요청과의 경쟁)이다.
"""
import cProfile
import functools
import io
import logging
import os
import pstats
import time

from flask import make_response, request
from sqlalchemy import event

from aot.aot_flask.extensions import db

logger = logging.getLogger(__name__)

_SLOW_TOP = 3


def _detailed():
    return os.environ.get('AOT_TRACE_MODAL') == '1' or \
        'modal_trace=1' in (request.referrer or '')


def trace_modal(name):
    def deco(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if request.args.get(f'{name}_type') != 'options':
                return view(*args, **kwargs)

            t0 = time.perf_counter()
            if not _detailed():
                resp = make_response(view(*args, **kwargs))
                resp.headers['Server-Timing'] = 'app;dur=%.0f' % (
                    (time.perf_counter() - t0) * 1000)
                return resp

            c0 = time.thread_time()
            state = {'q': 0, 'q_sec': 0.0, 'slow': []}
            engine = db.engine

            def before_exec(conn, cur, stmt, params, ctx, many):
                ctx._trace_t = time.perf_counter()

            def after_exec(conn, cur, stmt, params, ctx, many):
                dt = time.perf_counter() - getattr(ctx, '_trace_t', time.perf_counter())
                state['q'] += 1
                state['q_sec'] += dt
                state['slow'].append((dt, ' '.join(stmt.split())[:90]))

            event.listen(engine, 'before_cursor_execute', before_exec)
            event.listen(engine, 'after_cursor_execute', after_exec)
            resp = None
            prof = cProfile.Profile()
            try:
                prof.enable()
                try:
                    resp = make_response(view(*args, **kwargs))
                finally:
                    prof.disable()
                return resp
            finally:
                total = time.perf_counter() - t0
                cpu = time.thread_time() - c0
                event.remove(engine, 'before_cursor_execute', before_exec)
                event.remove(engine, 'after_cursor_execute', after_exec)
                if resp is not None:
                    resp.headers['Server-Timing'] = 'app;dur=%.0f' % (total * 1000)
                slow = sorted(state['slow'], reverse=True)[:_SLOW_TOP]
                logger.warning(
                    '[modal-trace] %s id=%s total=%.0fms cpu=%.0fms wait=%.0fms '
                    'db=%.0fms(%d q) bytes=%s slow=%s', name,
                    request.args.get(f'{name}_id'), total * 1000, cpu * 1000,
                    (total - cpu) * 1000, state['q_sec'] * 1000, state['q'],
                    resp.calculate_content_length() if resp is not None else '-',
                    [f'{d * 1000:.0f}ms {s}' for d, s in slow])
                # 이 워커 안에서의 함수별 CPU 상위(프로파일러 자체 오버헤드로 total 보다 커진다).
                buf = io.StringIO()
                pstats.Stats(prof, stream=buf).sort_stats('tottime').print_stats(14)
                top = [ln.rstrip() for ln in buf.getvalue().splitlines()
                       if ln.strip() and ln.lstrip()[0].isdigit()]
                logger.warning('[modal-trace-prof] %s id=%s\n%s', name,
                               request.args.get(f'{name}_id'), '\n'.join(top))
        return wrapper
    return deco

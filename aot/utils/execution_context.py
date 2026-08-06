# coding=utf-8
"""
Thread-local execution context for tracking the source of device actions.

Every execution path (Trigger, Conditional, Function, Scheduler, Manual)
sets its source_type before calling output_on_off(). The InfluxDB writer
reads get_extra_tags() to attach source metadata to runtime records.

Usage:
    from aot.utils.execution_context import set_execution_context, clear_execution_context

    set_execution_context('trigger', source_id=trigger.unique_id)
    try:
        output.output_on_off('on', ...)
    finally:
        clear_execution_context()
"""
import threading

_context = threading.local()


def set_execution_context(source_type, source_id=None, job_meta_id=None):
    """Set execution context on the current thread (일시적 override)."""
    _context.source_type = source_type
    _context.source_id = source_id
    _context.job_meta_id = job_meta_id


def set_thread_default(source_type, source_id=None):
    """이 스레드가 기본적으로 대표하는 주체를 등록한다.

    컨트롤러는 각자 자기 스레드에서 도므로(`AbstractController.run()`), 스레드
    시작 시 한 번 심어두면 그 스레드에서 나가는 모든 장치 명령이 자동으로 이
    주체를 물려받는다. 컨트롤러·Function 44곳의 호출부를 일일이 고치지 않고
    "어느 자동화가 명령했나" 를 채우는 방법이다.

    override(`set_execution_context`)가 있으면 그쪽이 이긴다.
    """
    _context.default_source_type = source_type
    _context.default_source_id = source_id


def get_context():
    """Return the current thread's execution context as a dict.

    override 가 없으면 스레드 기본값으로 떨어진다.
    """
    source_type = getattr(_context, 'source_type', None)
    if source_type:
        return {
            'source_type': source_type,
            'source_id': getattr(_context, 'source_id', None),
            'job_meta_id': getattr(_context, 'job_meta_id', None),
        }
    return {
        'source_type': getattr(_context, 'default_source_type', None),
        'source_id': getattr(_context, 'default_source_id', None),
        'job_meta_id': None,
    }


def clear_execution_context():
    """override 만 지운다. 스레드 기본값은 남는다.

    기본값까지 지우면 Trigger 가 한 번 발화한 뒤로 그 스레드의 후속 명령이
    주인을 잃는다 — 컨트롤러 스레드는 계속 살아 있기 때문이다.
    """
    for attr in ('source_type', 'source_id', 'job_meta_id'):
        if hasattr(_context, attr):
            delattr(_context, attr)


def clear_thread_default():
    """스레드 기본값까지 지운다 (테스트·스레드 재사용 경계용)."""
    for attr in ('default_source_type', 'default_source_id'):
        if hasattr(_context, attr):
            delattr(_context, attr)


def get_extra_tags():
    """Return InfluxDB-ready tags dict (only non-None values)."""
    ctx = get_context()
    tags = {}
    if ctx['source_type']:
        tags['source_type'] = ctx['source_type']
    if ctx['source_id']:
        tags['source_id'] = ctx['source_id']
    return tags

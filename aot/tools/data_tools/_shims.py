"""Shared form shims for the AI data-tool drawer mixins.

Split out of aot_data_tool_service.py (was a nested class on
AoTDataToolService) so definition/function/record drawer mixins can share
it without importing each other.
"""

import functools


def tz_scoped(fn):
    """읽기 도구 한 번의 호출 동안 시계 해석(`timekit.tz_scope`)과 읽기 결과 메모(`call_scope`)를 켠다.

    `@classmethod` 바로 아래에 둔다. 요청 밖(MCP)에서는 같은 구획의 시계를 호출마다
    DB 에서 다시 읽어, 장소 개요 한 번에 266회·2초가 들었다(2026-11-07 실측).
    캐시는 호출이 끝나면 사라진다 — 다른 호출·프로세스와 어긋나지 않는다.

    측정 DB 설정 읽기도 같은 범위로 한 번만 한다(`influx.influx_scope`): 채널마다 묻는
    읽기 도구는 질의 한 번에 `Misc` 를 3번 다시 읽었다.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from aot.utils.call_scope import call_scope
        from aot.utils.timekit import tz_scope
        from aot.utils.influx import influx_scope
        with tz_scope(), call_scope(), influx_scope():
            return fn(*args, **kwargs)
    return wrapper


class _FakeForm:
    """Minimal WTForms form/field shim: exposes .<field>.data and validate()."""
    class _Field:
        def __init__(self, data): self.data = data
    def __init__(self, **fields):
        for k, v in fields.items():
            setattr(self, k, _FakeForm._Field(v))
    def validate(self):
        return True

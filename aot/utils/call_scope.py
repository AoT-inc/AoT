# coding=utf-8
"""읽기 도구 한 번의 호출 동안만 사는 결과 메모 (프로세스 캐시가 아니다).

읽기 전용 도구 하나가 같은 DB 읽기를 수십~수백 번 되풀이할 때(장소 개요: 지도 도형 전체 적재 수천 회,
포함 캐시 2만 8천 행) 그 호출 안에서만 한 번씩 읽게 한다. `timekit.tz_scope` 와 같은 규율이다:

  - 블록이 끝나면 메모도 사라진다 — 다른 호출·프로세스·요청과 어긋날 수 없다.
  - 블록 밖에서는 `memo()` 가 곧바로 `fn()` 을 부른다 — 동작이 전과 같다.
  - 블록 안에서 그 값을 바꾸는 쓰기를 하면 `clear()` 로 비운다 (캐시를 채우는 읽기 경로는 해당).
  - 값은 **읽기 결과**여야 한다. 호출부가 바꾸지 않는 것만 메모한다.
"""
import contextlib
import contextvars

_MEMO = contextvars.ContextVar('_call_scope_memo', default=None)


@contextlib.contextmanager
def call_scope():
    """이 블록 안에서 `memo()` 가 켜진다. 중첩하면 바깥 메모를 그대로 쓴다."""
    if _MEMO.get() is not None:
        yield
        return
    token = _MEMO.set({})
    try:
        yield
    finally:
        _MEMO.reset(token)


def memo(key, fn):
    """블록 안에서는 `key` 마다 `fn()` 을 한 번만 부른다. 블록 밖이면 매번 부른다."""
    store = _MEMO.get()
    if store is None:
        return fn()
    if key not in store:
        store[key] = fn()
    return store[key]


def clear(prefix=None):
    """메모를 비운다. `prefix` 를 주면 키의 첫 칸이 같은 것만."""
    store = _MEMO.get()
    if store is None:
        return
    if prefix is None:
        store.clear()
        return
    for k in [k for k in store if isinstance(k, tuple) and k and k[0] == prefix]:
        del store[k]


def recall(key):
    """메모에 있으면 그 값, 없거나 블록 밖이면 None. 값이 None 인 것은 메모하지 않는다."""
    store = _MEMO.get()
    return None if store is None else store.get(key)


def remember(key, value):
    """블록 안에서만 `key` 에 값을 적는다 (`memo()` 를 쓸 수 없는 호출부용)."""
    store = _MEMO.get()
    if store is not None:
        store[key] = value

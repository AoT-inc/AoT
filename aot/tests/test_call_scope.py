# coding=utf-8
"""`call_scope` — 읽기 도구 한 번 동안만 사는 결과 메모 (프로세스 캐시가 아니다)."""
from unittest import mock

from aot.utils import call_scope


def test_outside_the_scope_nothing_is_remembered():
    calls = []
    for _ in range(2):
        call_scope.memo(('k',), lambda: calls.append(1))
    assert len(calls) == 2
    call_scope.remember(('k',), 1)
    assert call_scope.recall(('k',)) is None


def test_inside_the_scope_a_key_is_computed_once_and_forgotten_after():
    calls = []
    with call_scope.call_scope():
        a = call_scope.memo(('k', 1), lambda: calls.append(1) or [1])
        b = call_scope.memo(('k', 1), lambda: calls.append(1) or [2])
        with call_scope.call_scope():                     # 중첩은 바깥 메모를 쓴다
            c = call_scope.memo(('k', 1), lambda: calls.append(1) or [3])
        assert a is b is c and len(calls) == 1
        call_scope.memo(('k', 2), lambda: calls.append(1))
        call_scope.clear('k')
        call_scope.memo(('k', 1), lambda: calls.append(1))
        assert len(calls) == 3
    call_scope.memo(('k', 1), lambda: calls.append(1))     # 블록이 끝나면 사라진다
    assert len(calls) == 4


def test_scope_is_released_when_the_block_raises():
    try:
        with call_scope.call_scope():
            raise RuntimeError('boom')
    except RuntimeError:
        pass
    assert call_scope._MEMO.get() is None


def test_containment_load_reads_once_per_scope():
    from aot.space import containment_cache as cc

    class _Q:
        n = 0

        def filter(self, *_a):
            return self

        def all(self):
            _Q.n += 1
            return []

    class _Model:
        query = _Q()
        geo_id = child_kind = None
    with mock.patch.object(cc, 'GeoContainmentCache', _Model):
        cc.load(kind='shape')
        cc.load(kind='shape')
        assert _Q.n == 2                                    # 블록 밖: 매번 읽는다
        with call_scope.call_scope():
            cc.load(kind='shape')
            cc.load(kind='shape')
            assert _Q.n == 3
            cc.load(kind='plot')                            # 다른 키는 따로
            assert _Q.n == 4
            call_scope.clear('containment')                 # store/invalidate 가 하는 일
            cc.load(kind='shape')
            assert _Q.n == 5

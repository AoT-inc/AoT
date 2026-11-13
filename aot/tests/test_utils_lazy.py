# coding=utf-8
from aot.aot_flask.utils.utils_lazy import Lazy, val


def test_lazy_computes_once_and_only_when_used():
    calls = []
    lz = Lazy(lambda: calls.append(1) or [3, 1, 2])
    assert calls == []
    assert list(lz) == [3, 1, 2] and len(lz) == 3 and lz[0] == 3 and 2 in lz and lz
    assert calls == [1]


def test_lazy_forwards_attributes_and_val_passes_plain_values():
    assert Lazy(lambda: {'a': 1}).get('a') == 1
    assert val(Lazy(lambda: 5)) == 5 and val([1]) == [1]
    assert not Lazy(lambda: [])

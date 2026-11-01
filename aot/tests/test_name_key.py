# coding=utf-8
"""name_key — 표기만 다른 이름은 같은 열쇠, 철자가 다르면 다른 열쇠."""
from aot.tools.name_key import name_key


def test_same_name_in_different_notation():
    keys = {name_key(x) for x in ('온습도 7', '온습도_7', '온습도７', '온습도-7', '온습도7', ' 온습도  7 ')}
    assert keys == {'온습도7'}
    assert name_key('ON습도 7') == name_key('on습도_7')


def test_digit_hyphen_is_kept_and_spelling_is_not_merged():
    assert name_key('3-1') == name_key('3 - 1') != name_key('31')
    assert name_key('온습도 7') != name_key('온슴도 7')
    assert name_key('') == '' and name_key(None) == ''

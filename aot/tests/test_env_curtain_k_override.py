# coding=utf-8
"""보온커튼 수동 K(`k_override`)가 효과 크기에 반영되는지 (B2 회귀).

로더의 `_K_PRIMARY['curtain']` 이 `K_CURTAIN_T` 였는데 효과 함수는 `K_CURTAIN_U`
를 읽어, 수동 K 가 조용히 무시되고 기본값 0.04 로만 돌았다.
"""
import inspect

import pytest

from aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin import (
    _K_PRIMARY)
from aot.functions.utils.env_control import effect_functions as ef


def _env():
    return {'T_int': 15.0, 'T_ext': 5.0, 'cycle_sec': 60.0}


def _curtain_mag(k):
    fn = ef.build_effect_model('curtain', k)['temperature']
    return fn(_env(), 100.0, None).magnitude_native


def test_loader_key_is_the_one_effect_function_reads():
    assert _K_PRIMARY['curtain'] == 'K_CURTAIN_U'


def test_manual_curtain_k_changes_effect_magnitude():
    base = _curtain_mag({})
    assert base == pytest.approx(10.0 * 0.04)
    over = _curtain_mag({_K_PRIMARY['curtain']: 0.08})
    assert over == pytest.approx(10.0 * 0.08)
    assert over == pytest.approx(2 * base)


def test_legacy_key_still_honoured():
    assert _curtain_mag({'K_CURTAIN_T': 0.02}) == pytest.approx(10.0 * 0.02)


def test_canonical_key_wins_over_legacy():
    assert _curtain_mag({'K_CURTAIN_U': 0.08, 'K_CURTAIN_T': 0.02}) \
        == pytest.approx(10.0 * 0.08)


def test_every_loader_override_key_is_read_by_effect_builder():
    """다른 kind 도 같은 어긋남이 없게 — 로더 키가 빌더 소스에서 실제로 읽힌다."""
    src = inspect.getsource(ef._build_effect_model_raw)
    for kind, key in _K_PRIMARY.items():
        assert f"'{key}'" in src, f'{kind}: {key} 를 효과 빌더가 읽지 않는다'

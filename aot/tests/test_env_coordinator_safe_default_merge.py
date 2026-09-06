# coding=utf-8
"""`env_actuator` 액션 병합이 안전 기본값을 지우던 회귀 테스트.

`safe_default_pct` 는 예전 P2-3 액션 폼 필드였는데, 그 필드가 폼에서 빠진 뒤로
`opts.get('safe_default_pct', 0.0)` 가 항상 0.0 을 돌려주고 있었다. 그런데
`_reload_profiles()` 는 그 0.0 을 **명시값처럼** 취급해 매 사이클 병합마다
`existing.safe_default` 를 덮어썼다 — 시설 도면에서 자동 발견된 보온커튼·
차광막의 안전 위치(100 = 걷힘)가 0(닫힘)으로 뒤집혔다. 정전·통신 두절 시
가야 할 자리가 반대로 도는, 안전에 닿는 결함이다.

`_resolve_safe_default_pct()` 가 이를 고친다: 폼에 값이 없으면(지금은 항상
없다) 병합 때는 기존 값을, 신규 등록 때는 kind 별 안전 기본값을 보존한다.
"""
from aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin import (
    _KIND_SAFE_DEFAULT, _resolve_safe_default_pct,
)


# ── 병합 — 값 없는 액션이 기존 안전 위치를 지우면 안 된다 ──────────────────────

def test_merge_without_field_preserves_existing_safe_default():
    """폼에 필드가 없는 지금(opts 에 키 자체가 없음) — 기존 100 이 살아남아야 한다."""
    opts = {'output': 'dev-1', 'kind': 'curtain'}   # safe_default_pct 없음
    assert _resolve_safe_default_pct(opts, 100.0, 'curtain') == 100.0


def test_merge_with_empty_string_preserves_existing_safe_default():
    """일부 폼 직렬화 경로는 빈 문자열을 남긴다 — 이것도 '미지정'으로 본다."""
    opts = {'safe_default_pct': ''}
    assert _resolve_safe_default_pct(opts, 100.0, 'curtain') == 100.0


def test_merge_repeated_reload_does_not_drift_to_zero():
    """여러 사이클 반복 병합에도 값이 0으로 미끄러지지 않는지 확인 — 일부러
    같은 병합을 5번 반복해도 안전 위치가 그대로여야 한다."""
    opts = {'kind': 'shade'}
    value = 100.0
    for _ in range(5):
        value = _resolve_safe_default_pct(opts, value, 'shade')
    assert value == 100.0


# ── 신규 등록 — 자동발견 없이 수동 등록만 있을 때도 kind 기본값을 써야 한다 ──

def test_new_profile_without_field_uses_kind_default():
    opts = {'kind': 'curtain'}
    assert _resolve_safe_default_pct(opts, None, 'curtain') == \
        _KIND_SAFE_DEFAULT['curtain'] == 100.0


def test_new_profile_unknown_kind_defaults_to_zero():
    """개구부·팬 등 kind 기본값이 없는 액추에이터는 여전히 0(닫힘/OFF)."""
    opts = {'kind': 'exhaust_fan'}
    assert _resolve_safe_default_pct(opts, None, 'exhaust_fan') == 0.0


# ── 명시값 — 폼이 되살아나면 그 값이 그대로 이겨야 한다 ─────────────────────

def test_explicit_value_overrides_existing():
    opts = {'safe_default_pct': 50.0}
    assert _resolve_safe_default_pct(opts, 100.0, 'curtain') == 50.0


def test_explicit_zero_is_respected_not_treated_as_missing():
    """0 은 '명시적으로 OFF' 일 수 있다 — '미지정'과 섞으면 안 된다."""
    opts = {'safe_default_pct': 0.0}
    assert _resolve_safe_default_pct(opts, 100.0, 'curtain') == 0.0


def test_explicit_value_used_for_brand_new_profile():
    opts = {'safe_default_pct': 30.0}
    assert _resolve_safe_default_pct(opts, None, 'curtain') == 30.0

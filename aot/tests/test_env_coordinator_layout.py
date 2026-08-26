# coding=utf-8
"""통합환경제어 옵션 화면의 **배치**를 지킨다 (2026-08-26).

옵션이 62개인데 순서가 "필요한 순서" 가 아니라 **"추가된 순서"** 였다. 사용자
지적: *"옵션이 너무 많아서 스크롤 하다가 지치겠음. 일반 사용자에게 허들이 너무
높음."*

구체적으로 어긋나 있던 것 셋:

  · 시설 연결이 6번째 — 센서·액추에이터·구역이 전부 여기 딸려 있어서 이것을
    안 고르면 나머지가 의미가 없다.
  · 온습도 하드 임계(11·12번)와 유도 범위(17번)가 다섯 섹션 떨어져 있었다.
    **둘은 서로 간섭한다** — 저장 시 경고가 필요했던 이유가 정확히 그 거리다.
  · `vent_futility_gate` 가 "구동 주기" 안에 있었다. 환기 전략인데 모터 주기
    설정에 숨어 있어 찾을 수가 없다.

배치는 `_LAYOUT` 한 곳에서 정하고 `_apply_layout()` 이 적용한다. 옵션 정의
자체는 건드리지 않으므로 **id 도 저장된 값도 동작도 바뀌지 않는다.**
"""
import sys
import types

import pytest


def _info():
    """flask_babel 없이 읽는다 — 배치는 번역과 무관하다."""
    if 'flask_babel' not in sys.modules:
        b = types.ModuleType('flask_babel')
        b.lazy_gettext = lambda s: s
        b.gettext = lambda s, **k: s
        sys.modules['flask_babel'] = b
    from aot.functions.custom_functions.env_coordinator_impl import (
        _function_info as fi)
    return fi


def _options():
    return _info().FUNCTION_INFORMATION['custom_options']


def _ids(opts):
    return [o['id'] for o in opts if o.get('id')]


def _always_visible(opts):
    """접힘 밖에 있는 옵션 = 첫 화면에 보이는 것."""
    out, depth = [], 0
    for o in opts:
        t = o.get('type')
        if t == 'collapse_start':
            depth += 1
        elif t == 'collapse_end':
            depth -= 1
        elif o.get('id') and depth == 0:
            out.append(o['id'])
    return out


class TestNothingIsLost:
    """배치를 고치다 옵션을 흘리면 **화면에서 조용히 사라진다.**

    폼에도 없으므로 그 설정을 영영 못 바꾸는데, 에러는 나지 않는다.
    """

    def test_every_option_appears_exactly_once(self):
        ids = _ids(_options())
        dup = {i for i in ids if ids.count(i) > 1}
        assert not dup, '중복된 옵션: %s' % sorted(dup)

    def test_the_layout_covers_everything(self):
        """빠진 것은 '분류 안 됨' 으로 모이게 되어 있다 — 그 묶음이 생겼다는
        것은 `_LAYOUT` 에 새 옵션을 안 넣었다는 뜻이다."""
        names = [str(o.get('name', '')) for o in _options()
                 if o.get('type') == 'collapse_start']
        assert 'Not Yet Categorised' not in names, (
            '_LAYOUT 에 빠진 옵션이 있다 — 새 옵션을 추가하고 배치에 안 넣었다')

    def test_the_declared_layout_matches_the_option_list(self):
        fi = _info()
        declared = [i for _f, _t, blocks in fi._LAYOUT
                    for _s, ids in blocks for i in ids]
        assert len(declared) == len(set(declared)), (
            '_LAYOUT 에 같은 옵션이 두 번 있다: %s'
            % sorted({i for i in declared if declared.count(i) > 1}))
        assert set(declared) == set(_ids(_options()))


class TestTheFirstScreenStaysSmall:
    """이 검사가 이 파일의 존재 이유다 — 하나씩 늘어나면 다시 62개가 된다."""

    def test_at_most_a_dozen_options_are_always_visible(self):
        vis = _always_visible(_options())
        assert len(vis) <= 12, (
            '첫 화면 옵션이 %d개다. 새 옵션은 접힘 안에 넣을 것 — 정말 첫 '
            '화면에 있어야 한다면 이 한도를 올리는 근거를 함께 남길 것: %s'
            % (len(vis), vis))

    def test_the_essentials_are_visible(self):
        """이것들이 접히면 "무엇부터 채워야 하나" 에 답이 없어진다."""
        vis = set(_always_visible(_options()))
        for oid in ('geo_facility_id', 'update_period',
                    'temp_max', 'temp_min', 'humid_max', 'humid_min'):
            assert oid in vis, '%s 가 첫 화면에서 사라졌다' % oid


class TestOrderThatMatters:

    def test_the_facility_comes_first(self):
        """센서·액추에이터·구역이 전부 시설에 딸려 있다 — 이것을 안 고르면
        나머지 설정이 의미가 없다."""
        assert _always_visible(_options())[0] == 'geo_facility_id'

    def test_guide_ranges_sit_next_to_the_hard_limits(self):
        """둘이 어긋나면 목표가 조용히 좁혀진다. 하나를 고칠 때 다른 하나가
        눈에 보여야 한다 — 다섯 섹션 떨어져 있던 것이 원래 문제였다."""
        ids = _ids(_options())
        last_limit = max(ids.index(i) for i in
                         ('temp_max', 'temp_min', 'humid_max', 'humid_min'))
        first_guide = min(ids.index(i) for i in
                          ('guide_T_min', 'guide_T_max',
                           'guide_RH_min', 'guide_RH_max'))
        assert 0 < first_guide - last_limit <= 3, (
            '하드 임계와 유도 범위가 %d칸 떨어져 있다' % (first_guide - last_limit))

    def test_the_futility_gate_is_a_ventilation_option(self):
        """모터 주기 설정 안에 숨어 있어 찾을 수 없었다."""
        ids = _ids(_options())
        assert abs(ids.index('vent_futility_gate') - ids.index('vent_first')) <= 1

    def test_night_parking_is_not_near_the_top(self):
        """2026-08-26 에 새 기능을 3번째 섹션에 넣었다 — 고급 옵션이
        시설 연결보다 앞에 있었다."""
        ids = _ids(_options())
        assert ids.index('night_vent_park') > ids.index('geo_facility_id')
        assert 'night_vent_park' not in _always_visible(_options())


class TestTheLayoutDoesNotChangeBehaviour:
    """순서만 바꾼다 — 정의를 건드리면 저장된 값이 달라진다."""

    def test_option_definitions_are_the_same_objects(self):
        """`_apply_layout` 이 dict 를 새로 만들면 기본값·제약이 갈릴 수 있다.
        같은 객체를 재배치하기만 해야 한다."""
        fi = _info()
        opts = fi.FUNCTION_INFORMATION['custom_options']
        by_id = {o['id']: o for o in opts if o.get('id')}
        rebuilt = fi._apply_layout(opts, fi._LAYOUT)
        for o in rebuilt:
            if o.get('id'):
                assert o is by_id[o['id']], '%s 정의가 복제됐다' % o['id']

    def test_applying_twice_is_stable(self):
        """저장·재로드로 두 번 적용돼도 같은 결과여야 한다."""
        fi = _info()
        once = fi.FUNCTION_INFORMATION['custom_options']
        twice = fi._apply_layout(once, fi._LAYOUT)
        assert _ids(once) == _ids(twice)
        assert _always_visible(once) == _always_visible(twice)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

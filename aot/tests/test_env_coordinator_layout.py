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
    """값을 싣는 옵션만. 배치 표식(접힘 앵커)도 id 를 가지므로 걸러야 한다."""
    markers = ('collapse_start', 'collapse_end', 'header', 'env_status')
    return [o['id'] for o in opts
            if o.get('id') and o.get('type') not in markers]


def _always_visible(opts):
    """첫 화면에 **실제로** 보이는 옵션.

    접힘 밖이면서 `depends_on` 이 없는 것. 종속 옵션은 그 토글을 켜야 나오므로
    "항상 보인다" 가 아니다 — 세면 이 검사가 뜻을 잃는다.
    """
    markers = ('collapse_start', 'collapse_end', 'header', 'env_status')
    out, depth = [], 0
    for o in opts:
        t = o.get('type')
        if t == 'collapse_start':
            depth += 1
        elif t == 'collapse_end':
            depth -= 1
        elif o.get('id') and t not in markers and depth == 0 \
                and not o.get('depends_on'):
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
        """한도는 **연결 2 + 약속 5 + 전략 토글**이다.

        전략 토글을 하나 늘리면 이 숫자도 하나 는다 — 그때는 "정말 사용자가
        고를 정책인가" 를 먼저 묻고, 맞으면 한도를 올리며 근거를 남긴다.
        하위 설정은 `depends_on` 으로 붙이므로 여기 안 세어진다.
        """
        vis = _always_visible(_options())
        assert len(vis) <= 13, (
            '첫 화면 옵션이 %d개다. 새 옵션은 접힘 안에 넣을 것 — 정말 첫 '
            '화면에 있어야 한다면 이 한도를 올리는 근거를 함께 남길 것: %s'
            % (len(vis), vis))

    def test_the_essentials_are_visible(self):
        """이것들이 접히면 "무엇부터 채워야 하나" 에 답이 없어진다.

        ⚠ `update_period` 는 2026-08-27 에 **뺐다**. 안전한 일반 기본값(60초)이
          있어 안 정해도 돌아가므로 "반드시 정해야 하는 것" 이 아니다(D3).
          여기 남은 것은 **사람이 정하지 않으면 값이 있을 수 없는 것**뿐이다 —
          어느 시설인가, 어느 선을 넘으면 안 되는가.
        """
        vis = set(_always_visible(_options()))
        for oid in ('geo_facility_id',
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

    def test_strategy_toggles_are_visible_and_their_details_are_not(self):
        """전략은 **고르는 것**이라 보이고, 그 하위 설정은 켜야 나온다."""
        vis = set(_always_visible(_options()))
        for oid in ('vent_futility_gate', 'vent_first', 'hvac_interlock',
                    'night_vent_park', 'nursery_mode'):
            assert oid in vis, '전략 토글 %s 가 안 보인다' % oid
        for oid in ('night_vent_basis', 'night_vent_start',
                    'hvac_interlock_on_value', 'nursery_max_on_sec'):
            assert oid not in vis, '%s 가 토글과 무관하게 늘 보인다' % oid

    def test_every_dependency_points_at_a_real_toggle(self):
        """오타 하나면 그 행이 **영영 안 보인다** — 대상이 없으면 JS 가
        감추지 않게 해 뒀지만, 명부가 맞는지는 여기서 본다."""
        opts = _options()
        ids = {o['id'] for o in opts if o.get('id')}
        for o in opts:
            dep = o.get('depends_on')
            if dep:
                assert dep in ids, '%s 의 depends_on %r 이 없는 옵션이다' % (
                    o['id'], dep)

    def test_night_parking_comes_after_the_facility(self):
        """2026-08-26 에 새 기능을 3번째 섹션에 넣었다 — 고급 옵션이 시설
        연결보다 앞에 있었다.

        ⚠ 2026-08-27: 야간 파킹은 이제 **보이는 것이 맞다** — 전략 토글이다.
          감춰야 할 것은 그 하위 설정이고, 그쪽은
          `test_strategy_toggles_are_visible_and_their_details_are_not` 가 본다.
        """
        ids = _ids(_options())
        assert ids.index('night_vent_park') > ids.index('geo_facility_id')


class TestTheLayoutDoesNotChangeBehaviour:
    """순서만 바꾼다 — 정의를 건드리면 저장된 값이 달라진다."""

    def test_option_definitions_are_the_same_objects(self):
        """`_apply_layout` 이 dict 를 새로 만들면 기본값·제약이 갈릴 수 있다.
        같은 객체를 재배치하기만 해야 한다."""
        fi = _info()
        opts = fi.FUNCTION_INFORMATION['custom_options']
        by_id = {o['id']: o for o in opts if o.get('id')
                 and o.get('type') not in ('collapse_start', 'collapse_end')}
        rebuilt = fi._apply_layout(opts, fi._LAYOUT)
        for o in rebuilt:
            if o.get('id') and o.get('type') not in (
                    'collapse_start', 'collapse_end', 'header'):
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


class TestEachFoldOpensItsOwnSection:
    """접힘마다 **고유한 id** 가 있어야 한다 (2026-08-27 사용자 신고).

    템플릿이 DOM 앵커를 `name_prefix ~ (id or 'advanced')` 로 만든다. id 를
    안 주면 8개가 전부 `…_advanced` 를 가리켜 **어느 버튼을 눌러도 맨 위 것만
    펼쳐진다.** 처음 배치를 만들 때 실제로 그랬다.
    """

    def _folds(self):
        return [o for o in _options() if o.get('type') == 'collapse_start']

    def test_every_fold_has_an_id(self):
        missing = [str(o.get('name')) for o in self._folds() if not o.get('id')]
        assert not missing, '앵커가 없는 접힘: %s' % missing

    def test_fold_ids_are_unique(self):
        ids = [o['id'] for o in self._folds()]
        assert len(ids) == len(set(ids)), (
            '접힘 앵커가 겹친다 — 겹치는 만큼 다른 묶음이 안 열린다: %s'
            % sorted({i for i in ids if ids.count(i) > 1}))

    def test_fold_ids_are_ascii_and_not_derived_from_the_title(self):
        """제목은 번역된다 — 제목에서 만들면 언어를 바꿀 때 앵커가 달라진다."""
        for o in self._folds():
            assert o['id'].isascii(), '%r 이 ASCII 가 아니다' % o['id']
            assert str(o['id']) not in str(o.get('name', '')), (
                '앵커가 제목에서 파생됐다: %r' % o['id'])


class TestLayoutMarkersAreNotOptions:
    """배치 표식도 `id` 를 갖는다 — 값을 싣는 옵션과 섞이면 안 된다."""

    def test_markers_never_become_attributes(self):
        """데몬 파서가 표식을 옵션으로 읽으면 `grp_*` 속성이 생기고, 더 나쁘게는
        id·기본값이 없다고 판단해 **파싱을 통째로 중단한다**(2026-08-27 실측:
        62개 중 9개만 설정되고 멈췄다)."""
        parser = _read_parser()
        for fn in ('setup_custom_options_csv', 'setup_custom_options_json'):
            block = parser.split('def %s' % fn, 1)[1].split('\n    def ', 1)[0]
            assert block.count("'collapse_start'") >= 3, (
                '%s 가 배치 표식을 면제하지 않는다 — 세 자리 모두 필요하다'
                '(id 검사 · default_value 검사 · continue)' % fn)


def _read_parser():
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, '..', 'controllers',
                           'abstract_base_controller.py'), encoding='utf-8') as fh:
        return fh.read()

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
import re
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


# ⚠ **`_function_info` 에서 가져온다.** 여기 손으로 적으면 표식 종류가 늘 때
#   조용히 갈라지고, 그때 이 검사는 새 표식을 '옵션' 으로 세어 통과해 버린다 —
#   `range_band` 가 실제로 그랬다(id 를 갖는데 옵션이 아니다).
def _markers():
    import inspect
    src = inspect.getsource(_info()._apply_layout)
    m = re.search(r"_MARKERS = \(([^)]*)\)", src, re.S)
    return tuple(re.findall(r"'([a-z_]+)'", m.group(1)))


def _ids(opts):
    """값을 싣는 옵션만. 배치 표식(접힘 앵커)도 id 를 가지므로 걸러야 한다."""
    markers = _markers()
    return [o['id'] for o in opts
            if o.get('id') and o.get('type') not in markers]


def _by_id(opts, oid):
    for o in opts:
        if o.get('id') == oid and o.get('type') not in _markers():
            return o
    raise AssertionError('%s 옵션이 없다' % oid)


def _always_visible(opts):
    """첫 화면에 **실제로** 보이는 옵션.

    접힘 밖이면서 `depends_on` 이 없는 것. 종속 옵션은 그 토글을 켜야 나오므로
    "항상 보인다" 가 아니다 — 세면 이 검사가 뜻을 잃는다.

    ⚠ `advanced_only` 도 빼야 한다. 핵심 옵션(눈금·범위 밴드)의 **세부**는
      [고급] 을 켜야 나오고, 안 켜면 핵심 하나만 보인다 — 그것이 이 구조의
      요점이다. 세면 "핵심으로 묶었더니 첫 화면이 늘었다" 는 거꾸로 된 판정이
      나온다(2026-08-27: 묶고 나서 23개로 세어졌다).
    """
    markers = _markers()
    out, depth = [], 0
    for o in opts:
        t = o.get('type')
        if t == 'collapse_start':
            depth += 1
        elif t == 'collapse_end':
            depth -= 1
        elif (o.get('id') and t not in markers and depth == 0
                and not o.get('depends_on')
                and not o.get('advanced_only')):
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
        # `@group:x` · `@range:y` 는 옵션이 아니라 **핵심 옵션의 자리**다. 그
        # 세부는 배치에 적지 않는다 — 핵심 바로 뒤로 따라가므로(`_emit_members`)
        # 배치에도 적으면 어느 쪽이 정본인지 갈린다.
        placed = {i for i in declared if not i.startswith('@')}
        members = set()
        for g in fi._SCALE_GROUPS:
            members |= set(g['members'])
        for b in fi._RANGE_BANDS:
            members |= {b[k] for k in
                        ('guide_min', 'guide_max', 'hard_min', 'hard_max')
                        if b.get(k)}
        assert not (placed & members), (
            '세부 옵션이 배치에도 적혀 있다 — 핵심 뒤로만 따라가야 한다: %s'
            % sorted(placed & members))
        assert placed | members == set(_ids(_options()))


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

        ⚠ 온습도 넷은 2026-08-27 에 **범위 밴드가 대신한다.** 숫자 여덟 칸이
          아니라 손잡이 둘이고, 하드 임계는 거기서 파생한다. 그래서 여기서
          보는 것은 `temp_min` 이 아니라 **밴드가 첫 화면에 있는가** 다 —
          숫자 칸이 접혀 있어도 답할 수 있으면 된다.
        """
        opts = _options()
        vis = set(_always_visible(opts))
        assert 'geo_facility_id' in vis, '연동 시설이 첫 화면에서 사라졌다'
        fi = _info()
        depth, bands = 0, set()
        for o in opts:
            t = o.get('type')
            if t == 'collapse_start':
                depth += 1
            elif t == 'collapse_end':
                depth -= 1
            elif t == 'range_band' and depth == 0:
                bands.add(o['id'])
        for b in fi._RANGE_BANDS:
            assert b['id'] in bands, '%s 범위가 첫 화면에서 사라졌다' % b['id']


class TestOrderThatMatters:

    def test_the_facility_comes_first(self):
        """센서·액추에이터·구역이 전부 시설에 딸려 있다 — 이것을 안 고르면
        나머지 설정이 의미가 없다."""
        assert _always_visible(_options())[0] == 'geo_facility_id'

    def test_guide_ranges_sit_next_to_the_hard_limits(self):
        """둘이 어긋나면 목표가 조용히 좁혀진다. 하나를 고칠 때 다른 하나가
        눈에 보여야 한다 — 다섯 섹션 떨어져 있던 것이 원래 문제였다.

        지금은 **범위 밴드가 넷을 다 가진다.** 그래서 "온도 넷이 붙어 있고,
        습도 넷이 붙어 있는가" 를 밴드마다 본다 — 전체를 하나로 보면 온도와
        습도가 섞여 있어도 통과한다.

        ⚠ 사용자 신고(2026-08-27): *"심지어 온도는 반복되어 여러 곳에서
          확인함."* 슬라이더 · 유도 · 하드가 세 자리에 흩어져 있었다.
        """
        fi = _info()
        opts = _options()
        ids = _ids(opts)
        for b in fi._RANGE_BANDS:
            members = [b[k] for k in
                       ('guide_min', 'guide_max', 'hard_min', 'hard_max')
                       if b.get(k)]
            pos = sorted(ids.index(m) for m in members)
            assert pos == list(range(pos[0], pos[0] + len(pos))), (
                '%s 의 유도·하드가 붙어 있지 않다: %s' % (b['id'], pos))
            # 그리고 그 앞이 밴드 자신이어야 한다 — 세부가 자기 핵심에서
            # 떨어지면 [고급] 을 눌러도 열 것이 그 자리에 없다.
            band_at = [i for i, o in enumerate(opts)
                       if o.get('type') == 'range_band' and o.get('id') == b['id']]
            assert band_at, '%s 밴드가 배치에 없다' % b['id']
            first = opts.index(_by_id(opts, members[0]))
            assert 0 < first - band_at[0] <= 2, (
                '%s 의 세부가 밴드에서 떨어져 있다' % b['id'])

    def test_group_members_follow_their_core_option(self):
        """핵심 옵션의 [고급] 이 열어 줄 것이 **그 자리에** 있어야 한다.

        멤버가 화면 저편에 있으면 눌러도 아무 일이 안 일어난 것처럼 보인다 —
        *"고급을 눌러서 따라다니던 그 하위 옵션들은 어디에 있는거야?"*
        """
        fi = _info()
        opts = _options()
        for g in fi._SCALE_GROUPS:
            at = [i for i, o in enumerate(opts)
                  if o.get('type') == 'scale_group'
                  and (o.get('group') or {}).get('id') == g['id']]
            assert at, '%s 눈금 그룹이 배치에 없다' % g['id']
            pos = [opts.index(_by_id(opts, m)) for m in g['members']]
            assert pos == list(range(at[0] + 1, at[0] + 1 + len(pos))), (
                '%s 의 세부가 핵심 바로 뒤에 있지 않다' % g['id'])

    def test_the_futility_gate_is_a_ventilation_option(self):
        """모터 주기 설정 안에 숨어 있어 찾을 수 없었다."""
        ids = _ids(_options())
        assert abs(ids.index('vent_futility_gate') - ids.index('vent_first')) <= 1

    def test_strategy_is_asked_as_one_question_not_a_row_of_toggles(self):
        """전략은 **고르는 것**이지 하나씩 켜는 것이 아니다 (2026-08-27).

        사용자 지적: *"환기부터는 여전히 예전 방식이야. 일일이 사용자가 옵션을
        설정해야 함."* 맞다 — 환기 토글 셋(무익 판정·환기 우선·냉난방 연동)은
        따로 생각할 정책이 아니라 **같은 질문의 세기**다: "밖의 공기를 얼마나
        믿고 냉난방을 얼마나 아낄 것인가."

        육묘장 모드도 같다 — 코드가 스스로 *"육묘 모드는 게이트를 켜는
        스위치가 아니라 더 조이는 축"* 이라고 쓴다(`safety_gates.py`).
        """
        fi = _info()
        vis = set(_always_visible(_options()))
        # 핵심 옵션은 보인다 — 이것만 골라도 끝난다.
        for gid in ('vent_economy', 'misting_care', 'responsiveness'):
            assert any(g['id'] == gid for g in fi._SCALE_GROUPS), (
                '%s 눈금 묶음이 없다' % gid)
        # 묶인 토글은 **하나씩 보이지 않는다** — 보이면 같은 것을 두 곳에서
        # 정하게 되고, 어느 쪽이 이기는지 알 수 없다.
        merged = set()
        for g in fi._SCALE_GROUPS:
            merged |= set(g['members'])
        for oid in sorted(merged):
            assert oid not in vis, (
                '%s 는 핵심 옵션이 정하는데 따로도 보인다' % oid)
        # 켜는 토글 자체는 보인다.
        for oid in ('night_vent_park', 'use_wetting_fog_for_humidity'):
            assert oid in vis, '%s 가 안 보인다' % oid
        for oid in ('night_vent_basis', 'night_vent_start',
                    'hvac_interlock_on_value'):
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
        markers = _markers()
        by_id = {o['id']: o for o in opts
                 if o.get('id') and o.get('type') not in markers}
        rebuilt = fi._apply_layout(opts, fi._LAYOUT)
        for o in rebuilt:
            if o.get('id') and o.get('type') not in markers:
                assert o is by_id[o['id']], '%s 정의가 복제됐다' % o['id']

    def test_applying_twice_is_stable(self):
        """저장·재로드로 두 번 적용돼도 같은 결과여야 한다."""
        fi = _info()
        once = fi.FUNCTION_INFORMATION['custom_options']
        twice = fi._apply_layout(once, fi._LAYOUT)
        assert _ids(once) == _ids(twice)
        assert _always_visible(once) == _always_visible(twice)



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
        62개 중 9개만 설정되고 멈췄다).

        ⚠ 면제 목록을 **손으로 여섯 벌** 두던 시절의 검사는 "각 파서 안에
          `'collapse_start'` 가 세 번 나오는가" 였다. 그 여섯 벌이 바로
          문제였으므로(반쪽만 추가하면 조용히 멈춘다) 이제 상수 하나이고,
          검사도 *그 상수에 들어 있고 파서가 그것을 쓰는가* 로 바뀐다.
        """
        from aot.controllers import abstract_base_controller as abc
        for t in ('collapse_start', 'collapse_end'):
            for name in ('NO_ID_REQUIRED_TYPES', 'NO_DEFAULT_REQUIRED_TYPES',
                         'DISPLAY_ONLY_TYPES'):
                assert t in getattr(abc, name), '%s 에 %s 가 없다' % (name, t)
        parser = _read_parser()
        for fn in ('setup_custom_options_csv', 'setup_custom_options_json'):
            block = parser.split('def %s' % fn, 1)[1].split('\n    def ', 1)[0]
            for name in ('NO_ID_REQUIRED_TYPES', 'NO_DEFAULT_REQUIRED_TYPES',
                         'DISPLAY_ONLY_TYPES'):
                assert name in block, (
                    '%s 가 %s 를 쓰지 않는다 — 목록을 손으로 다시 적었는가?'
                    % (fn, name))

    def test_every_declared_option_type_is_known_to_the_parser(self):
        """선언한 종류를 파서가 모르면 "Unknown option type" 으로 그 옵션이
        조용히 `None` 이 된다 — `select_bay` 가 실제로 그랬고, 그 결과 동
        범위를 정한 코디네이터가 시설 **전체**를 제어했다."""
        from aot.controllers import abstract_base_controller as abc
        parser = _read_parser()
        declared = {o.get('type') for o in _options() if o.get('type')}
        for t in sorted(declared):
            known = (t in abc.DISPLAY_ONLY_TYPES
                     or ("'%s'" % t) in parser)
            assert known, '파서가 %r 종류를 모른다' % t


def _read_parser():
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, '..', 'controllers',
                           'abstract_base_controller.py'), encoding='utf-8') as fh:
        return fh.read()

class TestTheScreenFollowsTheDomainVocabulary:
    """화면 묶음의 축은 **도메인**이다 — 옵션 종류가 아니라 (2026-08-27).

    사용자 지적: *"각 도메인을 제어하기 위해 사용자에게 설정을 확인하기 위한
    것이 이 설정의 목표 아니었나?"* 맞다. 그런데 화면은 옵션 종류로 묶여
    있어서(범위 / 전략 / 주기 / 광량과 CO₂ / 모델), "환기를 어떻게 쓸
    것인가" 에 답하려면 세 묶음을 오가야 했다.

    ⚠ 정본은 `env_control/types.py` 의 `ACTUATOR_DOMAIN` 이고, 그 파일이
      "어휘를 두 벌 두지 말라" 고 못박고 있다. 화면이 자기 도메인을 새로
      만들면 갈라지고, 갈라지면 한쪽만 고쳐진 채 굴러간다.
    """

    def test_every_domain_group_names_a_real_domain(self):
        from aot.functions.utils.env_control import types as t
        fi = _info()
        real = set(t.ACTUATOR_DOMAIN.values())
        for title, dom in fi._DOMAIN_GROUPS.items():
            assert dom in real, (
                '%r 이 없는 도메인 %r 을 가리킨다 — types.ACTUATOR_DOMAIN 에 '
                '있는 것은 %s' % (title, dom, sorted(real)))

    def test_every_named_group_is_actually_in_the_layout(self):
        """표에만 있고 화면에 없으면 유령 항목이다 — 제목을 고치고 표를
        안 고치면 그 묶음은 도메인 대조 밖으로 조용히 빠진다."""
        fi = _info()
        titles = {str(title) for _f, title, _b in fi._LAYOUT}
        for title in fi._DOMAIN_GROUPS:
            assert title in titles, '%r 묶음이 배치에 없다' % title

    def test_the_domain_groups_come_before_the_cross_cutting_ones(self):
        """도메인은 "무엇을 움직이나" 이고 나머지는 "어떻게 판단하나" 다.
        판단 방식이 앞에 오면 장치 이야기를 하러 온 사람이 먼저 모델 설정을
        지나야 한다."""
        fi = _info()
        order = [str(title) for _f, title, _b in fi._LAYOUT]
        doms = [i for i, t in enumerate(order) if t in fi._DOMAIN_GROUPS]
        # 판단 방식 묶음 = 도메인 표에 없는 접힘들. 이름으로 못 박지 말 것 —
        # 제목은 바뀐다("Schedule and Time" → "When Control Runs", 2026-08-27).
        cross = [i for i, (folded, t, _b) in enumerate(fi._LAYOUT)
                 if folded and str(t) not in fi._DOMAIN_GROUPS]
        assert cross, '판단 방식 묶음이 하나도 없다'
        assert max(doms) < min(cross), '도메인 묶음이 판단 방식 뒤에 있다'


class TestTemperatureIsNotCalledAGrowingTarget:
    """이 함수의 목표는 **광합성**이고 1차 제어변수는 **VPD** 다. 온·습도는
    VPD 를 풀어낼 범위이자 넘지 말아야 할 선이다 — `_decompose_vpd` 가 VPD 를
    쓸 수 있을 때 둘을 `_..._constraint` 로 강등한다.

    그래서 "재배 온도"(Growing Temperature)는 틀린 이름이다. 사용자가 그것을
    목표로 읽으면 "온도를 맞춰 주는 함수" 로 이해하는데, 실제로는 VPD 를 위해
    온도가 움직인다 — 그 오해는 "왜 설정한 온도로 안 가나" 로 나타난다.
    """

    def test_the_bands_do_not_claim_to_be_growing_targets(self):
        fi = _info()
        for b in fi._RANGE_BANDS:
            name = str(b['name'])
            assert 'Growing' not in name, (
                '%r 이 재배 목표를 자처한다 — 이 함수의 목표는 VPD 다' % name)

    def test_the_function_still_declares_vpd_as_the_primary_target(self):
        """위 판단의 근거다. 이 문장이 바뀌면 이름도 다시 봐야 한다."""
        msg = str(_info().FUNCTION_INFORMATION['message'])
        assert 'VPD is the primary control target' in msg
        assert 'safety constraints' in msg

class TestHidingUsesAClassNotAnInlineStyle:
    """감추는 수단은 **클래스**여야 한다 — 인라인 `display:none` 은 진다.

    `.aot-modal-option-row` 가 `display: flex !important` 를 갖는데
    (`aot-modal-modern.css`), `!important` 는 인라인 선언을 이긴다. 그래서
    `row.style.display = 'none'` 은 **한 번도 아무것도 감추지 못했다** —
    에러 없이. 2026-08-27 실측: 시간창을 껐는데 시작·종료·광주기 4칸이 그대로
    보였다.

    ⚠ 고장이 오래 가려진 이유: 야간 파킹 하위는 `.aot-advanced-only` 를 함께
      갖고 있어 **그쪽 클래스 덕에** 감춰져 보였다. 그래서 "감춤은 되고 있다"
      고 믿었다.

    같은 실패를 이 레포는 지도 라벨에서도 겪었다(`aot-map-plot.js` 가
    `style.display` 로 직접 숨겨 `.aot-focus-show` 가 안 먹던 것).
    """

    def _css(self):
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'aot_flask', 'static', 'css',
                               'components', 'aot-dataviz.css'),
                  encoding='utf-8') as fh:
            return fh.read()

    def _js(self):
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'aot_flask', 'static', 'js', 'common',
                               'aot-option-depends.js'), encoding='utf-8') as fh:
            return fh.read()

    def test_the_handler_toggles_a_class(self):
        js = self._js()
        assert 'aot-depends-hidden' in js, '클래스를 안 쓴다'
        body = js.split('function apply(', 1)[1].split('\n  function ', 1)[0]
        assert "style.display = isOn" not in body, (
            '인라인 스타일로 감춘다 — `!important` 에 진다')

    def test_both_hiding_rules_carry_the_row_class(self):
        """행 클래스를 함께 적지 않으면 같은 특이도에서 나중 파일이 이긴다."""
        css = self._css()
        for cls in ('aot-depends-hidden', 'aot-advanced-only'):
            assert '.aot-modal-option-row.%s' % cls in css, (
                '%s 규칙에 행 클래스가 없다' % cls)

    def test_the_two_axes_are_separate(self):
        """`depends_on` 은 "그 기능을 켰는가", `advanced_only` 는 "세부까지
        볼 것인가" 다. 한 클래스로 합치면 고급을 켜는 순간 안 쓰는 기능의
        하위 설정까지 쏟아진다."""
        css = self._css()
        assert '.aot-depends-hidden' in css and '.aot-advanced-only' in css
        assert '.aot-depends-hidden,\n.aot-advanced-only' not in css

class TestOneSwitchPerThing:
    """같은 뜻의 스위치를 둘 두지 않는다 (2026-08-27).

    화면 위 [기본 설정] 의 `log_level_debug`(프레임워크)와 접힌 [진단] 의
    `debug_logging`(이 함수)이 **둘 다 "디버그 로깅 활성화"** 였다. 게다가
    `debug_logging` 이 감싸던 것은 거의 전부 `logger.debug(...)` 라, 프레임워크
    쪽을 켜지 않으면 **혼자서는 아무것도 출력하지 못했다** — 기본 로거 레벨이
    ERROR 이기 때문이다(CLAUDE.md 의 "입력 로거의 기본 레벨은 ERROR").

    즉 켠 사람은 켰다고 믿는데 아무 일도 안 일어난다. 스위치가 둘이면 언제나
    "어느 쪽이 진짜인가" 가 남는다.
    """

    def test_the_function_does_not_declare_its_own(self):
        assert 'debug_logging' not in set(_ids(_options())), (
            '같은 뜻의 두 번째 스위치가 되살아났다')

    def test_the_code_reads_the_framework_flag(self):
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        impl = os.path.join(here, 'functions', 'custom_functions',
                            'env_coordinator_impl')
        hits = 0
        for name in os.listdir(impl):
            if not name.endswith('.py') or name == '_function_info.py':
                continue
            with open(os.path.join(impl, name), encoding='utf-8') as fh:
                src = fh.read()
            assert "'debug_logging'" not in src, (
                '%s 가 아직 옛 스위치를 읽는다' % name)
            hits += src.count("'log_level_debug'")
        assert hits > 0, '프레임워크 스위치를 아무도 안 읽는다'

    def test_it_sits_in_basic_settings(self):
        """문제가 생겼을 때 가장 먼저 켜는 스위치다 — 찾아 내려가야 하는
        자리에 둘 이유가 없다."""
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'aot_flask', 'templates', 'pages',
                               'function_options',
                               'custom_function_options.html'),
                  encoding='utf-8') as fh:
            tpl = fh.read()
        basic = tpl.index("_('Basic Settings')")
        adv = tpl.index("_('Advanced Settings')")
        dbg = tpl.index('name="log_level_debug"')
        assert basic < dbg < adv, '디버그 로깅이 [기본 설정] 밖에 있다'

    def test_an_empty_advanced_group_is_not_drawn(self):
        """⚠ 디버그 로깅을 옮긴 뒤 그 묶음은 **제목만 남은 빈 카드**가 됐다.
        게다가 이 함수는 자기 [고급 설정] 접힘을 따로 가져서 같은 이름이 한
        화면에 두 번 나온다 — 사용자가 이미 지적한 "제목이 똑같이 두 번
        중복" 이 그 모양이다."""
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'aot_flask', 'templates', 'pages',
                               'function_options',
                               'custom_function_options.html'),
                  encoding='utf-8') as fh:
            tpl = fh.read()
        assert '_advanced_body' in tpl, '빈 묶음을 그대로 그린다'
        assert '{% if _advanced_body | trim %}' in tpl


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

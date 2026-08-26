# coding=utf-8
"""구역(bay)별 코디네이터 — 이미 있던 기능의 결함 셋.

`bay_scope` 로 시설의 한 구역만 맡는 기능은 예전부터 있었다(옵션·좌표 기반
소속 판정·형제 간 액추에이터 분리). 여기서 고정하는 것은 그 위에서 조용히
틀리던 세 가지다(2026-08-26).

1. **배분이 개수였다** — 구역은 bay 범위를 병합해 만들 수 있어 폭이 제각각인데
   `1 / bay 수` 로 나눴다. 4동 중 A(1~3동)·B(4동)면 실제 3:1 이 1:1 이 된다.
2. **없는 구역이 시설 전체로 넓어졌다** — 오타 하나가 제어 범위를 통째로
   넓히는데, 경고는 컨트롤러 로거 기본값(ERROR) 때문에 아무 데도 안 남았다.
3. **구역을 안 정한 코디네이터가 남의 구역을 잡아갔다** — 충돌 회피가 "양쪽 다
   구역을 정했을 때" 만 돌았다.
"""
import pytest

from aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin \
    import _bay_capacity_fraction


def _slices(*widths):
    """폭 목록 → 구역 슬라이스. id 는 'z0', 'z1' …"""
    out, x = [], 0.0
    for i, w in enumerate(widths):
        out.append({'id': 'z%d' % i, 'x_min': x, 'x_max': x + w})
        x += w
    return out


class TestCapacityFraction:

    def test_equal_bays_match_the_old_count_split(self):
        """폭이 같으면 예전(개수) 결과와 같다 — 업그레이드로 안 달라진다."""
        sl = _slices(7.0, 7.0, 7.0, 7.0)
        for i in range(4):
            assert _bay_capacity_fraction(sl, 'z%d' % i) == pytest.approx(0.25)

    def test_merged_zones_split_by_width(self):
        """실측 모양: 4동 중 A(1~3동) · B(4동) → 3:1."""
        sl = _slices(21.0, 7.0)
        assert _bay_capacity_fraction(sl, 'z0') == pytest.approx(0.75)
        assert _bay_capacity_fraction(sl, 'z1') == pytest.approx(0.25)

    def test_fractions_close_to_one(self):
        """조각의 합이 1.0 이어야 시설 용량이 새거나 겹치지 않는다.

        ⚠ 분모는 **구역 폭의 합**이지 시설 전폭이 아니다. 단동 연립은 동 사이
          간격(spacing)이 있어 전폭에는 그 틈이 섞이는데, 나누려는 것은 실내
          이지 틈이 아니다.
        """
        sl = _slices(9.0, 3.0, 12.0)
        total = sum(_bay_capacity_fraction(sl, s['id']) for s in sl)
        assert total == pytest.approx(1.0)

    def test_unknown_width_returns_none_not_a_guess(self):
        """폭을 모르면 **지어내지 않는다.**

        0 이나 1 을 돌려주면 그 구역만 조용히 다른 크기로 제어된다. None 이면
        호출부가 개수 분할로 물러나고 그 사실을 로그에 남긴다.
        """
        assert _bay_capacity_fraction([{'id': 'z0'}], 'z0') is None
        assert _bay_capacity_fraction(_slices(0.0, 0.0), 'z0') is None

    def test_missing_bay_returns_none(self):
        assert _bay_capacity_fraction(_slices(7.0, 7.0), 'nope') is None

    def test_no_slices_returns_none(self):
        assert _bay_capacity_fraction([], 'z0') is None
        assert _bay_capacity_fraction(None, 'z0') is None


class TestWiring:
    """소스로 고정하는 것들 — 여기가 끊기면 증상이 조용하다."""

    def _src(self, code_only=False):
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, '..', 'functions', 'custom_functions',
                               'env_coordinator_impl',
                               '_profile_loader_mixin.py'),
                  encoding='utf-8') as fh:
            src = fh.read()
        if not code_only:
            return src
        # ⚠ **주석을 지우고 본다.** 안 그러면 "이렇게 하지 말 것" 이라고 적어
        #   둔 주석 자체가 검사에 걸린다 — 규칙을 설명하는 것이 규칙 위반이
        #   되는 셈이다(CLAUDE.md 가 AST 검사에서 같은 함정을 적어 두었다).
        return '\n'.join(ln.split('#', 1)[0] for ln in src.splitlines())

    def test_capacity_uses_width_not_count(self):
        src = self._src()
        assert '_bay_capacity_fraction(bays_avail, bay_scope)' in src, (
            '용량 배분이 폭을 안 본다')
        # 개수 분할은 **폴백으로만** 남는다.
        i_call = src.index('_bay_capacity_fraction(bays_avail')
        i_fb = src.index('1.0 / max(1, len(bays_avail))')
        assert i_fb > i_call, '개수 분할이 아직 주 경로다'

    def test_unknown_bay_does_not_widen_the_scope(self):
        """없는 구역을 가리키면 **아무것도 맡지 않는다.**

        넓히는 쪽은 안 보인 채 남의 구역을 조작하고, 안 하는 쪽은 눈에 보인다
        (장치가 안 움직인다). 둘 다 사용자가 원한 것이 아니지만 보이는 쪽이 낫다.
        """
        src = self._src(code_only=True)
        block = src.split('bays_avail = integ.get', 1)[1].split(
            'self._bay_scope_active = bay_scope or None', 1)[0]
        assert "bay_scope = ''" not in block, (
            '없는 구역이 시설 전체로 넓어진다')
        assert 'self._profiles     = []' in block, '아무것도 안 맡는 경로가 없다'
        # ⚠ 컨트롤러 로거는 기본이 ERROR 다 — warning 은 아무 데도 안 남는다.
        assert 'self.logger.error(' in block, (
            '경고가 기본 설치에서 보이지 않는 등급이다')

    def test_derived_state_is_cleared_when_refusing(self):
        """하나라도 옛 값이 남으면 "프로필은 없는데 그룹은 있다" 가 된다."""
        src = self._src()
        block = src.split('self._bay_scope_missing = bay_scope', 1)[1].split(
            'return', 1)[0]
        for name in ('_profiles', '_sensors_resolved', '_vent_openings',
                     '_channel_map', '_actuator_idx', '_by_id', '_groups'):
            assert 'self.%s' % name in block, '%s 가 안 비워진다' % name

    def test_unscoped_coordinator_avoids_claimed_bays(self):
        """구역을 안 정한 코디네이터가 남의 구역을 비켜 가는가.

        예전에는 충돌 회피가 `if bay_scope:` 안에만 있어, 한쪽이 전체 시설이면
        그쪽이 남의 구역 장치까지 잡아갔다.
        """
        src = self._src()
        assert '_bays_claimed_by_siblings' in src, '형제 구역을 조회하지 않는다'
        assert 'set(ar.get(\'bay_ids\') or []) & claimed' in src, (
            '형제가 맡은 구역을 비켜 가지 않는다')

    def test_siblings_are_only_avoided_when_they_exist(self):
        """형제가 없으면 예전과 똑같이 시설 전체를 맡는다 — 구역을 쓰지 않는
        설치가 업그레이드로 조용히 달라지면 안 된다."""
        src = self._src()
        assert 'if claimed:' in src, '형제가 없어도 좁히고 있다'

    def test_sibling_query_excludes_itself(self):
        """자기 자신을 형제로 세면 자기 구역을 "남이 맡았다" 로 읽는다."""
        src = self._src()
        block = src.split('def _bays_claimed_by_siblings', 1)[1].split(
            '\n    def ', 1)[0]
        assert 'row.unique_id == mine' in block
        assert 'row.is_activated' in block, '꺼진 코디네이터까지 세고 있다'

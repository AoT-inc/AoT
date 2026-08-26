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
import re

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

    def test_sibling_query_uses_the_stored_option_key(self):
        """저장되는 키는 `geo_facility_id` 다.

        속성 이름(`self.geo_facility_id_device_id`)은 select_device 옵션이
        붙이는 접미사라 **DB 키와 다르다.** 속성 이름으로 조회하면 언제나 빈
        손이라 판정이 통째로 죽는데, 증상은 "형제가 없다" 와 구분되지 않는다 —
        조용히 예전 동작으로 돌아간다(2026-08-26 실측으로 발견).
        """
        block = self._src().split('def _bays_claimed_by_siblings', 1)[1].split(
            '\n    def ', 1)[0]
        assert "opts.get('geo_facility_id')" in block, (
            '형제 조회가 저장된 키를 안 읽는다')


# ─────────────────────────────────────────────────────────────────────────────
# bay_scope 는 **고르는 것**이지 적는 것이 아니다 (2026-08-26)
# ─────────────────────────────────────────────────────────────────────────────
# 자유 텍스트일 때는 오타 하나가 "이 구역만 제어한다" 를 무너뜨리는데 화면에
# 아무 표시도 안 났다. 선택지를 주면 틀릴 자리가 없어진다.

def _read(*parts):
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, '..', *parts), encoding='utf-8') as fh:
        return fh.read()


def test_bay_scope_is_a_dropdown():
    src = _read('functions', 'custom_functions', 'env_coordinator_impl',
                '_function_info.py')
    block = src.split("'id': 'bay_scope'", 1)[1].split("'phrase'", 1)[0]
    assert "'type': 'select_bay'" in block, 'bay_scope 가 자유 텍스트로 되돌아갔다'
    assert "'bay_source_option': 'geo_facility_id'" in block, (
        '목록을 어느 시설에서 가져올지 가리키지 않는다')


def test_the_template_keeps_the_saved_value():
    """목록을 못 받아도(시설 미선택·통신 실패) 저장된 값이 살아 있어야 한다.

    빈 select 를 제출하면 사용자가 손대지도 않은 구역 설정이 지워진다 —
    무에러다.
    """
    tpl = _read('aot_flask', 'templates', 'pages', 'form_options',
                'Custom_Options.html')
    block = tpl.split("== 'select_bay'", 1)[1].split('{% elif', 1)[0]
    assert 'data-bay-current' in block
    assert '{% if _cur %}<option value="{{_cur}}" selected>' in block, (
        '저장된 값을 미리 넣어 두지 않는다 — 목록 조회가 실패하면 설정이 '
        '조용히 지워진다')


def test_the_script_never_drops_an_unknown_value():
    """목록에 없는 저장값을 지우지 않고 **표시를 붙여** 남긴다.

    조용히 사라지면 사용자는 자기가 무엇을 골랐는지 알 수 없고, 서버는 그
    값으로 "아무것도 맡지 않음" 판정을 내린다.
    """
    js = _read('aot_flask', 'static', 'js', 'common', 'aot-bay-select.js')
    assert "if (cur && !seen)" in js
    assert 'not in this facility' in js


def test_the_daemon_knows_every_option_type_this_function_declares():
    """화면에 옵션 종류를 추가하고 **데몬 파서에 등록하지 않으면**, 그 옵션은
    `setattr` 자체가 일어나지 않아 **없는 것처럼** 동작한다.

    `bay_scope` 가 실제로 그랬다(2026-08-26). 드롭다운(`select_bay`)으로 바꾼
    커밋이 `abstract_base_controller.setup_custom_options_json()` 의 종류
    목록을 안 늘려서, 구역을 지정해 둔 코디네이터가 `getattr(self,
    'bay_scope', '')` → `''` 로 읽고 **시설 전체를 제어했다.**

    ⚠ 완전히 조용하지는 않다 — 기동 로그에 ERROR 한 줄이 남는다. 하지만
      그 줄은 기동 때 한 번뿐이고, 제어는 그 뒤로 계속 틀린 범위로 돈다.
      게다가 형제 조회는 `opts.get('bay_scope')` 로 DB 를 직접 읽어 **여전히
      구역을 본다** — 두 경로가 서로 다른 답을 갖는다.
    """
    info = _read('functions', 'custom_functions', 'env_coordinator_impl',
                 '_function_info.py')
    parser = _read('controllers', 'abstract_base_controller.py')
    block = parser.split('def setup_custom_options_json', 1)[1]
    declared = set(re.findall(r"'type':\s*'(\w+)'", info))
    for t in sorted(declared):
        assert "'%s'" % t in block, (
            "옵션 종류 %r 을 데몬 파서가 모른다 — 그 옵션은 값이 안 실린다" % t)


def test_the_bays_endpoint_is_read_only_and_light():
    """설정 화면이 선택지 몇 개를 채우려고 `/runtime` 을 부를 것이 아니다 —
    그쪽은 센서 스냅샷·액추에이터 상태까지 만든다."""
    src = _read('aot_flask', 'routes_geo.py')
    block = src.split("def api_facility_bays", 1)[1].split('\n@blueprint', 1)[0]
    assert "methods=['GET']" in src.split('def api_facility_bays', 1)[0][-400:]
    assert 'compute_bay_slices(spec_from_row(facility))' in block, (
        '구역 목록의 정본(spec_from_row)을 안 쓴다 — 화면 선택지와 서버 판정이 '
        '갈릴 수 있다')
    for w in ('db.session.add', 'db.session.commit', 'flag_modified'):
        assert w not in block, '읽기 전용이어야 한다: %s' % w

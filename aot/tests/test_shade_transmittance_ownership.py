# coding=utf-8
"""차광막 투과율의 **정본은 시설 하나다** (설계문서 D9, 2026-08-27).

닫힌 차광막을 빛이 얼마나 통과하는가(0~1)는 **그 천의 물성**이다. 차광막은
시설의 물건이므로 그 값을 아는 것도 시설이다. 그런데 세 곳이 각자 알고 있었다:

  · 시설 냉방부하 계산 — `t_for_cooling *= 0.50` **하드코딩**
  · 통합환경제어 함수 — 사용자에게 `shade_transmittance` 를 **또** 물음
  · 액추에이터별 액션 옵션 — 개별 지정(이건 남는다: 차광막이 여럿이고 천이
    다를 수 있다)

같은 물성을 두 곳이 각자 알면 갈라지고, 갈라지면 화면마다 다른 답이 나온다.
이 도메인이 가장 크게 데인 실패가 정확히 그 모양이다.

사용자 지적(2026-08-27): *"투과율은 시설로 이관하고 시설에서 값을 받아 처리"*
"""
import os
import re
import sys
import types
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


def _babel():
    if 'flask_babel' not in sys.modules:
        b = types.ModuleType('flask_babel')
        b.lazy_gettext = lambda s: s
        b.gettext = lambda s, **k: s
        sys.modules['flask_babel'] = b


class TestTheFacilityOwnsIt(unittest.TestCase):

    def test_the_hardcoded_assumption_is_gone(self):
        """0.50 이 냉방부하 계산에 박혀 있었다. 사용자가 그 값을 다른 데서
        정해도 시설의 계산은 영영 0.50 이었다."""
        src = _read('aot_flask', 'geo', 'facility_calc.py')
        block = src.split('# ---- 8. Cooling load', 1)[1][:900]
        self.assertNotIn('*= 0.50', block,
                         '냉방부하가 아직 상수를 곱한다')
        self.assertIn("envelope['curtain_shade_transmittance']", block,
                      '시설이 정한 값을 안 쓴다')

    def test_the_normaliser_reports_it_in_both_formats(self):
        """옛 형식(불리언뿐)에서도 키가 나와야 한다 — 없으면 소비처가
        `KeyError` 로 죽는다."""
        from aot.aot_flask.geo import facility_calc as fc
        new = fc._normalize_envelope({
            'layers': [{'role': 'outer', 'cover': 'pe'}],
            'curtain': {'shade': {'enabled': True, 'transmittance': 0.3}},
        })
        self.assertAlmostEqual(new['curtain_shade_transmittance'], 0.3)
        old = fc._normalize_envelope({'layer_count': 1,
                                      'curtain': {'shade': True}})
        self.assertAlmostEqual(old['curtain_shade_transmittance'],
                               fc.DEFAULT_SHADE_TRANSMITTANCE)

    def test_unset_falls_back_to_the_assumption_not_zero(self):
        """⚠ 0 은 "빛이 하나도 안 통과한다" 다. 미설정을 0 으로 읽으면 실내
        광량 추정이 0 으로 굳어 **대낮에 보광등이 켜진다.**"""
        from aot.aot_flask.geo.facility_calc import (
            DEFAULT_SHADE_TRANSMITTANCE, _shade_tau)
        for spec in ({}, {'enabled': True}, {'transmittance': 0},
                     {'transmittance': None}, {'transmittance': 'x'},
                     {'transmittance': 1.5}, {'transmittance': -1}):
            self.assertEqual(_shade_tau(spec), DEFAULT_SHADE_TRANSMITTANCE,
                             '%r 이 기본 가정으로 안 돌아간다' % (spec,))
        self.assertAlmostEqual(_shade_tau({'transmittance': 0.25}), 0.25)


class TestTheCoordinatorNoLongerAsks(unittest.TestCase):

    def test_the_option_is_gone(self):
        _babel()
        from aot.functions.custom_functions.env_coordinator_impl import (
            _function_info as fi)
        ids = {o.get('id') for o in fi.FUNCTION_INFORMATION['custom_options']}
        self.assertNotIn('shade_transmittance', ids,
                         '함수가 아직 물어본다 — 시설이 아는 값이다')

    def test_it_reads_the_facility_instead(self):
        src = _read('functions', 'custom_functions', 'env_coordinator_impl',
                    '_cycle_mixin.py')
        self.assertNotIn("getattr(self, 'shade_transmittance'", src,
                         '아직 자기 옵션을 읽는다')
        self.assertIn('default_tau=self._facility_shade_transmittance()', src)

    def test_the_lookup_is_not_cached_across_cycles(self):
        """프로세스가 도는 내내 들고 있으면 시설에서 값을 고쳐도 데몬은 영영
        옛 값으로 돈다 — 무에러다."""
        src = _read('functions', 'custom_functions', 'env_coordinator_impl',
                    '_cycle_mixin.py')
        head = src.split('def _run_cycle', 1)[1][:1200]
        self.assertIn('self._shade_tau_cache = None', head,
                      '사이클 시작에서 캐시를 안 비운다')

    def test_a_facility_without_a_shade_curtain_estimates_nothing(self):
        """차광막이 없다고 선언한 시설에서 추정할 것은 없다 — 실내 광량은
        실외 그대로(투과율 1.0)다. 0.5 로 두면 그늘이 없는 온실의 광량을
        절반으로 읽는다."""
        src = _read('functions', 'custom_functions', 'env_coordinator_impl',
                    '_helpers_mixin.py')
        body = src.split('def _facility_shade_transmittance', 1)[1][:2600]
        self.assertIn("shade.get('enabled')", body)
        self.assertIn('else 1.0', body)

    def test_the_per_actuator_override_still_exists(self):
        """차광막이 여럿이고 천이 다를 수 있다. 개별 지정을 없애면 그 시설은
        하나의 값으로 뭉뚱그려진다."""
        _babel()
        src = _read('actions', 'env_actuator.py')
        self.assertIn("'id': 'shade_transmittance'", src)
        # 그리고 그것이 **덮어쓰는 값**임을 문구가 말해야 한다.
        self.assertIn('linked facility', src,
                      '개별 지정이 시설 값을 대신한다는 사실을 안 말한다')


class TestTheFacilityScreenCanSetIt(unittest.TestCase):
    """옮겨 놓고 화면을 안 만들면 **아무도 정할 수 없는 값**이 된다.

    2026-08-22 에 지도 부여에서 정확히 그 일이 있었다(화면은 있고 강제는
    0곳). 방향만 반대다.
    """

    def test_the_editor_has_the_field(self):
        tpl = _read('aot_flask', 'templates', 'pages', 'geo', 'geo_facility.html')
        self.assertIn('id="curtain-shade-tau"', tpl)
        self.assertIn('id="curtain-shade-detail"', tpl)

    def test_the_field_is_read_and_filled(self):
        js = _read('aot_flask', 'static', 'js', 'geo', 'aot-facility-design.js')
        self.assertIn('curtain-shade-tau', js)
        self.assertIn('_shadeSpec(', js)

    def test_an_out_of_range_value_is_not_sent(self):
        """빈 칸이나 0 을 그대로 보내면 서버가 "빛이 하나도 안 통과한다" 로
        읽는다. 안 보내면 기본 가정이 선다."""
        js = _read('aot_flask', 'static', 'js', 'geo', 'aot-facility-design.js')
        body = js.split('function _shadeSpec', 1)[1][:500]
        self.assertTrue(re.search(r'v\s*>\s*0', body), '0 을 거르지 않는다')
        self.assertTrue(re.search(r'v\s*<=\s*1', body), '1 초과를 거르지 않는다')

    def test_the_detail_follows_the_toggle(self):
        """차광막이 없는 시설에 물성을 정하라고 하면 안 된다."""
        js = _read('aot_flask', 'static', 'js', 'geo', 'aot-facility-design.js')
        body = js.split('function onCurtainShadeToggle', 1)[1][:500]
        self.assertIn('curtain-shade-detail', body)


class TestTheMigrationDoesNotLoseOrOverwrite(unittest.TestCase):

    def test_it_never_overwrites_a_facility_value(self):
        """시설 쪽이 더 나중에, 더 그 물건을 아는 사람이 정한 값이다."""
        src = _read('scripts', 'migrate_shade_transmittance.py')
        self.assertIn("if existing is not None:", src)
        self.assertIn('conflict', src)

    def test_it_skips_facilities_without_a_shade_curtain(self):
        """쓰면 화면에 없는 값이 데이터에만 남아, 나중에 차광막을 켜는 순간
        아무도 정한 적 없는 투과율이 살아난다."""
        src = _read('scripts', 'migrate_shade_transmittance.py')
        self.assertIn('no-shade-curtain', src)

    def test_it_previews_by_default(self):
        src = _read('scripts', 'migrate_shade_transmittance.py')
        self.assertIn("'--apply', action='store_true'", src)

    def test_it_does_not_carry_orm_rows_out_of_the_session(self):
        """`session_scope` 가 닫히면 지연 로딩이 `DetachedInstanceError` 로
        터진다 — 그것도 **보고를 찍는 도중에**(2026-08-27 실측)."""
        src = _read('scripts', 'migrate_shade_transmittance.py')
        body = src.split('def _plan(', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('fac.unique_id', body,
                      '계획에 ORM 행을 그대로 담는다')


if __name__ == '__main__':
    unittest.main()

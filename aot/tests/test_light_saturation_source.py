# coding=utf-8
"""광포화점은 **작물이 정한다** — 차광 임계가 겸하지 않는다 (2026-08-27).

`light_max` 의 본뜻은 "차광막을 닫는 광량"(설비·운영 정책)인데, 광합성 판정의
**광포화점**까지 겸하고 있었다:

    light_sat = self.light_max if (self.light_max and self.light_max > 0) else None

뜻이 둘이면 한쪽을 맞추는 순간 다른 쪽이 틀어진다. 차광을 일찍 하려고 낮추면
광합성 모델이 *"빛은 이미 충분하다"* 로 판정한다.

실측(2026-08-27 로컬): `light_max=250` 인 코디네이터 둘이, 실측 일사가
542·650 W/m² 인 환경에서 **광 제한을 영영 못 봤다**(`solar < sat` 이 성립하지
않는다). 둘 다 `photosynth_mode_enabled` 가 켜져 있어 그 판정이 제어로 흘렀다.

작물 성질은 프로그램이 안다(`GeoProgram.photosynthesis.K_L`) — **프리셋이
아니다.** 함수에서 작물을 고르던 시절은 끝났고, `_crop_params()` 가 이미 그
JSON 을 정본으로 읽고 있다.
"""
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


def _code_only(src):
    """주석·문자열을 걷어낸 코드만. 규칙을 설명한 주석에 검사가 걸리지 않게."""
    import io
    import re
    import textwrap
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(
                io.StringIO(textwrap.dedent(src)).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        lines = [re.sub(r'#.*$', '', ln) for ln in src.split('\n')]
        return re.sub(r'\s+', '', ' '.join(lines))
    return re.sub(r'\s+', '', ' '.join(out))


class TestItComesFromTheCropNotTheShadeThreshold(unittest.TestCase):

    def test_the_cycle_no_longer_feeds_light_max_in(self):
        code = _code_only(_read('functions', 'custom_functions',
                                'env_coordinator_impl', '_cycle_mixin.py'))
        self.assertNotIn('light_sat=self.light_max', code,
                         '차광 임계가 아직 광포화점을 겸한다')
        self.assertIn('light_sat=self._light_saturation()', code)

    def test_the_helper_reads_the_crop_params(self):
        """`_crop_params()` 가 프로그램 JSON 을 얹는 유일한 자리다 — 여기서
        `photosynthesis` 를 다시 읽으면 두 벌이 되어 갈라진다."""
        body = _read('functions', 'custom_functions', 'env_coordinator_impl',
                     '_helpers_mixin.py')
        block = body.split('def _light_saturation', 1)[1].split('\n    def ', 1)[0]
        code = _code_only(block)
        self.assertIn('self._crop_params()', code)
        self.assertNotIn('photosynthesis.K_L', code)


class TestTheDerivation(unittest.TestCase):

    def _params(self, k_l):
        from aot.functions.utils.env_control.photosynthesis import CropParams
        p = CropParams()
        p.K_L = k_l
        return p

    def test_it_is_the_ninety_percent_point(self):
        """`A = A_max·L/(L+K_L)` 에서 `L = 9·K_L` 이면 `A = 0.9·A_max`.
        그 위로는 빛을 더 줘도 10% 미만만 남는다."""
        from aot.functions.utils.env_control.photosynthesis import (
            SAT_K_L_MULT, light_saturation_wm2)
        self.assertEqual(SAT_K_L_MULT, 9.0)
        # 실제 프로그램 값: 상추 육묘 80, いちご 100
        self.assertAlmostEqual(light_saturation_wm2(self._params(80.0)),
                               9 * 80 / 2.02, places=3)
        self.assertAlmostEqual(light_saturation_wm2(self._params(100.0)),
                               9 * 100 / 2.02, places=3)

    def test_it_converts_through_the_system_table(self):
        """`K_L` 은 PPFD 이고 판정은 전천일사다. 계수를 직접 곱하면 시스템
        변환표와 갈라진다."""
        code = _code_only(
            _read('functions', 'utils', 'env_control', 'photosynthesis.py')
            .split('def light_saturation_wm2', 1)[1].split('\ndef ', 1)[0])
        self.assertIn('light_to_wm2', code)
        self.assertNotIn('2.02', code, '변환 계수를 손으로 적었다')

    def test_no_crop_means_none_not_zero(self):
        """⚠ 0 을 돌려주면 `sat` 이 falsy 라 시스템 기본으로 돌아가긴 하지만,
        그 경로에 기대면 안 된다 — 0 을 유효한 포화점으로 읽는 자리가 생기면
        '언제나 광 충분' 이 되어 사고가 그대로 재현된다."""
        from aot.functions.utils.env_control.photosynthesis import (
            light_saturation_wm2)
        for bad in (None, 0.0, -1.0, 'x'):
            self.assertIsNone(light_saturation_wm2(self._params(bad)),
                              'K_L=%r 이 None 이 아니다' % (bad,))

    def test_the_fallback_is_the_system_default(self):
        """`light_sat` 이 None 이면 `_LIGHT_SAT` 으로 돌아간다 — 이 검사가
        위 계약의 짝이다."""
        from aot.functions.utils.env_control import situation
        self.assertEqual(situation._LIGHT_SAT, 600.0)
        # ⚠ 표현식 전체를 문자로 못박지 말 것 — 괄호 하나만 달라도 깨진다.
        #   보는 것은 **폴백이 있는가** 이지 그 표현이 무엇인가가 아니다.
        code = _code_only(
            _read('functions', 'utils', 'env_control', 'situation.py'))
        self.assertIn('else_LIGHT_SAT', code, '폴백이 사라졌다')
        self.assertIn('light_sat>0', code, '0 을 유효한 포화점으로 읽는다')


class TestTheThresholdSaysWhatItIs(unittest.TestCase):

    def test_the_tooltip_no_longer_claims_two_jobs(self):
        import sys
        import types
        if 'flask_babel' not in sys.modules:
            b = types.ModuleType('flask_babel')
            b.lazy_gettext = lambda s: s
            b.gettext = lambda s, **k: s
            sys.modules['flask_babel'] = b
        from aot.functions.custom_functions.env_coordinator_impl import (
            _function_info as fi)
        for o in fi.FUNCTION_INFORMATION['custom_options']:
            if o.get('id') == 'light_max':
                phrase = str(o.get('phrase') or '')
                self.assertIn('program', phrase,
                              '작물 쪽에서 온다는 사실을 안 말한다')
                return
        self.fail('light_max 가 없다')


if __name__ == '__main__':
    unittest.main()

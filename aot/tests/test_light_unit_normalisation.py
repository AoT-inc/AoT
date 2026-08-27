# coding=utf-8
"""광량은 **W/m² 로 맞춰서** 제어에 들어가야 한다 (2026-08-27).

사용자 지적: *"시스템은 측정 단위 변환기가 있으므로 변환된 값으로 처리 되어야
함."* 맞다. 그런데 읽는 경로가 단위를 보지 않고 있었다.

`light` 결과 키는 W/m² 로 약속돼 있는데(`_UNIT_BY_KEY`), 광량으로 받아들이는
이름에는 `lux`·`ppfd`·`par` 가 함께 있다(`_MEAS_LIGHT_NAMES`). 그래서 조도계를
붙이면 **50,000 lux 가 50,000 W/m² 로 읽힌다** — `light_max`(기본 800)를 언제나
넘어 차광막이 영구히 닫히고, 같은 값이 실내 광량 추정·일소 잠금·DLI 로도
흘러가 셋이 함께 틀어진다. **에러는 나지 않는다.**

⚠ 변환표는 시스템 것 하나뿐이어야 한다(`config_devices_units.UNIT_CONVERSIONS`).
  두 벌이 되면 갈라지고, 갈라지면 화면과 제어가 다른 값을 본다.
"""
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


def _code_only(src):
    """주석과 문자열을 걷어낸 **코드만** 돌려준다.

    ⚠ 소스를 문자열로 훑는 검사는 반드시 이것을 지나야 한다. 그러지 않으면
      *그 이름을 설명하는 주석*까지 금지하게 되어, 규칙을 적어 두는 것만으로
      검사가 깨진다 — 이 레포가 `test_measurement_freshness` 에서 이미 겪고
      기록해 둔 함정이다.
    """
    import io
    import re
    import textwrap
    import tokenize
    out = []
    try:
        # ⚠ 파일 **가운데를 잘라** 넘기는 경우가 있어 들여쓰기가 0 에서
        #   시작하지 않는다 — 그대로 토큰화하면 `IndentationError` 다.
        for tok in tokenize.generate_tokens(
                io.StringIO(textwrap.dedent(src)).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # 조각이라 토큰화가 안 되면 줄 단위로 주석만 걷는다. 완벽하지 않지만
        # 이 검사들이 보는 것(호출 형태)에는 충분하다.
        lines = [re.sub(r'#.*$', '', ln) for ln in src.split('\n')]
        return re.sub(r'\s+', '', ' '.join(lines))
    # ⚠ 공백을 통째로 없앤다 — 토큰 경로와 폴백 경로가 **같은 모양**을 내야
    #   검사가 어느 쪽으로 갔는지에 따라 갈리지 않는다.
    return re.sub(r'\s+', '', ' '.join(out))


class TestTheConverterIsTheSystemOne(unittest.TestCase):

    def test_it_walks_the_system_table(self):
        from aot.functions.utils.env_control import cumulative_tracker as ct
        src = _read('functions', 'utils', 'env_control', 'cumulative_tracker.py')
        body = _code_only(
            src.split('def light_to_wm2', 1)[1].split('\ndef ', 1)[0])
        self.assertIn('_convert_via_system', body,
                      '자체 변환을 만들었다 — 시스템 변환표가 정본이다')
        self.assertTrue(hasattr(ct, 'light_to_wm2'))

    def test_known_units_convert(self):
        from aot.functions.utils.env_control.cumulative_tracker import light_to_wm2
        # 한여름 정오 ≈ 1000 W/m² ≈ 126,000 lux
        self.assertAlmostEqual(light_to_wm2(50000, 'lux'), 395.0, places=1)
        self.assertAlmostEqual(light_to_wm2(50, 'klux'), 395.0, places=1)
        self.assertAlmostEqual(light_to_wm2(1000, 'umol_m2_s'), 1000 / 2.02,
                               places=3)
        self.assertAlmostEqual(light_to_wm2(400, 'W_m2'), 400.0, places=6)

    def test_ppfd_and_par_aliases_are_understood(self):
        """양자센서를 `ppfd`/`par` 로 등록하는 것이 흔하다."""
        from aot.functions.utils.env_control.cumulative_tracker import light_to_wm2
        for alias in ('ppfd', 'par', 'umol/m2/s'):
            self.assertAlmostEqual(light_to_wm2(1000, alias), 1000 / 2.02,
                                   places=3, msg='%s 를 모른다' % alias)

    def test_an_unknown_unit_is_left_alone(self):
        """⚠ 모르는 것을 추측해서 곱하면 원래 맞던 값까지 틀어진다."""
        from aot.functions.utils.env_control.cumulative_tracker import light_to_wm2
        for unit in (None, '', 'bananas'):
            self.assertEqual(light_to_wm2(400, unit), 400)

    def test_none_stays_none(self):
        """값이 없는 것과 0 은 다르다 — 0 으로 만들면 한밤중으로 읽힌다."""
        from aot.functions.utils.env_control.cumulative_tracker import light_to_wm2
        self.assertIsNone(light_to_wm2(None, 'lux'))


class TestTheReadPathAppliesIt(unittest.TestCase):

    def _src(self):
        return _read('aot_flask', 'geo', 'facility_sensors.py')

    def test_both_read_branches_normalise(self):
        """채널 직접 조회와 이름 탐색 — **둘 다** 지나야 한다. 한쪽만 고치면
        바인딩 방식에 따라 값이 달라진다."""
        src = self._src()
        block = _code_only(src.split('def _read_one_sensor', 1)[1])
        self.assertEqual(block.count('_normalise_light('), 2,
                         '두 읽기 경로 중 한쪽이 빠졌다')

    def test_it_uses_the_effective_unit_not_the_raw_one(self):
        """변환이 걸린 채널은 InfluxDB 에 **변환 단위로** 저장된다. raw unit 을
        보면 이미 변환된 값을 한 번 더 변환한다."""
        src = self._src()
        body = _code_only(
            src.split('def _normalise_light', 1)[1].split('\ndef ', 1)[0])
        self.assertIn('_effective_raw_unit(dm)', body)

    def test_it_does_not_build_a_second_conversion_table(self):
        src = self._src()
        body = _code_only(
            src.split('def _normalise_light', 1)[1].split('\ndef ', 1)[0])
        self.assertIn('light_to_wm2', body)
        self.assertNotIn('UNIT_CONVERSIONS', body,
                         '변환표를 두 번째로 들었다')


class TestTheRainUnitRecheckActuallyRuns(unittest.TestCase):
    """⚠ 예전 코드는 `return_measurement_info(dm.unique_id)` 였다.

    그 함수의 시그니처는 `(행, conversion)` 이라 **TypeError** 가 났고, 바로
    아래 `except Exception: pass` 가 그것을 삼켰다 — 이 재확인은 **한 번도
    성립한 적이 없었다**. 강수 채널의 이름이 원시 그대로(`length`·`depth`)이고
    단위만 변환된 경우, 그 채널은 영영 안 잡혔다.
    """

    def test_the_broken_call_is_gone(self):
        src = _code_only(_read('aot_flask', 'geo', 'facility_sensors.py'))
        self.assertNotIn('return_measurement_info(dm.unique_id)', src,
                         '인자 하나짜리 호출이 되살아났다 — TypeError 가 난다')

    def test_the_signature_really_takes_two(self):
        """위 주장의 근거다. 시그니처가 바뀌면 이 검사도 다시 봐야 한다."""
        import inspect
        from aot.utils.system_pi import return_measurement_info
        params = inspect.signature(return_measurement_info).parameters
        self.assertEqual(len(params), 2, str(list(params)))

    def test_it_now_uses_the_row_helper(self):
        src = _read('aot_flask', 'geo', 'facility_sensors.py')
        # ⚠ 원본에서 자른 **뒤에** 토큰화한다. 먼저 토큰화하면 `'rain'` 이
        #   문자열이라 사라져 자를 기준이 없어진다.
        block = _code_only(src.split("measurement_type == 'rain'", 1)[1][:400])
        self.assertIn('_effective_raw_unit(dm)', block)

    def test_both_rain_paths_are_fixed(self):
        """같은 깨진 호출이 **두 곳**에 있었다. 한 곳만 고치면 이름이 원시
        그대로인 강수 채널이 나머지 경로에서 그대로 안 잡힌다."""
        code = _code_only(_read('aot_flask', 'geo', 'facility_sensors.py'))
        self.assertEqual(code.count('_RAIN_UNITS'), 3,
                         '강수 단위 판정 자리가 늘거나 줄었다')
        self.assertNotIn('return_measurement_info', code)


if __name__ == '__main__':
    unittest.main()

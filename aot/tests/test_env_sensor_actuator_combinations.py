# coding=utf-8
"""센서와 장치의 **조합**이 제어로 이어지는가 (2026-09-20).

시설마다 장치 구성이 다르다. 측정만 있고 제어가 없는 축(참고값)이나 그 반대가
정상이고, 코디네이터는 그것을 이미 다룬다(`authority`). 그런데 어긋남 중 셋은
**아무 에러 없이 제어를 통째로 세운다** — 사람이 동작을 며칠 지켜보다 알게 되고,
로그에는 그 사이 아무 단서도 없다.

여기서 고정하는 것은 둘이다:
  1. `check_env_coordinator_health._check_combinations` 가 그 셋을 보고한다.
  2. 시설 도면에 배치했지만 제어가 다루지 않는 종류의 설비를 **조용히 버리지
     않는다**(2026-07-31 육묘장 사고 — 가습기가 등록되지 않아 VPD 를 낮출
     액추에이터가 하나도 없었는데, 그 사실이 어디에도 안 남았다).
"""

import ast
import os
import sys
import types
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPT = os.path.join(_ROOT, 'aot', 'scripts', 'check_env_coordinator_health.py')
_LOADER = os.path.join(
    _ROOT, 'aot', 'functions', 'custom_functions', 'env_coordinator_impl',
    '_profile_loader_mixin.py')
_INTEGRATION = os.path.join(
    _ROOT, 'aot', 'aot_flask', 'geo', 'facility_integration.py')


def _source(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _load_from_script(*names):
    """검사기에서 이름 붙은 함수·상수만 떼어 깨끗한 네임스페이스에서 돌린다.

    모듈을 그대로 import 하면 Flask 앱이 통째로 딸려 온다 — 이 파일의 다른
    검사들과 같은 이유로 AST 로 떼어 쓴다.
    """
    ns = {}
    for node in ast.parse(_source(_SCRIPT)).body:
        named = None
        if isinstance(node, ast.FunctionDef):
            named = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            named = node.targets[0].id
        if named in names:
            exec(compile(ast.Module([node], []), _SCRIPT, 'exec'), ns)
    missing = [n for n in names if n not in ns]
    if missing:
        raise AssertionError('떼어 내지 못했습니다: %s' % missing)
    return ns


class _FakeIntegration:
    """`get_facility_integration` 자리에 끼우는 가짜 모듈."""

    def __init__(self, payload):
        self.payload = payload

    def get_facility_integration(self, uuid, bypass_cache=False):
        return self.payload, None


def _check(payload, opts=None, ext_collector=False):
    ns = _load_from_script('_check_combinations', '_axes_of_kind',
                           '_AXIS_MTYPE', '_AXIS_LABEL')
    ns['_has_ext_collector'] = lambda: ext_collector
    name = 'aot.aot_flask.geo.facility_integration'
    saved = sys.modules.get(name)
    module = types.ModuleType(name)
    module.get_facility_integration = _FakeIntegration(payload).get_facility_integration
    sys.modules[name] = module
    try:
        return ns['_check_combinations'](opts or {}, 'fac-1', None)
    finally:
        if saved is None:
            del sys.modules[name]
        else:
            sys.modules[name] = saved


def _payload(indoor=(), outdoor=(), kinds=()):
    return {
        'sensors_resolved': [{'input_uuid': 'i%d' % n, 'measurement_type': m}
                             for n, m in enumerate(indoor)],
        'sensors_outdoor': [{'input_uuid': 'o%d' % n, 'measurement_type': m}
                            for n, m in enumerate(outdoor)],
        'actuators_resolved': [{'output_uuid': 'a%d' % n, 'kind': k}
                               for n, k in enumerate(kinds)],
    }


_FULL = _payload(indoor=('temperature', 'humidity'),
                 outdoor=('temperature', 'humidity'),
                 kinds=('opening', 'heater'))


class TestNormalSetupIsQuiet(unittest.TestCase):
    """제한이 없는 설치를 영구히 빨간불로 두면 아무도 안 본다."""

    def test_온습도_센서와_개구부만_있으면_조용하다(self):
        self.assertEqual([], _check(_FULL))

    def test_측정만_있고_목표도_장치도_없으면_보고하지_않는다(self):
        """그것이 곧 '보조 값' 이고 사용자가 의도한 정상 구성이다."""
        payload = _payload(indoor=('temperature', 'humidity', 'co2'),
                           kinds=('opening', 'heater'))
        self.assertEqual([], _check(payload))


class TestTargetWithoutMeasurement(unittest.TestCase):
    """목표는 있는데 잴 수가 없다 — 그 축이 제어에서 통째로 빠진다."""

    def test_실내_온도_센서가_없으면_심각으로_보고한다(self):
        found = _check(_payload(indoor=('humidity',), kinds=('heater',)))
        levels = {lvl for lvl, _ in found}
        self.assertIn('severe', levels)
        self.assertTrue(any('온도' in text for _, text in found), found)

    def test_습도도_같다(self):
        found = _check(_payload(indoor=('temperature',), kinds=('fogger',)))
        self.assertTrue(any(lvl == 'severe' and '습도' in text
                            for lvl, text in found), found)

    def test_광량_상한을_적었는데_광_측정이_없으면_보고한다(self):
        found = _check(_FULL, opts={'light_max': 250})
        self.assertTrue(any('광량' in text for _, text in found), found)

    def test_실외_컨텍스트_수집기가_있으면_보고하지_않는다(self):
        """실외 일사의 유입구는 둘이다 — 시설 실외 센서와 공유 수집기.

        뒤를 빠뜨리면 수집기로 일사를 받는 설치가 "광 센서를 다세요" 라는
        틀린 안내를 받는다.
        """
        payload = _payload(indoor=('temperature', 'humidity'),
                           kinds=('opening', 'shade'))
        found = _check(payload, opts={'light_max': 250}, ext_collector=True)
        self.assertEqual([], [t for _, t in found if '광량' in t], found)

    def test_차광막도_보광등도_없이_광량_상한만_적으면_보고한다(self):
        payload = _payload(indoor=('temperature', 'humidity'),
                           outdoor=('light',), kinds=('opening',))
        found = _check(payload, opts={'light_max': 250})
        self.assertTrue(any('움직일 장치가' in t and '광량' in t
                            for _, t in found), found)

    def test_실외_일사가_있으면_광량은_잰_것으로_본다(self):
        """실내 광센서가 없어도 막 아래 값을 추정하는 경로가 있다."""
        payload = _payload(indoor=('temperature', 'humidity'),
                           outdoor=('light',), kinds=('opening', 'shade'))
        found = _check(payload, opts={'light_max': 250})
        self.assertEqual([], [t for _, t in found if '광량' in t], found)


class TestTargetWithoutActuator(unittest.TestCase):
    """재기는 하는데 움직일 수단이 없다."""

    def test_온도를_움직일_장치가_하나도_없으면_보고한다(self):
        payload = _payload(indoor=('temperature', 'humidity'),
                           kinds=('co2_injector',))
        found = _check(payload)
        self.assertTrue(any('움직일 장치가' in text for _, text in found), found)

    def test_한_방향만_있어도_장치가_있는_것이다(self):
        """난방만 있고 냉방이 없는 것은 정상 구성이다 — 여기서 보고하지 않는다.

        그 상황은 실제로 더울 때 `_assess_strain` 이 `no_actuator` 로 말한다.
        """
        # 난방기는 온도를 **올리기만** 하고, 개구부는 습도를 **내리기만** 한다.
        # 두 축 모두 반대 방향 수단이 없지만 그것은 정상 구성이다.
        payload = _payload(indoor=('temperature', 'humidity'),
                           kinds=('heater', 'opening'))
        found = _check(payload)
        self.assertEqual([], [t for _, t in found if '움직일 장치가' in t], found)


class TestActuatorWithoutMeasurement(unittest.TestCase):
    """장치는 있는데 그 장치가 미는 축을 하나도 못 잰다 — 영원히 제자리다."""

    def test_보광등만_있고_광_측정이_없으면_보고한다(self):
        payload = _payload(indoor=('temperature', 'humidity'),
                           kinds=('opening', 'lighting'))
        found = _check(payload)
        self.assertTrue(any('lighting' in text for _, text in found), found)

    def test_광_측정이_있으면_보고하지_않는다(self):
        payload = _payload(indoor=('temperature', 'humidity', 'light'),
                           kinds=('opening', 'lighting'))
        found = _check(payload)
        self.assertEqual([], [t for _, t in found if 'lighting' in t], found)

    def test_축을_authority_표에서_읽는다(self):
        """표를 두 벌 두면 새 종류가 생길 때 조용히 갈라진다."""
        ns = _load_from_script('_axes_of_kind')
        self.assertEqual({'T'}, ns['_axes_of_kind']('heater'))
        self.assertEqual({'T', 'RH', 'CO2'}, ns['_axes_of_kind']('opening'))
        self.assertEqual(set(), ns['_axes_of_kind']('모르는종류'))


class TestUnmappedFittingIsNotDroppedSilently(unittest.TestCase):
    """제어가 다루지 않는 종류의 설비를 조용히 버리지 않는다.

    사용자는 도면에 장치를 배치하고 Output 까지 물렸는데 제어에 한 번도 안
    나타난다 — 화면 어디에도 이유가 없다(2026-07-31 육묘장).
    """

    def test_로더가_제외_사실을_error_로_남긴다(self):
        src = _source(_LOADER)
        body = src.split('def _reload_profiles', 1)[1]
        self.assertIn('unmapped', body,
                      '종류를 못 알아본 설비를 모으지 않는다')
        i = body.index('unmapped.append')
        j = body.index('_last_unmapped_actuators')
        self.assertLess(i, j)
        # ⚠ **`info` 가 아니라 `error` 다.** 컨트롤러 로거는 `log_level_debug`
        #   가 꺼져 있으면 레벨이 ERROR 라(`base_controller.py`), info 는 기본
        #   설치에서 아무 데도 안 남는다 — 알리려고 만든 줄이 정확히 알려야 할
        #   사람에게만 안 보인다.
        tail = body[j - 800:j + 400]
        self.assertIn('self.logger.error', tail, tail[-400:])

    def test_바뀔_때만_찍는다(self):
        """프로필 재적재는 주기적으로 돈다 — 매번이면 같은 줄이 하루 내내
        쌓여 정작 읽어야 할 로그를 밀어낸다."""
        body = _source(_LOADER).split('def _reload_profiles', 1)[1]
        self.assertIn("!= getattr(self, '_last_unmapped_actuators', None)", body)

    def test_통합_페이로드가_원래_종류를_싣는다(self):
        """이 값이 없으면 '종류를 알 수 없는 장치 1개' 까지만 말할 수 있어
        사용자가 어느 설비인지 찾지 못한다."""
        self.assertIn("'fitting_kind':", _source(_INTEGRATION))


if __name__ == '__main__':
    unittest.main()

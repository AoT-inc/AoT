# coding=utf-8
"""필지(site) 모달의 [환경·제어]는 **시설 안 설비까지 끌어오지 않는다.**

## 왜 있는가

2026-09-06 현장 보고: 김제 3포장(필지) 모달의 [환경·제어]에 `측창: 좌`·
`측창: 우` 가 떴다. 이 둘은 지도에 놓인 적이 없고, 3포장 안의 시설(육묘장3)의
**설비**(`env_side_vent_outer_u0_left_single`, kind=side_window)에 매여 있다.
필지에서 시설 안의 측창까지 늘어놓으면 "이 필지를 어떻게 볼까" 가 아니라
"여기서 뭘 다 조작할 수 있나" 가 되어, 정작 필지 단위로 판단할 것이 묻힌다.

## 어디를 가르나

`GeoBinding` 은 두 갈래다:

  · `spatial_kind='shape'`      — 도형에 **직접** 맡긴 장치. 어디서든 유지한다.
  · `spatial_id='<시설>:<설비>'` — 시설 **안**의 설비에 매인 장치. 필지에서 뺀다.

실측(김제 3포장): 밸브 v311~v342·SIM 관수밸브는 전부 `shape`, 측창 좌/우와
`v:육묘장` 은 전부 `fitting` 이라 경계가 정확히 갈린다.

## 함께 지키는 것

구역(zone) 모달과 필지 요약(`summary_for_site`)은 **안 바뀐다.** 요약은 자식
(구역·시설)마다 따로 판정하므로 시설 행은 자기 설비를 그대로 센다 — 이 도메인은
"같은 것을 화면마다 다르게 세는" 실패로 이미 크게 데었다.
"""
import inspect
import re
import unittest

from aot.aot_flask.geo import device_membership


class TestTheSwitchExists(unittest.TestCase):

    def test_both_functions_take_the_flag(self):
        for fn in (device_membership.device_ids_in_area,
                   device_membership._bound_device_ids):
            self.assertIn('include_facility_fittings',
                          inspect.signature(fn).parameters, fn.__name__)

    def test_it_defaults_to_including_them(self):
        """기본값이 바뀌면 구역 모달·그래프 필터가 조용히 좁아진다."""
        for fn in (device_membership.device_ids_in_area,
                   device_membership._bound_device_ids):
            self.assertIs(
                True,
                inspect.signature(fn).parameters['include_facility_fittings'].default,
                fn.__name__)

    def test_the_flag_reaches_the_binding_query(self):
        """`device_ids_in_area` 가 받기만 하고 안 넘기면 아무 일도 안 일어난다."""
        src = inspect.getsource(device_membership.device_ids_in_area)
        self.assertRegex(
            src, r'_bound_device_ids\([^)]*include_facility_fittings\s*=')

    def test_only_the_fitting_branch_is_gated(self):
        """도형에 **직접** 맡긴 장치까지 빠지면 구역 밸브가 통째로 사라진다."""
        src = inspect.getsource(device_membership._bound_device_ids)
        shape_q = src.index("spatial_kind == 'shape'")
        gate = src.index('if include_facility_fittings:')
        self.assertLess(shape_q, gate,
                        'shape 바인딩이 플래그 안쪽에 들어가 있습니다')
        self.assertIn("like(fac + ':%')", src[gate:])


class TestOnlyTheSiteEndpointTurnsItOff(unittest.TestCase):
    """켜고 끄는 자리를 늘리면 어느 화면이 무엇을 세는지 아무도 모르게 된다."""

    def _routes(self):
        import aot.aot_flask.routes_geo as rg
        return inspect.getsource(rg)

    def test_the_site_contents_endpoint_turns_it_off(self):
        body = inspect.getsource(
            __import__('aot.aot_flask.routes_geo', fromlist=['x'])
            .api_geo_site_contents)
        self.assertIn('include_facility_fittings=False', body)

    def test_the_zone_endpoint_does_not(self):
        """구역은 그대로다 — 구역 안 시설의 설비는 구역의 것이 맞다."""
        body = inspect.getsource(
            __import__('aot.aot_flask.routes_geo', fromlist=['x'])
            ._build_zone_contents)
        self.assertNotIn('include_facility_fittings', body)

    def test_nowhere_else_turns_it_off(self):
        """주석·문서가 아니라 **실제 호출 인자**만 센다(ast)."""
        import ast
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        hits = []
        for base, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ('tests', '__pycache__')]
            for n in names:
                if not n.endswith('.py'):
                    continue
                p = os.path.join(base, n)
                try:
                    tree = ast.parse(open(p, encoding='utf-8').read())
                except (OSError, SyntaxError):
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    for kw in node.keywords:
                        if (kw.arg == 'include_facility_fittings'
                                and isinstance(kw.value, ast.Constant)
                                and kw.value.value is False):
                            hits.append('%s:%d' % (os.path.relpath(p, root),
                                                   node.lineno))
        self.assertEqual(len(hits), 1,
                         '끄는 자리는 필지 엔드포인트 하나여야 합니다: %s' % hits)


class TestTheSiteSummaryIsUntouched(unittest.TestCase):

    def test_summary_asks_per_child(self):
        """요약이 필지 전체로 한 번에 물으면 이 변경과 어긋나게 된다."""
        from aot.aot_flask.geo import site_summary
        src = inspect.getsource(site_summary._device_ids_for)
        self.assertIn('device_ids_in_area(shape.unique_id)', src)
        self.assertNotIn('include_facility_fittings', src)


if __name__ == '__main__':
    unittest.main()

# coding=utf-8
"""장치 삭제는 지도를 지우지 않는다 — 그 자리를 지키는 회귀 시험.

배경(2026-08-03 aot-004): 중복 출력 하나를 지우자 공유 디자인 지도 '임실군'
(도형 62개 + GeoMap 행)이 통째로 사라졌다. 장치의 `map_config_id` 를 "장치가
그 지도를 소유한다" 로 읽고 장치 삭제 경로가 `delete_map_config` 로 지도를
지웠기 때문이다. 그때 붙인 2중 가드(`is_device_owned` + `_map_still_referenced`)
는 증상 대응이었고, P3 가 장치 삭제 경로에서 지도 삭제 호출을 없애 원인을
제거했다.

L3(2026-11-05): `delete_map_config` 와 `_map_still_referenced` 는 호출자가 0 인
채 `map_config_id` 컬럼만 붙들고 있어 함께 지웠다. 지도 삭제는 이제
`GeoDesignManager.delete_design_map` 하나이고, 그 경로는 장치 컬럼을 보지
않는다(장치 배치는 지도의 마커·바인딩이며 지도와 함께 정리된다).

이 파일이 지키는 것:
  - 지도를 지우는 장치 측 함수가 다시 생기지 않는다.
  - 지도 삭제 경로가 `map_config_id` 에 기대지 않는다.
  - 지도 팩토리 모듈(`utils_map_config`, clone 포함)은 L3 에서 지웠다 — 되살리지 않는다.

실제 DB 를 건드리지 않는다.
"""
import ast
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))


def test_device_side_map_factories_and_deleters_are_gone():
    """지도를 만들고(`ensure/create/clone_map_config`) 장치 쪽에서 지우던
    (`delete_map_config`·`_map_still_referenced`) 모듈은 L3 에서 삭제했다."""
    assert not os.path.exists(
        os.path.join(ROOT, 'aot/aot_flask/utils/utils_map_config.py')), (
        '지도 팩토리 모듈이 되살아났습니다 — 장치 삭제가 지도를 지우던 경로입니다.')


def test_design_map_delete_does_not_read_map_config_id():
    """지도 삭제의 유일한 경로는 장치 컬럼 `map_config_id` 를 보지 않는다."""
    path = os.path.join(ROOT, 'aot/aot_flask/geo/geo_design.py')
    tree = ast.parse(open(path, encoding='utf-8').read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == 'delete_design_map')
    attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    names = {n.value for n in ast.walk(fn)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert 'map_config_id' not in attrs
    assert 'map_config_id' not in names

# coding=utf-8
"""선언만 있고 스키마에도 코드에도 없는 옵션을 만들지 않는다 (2026-08-26).

## 왜 이것이 조용한 실패인가

`setup_custom_options_json`(abstract_base_controller)은 **옵션 스키마를
순회**하지 저장된 `custom_options` JSON 의 키를 순회하지 않는다. 그래서
스키마에 없는 이름은

  · 화면에 나오지 않고
  · 값이 DB 에 남아 있어도 **아무것도 설정하지 않으며**
  · `__init__` 의 선언은 남아 있어 **읽는 사람에게는 설정처럼 보인다.**

에러도 경고도 없다. 그리고 DB 의 옛 값은 지워지지 않으므로, 나중에
`custom_options` 를 들여다본 사람은 그것을 현재 설정으로 읽는다.

## 실제로 밟았다

2026-08-26 イチゴ 온실을 진단하다 `custom_options` 에서

    sensor_T_int  = <OpenWeather 의 measurement>
    sensor_RH_int = <OpenWeather 의 measurement>

를 보고 **"코디네이터가 실내 센서로 기상 API 를 쓰고 있다"** 고 결론지었다.
틀렸다. 그 이름들은 스키마에 없어 읽히지 않고, 실제 실내값은 시설 바인딩
(`_collect_internal` → `sensors_resolved` → 미러-온습도05)에서 정상적으로
온다. 죽은 값 하나가 진단을 통째로 엉뚱한 데로 보냈다.

지운 것은 7개다: sensor_T_int · sensor_RH_int · sensor_vpd · sensor_light ·
sensor_CO2_int · sensor_wind · sensor_wind_dir.

## 이 검사가 허용하는 것

- 스키마에 있는 옵션 (정상)
- `_` 로 시작하는 내부 상태 (런타임 필드)
- 코드가 실제로 읽는 이름 (옵션이 아닌 협력 필드 — 예: `control`)
- `select_measurement`/`select_device` 가 자동으로 만드는 짝
  (`<id>_device_id`, `<id>_measurement_id`)
"""
import ast
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_IMPL = _ROOT / 'aot' / 'functions' / 'custom_functions'
_COORD = _IMPL / 'env_coordinator.py'
_INFO = _IMPL / 'env_coordinator_impl' / '_function_info.py'

# 옵션이 아니지만 __init__ 에서 세우는 협력 필드 — 코드가 실제로 읽는다.
_NON_OPTION_FIELDS = {'control', 'timer_loop'}


def _schema_ids():
    return set(re.findall(r"'id'\s*:\s*'([a-zA-Z0-9_]+)'", _INFO.read_text()))


def _init_attrs():
    tree = ast.parse(_COORD.read_text())
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == '__init__'):
            continue
        for n in ast.walk(node):
            if isinstance(n, ast.Assign):
                targets = n.targets
            elif isinstance(n, ast.AnnAssign):
                targets = [n.target]
            else:
                continue
            for t in targets:
                if (isinstance(t, ast.Attribute)
                        and isinstance(t.value, ast.Name)
                        and t.value.id == 'self'):
                    out.append(t.attr)
    return sorted(set(out))


def _read_elsewhere(name):
    """선언 말고 실제로 읽는 자리가 있는가 (레포 전체, 번들 제외)."""
    hits = 0
    for path in _ROOT.joinpath('aot').rglob('*.py'):
        if path == _COORD:
            continue
        if re.search(r'\b' + re.escape(name) + r'\b', path.read_text(errors='ignore')):
            hits += 1
    return hits


def test_스키마에도_코드에도_없는_선언이_없다():
    schema = _schema_ids()
    orphans = []
    for attr in _init_attrs():
        if attr.startswith('_') or attr in _NON_OPTION_FIELDS or attr in schema:
            continue
        # select_measurement / select_device 가 만드는 짝
        base = re.sub(r'_(device_id|measurement_id)$', '', attr)
        if base != attr and base in schema:
            continue
        if _read_elsewhere(attr) == 0:
            orphans.append(attr)
    assert not orphans, (
        '스키마에 없고 아무도 읽지 않는 선언: %s\n'
        '  화면에 안 나오고 값도 안 채워지는데 설정처럼 보인다. 옵션으로 쓸 것이면 '
        '_function_info.py 에 정의를 넣고, 아니면 선언을 지울 것.' % orphans)


def test_지웠던_7개가_되살아나지_않았다():
    """이름을 명시해 둔다 — 되살리려면 이 목록을 손대며 이유를 마주하게 된다."""
    removed = {'sensor_T_int', 'sensor_RH_int', 'sensor_vpd', 'sensor_light',
               'sensor_CO2_int', 'sensor_wind', 'sensor_wind_dir'}
    back = removed & set(_init_attrs())
    assert not back, (
        '%s 가 다시 선언됐다. 실내·실외 센서는 시설 바인딩'
        '(sensors_resolved / sensors_outdoor)이 정본이다 — 두 번째 경로를 '
        '만들면 어느 쪽이 실질 설정인지 알 수 없어진다.' % sorted(back))


def test_옵션_적용은_스키마를_순회한다():
    """이 검사의 전제 — 저장된 키를 순회한다면 죽은 선언도 채워질 것이다."""
    import inspect
    from aot.controllers.abstract_base_controller import AbstractBaseController
    src = inspect.getsource(AbstractBaseController.setup_custom_options_json)
    assert 'for each_option_default in custom_options:' in src, (
        '적용 방식이 바뀌었다 — 이 검사의 근거를 다시 볼 것')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

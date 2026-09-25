# coding=utf-8
"""리스너형 입력의 측정 유효 수명(max_age_s) 노출 (2026-09-25).

## 발견한 버그

1. `mqtt_paho_json.py` 의 `INPUT_INFORMATION` 딕셔너리 리터럴에 `'options_enabled'`
   키가 두 번 있었다 — 두 번째(`['period']`)가 첫 번째(`['measurements_select']`)를
   조용히 덮어써서, "활성화할 측정값 선택" UI(`Measurements_Enabled.html`)가 이
   입력에서만 사라졌다. 파이썬 딕셔너리 리터럴은 중복 키를 에러 없이 마지막 것으로
   해석하므로 아무 경고도 없었다.

2. 어떤 입력 모듈도 `INPUT_INFORMATION['listener']` 를 설정하지 않아서
   `live.html`/`input_entry.html` 의 리스너 분기가 한 번도 실행되지 않았다. MQTT/
   ChirpStack 입력은 실제로는 주기 폴링을 하지 않는데도 주기 기준으로 신선도가
   판정됐고, `mqtt_paho`/`mqtt_paho_json`/`chirpstack_rak3172_valve_hb` 는
   표준 `period` 옵션 자체가 꺼져 있어 `측정 유효 수명`(`Input.max_age_s`) 필드가
   보이지도 설정되지도 않았다.

3. `kma_weather_500.py` 는 자체 커스텀 `period` 옵션(기본 300초)을 따로 두고
   표준 `period` 옵션은 켜지 않아서, 표준 `Input.period` 컬럼이 모델 기본값
   15초에 고정된 채로 `측정 유효 수명` 필드도 함께 숨겨져 있었다. 자동 유효
   수명 계산(`max(floor, period*factor)`)이 그 15초를 보지 못하고 바닥값
   300초로 떨어지는데, 이는 KMA 의 실제 갱신 주기(300초)와 같아서 지연이
   조금만 생겨도 값이 "오래됨"으로 판정되기 쉽다.

## 이 파일이 잠그는 것

- (1)류 버그가 이 저장소의 어떤 `aot/inputs/*.py` `INPUT_INFORMATION` 리터럴에도
  다시 생기지 않는지 AST 로 정적 검사한다.
- 실제로 자체 리스너 스레드에서 도는(폴링하지 않는) 입력들이
  `'listener': True` 를 선언하고, `측정 유효 수명` 필드가 보이도록
  `'period'` 또는 `'max_age_only'` 를 `options_enabled` 에 갖고 있는지 확인한다.
- `Period.html` 이 `'max_age_only'` 단독으로도 유효 수명 필드를 그리는지
  (기존 `'period'` 경로는 건드리지 않고) 렌더로 확인한다.
"""
import ast
import importlib.util
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_INPUTS_DIR = _ROOT / 'aot' / 'inputs'
_PERIOD_HTML = (_ROOT / 'aot' / 'aot_flask' / 'templates' / 'pages'
                / 'form_options' / 'Period.html')

# 자체 listener() 스레드로만 도는(get_measurement() 를 오버라이드하지 않는)
# 입력들 — 폴링 주기가 없으므로 표준 period 필드는 무의미하고, 유효 수명
# 필드만 보이면 된다.
_PURE_LISTENER_MODULES = [
    'mqtt_paho.py',
    'mqtt_paho_json.py',
    'chirpstack_rak3172_valve_hb.py',
]

# listener 스레드로 돌지만, 다른 모듈과의 일관성을 위해 표준 period 필드도
# (폴링에 쓰이진 않아도) 남겨둔 입력들.
_LISTENER_WITH_PERIOD_FIELD_MODULES = [
    'chirpstack_MQTT_jmespath.py',
    'ecowitt_mqtt.py',
]


def _input_information_dicts():
    """저장소의 모든 입력 모듈에서 `INPUT_INFORMATION = {...}` 리터럴을 찾는다.

    실행하지 않고 AST 만 본다 — 일부 입력 모듈은 무거운 하드웨어 의존성을
    임포트 시점에 요구하므로, 이 검사는 그것들과 무관하게 항상 돌아야 한다.
    """
    found = []
    for path in sorted(_INPUTS_DIR.glob('*.py')):
        if path.name in ('__init__.py', 'base_input.py', 'sensorutils.py'):
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == 'INPUT_INFORMATION'
                       for t in node.targets):
                continue
            if isinstance(node.value, ast.Dict):
                found.append((path, node.value))
    return found


class TestNoDuplicateInputInformationKeys:
    """딕셔너리 리터럴 중복 키가 조용히 값을 덮어쓰지 않는다 (mqtt_paho_json 사고)."""

    def test_어떤_INPUT_INFORMATION_에도_중복_최상위_키가_없다(self):
        offenders = []
        for path, dict_node in _input_information_dicts():
            keys = [k.value for k in dict_node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            seen = set()
            dupes = set()
            for k in keys:
                if k in seen:
                    dupes.add(k)
                seen.add(k)
            if dupes:
                offenders.append('%s: %s' % (path.name, sorted(dupes)))
        assert not offenders, (
            'INPUT_INFORMATION 딕셔너리 리터럴에 중복 키가 있다 — 나중 값이 '
            '조용히 이긴다 (mqtt_paho_json 의 options_enabled 사고 재발):\n'
            + '\n'.join(offenders))

    def test_mqtt_paho_json_은_measurements_select_를_유지한다(self):
        """이 버그가 실제로 숨겼던 옵션이 지금 켜져 있는지 직접 확인."""
        mod = _load_input_module('mqtt_paho_json.py')
        assert 'measurements_select' in mod.INPUT_INFORMATION['options_enabled']


def _load_input_module(filename):
    path = _INPUTS_DIR / filename
    spec = importlib.util.spec_from_file_location(
        'input_under_test_' + filename.replace('.', '_'), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize('filename', _PURE_LISTENER_MODULES)
class TestPureListenerInputsExposeFreshnessOverride:
    """폴링 주기가 없는 리스너 입력은 listener 플래그 + 유효 수명 필드만 노출한다."""

    def test_listener_플래그가_켜져_있다(self, filename):
        info = _load_input_module(filename).INPUT_INFORMATION
        assert info.get('listener') is True

    def test_측정_선택과_유효_수명_필드가_보인다(self, filename):
        info = _load_input_module(filename).INPUT_INFORMATION
        enabled = info.get('options_enabled', [])
        assert 'measurements_select' in enabled
        assert 'max_age_only' in enabled

    def test_실제로_폴링에_쓰이는_period_필드는_없다(self, filename):
        """get_measurement() 를 오버라이드하지 않으므로 표준 period 는 무의미하다."""
        info = _load_input_module(filename).INPUT_INFORMATION
        assert 'period' not in info.get('options_enabled', [])


@pytest.mark.parametrize('filename', _LISTENER_WITH_PERIOD_FIELD_MODULES)
class TestListenerInputsWithLegacyPeriodField:
    """listener 플래그는 켜지지만 기존 period 필드 노출 방식은 유지한다."""

    def test_listener_플래그가_켜져_있다(self, filename):
        info = _load_input_module(filename).INPUT_INFORMATION
        assert info.get('listener') is True

    def test_period_필드로_유효_수명이_이미_보인다(self, filename):
        info = _load_input_module(filename).INPUT_INFORMATION
        assert 'period' in info.get('options_enabled', [])


class TestKmaWeatherExposesFreshnessOverride:
    """KMA 는 자체 period 옵션을 쓰므로 표준 period 는 그대로 두고 유효 수명만 연다."""

    def test_max_age_only_이_켜져_있다(self):
        info = _load_input_module('kma_weather_500.py').INPUT_INFORMATION
        assert 'max_age_only' in info.get('options_enabled', [])

    def test_자체_period_커스텀_옵션은_그대로다(self):
        """폴링 로직을 바꾸지 않았다는 것을 확인 — 커스텀 옵션 'period' 가 여전히 있다."""
        info = _load_input_module('kma_weather_500.py').INPUT_INFORMATION
        custom_ids = [c['id'] for c in info.get('custom_options', [])]
        assert 'period' in custom_ids

    def test_표준_period_필드는_건드리지_않았다(self):
        """표준 period 를 켜면 실제 폴링 주기(현재 daemon 이 스케줄링에 쓰는 값)가
        바뀌므로, 이번 변경 범위 밖이다 — 켜지 않았는지 못박는다."""
        info = _load_input_module('kma_weather_500.py').INPUT_INFORMATION
        assert 'period' not in info.get('options_enabled', [])


class TestPeriodHtmlRendersMaxAgeOnly:
    """`max_age_only` 단독으로도 유효 수명 행이 그려지고, 표준 period 행은 안 그려진다."""

    def _render(self, options_enabled, options_disabled=None):
        import jinja2

        class _FakeField:
            def __init__(self, name):
                self._name = name

            def label(self, **kwargs):
                return '<label>%s</label>' % self._name

            def __call__(self, **kwargs):
                disabled = ' disabled' if kwargs.get('disabled') else ''
                return '<input name="%s"%s>' % (self._name, disabled)

        class _FakeForm:
            period = _FakeField('period')
            max_age_s = _FakeField('max_age_s')

        class _FakeDevice:
            period = 60
            max_age_s = None

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_PERIOD_HTML.parent)),
            undefined=jinja2.ChainableUndefined,
        )
        env.globals['_'] = lambda s: s  # flask_babel.gettext stand-in
        template = env.get_template(_PERIOD_HTML.name)
        return template.render(
            dict_options={'options_enabled': options_enabled,
                          'options_disabled': options_disabled or []},
            form=_FakeForm(),
            each_device=_FakeDevice(),
            dict_translation={'period': {'phrase': 'phrase'}},
        )

    def test_max_age_only_만으로도_유효_수명_행이_보인다(self):
        html = self._render(['max_age_only'])
        assert 'max_age_s' in html

    def test_max_age_only_만으로는_표준_period_행이_안_보인다(self):
        html = self._render(['max_age_only'])
        assert 'name="period"' not in html

    def test_기존_period_경로는_그대로_동작한다(self):
        html = self._render(['period'])
        assert 'name="period"' in html
        assert 'max_age_s' in html

    def test_아무것도_없으면_둘_다_안_보인다(self):
        html = self._render([])
        assert 'name="period"' not in html
        assert 'max_age_s' not in html

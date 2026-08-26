# coding=utf-8
"""ecowitt_MQTT 입력 — 존재하지 않는 API와 0 유실 (2026-08-26).

## 이 모듈은 여태 **한 번도 돌 수 없었다**

`__init__` 이 `initialize()` 를 부르고, 그 첫 줄이
`self.input_dev.option_get('ecowitt_device')` 였다. **`option_get` 은 이
코드베이스에 존재하지 않는다.** 그래서 생성 자체가 AttributeError 로 죽었다.

같은 자리에서 존재하지 않는 함수를 넷이나 불렀다:

    input_dev.option_get(...)        정의 0곳
    input_dev.on_option_change(...)  정의 0곳
    self.add_channel(...)            정의 0곳
    self.delete_channel(...)         정의 0곳

옵션은 `setup_custom_options` 가 **같은 이름의 속성**으로 실어 준다
(`self.ecowitt_device`). 채널은 사용자가 UI 에서 구성한다 — 형제 모듈
`mqtt_paho_json` 과 같은 구조다.

## 0 을 버리던 문제

`if value is None or isinstance(value, str) or value == 0: continue` 였다.
이 기기가 내보내는 값의 상당수는 **0 이 정상**이다 — 밤의 일사·UV, 비가 안
올 때의 강우량, 무풍일 때의 풍속. 버리면 "값이 가끔 안 들어온다" 가 되고,
더 나쁘게는 **평균과 적산이 0 을 빼고 계산돼** 조용히 부풀려진다.
걸러야 할 것은 0 이 아니라 '없음'(키 부재·빈 문자열)이다.

## 로그가 전부 주석 처리돼 있었다

디코드 실패·파싱 실패·JMESPath 오류 로그 7곳이 주석이었다. 그래서 어떤 실패도
흔적을 남기지 않았다. 되살렸다.
"""
import importlib.util
import inspect
import json
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC = _ROOT / 'aot' / 'inputs' / 'ecowitt_mqtt.py'


def _load():
    spec = importlib.util.spec_from_file_location('ecowitt_mqtt_under_test', _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeDev:
    unique_id = 'test-input'
    log_level_debug = False
    custom_options = json.dumps({
        'ecowitt_device': 'weather_station', 'mqtt_hostname': 'localhost',
        'mqtt_port': 1883, 'mqtt_channel': 'gw', 'mqtt_keepalive': 60,
        'mqtt_clientid': 't', 'mqtt_login': False, 'mqtt_use_tls': False,
        'mqtt_use_websockets': False, 'mqtt_username': '', 'mqtt_password': ''})


class TestNoPhantomApis:
    """존재하지 않는 함수를 부르지 않는다."""

    _PHANTOM = ('option_get', 'on_option_change', 'add_channel', 'delete_channel')

    def test_레포에_그_함수들이_없다(self):
        """전제 확인 — 나중에 누가 진짜로 만들면 이 테스트가 알려준다."""
        defined = set()
        for path in _ROOT.joinpath('aot').rglob('*.py'):
            src = path.read_text(errors='ignore')
            for name in self._PHANTOM:
                if re.search(r'def\s+' + name + r'\s*\(', src):
                    defined.add(name)
        assert not defined, (
            '%s 가 실제로 생겼다 — 이 모듈이 그것을 써야 하는지 다시 볼 것' % sorted(defined))

    def test_모듈이_그_함수들을_호출하지_않는다(self):
        body = _SRC.read_text()
        # 주석은 예외 — 무엇이 왜 사라졌는지 설명하는 글까지 막으면 안 된다.
        code = '\n'.join(ln for ln in body.splitlines()
                         if not ln.lstrip().startswith('#'))
        for name in self._PHANTOM:
            assert name + '(' not in code, '%s 호출이 되살아났다' % name

    def test_reinitialize_를_되살리지_않았다(self):
        """유일한 호출자가 존재하지 않는 훅이었다 — 되살리면 또 죽은 코드다."""
        assert 'def reinitialize' not in _SRC.read_text()


class TestOptionsAreReadAsAttributes:

    def test_생성이_된다(self):
        """예전에는 여기서 AttributeError 로 죽었다 — 그게 이 회귀의 본체다."""
        mod = _load()
        inst = mod.InputModule(_FakeDev(), testing=True)
        assert inst is not None

    def test_ecowitt_device_가_속성으로_실린다(self):
        mod = _load()
        inst = mod.InputModule(_FakeDev(), testing=True)
        inst.setup_custom_options(
            mod.INPUT_INFORMATION['custom_options'], _FakeDev())
        assert inst.ecowitt_device == 'weather_station'

    def test_init_에_선언돼_있다(self):
        """선언이 없으면 setup 전에 읽는 코드가 AttributeError 를 낸다."""
        src = inspect.getsource(_load().InputModule.__init__)
        assert 'self.ecowitt_device' in src


class TestZeroIsAValidReading:
    """0 은 '없음' 이 아니다."""

    @staticmethod
    def _kept(result):
        """on_message 의 판정 규칙 — 소스와 같은 형태로 유지할 것."""
        return not (result is None
                    or (isinstance(result, str) and not result.strip()))

    @pytest.mark.parametrize('value', [0.0, 0, 0.00])
    def test_0_은_저장한다(self, value):
        assert self._kept(value), (
            '밤의 일사·무풍의 풍속·비 안 올 때의 강우량이 전부 0 이다')

    @pytest.mark.parametrize('value', [None, '', '   '])
    def test_없음은_거른다(self, value):
        assert not self._kept(value)

    def test_소스에_0_비교가_없다(self):
        """`value == 0` 이 되살아나면 평균·적산이 조용히 부풀려진다."""
        code = '\n'.join(ln for ln in _SRC.read_text().splitlines()
                         if not ln.lstrip().startswith('#'))
        assert 'value == 0' not in code


class TestFailuresAreLogged:
    """로그가 전부 주석이면 어떤 실패도 흔적을 안 남긴다."""

    def test_주석_처리된_로그가_없다(self):
        src = _SRC.read_text()
        assert '# self.logger' not in src

    def test_파싱_실패를_ERROR_로_남긴다(self):
        src = inspect.getsource(_load().InputModule.on_message)
        assert src.count('self.logger.error(') >= 2, (
            '디코드·파싱 실패가 조용히 return 하고 있다')


class TestDroppedChannelsAreAnnounced:
    """거르는 것은 **말하고** 거른다."""

    def test_초기화에서_한_번_알린다(self):
        src = inspect.getsource(_load().InputModule.initialize)
        assert 'self.logger.error(' in src, (
            '기기 종류에 없는 채널을 조용히 버리면 "채널을 만들었는데 값이 '
            '안 들어온다" 가 되고 원인을 알 방법이 없다')

    def test_메시지마다_찍지_않는다(self):
        """초당 여러 번 오는 경로라 메시지마다 찍으면 로그를 덮는다."""
        src = inspect.getsource(_load().InputModule.on_message)
        i = src.index('if allowed is not None')
        assert 'logger.error' not in src[i:i + 200]


def test_기기_목록_헬퍼가_인자를_받는다():
    """예전에는 `current_app.input_dev` 에서 꺼내려 했다 — 그런 속성은 없다."""
    mod = _load()
    opts = mod.ecowitt_measurement_options('weather_station')
    assert ('tempf', ) == tuple(o[0] for o in opts)[:1]
    assert mod.ecowitt_measurement_options('없는기기') == []


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

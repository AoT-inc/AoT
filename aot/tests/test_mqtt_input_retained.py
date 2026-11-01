# coding=utf-8
"""MQTT 입력 — retained 메시지를 측정으로 저장하지 않는다 (2026-10-14).

## 사고

실내 미러 센서(MQTT_PAHO_JSON)의 마지막 실측은 07:29:32 KST 였다. 데몬이
08:03:08 에 재시작하자 브로커가 구독 직후 **retained 메시지**를 즉시 다시
보냈고(실측: 구독 후 0.04 초, retain=1, 페이로드 dateutc 는 22:29:32 UTC),
`on_message` 는 retained 여부를 보지 않고 수신 시각(`utcnow`)을 붙여 저장했다.
같은 값이 08:03:17 의 새 측정으로 기록됐고, 환경제어가 34분 묵은 값을
신선한 실측으로 읽어 김제 측창이 열리고 영양 보온커튼이 닫혔다.

## 고친 방식

`msg.retain` 이 참이면 저장하지 않는다. 상태를 retained 로만 내보내는 장치를
쓰는 설치를 위해 입력 옵션 `mqtt_store_retained`(기본 꺼짐)를 켜면 예전처럼
저장한다. 같은 패턴인 `mqtt_paho`·`ecowitt_mqtt` 도 같이 고쳤다.
"""
import importlib.util
import json
import pathlib
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_INPUTS = _ROOT / 'aot' / 'inputs'


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name + '_retained_under_test', _INPUTS / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeDev:
    unique_id = 'test-input'
    log_level_debug = False

    def __init__(self, extra=None):
        opts = {
            'ecowitt_device': 'weather_station', 'mqtt_hostname': 'localhost',
            'mqtt_port': 1883, 'mqtt_channel': 'gw/topic', 'mqtt_keepalive': 60,
            'mqtt_clientid': 't', 'mqtt_login': False, 'mqtt_use_tls': False,
            'mqtt_use_websockets': False, 'mqtt_username': '', 'mqtt_password': ''}
        opts.update(extra or {})
        self.custom_options = json.dumps(opts)


class _Chan:
    measurement = 'temperature'
    unit = 'C'
    conversion_id = None


def _msg(payload, retain, topic='gw/topic'):
    return types.SimpleNamespace(
        topic=topic, payload=payload.encode(), retain=retain)


# (모듈, 페이로드, 채널 옵션)
_CASES = {
    'mqtt_paho_json': ('{"temp": 8.1}', {'json_name': {0: 'temp'}}),
    'ecowitt_mqtt': ('{"temp": 8.1}', {'json_name': {0: 'temp'}}),
    'mqtt_paho': ('8.1', {'subscribe_topic': {0: 'gw/topic'}}),
}


def _build(name, store_retained=None, monkeypatch=None):
    """on_message 만 돌릴 수 있게 최소한으로 꾸민 입력과, 저장 호출 기록."""
    mod = _load(name)
    stored = []
    monkeypatch.setattr(
        mod, 'add_measurements_influxdb',
        lambda uid, meas, **kw: stored.append(meas))
    monkeypatch.setattr(
        mod, 'run_input_actions', lambda uid, msg, meas, lvl: ('', meas))

    inst = mod.InputModule(_FakeDev(), testing=True)
    if store_retained is not None:
        inst.mqtt_store_retained = store_retained
    inst.unique_id = 'test-input'
    inst.log_level_debug = False
    inst.channels_measurement = {0: _Chan()}
    inst.channels_conversion = {0: None}
    inst.options_channels = _CASES[name][1]
    if name != 'mqtt_paho':
        # jmespath 는 데몬 이미지에만 있다 — 최상위 키 조회만 하는 대역을 쓴다.
        inst.jmespath = types.SimpleNamespace(
            compile=lambda expr: types.SimpleNamespace(
                search=lambda data: data.get(expr)))
    if name == 'ecowitt_mqtt':
        inst._allowed_json_names = None
    return inst, stored


@pytest.mark.parametrize('name', sorted(_CASES))
class TestRetainedMessages:

    def test_retained_는_기본으로_저장하지_않는다(self, name, monkeypatch):
        inst, stored = _build(name, monkeypatch=monkeypatch)
        inst.on_message(None, None, _msg(_CASES[name][0], retain=1))
        assert stored == []

    def test_retained_를_건너뛰면_수신시각도_갱신하지_않는다(self, name, monkeypatch):
        """낡은 값이 '방금 수신' 으로 보이면 안 된다."""
        inst, stored = _build(name, monkeypatch=monkeypatch)
        inst.on_message(None, None, _msg(_CASES[name][0], retain=True))
        assert inst._comm_last_ts is None

    def test_retained_가_아니면_저장한다(self, name, monkeypatch):
        inst, stored = _build(name, monkeypatch=monkeypatch)
        inst.on_message(None, None, _msg(_CASES[name][0], retain=0))
        assert len(stored) == 1
        assert stored[0][0]['value'] == 8.1
        assert inst._comm_last_ts is not None

    def test_옵션을_켜면_retained_도_예전처럼_저장한다(self, name, monkeypatch):
        inst, stored = _build(name, store_retained=True, monkeypatch=monkeypatch)
        inst.on_message(None, None, _msg(_CASES[name][0], retain=1))
        assert len(stored) == 1
        assert stored[0][0]['value'] == 8.1

    def test_옵션_기본값은_꺼짐이고_저장된_설정에_없어도_꺼짐이다(self, name):
        mod = _load(name)
        opt = [o for o in mod.INPUT_INFORMATION['custom_options']
               if o['id'] == 'mqtt_store_retained']
        assert len(opt) == 1
        assert opt[0]['type'] == 'bool'
        assert opt[0]['default_value'] is False
        # 옵션이 생기기 전에 저장된 입력(custom_options 에 키 없음)도 꺼짐으로 읽힌다.
        inst = mod.InputModule(_FakeDev(), testing=True)
        inst.setup_custom_options(mod.INPUT_INFORMATION['custom_options'], _FakeDev())
        assert not inst.mqtt_store_retained
        inst = mod.InputModule(_FakeDev(), testing=True)
        dev = _FakeDev({'mqtt_store_retained': True})
        inst.setup_custom_options(mod.INPUT_INFORMATION['custom_options'], dev)
        assert inst.mqtt_store_retained is True

    def test_옵션이_init_에_선언돼_있다(self, name):
        inst = _load(name).InputModule(_FakeDev(), testing=True)
        assert hasattr(inst, 'mqtt_store_retained')


def test_옵션_문구가_ko_ja_로_번역된다():
    """lazy_gettext 문구가 .po/.mo 의 msgid 와 정확히 일치해야 번역이 걸린다."""
    from babel.support import Translations
    mod = _load('mqtt_paho_json')
    opt = [o for o in mod.INPUT_INFORMATION['custom_options']
           if o['id'] == 'mqtt_store_retained'][0]
    for lang in ('ko', 'ja'):
        tr = Translations.load(
            str(_ROOT / 'aot' / 'aot_flask' / 'translations'), [lang])
        for key in ('name', 'phrase'):
            src = str(opt[key])
            assert tr.gettext(src) != src, '%s %s 번역 없음' % (lang, key)

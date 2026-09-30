# coding=utf-8
"""
OpenWeatherMap (City/Coords, Current) 입력 — 요청 URL 스킴 (2026-09-25).

`api_key` 를 쿼리스트링에 실어 보내는 구간이라 스킴이 http:// 로 되돌아가면
키와 위치가 평문으로 노출된다. 이 테스트는 네트워크 없이 `initialize()` 가
만드는 URL 문자열만 검사한다.
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ.setdefault("ALEMBIC_RUNNING", "1")

from aot.inputs.openweathermap_weather import InputModule


def _make(testing_kwargs):
    module = InputModule(None, testing=True)
    module.api_key = 'TESTKEY'
    for key, value in testing_kwargs.items():
        setattr(module, key, value)
    module.initialize()
    return module


class TestOpenWeatherMapUsesHttps:
    def test_좌표_요청은_https(self):
        module = _make({'latitude': 35.0, 'longitude': 127.0})
        assert module.api_url.startswith('https://api.openweathermap.org/')
        assert not module.api_url.startswith('http://')

    def test_도시명_요청도_https(self):
        module = _make({'city': 'Seoul'})
        assert module.api_url.startswith('https://api.openweathermap.org/')
        assert not module.api_url.startswith('http://')

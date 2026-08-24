# coding=utf-8
"""
EXT-KR-01 키 해석과 실패 보고 (2026-08-24 실측으로 드러난 것).

운영자가 AI 라이브러리 화면에서 API 키를 넣었는데 동기화가 계속 0건이었다.
원인은 **키 저장소가 갈라져 있던 것**이다: 화면은 `config_json['api_key']` 에
쓰는데 이 클라이언트는 `GeoSetting.keys` 만 읽었다. nongsaro/pest 클라이언트는
처음부터 config 를 먼저 봤으니, 같은 화면에서 소스마다 동작이 달랐던 셈이다.

더 나쁜 것은 **아무도 틀렸다고 말해 주지 않았다**는 점이다 — 키가 없으면 캐시를
그대로 두고 빈 목록을 돌려줬고, sync 는 `status='ok', records=0` 을 남겼다.
'동작하는 척' 이다.

그리고 400 응답 한 번에 **운영 키가 평문으로 로그에 남았다**(requests 예외 문자열이
쿼리스트링을 통째로 담는다).
"""
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from aot.ai.context.ext import smartfarm_client as sc


class TestKeyRedaction(unittest.TestCase):

    def test_the_key_never_reaches_a_log_line(self):
        key = 'deadbeefdeadbeefdeadbeefdeadbeef'
        msg = "400 Client Error for url: https://api.example/x?serviceKey=%s&pageNo=1" % key
        out = sc._redact_key(msg, key)
        self.assertNotIn(key, out)
        self.assertIn('<SERVICE_KEY>', out)

    def test_url_encoded_form_is_redacted_too(self):
        """requests 는 인코딩된 URL 을 예외에 담는다 — 원문만 지우면 샌다."""
        key = 'ab+cd/ef=='
        from urllib.parse import quote_plus
        msg = "failed: serviceKey=%s&x=1" % quote_plus(key)
        self.assertNotIn(quote_plus(key), sc._redact_key(msg, key))

    def test_an_unknown_key_shape_is_still_scrubbed_by_pattern(self):
        """키 값을 몰라도 serviceKey= 뒤는 지운다 — 방어선이 둘이어야 한다."""
        out = sc._redact_key('boom serviceKey=whatever-this-is&z=2', '')
        self.assertNotIn('whatever-this-is', out)


class TestKeyResolutionAndFailureReporting(unittest.TestCase):

    def _sync(self, config, cached_rows=None, refresh=None):
        with mock.patch.object(sc.ExtSmartfarmClient, '_is_cache_fresh', return_value=False), \
             mock.patch.object(sc.ExtSmartfarmClient, '_read_cache', return_value=cached_rows or []), \
             mock.patch.object(sc.ExtSmartfarmClient, '_refresh_cache',
                               side_effect=refresh or (lambda *a, **k: None)) as ref, \
             mock.patch.object(sc, 'get_geo_setting_key', return_value=''):
            out = sc.ExtSmartfarmClient.sync(facility_id='f', config=config)
        return out, ref

    def test_the_key_typed_on_the_library_page_is_used(self):
        """화면이 쓰는 자리(config_json)를 클라이언트가 읽어야 한다."""
        seen = {}

        def _refresh(crop_type, api_key=''):
            seen['api_key'] = api_key

        self._sync({'crop_type': 'tomato', 'api_key': 'FROM-CONFIG'}, refresh=_refresh)
        self.assertEqual('FROM-CONFIG', seen.get('api_key'))

    def test_no_key_anywhere_is_an_error_not_a_quiet_zero(self):
        out, _ = self._sync({'crop_type': 'tomato'})
        self.assertIsInstance(out, dict)
        self.assertIn('error', out)
        self.assertIn('RDA_API_KEY', out['error'])

    def test_a_key_that_returns_nothing_is_reported_as_a_data_error(self):
        """키는 있는데 행이 안 오는 것과 키가 없는 것은 다른 사건이다."""
        out, _ = self._sync({'crop_type': 'tomato', 'api_key': 'K'})
        self.assertIsInstance(out, dict)
        self.assertIn('error', out)
        self.assertNotIn('RDA_API_KEY', out['error'])

    def test_missing_crop_type_is_refused_instead_of_defaulting_to_tomato(self):
        """설계 §9 가 지시한 하드코딩 제거. 조용히 tomato 로 대체하면 운영자는
        자기 작물 값인 줄 알고 남의 작물 설정값을 근거로 답을 듣는다."""
        out, _ = self._sync({'api_key': 'K'})
        self.assertIsInstance(out, dict)
        self.assertIn('crop_type', out['error'])

    def test_rows_present_still_return_records(self):
        rows = [{'crop_type': 'tomato', 'growth_stage': 'flowering',
                 'opt_temp_min': 18, 'opt_temp_max': 26}]
        out, _ = self._sync({'crop_type': 'tomato', 'api_key': 'K'}, cached_rows=rows)
        self.assertIsInstance(out, list)
        self.assertTrue(out)


if __name__ == '__main__':
    unittest.main()

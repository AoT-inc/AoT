# coding=utf-8
"""
D3 — 소스 카탈로그의 지역·주제 축.

왜 필요한가. 내장 피드 여섯은 **전부 한국 공공데이터**(RDA·농사로·NCPMS·
스마트팜코리아)인데, 화면도 도구도 그 사실을 말하지 않았다. AoT 는 22개 언어로
출시되므로 한국 밖 운영자에게 그 목록은 "고를 수 있는 것 전부" 처럼 보이고,
AI 는 어느 나라 사용자에게든 EXT-KR-01 을 권할 수 있었다.

여기서 고정하는 것은 라벨이 아니라 **정직성의 배선**이다: 모든 프리셋이 지역을
선언해야 하고, 도구는 그 값을 결과에서 계산해 실어야 한다(상수로 "한국 전용" 을
박아 두면 지역 불가지 프리셋이 하나라도 생기는 순간 거짓말이 된다).
"""
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from aot.aot_flask.routes_ai_library import LIBRARY_PRESETS

_VALID_REGIONS = {'KR', 'any'}


class TestLibraryCatalogAxes(unittest.TestCase):

    def test_every_preset_declares_a_region_and_topics(self):
        """새 프리셋을 추가하면서 축을 빠뜨리면 여기서 잡힌다 — 빠진 프리셋은
        화면의 어느 그룹에도 안 들어가 조용히 사라진다."""
        for key, p in LIBRARY_PRESETS.items():
            self.assertIn('region', p, '%s 에 region 이 없다' % key)
            self.assertIn(p['region'], _VALID_REGIONS,
                          '%s 의 region 이 %r 이다' % (key, p['region']))
            self.assertTrue(p.get('topics'), '%s 에 topics 가 없다' % key)

    def test_generic_types_are_region_agnostic(self):
        """document/web_url/rest_api/internal_query/google_drive 는 어느
        나라에서나 쓴다 — 여기에 지역이 붙으면 한국 밖 운영자에게 남는 선택이
        하나도 없어진다."""
        for key in ('document', 'web_url', 'rest_api', 'internal_query', 'google_drive'):
            self.assertEqual('any', LIBRARY_PRESETS[key]['region'], key)

    def test_at_least_one_source_is_available_outside_korea(self):
        """이 검사가 깨지면 한국 밖에서는 라이브러리를 채울 방법이 없다는 뜻이다."""
        non_kr = [k for k, p in LIBRARY_PRESETS.items() if p['region'] != 'KR']
        self.assertTrue(non_kr)

    def test_tool_reports_regions_computed_from_the_catalog(self):
        """상수가 아니라 계산값이어야 한다 — 지역 불가지 시스템 프리셋이
        생기면 도구의 안내도 저절로 따라와야 하고, 그때 사람이 문구를 고치는
        것을 잊어도 거짓말이 되지 않아야 한다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        out = AoTDataToolService.list_library_source_types_tool()
        self.assertIn('system_preset_regions', out)
        expected = sorted({p.get('region', 'any')
                           for p in LIBRARY_PRESETS.values() if p.get('is_system')})
        self.assertEqual(expected, out['system_preset_regions'])
        for entry in out['system_presets'] + out['custom_types']:
            self.assertIn('region', entry)
            self.assertIn('topics', entry)

    def test_tool_note_tells_the_model_what_to_do_outside_that_region(self):
        """지역을 실어 놓고 그것으로 무엇을 하라는 말이 없으면 모델은 그냥
        무시한다 — 실제로 예전 note 는 '둘 다 제시하라' 만 말했다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        note = AoTDataToolService.list_library_source_types_tool()['note']
        self.assertIn('region', note)
        self.assertIn('custom_types', note)
        self.assertIn('Korea', note)


if __name__ == '__main__':
    unittest.main()

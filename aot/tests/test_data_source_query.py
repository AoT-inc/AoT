# coding=utf-8
"""
연결된 데이터 API 를 **물어볼 때** 조회한다 (2026-08-25).

왜 필요했나. REST 소스는 등록할 때 정한 파라미터 하나로만 답할 수 있었다.
실측: 스마트팜코리아 노지 농가 1,650곳 중 라이브러리에 들어온 것은 **한 곳**
뿐이었고, "다른 농가는 어떤가" 는 새 소스를 등록해야 답이 됐다. 기대되는 동작은
LLM 이 사람 대신 그 API 를 질문할 때마다 두드리는 것이다.

여기서 고정하는 것은 API 응답 내용이 아니라 **경계**다: 무엇을 조회 가능하다고
내보내는가, 파라미터가 없을 때 어떻게 말하는가, 그리고 **잘렸다는 사실을
반드시 말하는가**. 마지막 것이 가장 중요하다 — 잘린 줄 모르면 모델은 그것을
전부로 읽고 "그런 농가는 없다" 같은 단정을 한다.

네트워크를 타지 않는다(fetch_operation 을 대역으로 바꾼다).
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from aot.ai.services import data_source_query_service as dsq


class _Src(object):
    def __init__(self, sid='s1', name='SFK'):
        self.source_id = sid
        self.source_name = name


_CFG = {'preset_key': 'smartfarmkorea', 'api_key': 'K', 'userId': 'PFS_CONFIG'}


def _with_source(rows=None, err=None, cfg=None):
    """소스 목록과 API 호출을 대역으로 세운다."""
    return (mock.patch.object(dsq, '_sources', return_value=[(_Src(), dict(cfg or _CFG))]),
            mock.patch('aot.ai.context.ext.smartfarmkorea_client.fetch_operation',
                       return_value=(rows, err)))


class TestQueryableSurface(unittest.TestCase):

    def test_only_sources_that_declare_operations_are_offered(self):
        """농사로·병해충 계열은 sync() 하나뿐이라 '이 파라미터로 이것만' 을
        표현할 수 없다. 조회 가능한 척 내보내면 모델이 부를 수 없는 것을
        부르려 든다."""
        self.assertNotIn('ext_nongsaro', dsq._QUERYABLE_PRESETS)
        self.assertNotIn('ext_pest', dsq._QUERYABLE_PRESETS)
        self.assertIn('smartfarmkorea', dsq._QUERYABLE_PRESETS)

    def test_describe_lists_each_operation_with_its_parameters(self):
        """모델은 이 목록만 보고 무엇을 물을 수 있는지 판단한다 — 필요한
        파라미터를 숨기면 추측해서 부른다."""
        with mock.patch.object(dsq, '_sources', return_value=[(_Src(), dict(_CFG))]):
            out = dsq.describe_all()
        self.assertEqual(1, len(out))
        ops = {o['operation']: o['params'] for o in out[0]['operations']}
        self.assertIn('cropping', ops)
        self.assertNotIn('serviceKey', ops['cropping'], 'API 키를 모델에게 요구하면 안 된다')
        self.assertIn('userId', ops['cropping'])
        self.assertIn('smartfarmkorea_lookup', out[0]['note'])


class TestQueryBoundaries(unittest.TestCase):

    def _run(self, rows=None, err=None, **kw):
        p1, p2 = _with_source(rows, err)
        with p1, p2:
            return dsq.query('s1', kw.pop('operation', 'cropping'), **kw)

    def test_it_says_how_many_rows_actually_existed(self):
        """가장 중요한 계약. 잘린 줄 모르면 모델은 이게 전부라고 읽는다."""
        payload, err = self._run(rows=[{'a': i} for i in range(100)], limit=3)
        self.assertIsNone(err)
        self.assertEqual(3, payload['returned'])
        self.assertEqual(100, payload['total_available'])
        self.assertIn('do NOT treat this as the complete set', payload['truncated'])

    def test_no_truncation_note_when_nothing_was_cut(self):
        payload, _ = self._run(rows=[{'a': 1}], limit=5)
        self.assertNotIn('truncated', payload)

    def test_limit_is_capped(self):
        payload, _ = self._run(rows=[{'a': i} for i in range(500)], limit=10 ** 6)
        self.assertLessEqual(payload['returned'], dsq._MAX_LIMIT)

    def test_a_missing_parameter_is_explained_not_guessed(self):
        cfg = dict(_CFG); cfg.pop('userId')
        p1, p2 = _with_source(rows=[{'a': 1}], cfg=cfg)
        with p1, p2:
            payload, err = dsq.query('s1', 'cropping')
        self.assertIsNone(payload)
        self.assertIn('userId', err)
        self.assertIn('smartfarmkorea_lookup', err)

    def test_a_value_already_on_the_source_is_used_as_the_default(self):
        """소스에 농가가 지정돼 있으면 모델이 매번 다시 적을 이유가 없다."""
        captured = {}

        def _fake(op, params, operations=None):
            captured.update(params)
            return [{'a': 1}], None

        with mock.patch.object(dsq, '_sources', return_value=[(_Src(), dict(_CFG))]), \
             mock.patch('aot.ai.context.ext.smartfarmkorea_client.fetch_operation', _fake):
            dsq.query('s1', 'cropping')
        self.assertEqual('PFS_CONFIG', captured['userId'])

    def test_an_explicit_parameter_beats_the_stored_one(self):
        captured = {}

        def _fake(op, params, operations=None):
            captured.update(params)
            return [{'a': 1}], None

        with mock.patch.object(dsq, '_sources', return_value=[(_Src(), dict(_CFG))]), \
             mock.patch('aot.ai.context.ext.smartfarmkorea_client.fetch_operation', _fake):
            dsq.query('s1', 'cropping', params={'userId': 'PFS_OTHER'})
        self.assertEqual('PFS_OTHER', captured['userId'])

    def test_unknown_operation_lists_the_real_ones(self):
        payload, err = self._run(operation='nope')
        self.assertIsNone(payload)
        self.assertIn('cropping', err)

    def test_a_source_without_a_key_says_so(self):
        cfg = dict(_CFG); cfg['api_key'] = ''
        p1, p2 = _with_source(rows=[{'a': 1}], cfg=cfg)
        with p1, p2:
            payload, err = dsq.query('s1', 'identity')
        self.assertIn('API key', err)

    def test_status_fields_and_empty_cells_are_dropped(self):
        payload, _ = self._run(rows=[{'statusCode': '00', 'statusMessage': 'NORMAL_CODE',
                                      'x': 1, 'y': '', 'z': 'NA'}])
        self.assertEqual([{'x': 1}], payload['rows'])

    def test_a_very_long_cell_is_shortened(self):
        payload, _ = self._run(rows=[{'names': 'x' * 5000}])
        self.assertLessEqual(len(payload['rows'][0]['names']), dsq._MAX_CELL + 1)


class TestDiscoveryIsOnePlace(unittest.TestCase):
    """표와 API 를 따로 찾게 하면 모델이 한쪽만 보고 '없다' 고 단정한다 —
    실측으로 이미 한 번 겪었다(2026-08-25)."""

    def test_list_lookup_sources_labels_each_kind(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as T
        with mock.patch.object(dsq, 'describe_all',
                               return_value=[{'source_id': 'a', 'label': 'API', 'operations': []}]), \
             mock.patch('aot.databases.models.AIContextSource') as _S:
            _S.query.filter_by.return_value.all.return_value = []
            out = T.list_lookup_sources()
        kinds = {s.get('kind') for s in out['sources']}
        self.assertEqual({'api'}, kinds)
        self.assertIn('query_data_source', out['note'])


if __name__ == '__main__':
    unittest.main()

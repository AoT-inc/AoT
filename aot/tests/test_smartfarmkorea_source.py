# coding=utf-8
"""
SmartFarmKorea (EXT-KR-04) source integration tests.

Covers:
  - URL construction for all 7 operations (cross-checked against the source
    page's own "샘플 URL" panel — see docs/design/ai-library-redesign.md, no
    separate design doc for this feature; the client module's docstring
    carries the reference).
  - fetch_and_format_selected() digest formatting.
  - context_source_service.sync_source()'s smartfarmkorea dispatch branch,
    with requests.get mocked (no live network call — this is a registered
    government API requiring a real service key neither test nor CI has).

In-memory sqlite, isolated app context — no live DB touched (see
feedback_never_test_against_live_db).
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.databases.models import AIContextSource, AIGlobalSettings, AIKnowledgeChunk
from aot.ai.context.ext import smartfarmkorea_client as sfk


def _make_test_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    Babel(app)
    return app


class TestSmartfarmkoreaUrlBuilding(unittest.TestCase):
    """Pure functions — no DB, no network. Every URL below was scraped
    verbatim from the source page's 샘플 URL panel (2026-07-19)."""

    def test_all_seven_operations_match_scraped_sample_urls(self):
        cases = [
            ('identity', {'serviceKey': 'SERVICE_KEY'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService/getIdentityDataList/SERVICE_KEY'),
            ('cropping', {'serviceKey': 'SERVICE_KEY', 'userId': 'PF_0000011'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService/getCroppingSeasonDataList/SERVICE_KEY/PF_0000011'),
            ('env', {'serviceKey': 'SERVICE_KEY', 'facilityId': 'PF_0006032_01', 'measDate': '2022-12-04',
                     'fldCode': 'FG', 'sectCode': 'EI', 'fatrCode': 'TI', 'itemCode': '080400'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService/getEnvDataList/'
             'SERVICE_KEY/PF_0006032_01/2022-12-04/FG/EI/TI/080400'),
            ('growth_strawberry', {'serviceKey': 'SERVICE_KEY', 'userId': 'PF_0001004', 'croppingSerlNo': '15',
                                    'startDate': '2015-11-29', 'endDate': '2015-11-29'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService/getStrbCultivateDataList/'
             'SERVICE_KEY/PF_0001004/15/2015-11-29/2015-11-29'),
            ('growth_mum', {'serviceKey': 'SK', 'userId': 'PF_0000122', 'croppingSerlNo': '276',
                             'startDate': '2017-03-12', 'endDate': '2017-03-12'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService/getMumCultivateDataList/'
             'SK/PF_0000122/276/2017-03-12/2017-03-12'),
            ('growth_melon', {'serviceKey': 'SK', 'userId': 'PF_0000476', 'croppingSerlNo': '272',
                               'startDate': '2017-02-12', 'endDate': '2017-02-12'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService/getFruitCultivateDataList/'
             'SK/PF_0000476/272/2017-02-12/2017-02-12'),
            ('growth_other', {'serviceKey': 'SK', 'userId': 'PF_0000021', 'croppingSerlNo': '4',
                               'startDate': '2015-12-06', 'endDate': '2015-12-06'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService/getCultivateDataList/'
             'SK/PF_0000021/4/2015-12-06/2015-12-06'),
        ]
        self.assertEqual(len(cases), len(sfk.OPERATIONS))  # every operation covered
        for op_key, params, expected in cases:
            self.assertEqual(sfk.build_url(op_key, params), expected, msg=op_key)

    def test_all_outdoor_operations_match_scraped_sample_urls(self):
        """OUTDOOR_OPERATIONS (EXT-KR-05, menuId=M11040302) — every URL below
        was scraped verbatim from that page's own 샘플 URL panel (2026-07-19),
        same verification method as the facility dataset above."""
        cases = [
            ('identity', {'serviceKey': 'SERVICE_KEY'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/OutdoorFarmRest/getIdentityDataList/SERVICE_KEY'),
            ('cropping', {'serviceKey': 'SERVICE_KEY', 'userId': 'PF_0000006'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/OutdoorFarmRest/getCroppingSeasonDataList/SERVICE_KEY/PF_0000006'),
            ('env', {'serviceKey': 'SERVICE_KEY', 'facilityId': 'PF_0006001_01', 'measDate': '2022-12-06',
                     'fldCode': 'FG', 'sectCode': 'NT', 'fatrCode': 'EO', 'itemCode': '065900'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/OutdoorFarmRest/getEnvDataList/'
             'SERVICE_KEY/PF_0006001_01/2022-12-06/FG/NT/EO/065900'),
            ('growth_garlic', {'serviceKey': 'SERVICE_KEY', 'userId': 'PF_0020437', 'croppingSerlNo': '3721',
                                'startDate': '2020-10-14', 'endDate': '2020-10-14'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/OutdoorFarmRest/getGarlicCultivateDataList/'
             'SERVICE_KEY/PF_0020437/3721/2020-10-14/2020-10-14'),
            ('growth_onion', {'serviceKey': 'SERVICE_KEY', 'userId': 'PF_0020507', 'croppingSerlNo': '3664',
                               'startDate': '2020-10-14', 'endDate': '2020-10-14'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/OutdoorFarmRest/getOnionCultivateDataList/'
             'SERVICE_KEY/PF_0020507/3664/2020-10-14/2020-10-14'),
            ('growth_blueberry', {'serviceKey': 'SERVICE_KEY', 'userId': 'PF_0020477', 'croppingSerlNo': '3587',
                                   'startDate': '2020-10-01', 'endDate': '2020-10-01'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/OutdoorFarmRest/getBlueberryCultivateDataList/'
             'SERVICE_KEY/PF_0020477/3587/2020-10-01/2020-10-01'),
            # 2026-08-24 추가. 실호출로 데이터가 나오는 것을 확인한 둘이다
            # (품목코드가 맞는 농가를 골라서 재야 한다 — 무=110100, 배추=100100.
            # 클라이언트의 해당 항목 주석 참조).
            ('growth_radish', {'serviceKey': 'SERVICE_KEY', 'userId': 'PF_0002739', 'croppingSerlNo': '3540',
                               'startDate': '2018-07-20', 'endDate': '2018-11-30'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/OutdoorFarmRest/getRadishCultivateDataList/'
             'SERVICE_KEY/PF_0002739/3540/2018-07-20/2018-11-30'),
            ('growth_cabbage', {'serviceKey': 'SERVICE_KEY', 'userId': 'PF_0002739', 'croppingSerlNo': '3540',
                                'startDate': '2018-07-20', 'endDate': '2018-11-30'},
             'http://www.smartfarmkorea.net/Agree_WS/webservices/OutdoorFarmRest/getCabbageCultivateDataList/'
             'SERVICE_KEY/PF_0002739/3540/2018-07-20/2018-11-30'),
        ]
        self.assertEqual(len(cases), len(sfk.OUTDOOR_OPERATIONS))  # every operation covered
        for op_key, params, expected in cases:
            self.assertEqual(sfk.build_url(op_key, params, operations=sfk.OUTDOOR_OPERATIONS), expected, msg=op_key)

    def test_outdoor_and_facility_identity_urls_differ_in_base_only(self):
        """Same op_key ('identity') exists in both dicts with different
        underlying farm populations — confirms the two dicts never cross-wire
        their base URL despite the key collision the module docstring warns
        about."""
        params = {'serviceKey': 'X'}
        facility_url = sfk.build_url('identity', params)
        outdoor_url = sfk.build_url('identity', params, operations=sfk.OUTDOOR_OPERATIONS)
        self.assertIn('ProvideRestService', facility_url)
        self.assertIn('OutdoorFarmRest', outdoor_url)
        self.assertNotEqual(facility_url, outdoor_url)

    def test_format_record_translates_outdoor_numeric_suffix_fields(self):
        """growth_blueberry's fruitWeight1..10/sugarContent1..10 need the
        numeric-suffix fallback in _field_label(), not an exact-key lookup."""
        rec = {
            'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'userId': 'PF_0020477',
            'fruitWeight1': '3.75', 'fruitWeight2': '3.80', 'sugarContent1': '12.4',
            'suckerNum': '5.0', 'soilPh': '4.0',
        }
        formatted = sfk._format_record(rec)
        self.assertIn('과중(g)1=3.75', formatted)
        self.assertIn('과중(g)2=3.80', formatted)
        self.assertIn('당도(Brix)1=12.4', formatted)
        self.assertIn('흡지수(개)=5.0', formatted)
        self.assertIn('토양PH=4.0', formatted)

    def test_all_eleven_livestock_operations_match_scraped_sample_urls(self):
        """LIVESTOCK_OPERATIONS (EXT-KR-06, menuId=M11040303) — every URL
        below was scraped verbatim from that page's own 샘플 URL panel
        (2026-07-19). Unlike facility/outdoor, every operation shares the
        SAME 3 params (serviceKey/startDate/endDate) — confirmed by reading
        all 11 request-parameter tables, not assumed from one sample."""
        cases = [
            ('dairy_inspection', 'getInspctDataList', 'SERVICE_KEY', '20200717', '20200717'),
            ('dairy_robot_milking', 'getMilkingDataList', 'SERVICE_KEY', '20200813', '20200813'),
            ('dairy_ict_milking', 'getIctDataList', 'SERVICE_KEY', '20210925', '20210925'),
            ('dairy_ict_group_feed', 'getIctMkFdDataList', 'SERVICE_KEY', '20200711', '20200711'),
            ('dairy_robot_group_feed', 'getRoboMkFdDataList', 'SERVICE_KEY', '20210610', '20210610'),
            ('swine_sow', 'getSowDataList', 'SERVICE_KEY', '20200122', '20200122'),
            ('swine_lactating_feed', 'getMoPigDataList', 'SERVICE_KEY', '20200827', '20200827'),
            ('swine_lactating_feed_breeding', 'getMoPigFdBrdDataList', 'SERVICE_KEY', '20220601', '20220601'),
            ('poultry_daily', 'getLayingDataList', 'SERVICE_KEY', '20230418', '20230418'),
            ('hanwoo_epd', 'getCowDataList', 'SERVICE_KEY', '20230201', '20230201'),
            ('hanwoo_grading', 'getShipmntDataList', 'SERVICE_KEY', '20191021', '20191021'),
        ]
        self.assertEqual(len(cases), len(sfk.LIVESTOCK_OPERATIONS))  # every operation covered
        for op_key, path, service_key, start, end in cases:
            expected = (
                f"http://www.smartfarmkorea.net/Agree_WS/webservices/StockRestService/"
                f"{path}/{service_key}/{start}/{end}"
            )
            params = {'serviceKey': service_key, 'startDate': start, 'endDate': end}
            self.assertEqual(
                sfk.build_url(op_key, params, operations=sfk.LIVESTOCK_OPERATIONS), expected, msg=op_key,
            )

    def test_livestock_operations_need_no_discovery_chain(self):
        """Unlike facility/outdoor (userId/facilityId/croppingSerlNo come
        from a prior 'identity'/'cropping' call), every livestock op's
        non-serviceKey params are just startDate/endDate — no 'identity' key
        exists at all in this dict."""
        self.assertNotIn('identity', sfk.LIVESTOCK_OPERATIONS)
        for op_key, op in sfk.LIVESTOCK_OPERATIONS.items():
            self.assertEqual(set(op['params']), {'serviceKey', 'startDate', 'endDate'}, msg=op_key)

    def test_format_record_uses_livestock_labels_not_crop_labels(self):
        """'itemCode' means 품목코드(crop) in facility/outdoor but
        축종코드(species) in livestock — the dataset_labels override must win
        without touching the global crop-dataset label."""
        rec = {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'farmId': '0020261', 'itemCode': 'D00'}
        formatted_default = sfk._format_record(rec)
        self.assertIn('품목코드=D00', formatted_default)
        formatted_livestock = sfk._format_record(rec, dataset_labels=sfk._LIVESTOCK_FIELD_LABELS)
        self.assertIn('농장ID=0020261', formatted_livestock)
        self.assertIn('축종코드=D00', formatted_livestock)
        self.assertNotIn('품목코드', formatted_livestock)

    def test_missing_required_param_raises_with_all_missing_named(self):
        with self.assertRaises(ValueError) as ctx:
            sfk.build_url('env', {'serviceKey': 'X', 'facilityId': ''})
        msg = str(ctx.exception)
        for p in ('facilityId', 'measDate', 'fldCode', 'sectCode', 'fatrCode', 'itemCode'):
            self.assertIn(p, msg)

    def test_missing_param_absent_from_dict_treated_same_as_empty(self):
        """build_url must not KeyError on a partial params dict — same error
        path as an empty string, not a second exception type to catch."""
        with self.assertRaises(ValueError):
            sfk.build_url('cropping', {'serviceKey': 'X'})  # userId absent entirely

    def test_format_record_drops_status_fields_and_translates_labels(self):
        rec = {
            'statusCode': '00', 'statusMessage': 'NORMAL_CODE',
            'facilityId': 'PF_0006032_01', 'measDate': '2022-12-04 00:00:00',
            'itemCode': '080400', 'senVal': '11.00',
        }
        formatted = sfk._format_record(rec)
        self.assertNotIn('statusCode', formatted)
        self.assertNotIn('NORMAL_CODE', formatted)
        self.assertIn('시설ID=PF_0006032_01', formatted)
        self.assertIn('측정값=11.00', formatted)

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_fetch_operation_rejects_non_normal_status(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{'statusCode': '99', 'statusMessage': 'INVALID_SERVICE_KEY'}]
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        records, err = sfk.fetch_operation('identity', {'serviceKey': 'BAD'})
        self.assertIsNone(records)
        self.assertIn('INVALID_SERVICE_KEY', err)

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_fetch_and_format_selected_multi_op_digest(self, mock_get):
        def side_effect(url, timeout):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if 'getIdentityDataList' in url:
                resp.json.return_value = [
                    {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'userId': 'PFS_0000001',
                     'facilityId': 'PFS_0000001_01', 'addressName': '경상남도 사천시', 'itemCode': '080300'},
                ]
            elif 'getEnvDataList' in url:
                resp.json.return_value = [
                    {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'facilityId': 'PF_0006032_01',
                     'measDate': '2022-12-04 00:00:00', 'senVal': '11.00'},
                ]
            else:
                resp.json.return_value = []
            return resp
        mock_get.side_effect = side_effect

        config = {
            'operations': ['identity', 'env'],
            'api_key': 'SK', 'facilityId': 'PF_0006032_01', 'measDate': '2022-12-04',
            'fldCode': 'FG', 'sectCode': 'EI', 'fatrCode': 'TI', 'itemCode': '080400',
        }
        text, tags, errors = sfk.fetch_and_format_selected(config)
        self.assertIn('아이덴티티 정보', text)
        self.assertIn('환경 정보', text)
        self.assertIn('경상남도 사천시', text)
        self.assertEqual(set(tags), {'아이덴티티', 'identity', '환경', 'env'})
        self.assertEqual(errors, [])

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_partial_failure_still_yields_text_for_the_operation_that_succeeded(self, mock_get):
        def side_effect(url, timeout):
            resp = MagicMock()
            if 'getIdentityDataList' in url:
                resp.raise_for_status.return_value = None
                resp.json.return_value = [{'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'userId': 'X'}]
                return resp
            raise requests.exceptions.ConnectionError('network down')
        mock_get.side_effect = side_effect

        text, tags, errors = sfk.fetch_and_format_selected({
            'operations': ['identity', 'cropping'], 'api_key': 'SK', 'userId': 'PF_1',
        })
        self.assertIn('아이덴티티 정보', text)
        self.assertTrue(any('cropping' in e for e in errors))

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_fetch_and_format_selected_livestock_uses_livestock_labels(self, mock_get):
        """End-to-end through fetch_and_format_selected (not just
        _format_record directly) — confirms LIVESTOCK_OPERATIONS routes to
        _LIVESTOCK_FIELD_LABELS automatically via the `operations is
        LIVESTOCK_OPERATIONS` identity check in the function itself."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'farmCode': 'PF_0020151',
             'breedNm': '로만화이트라이트', 'totalCo': '64'},
        ]
        mock_get.return_value = resp

        config = {'operations': ['poultry_daily'], 'api_key': 'SK', 'startDate': '20230418', 'endDate': '20230418'}
        text, tags, errors = sfk.fetch_and_format_selected(config, operations=sfk.LIVESTOCK_OPERATIONS)
        self.assertEqual(errors, [])
        self.assertIn('일일생산 정보', text)
        self.assertIn('농장ID=PF_0020151', text)
        self.assertIn('품종명=로만화이트라이트', text)
        self.assertEqual(set(tags), {'양계', 'poultry_daily'})


class TestSmartfarmkoreaDiscovery(unittest.TestCase):
    """Phase 1 cascading-picker backend — resolve_farms/resolve_seasons turn
    identity/cropping into human-readable option lists. Mocks the API."""

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_resolve_farms_shapes_identity_into_picker_options(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'userId': 'PFS_0000001',
             'facilityId': 'PFS_0000001_01', 'addressName': '경상남도 사천시', 'itemCode': '080300'},
            {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'userId': '',  # skipped: no userId
             'facilityId': 'X', 'addressName': 'Y', 'itemCode': 'Z'},
        ]
        mock_get.return_value = resp
        farms, err = sfk.resolve_farms('SK', operations=sfk.OPERATIONS)
        self.assertIsNone(err)
        self.assertEqual(len(farms), 1)  # the empty-userId row is dropped
        self.assertEqual(farms[0]['userId'], 'PFS_0000001')
        self.assertEqual(farms[0]['facilityId'], 'PFS_0000001_01')
        self.assertIn('경상남도 사천시', farms[0]['label'])
        self.assertIn('PFS_0000001', farms[0]['label'])

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_resolve_seasons_coerces_numeric_croppingSerlNo(self, mock_get):
        """REGRESSION: the live API returns croppingSerlNo as a JSON NUMBER
        (79, not "79"); a bare .strip() AttributeErrors. resolve_seasons must
        coerce to str first (found live 2026-07-19)."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {'statusCode': '00', 'statusMessage': 'NORMAL_CODE',
             'croppingSerlNo': 79, 'croppingSeasonName': '데프니스_20150902', 'itemCode': '080300'},
            {'statusCode': '00', 'statusMessage': 'NORMAL_CODE',
             'croppingSerlNo': 4940, 'croppingSeasonName': '2021년 토마토', 'itemCode': '080300'},
        ]
        mock_get.return_value = resp
        seasons, err = sfk.resolve_seasons('SK', 'PFS_0000001', operations=sfk.OPERATIONS)
        self.assertIsNone(err)
        self.assertEqual([s['croppingSerlNo'] for s in seasons], ['79', '4940'])  # coerced to str
        self.assertEqual(seasons[0]['label'], '데프니스_20150902')  # human-readable, not the code

    def test_resolve_farms_no_op_for_dataset_without_identity(self):
        farms, err = sfk.resolve_farms('SK', operations=sfk.LIVESTOCK_OPERATIONS)
        self.assertIsNone(farms)
        self.assertIn('identity', err)

    def test_resolve_seasons_requires_user_id(self):
        seasons, err = sfk.resolve_seasons('SK', '', operations=sfk.OPERATIONS)
        self.assertIsNone(seasons)
        self.assertIn('userId', err)

    def test_operations_for_preset_maps_all_three_datasets(self):
        self.assertIs(sfk.operations_for_preset('smartfarmkorea'), sfk.OPERATIONS)
        self.assertIs(sfk.operations_for_preset('smartfarmkorea_outdoor'), sfk.OUTDOOR_OPERATIONS)
        self.assertIs(sfk.operations_for_preset('smartfarmkorea_livestock'), sfk.LIVESTOCK_OPERATIONS)
        self.assertIs(sfk.operations_for_preset(''), sfk.OPERATIONS)  # unknown → facility default


class TestSmartfarmkoreaSyncDispatch(unittest.TestCase):
    """sync_source()'s smartfarmkorea branch — verifies chunks land as
    provenance='external_authority' (not the AIContextRecord shred bridge)
    and that tags/attribution are set correctly."""

    def setUp(self):
        self.app = _make_test_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        AIGlobalSettings(id=1, knowledge_digest_enabled=True).save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _make_source(self, operations, extra_config=None):
        config = {'preset_key': 'smartfarmkorea', 'api_key': 'SK', 'operations': operations}
        config.update(extra_config or {})
        source = AIContextSource(
            facility_id='default', source_name='SmartFarmKorea Big Data (EXT-KR-04)',
            source_type='rest_api', parameter_name='smartfarmkorea.test',
            config_json=json.dumps(config), is_active=True, is_enabled=True,
        )
        source.save()
        return source

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_sync_writes_knowledge_chunk_not_context_record(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'userId': 'PFS_0000001',
             'facilityId': 'PFS_0000001_01', 'addressName': '경상남도 사천시', 'itemCode': '080300'},
        ]
        mock_get.return_value = resp

        source = self._make_source(['identity'])
        from aot.ai.services.context_source_service import sync_source
        from aot.databases.models import AIContextRecord
        messages = sync_source(source.source_id)

        self.assertEqual(messages['error'], [])
        self.assertEqual(AIContextRecord.query.count(), 0)  # no shred bridge for this preset
        chunks = AIKnowledgeChunk.query.filter_by(source_id=source.source_id).all()
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].provenance, 'external_authority')
        self.assertIn('아이덴티티', (chunks[0].tags or '').split(','))
        self.assertIn('SmartFarmKorea', chunks[0].attribution)
        self.assertIn('경상남도 사천시', chunks[0].digest_text)

    def test_sync_errors_cleanly_when_no_operations_selected(self):
        source = self._make_source([])
        from aot.ai.services.context_source_service import sync_source
        messages = sync_source(source.source_id)
        self.assertTrue(messages['error'])
        self.assertEqual(AIKnowledgeChunk.query.count(), 0)

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_sync_result_is_searchable_and_tagged_by_category(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'facilityId': 'PF_1',
             'measDate': '2022-12-04', 'senVal': '쥬키니SFK토큰11.00'},
        ]
        mock_get.return_value = resp

        source = self._make_source(
            ['env'],
            {'facilityId': 'PF_1', 'measDate': '2022-12-04', 'fldCode': 'FG',
             'sectCode': 'EI', 'fatrCode': 'TI', 'itemCode': '080400'},
        )
        from aot.ai.services.context_source_service import sync_source
        from aot.ai.services import knowledge_search
        knowledge_search._library_sections = []
        knowledge_search._library_stamp = None
        sync_source(source.source_id)

        hits = [h for h in knowledge_search.search('쥬키니SFK토큰') if h['origin'] == 'library']
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['provenance'], 'external_authority')
        self.assertIn('env', hits[0]['tags'])

        # tag-scoped: an unrelated tag filter must exclude it
        excluded = [h for h in knowledge_search.search('쥬키니SFK토큰', tags=['growth_strawberry'])
                    if h['origin'] == 'library']
        self.assertEqual(len(excluded), 0)

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_outdoor_preset_dispatches_to_outdoor_operations_not_facility(self, mock_get):
        """smartfarmkorea_outdoor must hit OutdoorFarmRest and route through
        the same chunk pipeline as smartfarmkorea (provenance/tags), proving
        the preset_key -> operations dict selection in
        context_source_service.sync_source() actually took effect."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'userId': 'PF_0000006',
             'facilityId': 'PF_0006001_01', 'addressName': '강원특별자치도 태백시', 'itemCode': '100100'},
        ]
        mock_get.return_value = resp

        config = {'preset_key': 'smartfarmkorea_outdoor', 'api_key': 'SK', 'operations': ['identity']}
        source = AIContextSource(
            facility_id='default', source_name='SmartFarmKorea Big Data — Outdoor Field (EXT-KR-05)',
            source_type='rest_api', parameter_name='smartfarmkorea_outdoor.test',
            config_json=json.dumps(config), is_active=True, is_enabled=True,
        )
        source.save()

        from aot.ai.services.context_source_service import sync_source
        messages = sync_source(source.source_id)

        self.assertEqual(messages['error'], [])
        called_url = mock_get.call_args[0][0]
        self.assertIn('OutdoorFarmRest', called_url)
        self.assertNotIn('ProvideRestService', called_url)

        chunks = AIKnowledgeChunk.query.filter_by(source_id=source.source_id).all()
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].provenance, 'external_authority')
        self.assertIn('강원특별자치도 태백시', chunks[0].digest_text)

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_livestock_preset_dispatches_to_livestock_operations(self, mock_get):
        """smartfarmkorea_livestock must hit StockRestService, use only
        startDate/endDate (no userId/facilityId needed), and use the
        livestock field-label override (품종명, not a crop label)."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'farmCode': 'PF_0020151',
             'breedNm': '로만화이트라이트'},
        ]
        mock_get.return_value = resp

        config = {
            'preset_key': 'smartfarmkorea_livestock', 'api_key': 'SK', 'operations': ['poultry_daily'],
            'startDate': '20230418', 'endDate': '20230418',
        }
        source = AIContextSource(
            facility_id='default', source_name='SmartFarmKorea Big Data — Livestock (EXT-KR-06)',
            source_type='rest_api', parameter_name='smartfarmkorea_livestock.test',
            config_json=json.dumps(config), is_active=True, is_enabled=True,
        )
        source.save()

        from aot.ai.services.context_source_service import sync_source
        messages = sync_source(source.source_id)

        self.assertEqual(messages['error'], [])
        called_url = mock_get.call_args[0][0]
        self.assertIn('StockRestService', called_url)
        self.assertIn('/getLayingDataList/SK/20230418/20230418', called_url)

        chunks = AIKnowledgeChunk.query.filter_by(source_id=source.source_id).all()
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].provenance, 'external_authority')
        self.assertIn('농장ID=PF_0020151', chunks[0].digest_text)
        self.assertIn('품종명=로만화이트라이트', chunks[0].digest_text)


class TestSmartfarmkoreaAITools(unittest.TestCase):
    """Phase 2 AI tools — smartfarmkorea_lookup (read) + configure_library_source
    (mutating, approval-gated). These wrap the discovery primitive + the
    source-config write so the AI can register a source end-to-end."""

    def setUp(self):
        self.app = _make_test_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        AIGlobalSettings(id=1, knowledge_digest_enabled=True).save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_lookup_tool_filters_and_caps(self, mock_get):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as T
        rows = [{'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'userId': f'PF_{i:04d}',
                 'facilityId': f'PF_{i:04d}_01', 'addressName': ('경상남도 사천시' if i % 2 else '전북 김제시'),
                 'itemCode': '080300'} for i in range(50)]
        resp = MagicMock(); resp.raise_for_status.return_value = None; resp.json.return_value = rows
        mock_get.return_value = resp
        out = T.smartfarmkorea_lookup_tool(dataset='smartfarmkorea', api_key='SK', mode='farms', query='사천', limit=5)
        self.assertEqual(out['total'], 50)
        self.assertEqual(out['returned'], 5)          # capped
        self.assertTrue(all('사천' in it['label'] for it in out['items']))  # filtered

    def test_list_library_source_types_returns_full_catalog(self):
        """REGRESSION: the AI only ever recommended SmartFarmKorea because it
        had no way to enumerate the other source types. This tool must return
        BOTH the external-API presets AND the custom types."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as T
        r = T.list_library_source_types_tool()
        sys_keys = {e['key'] for e in r['system_presets']}
        cust_keys = {e['key'] for e in r['custom_types']}
        # external presets beyond SmartFarmKorea are present
        self.assertTrue({'ext_smartfarm', 'ext_nongsaro', 'ext_pest'} <= sys_keys)
        self.assertTrue({'smartfarmkorea', 'smartfarmkorea_outdoor', 'smartfarmkorea_livestock'} <= sys_keys)
        # custom (user-owned data) types are present — subset check (not exact
        # equality) so this doesn't need updating every time a new custom
        # type is added (e.g. google_drive, added 2026-07-21).
        self.assertTrue({'rest_api', 'document', 'web_url', 'internal_query'} <= cust_keys)
        # SmartFarmKorea is not the only thing on offer
        self.assertGreater(len(sys_keys), 3)

    def test_lookup_tool_livestock_has_no_discovery(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as T
        out = T.smartfarmkorea_lookup_tool(dataset='smartfarmkorea_livestock', api_key='SK', mode='farms')
        self.assertIn('identity', out['error'])

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_lookup_tool_crop_filter_excludes_other_crops(self, mock_get):
        """crop='딸기' must return only 딸기 farms — the fix for the AI
        proposing a 토마토 farm (itemCode 080300) for a 딸기 request. Labels
        also show the crop NAME, not the raw code."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as T
        rows = [
            {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'userId': 'PF_A',
             'facilityId': 'PF_A_01', 'addressName': '경상남도 사천시', 'itemCode': '080400'},  # 딸기
            {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'userId': 'PF_B',
             'facilityId': 'PF_B_01', 'addressName': '경상남도 사천시', 'itemCode': '080300'},  # 토마토
        ]
        resp = MagicMock(); resp.raise_for_status.return_value = None; resp.json.return_value = rows
        mock_get.return_value = resp
        out = T.smartfarmkorea_lookup_tool(dataset='smartfarmkorea', api_key='SK', mode='farms', crop='딸기')
        self.assertEqual(out['returned'], 1)
        self.assertEqual(out['items'][0]['userId'], 'PF_A')
        self.assertEqual(out['items'][0]['crop'], '딸기')
        self.assertIn('딸기', out['items'][0]['label'])       # crop name, not '080400'
        self.assertNotIn('080400', out['items'][0]['label'])

    def test_crop_name_maps_verified_codes_and_falls_back(self):
        self.assertEqual(sfk.crop_name('080400'), '딸기')
        self.assertEqual(sfk.crop_name('080300'), '토마토')
        self.assertEqual(sfk.crop_name('065900'), '블루베리')
        self.assertEqual(sfk.crop_name('999999'), '999999')   # unmapped → raw code
        self.assertEqual(sfk.crop_name(None), '')

    def test_configure_tool_rejects_non_sfk_preset(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as T
        out = T.configure_library_source_tool(preset_key='document', api_key='SK', operations=['x'])
        self.assertIn('preset_key must be one of', out['error'])

    def test_configure_tool_reports_missing_params_per_operation(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as T
        out = T.configure_library_source_tool(
            preset_key='smartfarmkorea', api_key='SK', operations=['growth_strawberry'])
        self.assertIn('missing required params', out['error'])
        miss = out['details'][0]['missing']
        for p in ('userId', 'croppingSerlNo', 'startDate', 'endDate'):
            self.assertIn(p, miss)

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_configure_tool_creates_activates_and_syncs(self, mock_get):
        """The AI-driven one-shot: create source + activate + sync in one call.
        Confirms the resolved codes land in config_json and a chunk is written."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as T
        resp = MagicMock(); resp.raise_for_status.return_value = None
        resp.json.return_value = [
            {'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'croppingSerlNo': 4940,
             'croppingSeasonName': '2021년 토마토', 'itemCode': '080300'},
        ]
        mock_get.return_value = resp
        out = T.configure_library_source_tool(
            preset_key='smartfarmkorea', api_key='SK', operations=['cropping'],
            userId='PFS_0000001', facilityId='PFS_0000001_01', itemCode='080300',
            farm_label='경상남도 사천시 (PFS_0000001)')
        self.assertEqual(out['status'], 'created')
        self.assertTrue(out['activated'])
        self.assertTrue(out['synced'])

        src = AIContextSource.query.filter_by(source_id=out['source_id']).first()
        cfg = json.loads(src.config_json)
        self.assertEqual(cfg['userId'], 'PFS_0000001')           # resolved id persisted
        self.assertEqual(cfg['_farmLabel'], '경상남도 사천시 (PFS_0000001)')  # human label persisted
        self.assertTrue(bool(src.is_enabled))                    # activated
        chunks = AIKnowledgeChunk.query.filter_by(source_id=out['source_id']).all()
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].provenance, 'external_authority')


if __name__ == '__main__':
    unittest.main()

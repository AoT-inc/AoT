# coding=utf-8
"""출처 일반화(재설계 PR 8, 2026-11-03) — API 키는 설정(AI 라이브러리) 화면에서만, AI 는 source_id 로 가리킨다.

- 안쪽 `smartfarmkorea_lookup`·`configure_library_source` 는 `api_key` 인자를 받지 않는다(받으면 거절). 키는 출처에 저장된 것을 쓴다.
- 새 출처를 AI 가 만들면 키가 없어 **비활성**이고 사용자가 화면에서 키를 넣어야 켜진다. 기존 `source_id` 는 키를 지킨 채 다시 설정.
- 탐색(농가·작기 찾기)은 출처의 동작이다: `records.data_source(operation='farms'|'seasons')`.
- 값 이름은 프리셋의 동작 표가 정한다(코드에 박지 않는다). 도메인 op 는 `configure.library_source` 하나.
"""
import json
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.databases.models import AIContextSource, AIGlobalSettings


def _app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    Babel(app)
    return app


class _Db(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        AIGlobalSettings(id=1, knowledge_digest_enabled=True).save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def source(self, preset='smartfarmkorea', key='SK', enabled=False, **cfg):
        config = dict({'preset_key': preset, 'operations': ['identity']}, **cfg)
        if key:
            config['api_key'] = key
        src = AIContextSource(facility_id='default', source_name=preset, source_type='rest_api',
                              parameter_name='%s.%s' % (preset, len(AIContextSource.query.all())),
                              config_json=json.dumps(config), sync_interval_min=1440,
                              is_active=True, is_enabled=enabled)
        db.session.add(src)
        db.session.commit()
        return src


def _T():
    from aot.tools.aot_data_tool_service import AoTDataToolService
    return AoTDataToolService


class NoKeyArgumentTest(_Db):

    def test_lookup_refuses_a_key_argument(self):
        self.source()
        out = _T().smartfarmkorea_lookup_tool(dataset='smartfarmkorea', mode='farms', api_key='SK')
        self.assertIn('AI Library', out['error'])

    def test_configure_refuses_a_key_argument_and_changes_nothing(self):
        out = _T().configure_library_source_tool(preset_key='smartfarmkorea', operations=['identity'],
                                                 api_key='SK')
        self.assertIn('AI Library', out['error'])
        self.assertEqual(0, AIContextSource.query.count())

    def test_the_catalog_has_no_key_argument_left(self):
        from aot.tools.domain.contract import catalog
        for name in ('configure_library_source',):     # smartfarmkorea_lookup 은 26-11 5단계에서 지웠다
            props = catalog()[name]['inputSchema']['properties']
            self.assertNotIn('api_key', props, name)
        self.assertIn('params', catalog()['configure_library_source']['inputSchema']['properties'])

    def test_no_domain_op_takes_a_key(self):
        from aot.tools.domain.registry_data import OPS
        for o in OPS:
            self.assertNotIn('api_key', set(o.args) | set(o.extra_args), '%s.%s' % (o.tool, o.op))


class StoredKeyLookupTest(_Db):

    def _farms(self):
        rows = [{'statusCode': '00', 'statusMessage': 'NORMAL_CODE', 'userId': 'PF_A', 'facilityId': 'PF_A_01',
                 'addressName': '경상남도 사천시', 'itemCode': '080400'}]
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = rows
        return resp

    def test_without_a_registered_source_it_points_at_the_settings_page(self):
        out = _T().smartfarmkorea_lookup_tool(dataset='smartfarmkorea', mode='farms')
        self.assertIn('AI Library page', out['error'])

    def test_a_source_without_a_key_asks_the_user_for_it(self):
        self.source(key=None)
        out = _T().smartfarmkorea_lookup_tool(dataset='smartfarmkorea', mode='farms')
        self.assertIn('no API key', out['error'])

    def test_several_sources_need_a_source_id(self):
        a, b = self.source(), self.source()
        out = _T().smartfarmkorea_lookup_tool(dataset='smartfarmkorea', mode='farms')
        self.assertIn('source_id', out['error'])
        with patch('aot.ai.context.ext.smartfarmkorea_client.requests.get', return_value=self._farms()):
            out = _T().smartfarmkorea_lookup_tool(source_id=b.source_id, mode='farms')
        self.assertEqual(1, out['total'])

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_the_stored_key_is_what_goes_to_the_provider(self, get):
        get.return_value = self._farms()
        self.source(key='STORED-KEY')
        _T().smartfarmkorea_lookup_tool(dataset='smartfarmkorea', mode='farms')
        self.assertIn('STORED-KEY', json.dumps([str(c) for c in get.call_args_list]))

    @patch('aot.ai.context.ext.smartfarmkorea_client.requests.get')
    def test_farms_and_seasons_are_operations_of_the_source(self, get):
        get.return_value = self._farms()
        src = self.source(enabled=True)
        out = _T().query_data_source(source_id=src.source_id, operation='farms', params={'crop': '딸기'})
        self.assertEqual(['PF_A'], [i['userId'] for i in out['items']])
        out = _T().query_data_source(source_id=src.source_id, operation='seasons', params={})
        self.assertIn('userId', out['error'].replace('user_id', 'userId'))

    def test_the_source_lists_its_discovery_operations_only_where_they_exist(self):
        from aot.ai.services import data_source_query_service as svc
        self.source(enabled=True)
        self.source('smartfarmkorea_livestock', enabled=True, operations=['poultry_daily'])
        by = {d['preset']: {o['operation'] for o in d['operations']} for d in svc.describe_all()}
        self.assertTrue({'farms', 'seasons'} <= by['smartfarmkorea'])
        self.assertFalse({'farms', 'seasons'} & by['smartfarmkorea_livestock'])

    def test_discovery_on_a_source_that_has_none_is_a_clear_error(self):
        src = self.source('smartfarmkorea_livestock', enabled=True, operations=['poultry_daily'])
        out = _T().query_data_source(source_id=src.source_id, operation='farms')
        self.assertIn('identity', out['error'])


class ConfigureTest(_Db):

    def test_a_new_source_without_a_key_stays_inactive_and_says_who_types_it(self):
        out = _T().configure_library_source_tool(preset_key='smartfarmkorea', operations=['identity'])
        self.assertEqual('created', out['status'])
        self.assertFalse(out['activated'])
        self.assertTrue(out['needs_api_key'])
        self.assertIn('AI Library', out['next_for_user'])
        self.assertNotIn('synced', out)                          # 키 없이는 동기화하지 않는다
        src = AIContextSource.query.filter_by(source_id=out['source_id']).first()
        self.assertFalse(bool(src.is_enabled))
        self.assertNotIn('api_key', json.loads(src.config_json))

    def test_an_existing_source_keeps_its_key_and_old_values(self):
        src = self.source(userId='PF_1')
        out = _T().configure_library_source_tool(source_id=src.source_id, operations=['cropping'], activate=False)
        self.assertEqual('updated', out['status'])
        cfg = json.loads(AIContextSource.query.filter_by(source_id=src.source_id).first().config_json)
        self.assertEqual(('SK', 'PF_1', ['cropping']), (cfg['api_key'], cfg['userId'], cfg['operations']))

    def test_the_preset_comes_from_the_source_when_only_the_id_is_given(self):
        src = self.source('smartfarmkorea_outdoor', operations=['identity'])
        out = _T().configure_library_source_tool(source_id=src.source_id, operations=['identity'], activate=False)
        self.assertEqual('updated', out['status'], out)

    def test_params_may_come_as_an_object_or_json_text_and_flat_values_still_work(self):
        src = self.source()
        for kw in ({'params': {'userId': 'U1'}}, {'params': '{"userId": "U2"}'}, {'userId': 'U3'}):
            out = _T().configure_library_source_tool(source_id=src.source_id, operations=['cropping'],
                                                     activate=False, **kw)
            self.assertEqual('updated', out['status'], out)
        cfg = json.loads(AIContextSource.query.filter_by(source_id=src.source_id).first().config_json)
        self.assertEqual('U3', cfg['userId'])

    def test_a_value_the_preset_does_not_know_is_refused_with_the_valid_names(self):
        src = self.source()
        out = _T().configure_library_source_tool(source_id=src.source_id, operations=['cropping'],
                                                 params={'userId': 'U', 'nonsense': 1})
        self.assertIn('nonsense', out['error'])
        self.assertIn('userId', out['valid_parameters'])

    def test_missing_values_are_named_per_operation_from_the_presets_own_table(self):
        src = self.source()
        out = _T().configure_library_source_tool(source_id=src.source_id, operations=['growth_strawberry'])
        self.assertIn('missing required params', out['error'])
        self.assertIn('croppingSerlNo', out['details'][0]['missing'])

    def test_a_preset_without_operations_is_not_registered_here(self):
        out = _T().configure_library_source_tool(preset_key='document', operations=['x'])
        self.assertIn('preset_key must be one of', out['error'])

    def test_a_preset_that_needs_no_key_can_be_created_and_activated(self):
        from aot.ai.services import data_source_query_service as svc
        key = 'ext_openmeteo'
        self.assertIn(key, svc.queryable_presets())
        ops = svc.operations_of(key)
        op = sorted(ops)[0]
        params = {p: '1' for p in ops[op]['params'] if p != 'apikey'}
        out = _T().configure_library_source_tool(preset_key=key, operations=[op], params=params, sync=False)
        self.assertEqual('created', out['status'], out)
        self.assertTrue(out['activated'], out)


class DomainOpsTest(unittest.TestCase):

    def _ops(self):
        from aot.tools.domain.registry_data import OPS
        return {(o.tool, o.op): o for o in OPS}

    def test_one_register_op_and_the_service_specific_discovery_op_is_gone(self):
        ops = self._ops()
        self.assertIn(('configure', 'library_source'), ops)
        self.assertNotIn(('configure', 'library_source_configure'), ops)
        self.assertNotIn(('records', 'smartfarmkorea'), ops)
        o = ops[('configure', 'library_source')]
        self.assertEqual({'configure_library_source'}, set(o.inner.values()))
        self.assertIn('params', o.extra_args)
        for old in ('userId', 'facilityId', 'croppingSerlNo', 'itemCode', 'measDate', 'startDate', 'endDate', 'api_key'):
            self.assertNotIn(old, o.extra_args)

    def test_discovery_is_covered_by_the_data_source_op(self):
        from aot.tools.domain import contract
        # 옛 smartfarmkorea_lookup 도구는 26-11 5단계에서 지웠다 — 발견은 records.data_source 가 맡는다.
        from aot.tools.tool_registry import virtual_tool_registry
        self.assertNotIn('smartfarmkorea_lookup', virtual_tool_registry())
        self.assertNotIn('smartfarmkorea_lookup', contract.COVERED_ELSEWHERE)
        self.assertEqual([], contract.problems())

    def test_no_service_name_in_the_generic_ops(self):
        ops = self._ops()
        for key in (('configure', 'library_source'), ('records', 'data_source'), ('find', 'lookup_sources'),
                    ('find', 'library_source_types')):
            o = ops[key]
            text = (o.use + ' ' + ' '.join(o.extra_args.values())).lower()
            self.assertNotIn('smartfarm', text, key)

    def test_the_old_op_name_is_an_alias_and_old_specific_values_are_refused(self):
        from aot.tools.domain import dispatch, renames
        _t, args, got = renames.resolve_call('configure', {'op': 'library_source_configure', 'operations': ['x']})
        self.assertEqual('library_source', args['op'])
        v = dispatch.plan('configure', {'op': 'library_source', 'operations': ['identity'], 'api_key': 'K'})
        body = json.loads(v[1][0]['text'])
        self.assertEqual('refuse', v[0])
        self.assertEqual('unknown_argument', body['reason_code'])

    def test_the_listing_asks_only_for_operations_up_front(self):
        from aot.tools.domain import surface
        from aot.tools import tool_registry as R
        from aot.tools.domain.registry_data import OPS
        ents = {e['name']: e for e in surface.entries(OPS, lambda n: True, set(R.approval_required_tools()))}
        line = [l for l in ents['configure']['description'].splitlines() if l.startswith('library_source — ')][0]
        self.assertIn('(needs: operations)', line)
        self.assertIn('approval', line)


if __name__ == '__main__':
    unittest.main()

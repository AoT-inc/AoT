# coding=utf-8
"""조사가 끝까지 가고, 비친 것을 나중에 찾을 수 있는가.

사용자 보고(2026-08-25) 두 건에서 나왔다.

  ① "조사 방법을 제대로 몰라서 한참 설명해야 했음."
     재현: "땅콩 재배 방법을 조사해서 라이브러리에 정리해줘" → 모델이
     knowledge_search 로 0건을 받고 → list_lookup_sources 로 FAO ECOCROP 을
     **보고도** → 조회하지 않고 "자료를 제공해주시면 정리해 드리겠습니다" 로
     끝냈다(도구 2회, 41초). 목록만 주면 자료 사전으로 읽는다.

  ② "학명 기준으로 태그를 달아놔서 나중에 다시 찾지 못할 것 같음."
     knowledge_search 는 제목(3배)과 본문만 점수화하고 태그는 필터일 뿐이다.
     영문 자료를 조사하면 그 자료의 어휘로 제목이 달리고, 사용자의 말로는
     0점이 된다 — 저장은 성공하고 나중에 조용히 못 찾는다.
"""
import json

import pytest

from aot.config import ProdConfig


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'research.db'}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


class TestLookupSourcesTellsTheNextStep:
    """목록을 본 모델이 조회로 넘어가는가."""

    def _note(self, app):
        from aot.aot_flask.extensions import db
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        from aot.databases.models import AIContextSource

        with app.app_context():
            src = AIContextSource(
                facility_id='f', source_name='ECOCROP', source_type='csv_table',
                parameter_name='ext_ecocrop.t', sync_interval_min=0,
                is_active=True, is_enabled=True,
                config_json=json.dumps({'preset_key': 'ext_ecocrop',
                                        'data_url': 'http://x/y.csv',
                                        'answers': '작물 요구조건'}))
            db.session.add(src)
            db.session.commit()
            return AoTDataToolService.list_lookup_sources().get('note', '')

    def test_it_names_the_tool_to_call_next(self, app):
        note = self._note(app)
        assert 'query_reference_table' in note
        assert 'query_data_source' in note

    def test_it_says_the_job_is_not_done_yet(self, app):
        """서술형 안내로는 모델이 여기서 멈췄다 — 명령형이어야 한다."""
        note = self._note(app)
        assert 'NOT done' in note

    def test_aliases_are_not_read_as_a_whitelist(self, app):
        """별칭 24개에 '땅콩' 이 없다는 사실이 '이 표로는 못 찾는다' 는 정지
        신호로 작동했다. 없는 별칭은 행이 없다는 증거가 아니다."""
        note = self._note(app)
        assert 'not a whitelist' in note
        assert 'translate' in note

    def test_it_forbids_bouncing_the_question_back_to_the_user(self, app):
        """실제 실패 문장이 '자료를 제공해주시면 정리해 드리겠습니다' 였다."""
        note = self._note(app)
        assert 'NEVER ask the user to supply' in note


class TestLocalNameGuard:
    """비친 항목을 사용자가 자기 말로 다시 찾을 수 있는가."""

    def _check(self, app, heading, body, lang='ko'):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.test_request_context(headers={'Accept-Language': lang}):
            return AoTDataToolService._missing_local_name(heading, body)

    def test_a_scientific_only_heading_is_rejected(self, app):
        """정확히 보고된 실패 — 땅콩을 조사하고 학명으로만 적은 경우."""
        assert self._check(app, 'Arachis hypogaea cultivation', 'arachis,groundnut') == 'ko'

    def test_the_local_name_in_the_heading_passes(self, app):
        assert self._check(app, '땅콩(Arachis hypogaea) 재배', 'arachis,groundnut') is None

    def test_the_local_name_in_the_body_alone_passes(self, app):
        """본문도 점수화된다(1배) — 제목이 영문이어도 본문이 현지어면 걸린다."""
        assert self._check(app, 'Arachis hypogaea', '땅콩은 배수가 좋은 흙을 좋아한다.') is None

    def test_a_tag_does_not_count(self, app):
        """검색은 태그를 점수화하지 않는다 — 태그에만 있는 이름으로는 이
        항목이 걸리지 않으므로, 태그를 세면 검사가 목적을 잃는다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.test_request_context(headers={'Accept-Language': 'ko'}):
            res = AoTDataToolService.knowledge_shelve(
                content='Optimal 22-32C.', tags='땅콩,crop', heading='Arachis hypogaea')
            assert res.get('error') == 'not findable later', res

    def test_a_latin_script_install_is_never_blocked(self, app):
        """판정할 수 없는 곳에서는 막지 않는다 — 이 검사는 확실한 실패만 잡는다."""
        assert self._check(app, 'Arachis hypogaea', 'groundnut', lang='en') is None

    def test_outside_a_request_it_does_not_block(self, app):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.app_context():
            assert AoTDataToolService._missing_local_name('Arachis', 'groundnut') is None




class TestTheGuardActuallyBlocksTheWrite:
    def test_shelving_an_unfindable_note_is_refused_and_nothing_is_saved(self, app):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        from aot.databases.models import AIKnowledgeChunk

        with app.test_request_context(headers={'Accept-Language': 'ko'}):
            before = AIKnowledgeChunk.query.count()
            res = AoTDataToolService.knowledge_shelve(
                content='Optimal 20-30C, rainfall 500-1200mm.',
                tags='arachis,groundnut', heading='Arachis hypogaea requirements')

            assert res.get('error') == 'not findable later', res
            assert 'heading' in res['message']
            assert AIKnowledgeChunk.query.count() == before, '거부했는데 저장됐다'

    def test_the_same_note_with_a_local_name_goes_through(self, app):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.test_request_context(headers={'Accept-Language': 'ko'}):
            res = AoTDataToolService.knowledge_shelve(
                content='생육 적온 20~30도, 연강수량 500~1200mm.',
                tags='땅콩,peanut,재배', heading='땅콩(Arachis hypogaea) 생육 적합 범위')

            assert res.get('error') != 'not findable later', res


class TestYamlShapedResponseIsRecovered:
    """모델이 문법만 YAML 로 냈을 때 그 원문이 답변으로 새지 않는가.

    실측(2026-08-25, gemini-2.5-flash): JSON 파싱이 실패하자
    "insight: …\\nactions:\\n  - action_type: virtual_tool_call…" 이 그대로
    사용자 답변이 됐다. 내부 실행계획이 화면에 노출됐고, actions 가 비어
    루프도 거기서 끝났다.
    """

    def _parse(self, raw):
        """AbstractAI 는 추상 클래스라 인스턴스화되지 않는다 — 파서가 실제로
        쓰는 헬퍼만 빌려 붙인 최소 대역으로 부른다."""
        from aot.ai.agents.base_ai import AbstractAI

        class _Shim:
            _extract_json_from_text = AbstractAI._extract_json_from_text
            _get_available_tool_names = AbstractAI._get_available_tool_names

        return AbstractAI._safe_api_result(_Shim(), raw, 'TestEngine')

    def test_a_yaml_body_is_recovered_not_leaked(self):
        raw = ("insight: 라이브러리에 없어 FAO ECOCROP 을 조회하겠습니다.\n"
               "actions:\n"
               "  - action_type: virtual_tool_call\n"
               "    tool_name: query_reference_table\n"
               "    params:\n"
               "      query: peanut\n")
        out = self._parse(raw)

        assert 'action_type' not in out['insight'], '실행계획이 답변으로 샜다'
        assert out['insight'].startswith('라이브러리에')
        assert len(out['actions']) == 1
        assert out['actions'][0]['tool_name'] == 'query_reference_table'
        assert not out.get('_parse_failed')

    def test_plain_prose_still_falls_back(self):
        """YAML 은 산문도 관대하게 삼킨다 — 'insight' 키가 있을 때만 받아야
        엉뚱한 dict 로 답변을 잃지 않는다."""
        out = self._parse('땅콩은 콩과 작물입니다. 배수가 잘되는 토양을 좋아합니다.')
        assert '땅콩' in out['insight']
        assert out.get('_parse_failed')


class TestBothNamesRequired:
    """표에서 옮긴 항목은 양쪽 이름으로 다 찾을 수 있어야 한다.

    현지 이름만 요구했을 때 실측(2026-08-25): 땅콩 항목이 '땅콩 재배 기준' /
    'crop,땅콩' 으로 저장돼 한국어 조회는 전부 걸렸지만 'peanut' 은 0건이었다.
    그 표로 되짚어 가거나 다른 언어 사용자가 닿을 길이 없었다.
    """

    def _table(self, app, title='FAO ECOCROP — 종별 생육 적합 범위'):
        from aot.aot_flask.extensions import db
        from aot.databases.models import AIContextSource

        src = AIContextSource(
            facility_id='f', source_name='ECOCROP', source_type='csv_table',
            parameter_name='ext_ecocrop.t', sync_interval_min=0,
            is_active=True, is_enabled=True,
            config_json=json.dumps({'preset_key': 'ext_ecocrop', 'title': title,
                                    'data_url': 'http://x/y.csv', 'answers': 'a'}))
        db.session.add(src)
        db.session.commit()
        return src.source_id

    def test_a_local_name_alone_is_refused_for_a_table_note(self, app):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.test_request_context(headers={'Accept-Language': 'ko'}):
            ref = self._table(app)
            res = AoTDataToolService.knowledge_shelve(
                content='최적 22~32도.', tags='땅콩',
                heading='땅콩 재배 기준', source_ref=ref)

            assert res.get('error') == 'findable in only one language', res
            assert 'ECOCROP' in res['message'], '어느 표인지 말해야 고칠 수 있다'

    def test_both_names_go_through(self, app):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.test_request_context(headers={'Accept-Language': 'ko'}):
            ref = self._table(app)
            res = AoTDataToolService.knowledge_shelve(
                content='최적 22~32도.', tags='땅콩,peanut',
                heading='땅콩(Arachis hypogaea) 재배 기준', source_ref=ref)

            assert 'error' not in res or res['error'] not in (
                'findable in only one language', 'not findable later'), res

    def test_a_generic_english_scope_tag_does_not_satisfy_it(self, app):
        """실측 사례의 태그가 정확히 'crop,땅콩' 이었다. 태그를 세면 범용
        분류어 'crop' 이 라틴 낱말이라 통과해 버려, 잡아야 할 바로 그 항목이
        빠져나간다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.test_request_context(headers={'Accept-Language': 'ko'}):
            ref = self._table(app)
            res = AoTDataToolService.knowledge_shelve(
                content='최적 22~32도.', tags='crop,땅콩',
                heading='땅콩 재배 기준', source_ref=ref)

            assert res.get('error') == 'findable in only one language', res

    def test_the_source_name_in_the_body_is_enough(self, app):
        """본문도 검색이 점수화한다 — 제목에 없어도 본문에 있으면 찾을 수 있다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.test_request_context(headers={'Accept-Language': 'ko'}):
            ref = self._table(app)
            res = AoTDataToolService.knowledge_shelve(
                content='땅콩(Arachis hypogaea) 최적 22~32도.', tags='crop,땅콩',
                heading='땅콩 재배 기준', source_ref=ref)

            assert res.get('error') != 'findable in only one language', res

    def test_a_field_observation_is_not_forced_to_invent_a_foreign_name(self, app):
        """현장 메모에는 대응하는 외국어 이름이 애초에 없다 — 요구하면
        지어내게 된다. source_ref 가 없으면 이 검사는 돌지 않는다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.test_request_context(headers={'Accept-Language': 'ko'}):
            res = AoTDataToolService.knowledge_shelve(
                content='3동 관수 밸브가 새는 중.', tags='관수,고장',
                heading='3동 관수 밸브 누수')

            assert 'error' not in res or res['error'] not in (
                'findable in only one language', 'not findable later'), res

    def test_an_api_source_is_exempt(self, app):
        """API 소스는 측정값이라 '이름으로 찾는' 자료가 아니고, 한국 기관
        자료에 영문 이름을 강요할 이유도 없다."""
        from aot.aot_flask.extensions import db
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        from aot.databases.models import AIContextSource

        with app.test_request_context(headers={'Accept-Language': 'ko'}):
            src = AIContextSource(
                facility_id='f', source_name='SmartFarmKorea', source_type='rest_api',
                parameter_name='sfk.t', sync_interval_min=0,
                is_active=True, is_enabled=True,
                config_json=json.dumps({'preset_key': 'smartfarmkorea'}))
            db.session.add(src)
            db.session.commit()

            res = AoTDataToolService.knowledge_shelve(
                content='2015년 작기 측정값.', tags='토마토,작기',
                heading='김제 토마토 작기', source_ref=src.source_id)

            assert res.get('error') != 'findable in only one language', res

    def test_an_unknown_source_ref_does_not_block(self, app):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.test_request_context(headers={'Accept-Language': 'ko'}):
            res = AoTDataToolService.knowledge_shelve(
                content='내용.', tags='땅콩', heading='땅콩 메모',
                source_ref='없는-소스-id')

            assert res.get('error') != 'findable in only one language', res

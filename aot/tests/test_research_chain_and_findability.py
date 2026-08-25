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

    def _check(self, app, heading, tags, lang='ko'):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.test_request_context(headers={'Accept-Language': lang}):
            return AoTDataToolService._missing_local_name(heading, tags)

    def test_a_scientific_only_heading_is_rejected(self, app):
        """정확히 보고된 실패 — 땅콩을 조사하고 학명으로만 적은 경우."""
        assert self._check(app, 'Arachis hypogaea cultivation', 'arachis,groundnut') == 'ko'

    def test_the_local_name_in_the_heading_passes(self, app):
        assert self._check(app, '땅콩(Arachis hypogaea) 재배', 'arachis,groundnut') is None

    def test_the_local_name_in_the_tags_alone_passes(self, app):
        """문턱을 낮게 둔다 — 제목이든 태그든 한 글자라도 있으면 통과다."""
        assert self._check(app, 'Arachis hypogaea', '땅콩,재배') is None

    def test_a_latin_script_install_is_never_blocked(self, app):
        """판정할 수 없는 곳에서는 막지 않는다 — 이 검사는 확실한 실패만 잡는다."""
        assert self._check(app, 'Arachis hypogaea', 'groundnut', lang='en') is None

    def test_outside_a_request_it_does_not_block(self, app):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.app_context():
            assert AoTDataToolService._missing_local_name('Arachis', 'groundnut') is None

    def test_tags_may_arrive_as_a_list(self, app):
        assert self._check(app, 'Arachis hypogaea', ['땅콩', '재배']) is None


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

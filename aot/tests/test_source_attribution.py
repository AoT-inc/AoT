# coding=utf-8
"""출처 표시 — CC BY 자료를 쓰면서 밝히지 않는 상태를 막는다.

라이브러리가 붙인 공개 자료 상당수가 CC BY 다(FAO ECOCROP, Open-Meteo).
CC BY 는 자료를 **표시하는 자리 옆에** 출처를 밝히라고 요구하고, Open-Meteo 는
문구까지 지정한다. AoT 에서 그 자료가 표시되는 자리는 AI 의 답변과 라이브러리
화면 둘이고, 답변 쪽은 조회 응답에 실린 것만 모델이 알기 때문에 응답이 곧
준수 여부를 가른다.
"""
import json

import pytest

from aot.ai.services import source_attribution as sa
from aot.config import ProdConfig


class TestApply:
    def test_the_obligation_travels_with_the_credit(self):
        """문구만 실으면 모델은 그것을 메타데이터로 읽는다 — 참조표 경로가
        실제로 그랬다. '답변에 적으라' 를 함께 싣는다."""
        payload = sa.apply({}, {'attribution': 'FAO ECOCROP (CC BY 4.0)'})

        assert payload['attribution'] == 'FAO ECOCROP (CC BY 4.0)'
        assert 'answer' in payload['attribution_note']

    def test_nothing_is_added_when_there_is_nothing_to_credit(self):
        """빈 필드를 실으면 응답만 커지고, 모델은 '출처 없음' 을 출처로 읽는다."""
        assert sa.apply({}, {}) == {}
        assert sa.apply({}, {'attribution': '   '}) == {}

    def test_the_operator_wins_over_the_preset_default(self):
        payload = sa.apply({}, {'attribution': '직접 적은 표기'}, 'ext_openmeteo')
        assert payload['attribution'] == '직접 적은 표기'

    def test_the_preset_default_fills_an_empty_field(self):
        """운영자가 직접 타이핑해야 한다면 대부분 비워 두고, 그러면
        라이선스를 어긴 채로 돌아간다."""
        payload = sa.apply({}, {}, 'ext_openmeteo')
        assert 'Open-Meteo.com' in payload['attribution']
        assert payload['source_url'] == 'https://open-meteo.com/'

    def test_the_open_meteo_wording_is_the_one_they_require(self):
        """licence 페이지가 이 문장과 링크를 명시적으로 요구한다 — 줄이면
        준수가 아니다."""
        creds = sa.defaults_for('ext_openmeteo')
        assert creds['attribution'].startswith('Weather data by Open-Meteo.com')
        assert creds['source_url'].startswith('https://open-meteo.com')

    def test_caveat_rides_along(self):
        payload = sa.apply({}, {'caveat': '적합성 범위이지 목표값이 아니다'})
        assert payload['caveat']
        # 주의사항만 있고 출처가 없으면 표시 의무도 없다.
        assert 'attribution_note' not in payload


class TestBothQueryPathsCarryIt:
    """참조표와 조회형 API 가 같은 의무를 싣는가 — 한쪽만 지키면 그쪽으로
    안 물어본 질문의 답에는 출처가 빠진다."""

    @pytest.fixture
    def app(self, tmp_path):
        from aot.aot_flask.app import create_app
        from aot.aot_flask.extensions import db

        class _Config(ProdConfig):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'attr.db'}"
            TESTING = True

        application = create_app(config=_Config)
        with application.app_context():
            db.create_all()
        yield application
        with application.app_context():
            db.session.remove()

    def test_the_api_path_credits_open_meteo(self, app, monkeypatch):
        from aot.aot_flask.extensions import db
        from aot.ai.context.ext import openmeteo_client
        from aot.ai.services.data_source_query_service import query
        from aot.databases.models import AIContextSource

        monkeypatch.setattr(openmeteo_client, 'fetch_operation',
                            lambda op, params, operations=None: ([{'time': 'x'}], None))

        with app.app_context():
            src = AIContextSource(
                facility_id='f', source_name='Open-Meteo', source_type='query_api',
                parameter_name='ext_openmeteo.t', sync_interval_min=0,
                is_active=True, is_enabled=True,
                config_json=json.dumps({'preset_key': 'ext_openmeteo',
                                        'latitude': '35.8', 'longitude': '126.88'}))
            db.session.add(src)
            db.session.commit()

            payload, err = query(src.source_id, 'forecast_daily')

            assert err is None, err
            assert 'Open-Meteo.com' in payload['attribution']
            assert payload['attribution_note']

    def test_the_reference_table_path_states_the_obligation(self):
        """이 경로는 이미 attribution 을 싣고 있었지만 의무는 말하지 않았다."""
        import inspect

        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        body = inspect.getsource(AoTDataToolService.query_reference_table)
        assert 'source_attribution' in body


class TestTheNoticeIsShownOnScreen:
    def test_only_enabled_sources_are_credited(self, tmp_path):
        """끈 소스의 자료는 지금 표시되지 않는다 — 그 출처를 밝히면 쓰지도
        않는 자료를 쓴다고 말하는 셈이다."""
        from aot.aot_flask.routes_ai_library import _attribution_notices

        class _Src:
            def __init__(self, enabled):
                self.is_enabled = enabled
                self.config_json = json.dumps({'preset_key': 'ext_openmeteo'})

        assert _attribution_notices([_Src(False)]) == []
        assert len(_attribution_notices([_Src(True)])) == 1

    def test_the_same_credit_is_not_repeated(self):
        from aot.aot_flask.routes_ai_library import _attribution_notices

        class _Src:
            is_enabled = True
            config_json = json.dumps({'attribution': '같은 출처'})

        assert len(_attribution_notices([_Src(), _Src()])) == 1

    def test_a_malformed_config_does_not_break_the_page(self):
        from aot.aot_flask.routes_ai_library import _attribution_notices

        class _Src:
            is_enabled = True
            config_json = '{ not json'

        assert _attribution_notices([_Src()]) == []

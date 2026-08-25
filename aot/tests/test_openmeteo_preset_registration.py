# coding=utf-8
"""ext_openmeteo 프리셋 등록 — 화면에서 켤 수 있게 되는 배선.

클라이언트가 돌아도(test_openmeteo_client) 프리셋이 없으면 아무도 못 쓴다.
여기서 고정하는 것은 그 마지막 구간이다: 좌표가 자동으로 채워지는가, 키 없이
활성화되는가, 조회 대상으로 잡히는가, 그리고 **기상이 지식으로 굳지 않는가**.
"""
import json

import pytest

from aot.config import ProdConfig


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'openmeteo_preset.db'}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


def _make_source(config):
    from aot.aot_flask.extensions import db
    from aot.databases.models import AIContextSource

    src = AIContextSource(
        facility_id='test-facility',
        source_name='Open-Meteo', source_type='query_api',
        parameter_name='ext_openmeteo.test', config_json=json.dumps(config),
        sync_interval_min=0, is_active=True, is_enabled=True)
    db.session.add(src)
    db.session.commit()
    return src


class TestPresetDeclaration:
    def test_the_preset_exists_and_needs_no_key(self):
        """무료 엔드포인트는 키를 요구하지 않는다 — 키를 강제하면 "그대로
        활성화하면 됨" 이 성립하지 않는다."""
        from aot.aot_flask.routes_ai_library import LIBRARY_PRESETS

        preset = LIBRARY_PRESETS['ext_openmeteo']
        assert preset['source_type'] == 'query_api'
        assert preset['needs_api_key'] is False
        assert preset['region'] == 'any'

    def test_it_never_syncs_on_a_schedule(self):
        """기상을 주기 동기화해 지식으로 굳히면 그 값은 틀린 채로 남는다."""
        from aot.aot_flask.routes_ai_library import LIBRARY_PRESETS

        assert LIBRARY_PRESETS['ext_openmeteo']['sync_interval_min'] == 0

    def test_the_family_key_matches_the_preset_key(self):
        """둘이 어긋나면 등록은 되는데 조회 대상으로 안 잡힌다 — 화면상
        정상이라 발견이 늦다."""
        from aot.aot_flask.routes_ai_library import LIBRARY_PRESETS
        from aot.ai.services.data_source_query_service import _FAMILIES

        for key in _FAMILIES:
            assert key in LIBRARY_PRESETS, '%s 계열에 대응하는 프리셋이 없다' % key


class TestCoordinateDefaults:
    """좌표를 **실제로 좌표가 사는 곳**에서 가져오는가.

    첫 구현은 `Misc.map_latitude` 를 읽었고 실측에서 하나도 못 채웠다 — 그
    컬럼은 어느 쓰기 경로도 채우지 않아 실 설치에서 전부 NULL 이다. 이
    검사들이 그 회귀를 막는다.
    """

    def test_coordinates_come_from_the_saved_map_camera(self, app):
        from aot.aot_flask.extensions import db
        from aot.aot_flask.routes_ai_library import _preset_computed_defaults
        from aot.databases.models import GeoMap

        with app.app_context():
            gmap = GeoMap(name='밭')
            gmap.state_json = json.dumps({'center': {'lat': 35.8, 'lng': 126.88}, 'zoom': 15})
            db.session.add(gmap)
            db.session.commit()

            assert _preset_computed_defaults('ext_openmeteo') == {
                'latitude': '35.800000', 'longitude': '126.880000'}

    def test_the_saved_camera_beats_the_legacy_columns(self, app):
        """둘 다 있으면 저장된 카메라가 이긴다. 컬럼을 직접 읽던 구현은 이
        반대였고, 그래서 지도를 바꿔도 같은 좌표가 나왔다.

        (컬럼만 있는 지도는 `GeoMap.viewport()` 가 그 값을 폴백으로 돌려준다 —
        SSOT 인 그 메서드를 거치는 한 우리는 그 판단을 다시 하지 않는다.)"""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.routes_ai_library import _preset_computed_defaults
        from aot.databases.models import GeoMap

        with app.app_context():
            gmap = GeoMap(name='둘 다')
            gmap.latitude, gmap.longitude = 37.5, 127.0
            gmap.state_json = json.dumps({'center': {'lat': 35.8, 'lng': 126.88}})
            db.session.add(gmap)
            db.session.commit()

            assert _preset_computed_defaults('ext_openmeteo') == {
                'latitude': '35.800000', 'longitude': '126.880000'}

    def test_it_falls_back_to_a_drawn_shape(self, app):
        """카메라가 저장돼 있지 않아도 밭은 그려져 있다."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.routes_ai_library import _preset_computed_defaults
        from aot.databases.models import GeoShape

        with app.app_context():
            shape = GeoShape()
            shape.geo_id = 1
            shape.feature = json.dumps({
                'type': 'Feature', 'properties': {},
                'geometry': {'type': 'Polygon', 'coordinates': [[
                    [126.0, 35.0], [126.0, 35.2], [126.2, 35.2], [126.2, 35.0], [126.0, 35.0]]]}})
            db.session.add(shape)
            db.session.commit()

            got = _preset_computed_defaults('ext_openmeteo')
            # GeoJSON 은 (경도, 위도) 순이다 — 뒤집으면 조회는 성공하고 값만
            # 엉뚱해서(바다 한가운데) 오류로 드러나지 않는다.
            assert 35.0 <= float(got['latitude']) <= 35.2, got
            assert 126.0 <= float(got['longitude']) <= 126.2, got

    def test_other_presets_are_untouched(self, app):
        with app.app_context():
            from aot.aot_flask.routes_ai_library import _preset_computed_defaults
            assert _preset_computed_defaults('ext_ecocrop') == {}

    def test_an_empty_install_is_not_an_error(self, app):
        """좌표를 못 구해도 등록 자체는 되어야 한다 — 활성화 때 무엇이
        없는지 말해 주면 된다."""
        with app.app_context():
            from aot.aot_flask.routes_ai_library import _preset_computed_defaults
            assert _preset_computed_defaults('ext_openmeteo') == {}


class TestActivationGate:
    def _check(self, app, config):
        from aot.aot_flask.routes_ai_library import _missing_config_error

        with app.app_context():
            src = _make_source(config)
            return _missing_config_error(src)

    def test_activation_is_blocked_without_coordinates(self, app):
        err = self._check(app, {'preset_key': 'ext_openmeteo'})
        assert err and 'latitude' in err and 'longitude' in err

    def test_activation_passes_with_coordinates_and_no_key(self, app):
        """is_system 프리셋은 키 검사에서 빠져나가므로, 좌표 검사가 그보다
        **먼저** 돌지 않으면 이 검사는 죽은 채로 통과한다."""
        assert self._check(app, {'preset_key': 'ext_openmeteo',
                                 'latitude': '35.8', 'longitude': '126.88'}) is None


class TestItBecomesQueryable:
    _CFG = {'preset_key': 'ext_openmeteo', 'latitude': '35.8', 'longitude': '126.88'}

    def test_a_registered_source_is_listed_with_its_operations(self, app):
        from aot.ai.services.data_source_query_service import describe_all

        with app.app_context():
            _make_source(self._CFG)
            listed = [d for d in describe_all() if d['preset'] == 'ext_openmeteo']

            assert len(listed) == 1, listed
            ops = {o['operation'] for o in listed[0]['operations']}
            assert {'forecast_daily', 'forecast_hourly', 'soil', 'climate_history'} <= ops

    def test_the_stored_coordinates_fill_themselves_in(self, app, monkeypatch):
        """모델이 매번 위경도를 적어야 한다면 등록해 둔 의미가 없다."""
        from aot.ai.context.ext import openmeteo_client
        from aot.ai.services.data_source_query_service import query

        seen = {}

        def _fake(op_key, params, operations=None):
            seen.update(params)
            return [{'grid_latitude': 35.8}, {'time': '2026-08-25'}], None

        monkeypatch.setattr(openmeteo_client, 'fetch_operation', _fake)

        with app.app_context():
            src = _make_source(self._CFG)
            payload, err = query(src.source_id, 'forecast_daily')

            assert err is None, err
            assert seen['latitude'] == '35.8' and seen['longitude'] == '126.88'
            assert payload['source_ref'] == src.source_id

    def test_no_api_key_is_sent_when_none_is_configured(self, app, monkeypatch):
        """빈 키를 실어 보내면 상업 엔드포인트로 가려다 거절당한다."""
        from aot.ai.context.ext import openmeteo_client
        from aot.ai.services.data_source_query_service import query

        seen = {}
        monkeypatch.setattr(openmeteo_client, 'fetch_operation',
                            lambda op, params, operations=None: (seen.update(params), ([], None))[1])

        with app.app_context():
            src = _make_source(self._CFG)
            query(src.source_id, 'forecast_daily')
            assert 'apikey' not in seen


class TestSyncDoesNotIngest:
    def test_activation_checks_the_connection_but_stores_no_knowledge(self, app, monkeypatch):
        """이 프리셋이 지식 청크를 하나라도 만들면, 기상값이 틀린 채로
        라이브러리에 영원히 남는다."""
        from aot.ai.context.ext import openmeteo_client
        from aot.ai.services import context_source_service
        from aot.databases.models import AIKnowledgeChunk

        monkeypatch.setattr(
            openmeteo_client, 'fetch_operation',
            lambda op, params, operations=None: ([{'grid_latitude': 35.8},
                                                  {'time': '2026-08-25'}], None))

        with app.app_context():
            src = _make_source({'preset_key': 'ext_openmeteo',
                                'latitude': '35.8', 'longitude': '126.88'})
            before = AIKnowledgeChunk.query.count()
            result = context_source_service.sync_source(src.source_id)

            assert AIKnowledgeChunk.query.count() == before, \
                'query_api 소스가 지식 항목을 만들었다'
            assert result is not None


class TestForecastFallback:
    def test_the_korea_only_path_points_at_the_registered_source(self, app):
        """한국 밖에서 "예보 없음" 으로 끝내면 대안이 있어도 모델이 못 찾는다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.app_context():
            src = _make_source({'preset_key': 'ext_openmeteo',
                                'latitude': '35.8', 'longitude': '126.88'})
            hint = AoTDataToolService._forecast_fallback_hint()

            assert 'query_data_source' in hint
            assert src.source_id in hint

    def test_it_does_not_recommend_a_source_that_is_not_registered(self, app):
        """없는 것을 권하면 모델이 부를 수 없는 것을 부르고, 그 실패는
        사용자에게 그냥 고장으로 보인다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        with app.app_context():
            hint = AoTDataToolService._forecast_fallback_hint()
            assert 'query_data_source' not in hint
            assert 'AI Library' in hint

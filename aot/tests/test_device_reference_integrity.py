# coding=utf-8
"""장치를 지우거나 이름으로 찾을 때 **조용히 틀리지 않는다**.

두 가지가 조용했다.

1. **삭제가 참조자를 보지 않았다.** 출력을 지우면 그것을 가리키던 시퀀스
   스텝·위젯·PID 설정이 죽은 id 를 든 채 남았고 아무 오류도 나지 않았다.
   2026-08-28 로컬 DB: **활성** 시퀀스 '3포장 밸브제어' 의 스텝 8개 전부가
   존재하지 않는 출력을 가리키고 있었다. 그 시퀀스는 매 주기 아무 데도
   닿지 않는 명령을 냈고, 화면에는 이유 없는 대시('-') 하나만 나왔다.

2. **이름 조회가 `.first()` 였다.** 이름이 겹치면 행 순서가 어느 장치를
   조작할지 정했다. 사용자는 v11 두 개 중 꺼져 있는 쪽을 보고 "밸브가 안
   열렸다" 고 판단했다 — 밸브는 열려 있었다.

둘 다 예외가 나지 않으므로, 단언으로 고정해 두지 않으면 다시 깨져도
아무도 모른다.
"""
import json

import pytest

from aot.config import ProdConfig


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    db_file = tmp_path / "refs.db"

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


def _output(name, tab_id=None, output_type='virtual_on_off_single'):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import DeviceMeasurements, Output, OutputChannel

    out = Output(unique_id=set_uuid())
    out.name = name
    out.tab_id = tab_id
    out.output_type = output_type
    db.session.add(out)
    db.session.commit()

    ch = OutputChannel(unique_id=set_uuid())
    ch.output_id = out.unique_id
    ch.channel = 0
    db.session.add(ch)
    meas = DeviceMeasurements(unique_id=set_uuid())
    meas.device_id = out.unique_id
    meas.channel = 0
    db.session.add(meas)
    db.session.commit()
    return out, ch, meas


class _Form:
    class _F:
        def __init__(self, data):
            self.data = data

    def __init__(self, output_id):
        self.output_id = _Form._F(output_id)


# ---------------------------------------------------------------------------
# 참조자 조회
# ---------------------------------------------------------------------------

class TestFindReferrers:
    def test_a_sequence_step_counts_as_a_referrer(self, app):
        """스텝은 출력을 "출력id,채널id" 로 저장한다 — 장치 id 만 찾으면 놓친다."""
        from aot.aot_flask.extensions import db
        from aot.databases import set_uuid
        from aot.databases.models import Actions, Trigger
        from aot.services.device_references import find_device_referrers

        with app.app_context():
            out, ch, _ = _output('v11')

            trig = Trigger(unique_id=set_uuid())
            trig.name = '3포장 밸브제어'
            trig.trigger_type = 'trigger_sequence'
            db.session.add(trig)
            db.session.commit()

            act = Actions(unique_id=set_uuid())
            act.function_id = trig.unique_id
            act.action_type = 'output_on_off'
            act.custom_options = json.dumps(
                {'output': f'{out.unique_id},{ch.unique_id}', 'state': 'on'})
            db.session.add(act)
            db.session.commit()

            found = find_device_referrers([out.unique_id])
            assert out.unique_id in found
            assert any('3포장 밸브제어' in label for label in found[out.unique_id])
            db.session.remove()

    def test_a_widget_pointing_at_the_measurement_counts(self, app):
        """그래프 위젯은 출력이 아니라 그 **측정 정의** id 를 가리킨다."""
        from aot.aot_flask.extensions import db
        from aot.databases import set_uuid
        from aot.databases.models import Widget
        from aot.services.device_references import find_device_referrers

        with app.app_context():
            out, _, meas = _output('펌프')

            w = Widget(unique_id=set_uuid())
            w.name = '1포장'
            w.graph_type = 'AoT_graph'
            w.custom_options = json.dumps({'measurements': [meas.unique_id]})
            db.session.add(w)
            db.session.commit()

            found = find_device_referrers([out.unique_id])
            assert any('1포장' in label for label in found[out.unique_id])
            db.session.remove()

    def test_a_paired_actuator_channel_counts(self, app):
        from aot.aot_flask.extensions import db
        from aot.databases.models import OutputChannel
        from aot.services.device_references import find_device_referrers

        with app.app_context():
            driven, driven_ch, _ = _output('열림 릴레이')
            vent, vent_ch, _ = _output('측창', output_type='actuator_paired')
            vent_ch.custom_options = json.dumps({
                'output_open_id': f'{driven.unique_id},{driven_ch.unique_id}'})
            db.session.commit()

            found = find_device_referrers([driven.unique_id])
            assert any('측창' in label for label in found[driven.unique_id])
            db.session.remove()

    def test_an_unused_device_has_no_referrers(self, app):
        from aot.aot_flask.extensions import db
        from aot.services.device_references import find_device_referrers

        with app.app_context():
            out, _, _ = _output('아무도 안 쓰는 밸브')
            assert find_device_referrers([out.unique_id]) == {}
            db.session.remove()

    def test_devices_deleted_together_do_not_block_each_other(self, app):
        """탭을 통째로 지울 때 그 안끼리의 참조까지 막으면 영영 못 지운다."""
        from aot.aot_flask.extensions import db
        from aot.databases.models import OutputChannel
        from aot.services.device_references import find_device_referrers

        with app.app_context():
            driven, driven_ch, _ = _output('열림 릴레이', tab_id='t1')
            vent, vent_ch, _ = _output('측창', tab_id='t1',
                                       output_type='actuator_paired')
            vent_ch.custom_options = json.dumps({
                'output_open_id': f'{driven.unique_id},{driven_ch.unique_id}'})
            db.session.commit()

            ids = [driven.unique_id, vent.unique_id]
            assert find_device_referrers(ids) != {}          # 그냥 물으면 걸리고
            assert find_device_referrers(ids, ignore_ids=ids) == {}   # 함께 지우면 안 걸린다
            db.session.remove()


# ---------------------------------------------------------------------------
# 삭제 차단
# ---------------------------------------------------------------------------

class TestDeletionIsBlocked:
    def test_output_in_use_is_not_deleted(self, app):
        from aot.aot_flask.extensions import db
        from aot.aot_flask.utils import utils_output
        from aot.databases import set_uuid
        from aot.databases.models import Actions, Output, Trigger

        with app.test_request_context():
            out, ch, _ = _output('v11')

            trig = Trigger(unique_id=set_uuid())
            trig.name = '3포장 밸브제어'
            db.session.add(trig)
            db.session.commit()
            act = Actions(unique_id=set_uuid())
            act.function_id = trig.unique_id
            act.custom_options = json.dumps(
                {'output': f'{out.unique_id},{ch.unique_id}'})
            db.session.add(act)
            db.session.commit()

            messages = utils_output.output_del(_Form(out.unique_id))

            assert messages['error'], "참조자가 있는데 삭제가 통과했다"
            assert '3포장 밸브제어' in messages['error'][0]
            assert not messages.get('deleted')
            # 그리고 실제로 남아 있어야 한다 — 부분 삭제는 최악이다.
            assert Output.query.filter_by(unique_id=out.unique_id).first() is not None
            db.session.remove()

    def test_unused_output_still_deletes(self, app):
        """검사가 정상 삭제까지 막으면 그건 고장이다."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.utils import utils_output
        from aot.databases.models import Output

        with app.test_request_context():
            out, _, _ = _output('버릴 밸브')
            messages = utils_output.output_del(_Form(out.unique_id))

            assert not messages['error'], messages['error']
            assert Output.query.filter_by(unique_id=out.unique_id).first() is None
            db.session.remove()

    def test_tab_delete_is_blocked_by_an_outside_referrer(self, app):
        from aot.aot_flask.extensions import db
        from aot.databases import set_uuid
        from aot.databases.models import Actions, Output, Trigger
        from aot.services.tab_service import TabService

        with app.test_request_context():
            keep = TabService.create_tab('output', name='Output')
            doomed = TabService.create_tab('output', name='나주')
            out, ch, _ = _output('v11', tab_id=doomed.unique_id)

            trig = Trigger(unique_id=set_uuid())
            trig.name = '시퀀스: 나주'
            db.session.add(trig)
            db.session.commit()
            act = Actions(unique_id=set_uuid())
            act.function_id = trig.unique_id
            act.custom_options = json.dumps(
                {'output': f'{out.unique_id},{ch.unique_id}'})
            db.session.add(act)
            db.session.commit()

            result = TabService.delete_tab(doomed.unique_id)
            assert result['success'] is False
            assert '시퀀스: 나주' in result['message']
            assert Output.query.filter_by(unique_id=out.unique_id).first() is not None
            db.session.remove()


# ---------------------------------------------------------------------------
# 이름 조회
# ---------------------------------------------------------------------------

class TestResolveDevice:
    def test_an_exact_id_wins_even_when_names_collide(self, app):
        """id 로 정확히 지목한 요청이 동명이인 때문에 막히면 안 된다."""
        from aot.aot_flask.extensions import db
        from aot.services.resolvers.device_resolver import resolve_output

        with app.app_context():
            a, _, _ = _output('v11')
            _output('v11')
            match = resolve_output(a.unique_id)
            assert match.error is None
            assert match.row.unique_id == a.unique_id
            db.session.remove()

    def test_a_unique_name_resolves(self, app):
        from aot.aot_flask.extensions import db
        from aot.services.resolvers.device_resolver import resolve_output

        with app.app_context():
            out, _, _ = _output('펌프')
            match = resolve_output('펌프')
            assert match.error is None
            assert match.row.unique_id == out.unique_id
            db.session.remove()

    def test_a_colliding_name_refuses_instead_of_guessing(self, app):
        """`.first()` 가 조용히 하나를 집던 자리. 틀린 밸브를 여는 것보다 낫다."""
        from aot.aot_flask.extensions import db
        from aot.services.resolvers.device_resolver import resolve_output
        from aot.services.tab_service import TabService

        with app.app_context():
            naju = TabService.create_tab('output', name='나주')
            nw = TabService.create_tab('output', name='농우바이오')
            _output('v11', tab_id=naju.unique_id)
            _output('v11', tab_id=nw.unique_id)

            match = resolve_output('v11')
            assert match.row is None
            assert match.ambiguous
            # 사용자가 구분할 수 있는 단서(소속 탭)를 준다. uuid 는 주지 않는다.
            assert '나주' in match.error and '농우바이오' in match.error
            assert '-' * 4 not in match.error
            db.session.remove()

    def test_a_missing_name_is_not_an_error(self, app):
        """"못 찾음" 은 호출자가 자기 문구로 말한다 — 도구마다 표현이 다르다."""
        from aot.aot_flask.extensions import db
        from aot.services.resolvers.device_resolver import resolve_output

        with app.app_context():
            match = resolve_output('없는 이름')
            assert match.row is None and match.error is None
            db.session.remove()

    def test_partial_match_also_refuses_when_it_collides(self, app):
        from aot.aot_flask.extensions import db
        from aot.services.resolvers.device_resolver import resolve_output

        with app.app_context():
            _output('밸브 1')
            _output('밸브 2')
            assert resolve_output('밸브', allow_partial=True).ambiguous
            db.session.remove()

    def test_operate_device_refuses_an_ambiguous_name(self, app):
        """실제 사고 경로 — 이름이 겹치면 조작하지 않는다."""
        from aot.aot_flask.extensions import db
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        from aot.services.tab_service import TabService

        with app.app_context():
            naju = TabService.create_tab('output', name='나주')
            nw = TabService.create_tab('output', name='농우바이오')
            _output('v11', tab_id=naju.unique_id)
            _output('v11', tab_id=nw.unique_id)

            result = AoTDataToolService.operate_device_tool(device_id="v11", state="on")
            assert 'error' in result
            assert '나주' in result['error']
            db.session.remove()


# ---------------------------------------------------------------------------
# 화면에서 구분하기
# ---------------------------------------------------------------------------

class TestDisambiguatedName:
    def test_a_unique_name_is_left_alone(self, app):
        """늘 덧붙이면 목록이 시끄러워진다 — 필요할 때만 나와야 한다."""
        from aot.aot_flask.extensions import db
        from aot.services.device_references import disambiguated_name
        from aot.services.tab_service import TabService

        with app.test_request_context():
            tab = TabService.create_tab('output', name='나주')
            out, _, _ = _output('펌프', tab_id=tab.unique_id)
            assert disambiguated_name(out) == '펌프'
            db.session.remove()

    def test_a_colliding_name_gains_its_tab(self, app):
        from aot.aot_flask.extensions import db
        from aot.services.device_references import disambiguated_name
        from aot.services.tab_service import TabService

        with app.test_request_context():
            naju = TabService.create_tab('output', name='나주')
            nw = TabService.create_tab('output', name='농우바이오')
            a, _, _ = _output('v11', tab_id=naju.unique_id)
            b, _, _ = _output('v11', tab_id=nw.unique_id)

            assert disambiguated_name(a) == 'v11 (나주)'
            assert disambiguated_name(b) == 'v11 (농우바이오)'
            db.session.remove()


# ---------------------------------------------------------------------------
# 지도 — JSON 안의 참조는 트리거도 FK 도 닿지 못한다
# ---------------------------------------------------------------------------

def _map_and_widget(map_name='김제', widget_name='GIS'):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import GeoMap, Widget

    gmap = GeoMap(unique_id=set_uuid())
    gmap.name = map_name
    db.session.add(gmap)
    db.session.commit()

    w = Widget(unique_id=set_uuid())
    w.name = widget_name
    w.graph_type = 'AoT_map'
    w.custom_options = json.dumps({'map_uuid': gmap.unique_id,
                                   'default_zoom': '17.68'})
    db.session.add(w)
    db.session.commit()
    return gmap, w


class TestMapDeletion:
    def test_a_map_a_widget_still_shows_is_not_deleted(self, app):
        """도형·시설은 트리거가 연쇄 정리하지만, 위젯은 지도 uuid 를
        custom_options JSON 안에 둔다 — 트리거도 FK 도 거기까지 닿지 못한다.
        그래서 지도를 지우면 그 위젯이 오류 없이 **빈 지도**를 보여줬다."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo.geo_design import GeoDesignManager
        from aot.databases.models import GeoMap

        with app.test_request_context():
            gmap, _w = _map_and_widget()

            result, error = GeoDesignManager.delete_design_map(gmap.unique_id)

            assert error, "위젯이 보고 있는데 지도가 지워졌다"
            assert 'GIS' in error
            assert result == {'blocked': True}
            assert GeoMap.query.filter_by(unique_id=gmap.unique_id).first() is not None
            db.session.remove()

    def test_a_map_nobody_shows_still_deletes(self, app):
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo.geo_design import GeoDesignManager
        from aot.databases import set_uuid
        from aot.databases.models import GeoMap

        with app.test_request_context():
            map_id = set_uuid()
            gmap = GeoMap(unique_id=map_id)
            gmap.name = '아무도 안 보는 지도'
            db.session.add(gmap)
            db.session.commit()

            # uuid 는 미리 잡아 둔다 — 삭제 뒤에는 인스턴스를 읽을 수 없다.
            result, error = GeoDesignManager.delete_design_map(map_id)

            assert error is None, error
            assert result == {'ok': True}
            assert GeoMap.query.filter_by(unique_id=map_id).first() is None
            db.session.remove()


class TestWidgetDuplicationKeepsItsView:
    """위젯 복제는 지도 참조를 **끊지 않는다.**

    1차 조사에서 이것을 결함으로 적었으나 틀렸다. 위젯은 보기(view)이지
    장치가 아니다 — 같은 지도를 두 위젯이 다른 줌으로 보는 것은 정상
    용법이고, 여기서 참조를 끊으면 복제한 위젯이 빈 채로 태어난다.
    장치 복제(I10)와는 정반대 방향의 요구다. 이 테스트는 앞으로 누군가
    "일관성" 을 이유로 위젯에도 거부목록을 적용하는 것을 막는다.
    """

    def test_the_copy_shows_the_same_map(self, app):
        from aot.aot_flask.extensions import db
        from aot.databases import clone_model, set_uuid
        from aot.databases.models import Widget

        with app.test_request_context():
            gmap, w = _map_and_widget()

            copy = clone_model(w, unique_id=set_uuid(),
                               name=f"{w.name} (copy)")
            opts = json.loads(copy.custom_options)

            assert opts['map_uuid'] == gmap.unique_id
            assert opts['default_zoom'] == '17.68'
            db.session.remove()

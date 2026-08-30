# coding=utf-8
"""복제하면 **사본은 사본만 가리킨다** — 복제 경로의 참조 무결성 회귀.

2026-08-28 로컬 DB 에서 확인된 실제 피해가 출발점이다.

- 이름이 같은 출력이 쌍으로 남아 있었다(v11/v12/v21/v22/펌프 — 나주 탭과
  그 사본 탭). 탭 복제만 사본 이름을 바꾸지 않았기 때문이고, 화면에는
  이름밖에 안 나오므로 사용자가 꺼져 있는 쪽 v11 을 보고 "밸브가 안
  열렸다" 고 판단했다.
- 같은 이름의 시퀀스가 셋까지 쌓여 있었고 **전부 스텝이 0개**였다.
  `duplicate_tab` 이 Trigger 는 복사하면서 `function_actions` 는 한 건도
  옮기지 않았기 때문이다. 그런데 `timer_schedule` 은 그대로 복사되어,
  요일별 스케줄만 꽉 찬 껍데기가 됐다.

그래서 이 파일이 지키는 계약은 넷이다.

1. 사본의 자식(스텝·측정 정의·채널)이 실제로 따라온다.
2. 사본 안의 참조는 **사본의 새 id** 를 가리킨다 — `timer_schedule` 의
   요일별 맵과 Conditional 코드 안의 id 리터럴 둘 다.
3. 사본은 원본의 지도 도형을 물려받지 않는다([I10] 교차참조 거부목록).
4. 사본 이름이 원본과 겹치지 않는다.

특히 2번은 **조용히** 깨진다 — `weekly_schedule.day_action_enabled()` 는
키가 없으면 오류가 아니라 전역 기본값으로 떨어진다. 그래서 단언으로
고정해 두지 않으면 다시 깨져도 아무도 모른다.
"""
import json

import pytest

from aot.config import ProdConfig


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    db_file = tmp_path / "duplication.db"

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


# ---------------------------------------------------------------------------
# 순수 함수 — DB 없이 도는 것들
# ---------------------------------------------------------------------------

class TestRemapSchedule:
    def test_day_maps_follow_the_clone(self):
        from aot.services.duplication import remap_schedule_action_ids

        sched = {
            "version": 1, "mode": "per_day",
            "shared": {"start": "06:00", "end": "07:30", "period": 3600},
            "days": {"0": {"enabled": True, "start": "06:00", "end": "07:30",
                           "period": 3600,
                           "actions": {"old-a": False},
                           "groups": {"old-a": "구역1"},
                           "durations": {"old-a": 900}}},
        }
        out = json.loads(remap_schedule_action_ids(
            json.dumps(sched), {"old-a": "new-a"}))

        day = out["days"]["0"]
        assert day["actions"] == {"new-a": False}
        assert day["groups"] == {"new-a": "구역1"}
        assert day["durations"] == {"new-a": 900}

    def test_keys_that_are_not_ours_are_dropped(self):
        """사본 것이 아닌 키를 남기는 것이 지금까지 쓰레기가 쌓인 방식이다."""
        from aot.services.duplication import remap_schedule_action_ids

        sched = {"days": {"0": {"actions": {"old-a": True, "stranger": True}}}}
        out = json.loads(remap_schedule_action_ids(
            json.dumps(sched), {"old-a": "new-a"}))
        assert out["days"]["0"]["actions"] == {"new-a": True}

    def test_unreadable_schedule_is_left_alone(self):
        from aot.services.duplication import remap_schedule_action_ids
        assert remap_schedule_action_ids("{not json", {"a": "b"}) == "{not json"


class TestRemapCodeIds:
    def test_full_uuid_is_rewired(self):
        from aot.services.duplication import remap_code_ids
        old = "11111111-2222-3333-4444-555555555555"
        new = "99999999-8888-7777-6666-555555555555"
        assert remap_code_ids(f'self.run_action("{old}")', {old: new}) == \
            f'self.run_action("{new}")'

    def test_short_prefix_is_rewired(self):
        """생성된 예제 코드는 앞 8자만 적는다 — run_action() 이 startswith 로 찾는다."""
        from aot.services.duplication import remap_code_ids
        old = "11111111-2222-3333-4444-555555555555"
        new = "99999999-8888-7777-6666-555555555555"
        assert remap_code_ids('self.condition("11111111")', {old: new}) == \
            'self.condition("99999999")'

    def test_ambiguous_prefix_is_left_for_a_human(self):
        from aot.services.duplication import remap_code_ids
        id_map = {
            "11111111-aaaa-3333-4444-555555555555": "aaaaaaaa-0000-0000-0000-000000000000",
            "11111111-bbbb-3333-4444-555555555555": "bbbbbbbb-0000-0000-0000-000000000000",
        }
        assert remap_code_ids('self.condition("11111111")', id_map) == \
            'self.condition("11111111")'


class TestCopyName:
    def test_styles_match_the_existing_individual_duplicate_paths(self):
        from aot.services.duplication import unique_copy_name
        assert unique_copy_name("v11", set(), style='prefix') == "Copy of v11"
        assert unique_copy_name("시퀀스", set(), style='suffix') == "시퀀스 (Copy)"

    def test_numbers_climb_instead_of_colliding(self):
        """같은 이름의 시퀀스가 셋까지 쌓였던 것이 이 규칙이 없어서였다."""
        from aot.services.duplication import unique_copy_name
        taken = {"시퀀스 (Copy)", "시퀀스 (Copy 2)"}
        assert unique_copy_name("시퀀스", taken, style='suffix') == "시퀀스 (Copy 3)"


class TestPairedChannelRefs:
    def test_physical_channel_refs_are_blanked(self):
        from aot.services.duplication import blank_paired_channel_refs

        class _Ch:
            custom_options = json.dumps({
                "actuator_kind": "side_vent",
                "output_open_id": "a,b", "output_close_id": "c,d",
                "selector_output_id": "e,f", "last_position_pct": 100.0,
                "travel_time_open_sec": 8.0,
            })

        ch = _Ch()
        assert blank_paired_channel_refs(ch) is True
        opts = json.loads(ch.custom_options)
        assert opts["output_open_id"] == ""
        assert opts["output_close_id"] == ""
        assert opts["selector_output_id"] == ""
        assert opts["last_position_pct"] == 0.0
        # 설정은 사본에도 그대로 있어야 한다 — 비우는 것은 참조뿐이다.
        assert opts["travel_time_open_sec"] == 8.0


# ---------------------------------------------------------------------------
# DB 를 거치는 실제 복제
# ---------------------------------------------------------------------------

def _make_sequence(tab_id, name="시퀀스", step_names=("v11", "v12")):
    """스텝과 요일별 스케줄을 갖춘 시퀀스 하나."""
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import Actions, Trigger

    trig = Trigger(unique_id=set_uuid())
    trig.name = name
    trig.tab_id = tab_id
    trig.trigger_type = 'trigger_sequence'
    trig.is_activated = True
    trig.map_overlay_id = 4242          # 원본이 놓인 지도 도형
    trig.map_config_id = 'shared-design-map'
    db.session.add(trig)
    db.session.commit()

    action_ids = []
    for i, step in enumerate(step_names):
        act = Actions(unique_id=set_uuid())
        act.function_id = trig.unique_id
        act.action_type = 'output_on_off'
        act.custom_options = json.dumps({
            'output': f'output-{step},channel-{step}',
            'state': 'on', 'gridstack_y': i, 'action_duration': 600,
        })
        db.session.add(act)
        action_ids.append(act.unique_id)
    db.session.commit()

    trig.timer_schedule = json.dumps({
        "version": 1, "mode": "per_day",
        "shared": {"start": "06:00", "end": "07:30", "period": 3600},
        "days": {str(d): {
            "enabled": True, "start": "06:00", "end": "07:30", "period": 3600,
            # 0번 스텝만 꺼 둔다 — 사본에서 이 설정이 살아남는지가 핵심이다.
            "actions": {action_ids[0]: False},
            "durations": {action_ids[0]: 111},
            "groups": {action_ids[0]: "구역1"},
        } for d in range(7)},
    })
    db.session.commit()
    return trig, action_ids


class TestDuplicateFunctionTab:
    def test_steps_come_along(self, app):
        """복제된 시퀀스가 스텝 0개인 껍데기가 되던 것이 원래 증상이다."""
        from aot.aot_flask.extensions import db
        from aot.databases.models import Actions, Tab, Trigger
        from aot.services.tab_service import TabService

        with app.app_context():
            src = TabService.create_tab('function', name='김제')
            trig, _ = _make_sequence(src.unique_id, step_names=("v11", "v12"))

            new_tab = TabService.duplicate_tab(src.unique_id)
            assert new_tab is not None

            copy = Trigger.query.filter(
                Trigger.tab_id == new_tab.unique_id).one()
            steps = Actions.query.filter(
                Actions.function_id == copy.unique_id).all()
            assert len(steps) == 2
            assert Tab.query.count() == 2
            db.session.remove()

    def test_per_day_settings_point_at_the_copys_own_steps(self, app):
        """조용히 깨지는 자리 — 키가 없으면 전역 기본값으로 떨어진다."""
        from aot.aot_flask.extensions import db
        from aot.databases.models import Actions, Trigger
        from aot.services.tab_service import TabService
        from aot.utils.weekly_schedule import (
            day_action_duration, day_action_enabled, day_action_group)

        with app.app_context():
            src = TabService.create_tab('function', name='김제')
            _make_sequence(src.unique_id, step_names=("v11", "v12"))

            new_tab = TabService.duplicate_tab(src.unique_id)
            copy = Trigger.query.filter(
                Trigger.tab_id == new_tab.unique_id).one()
            steps = sorted(
                Actions.query.filter(Actions.function_id == copy.unique_id).all(),
                key=lambda a: json.loads(a.custom_options)['gridstack_y'])

            sched = json.loads(copy.timer_schedule)
            first = steps[0].unique_id

            # 사본의 요일별 맵은 사본 스텝만 담는다.
            assert set(sched['days']['0']['actions']) == {first}
            # 그리고 원본에서 꺼 둔 설정이 사본에서도 살아 있다.
            assert day_action_enabled(sched, 0, first, True) is False
            assert day_action_duration(sched, 0, first, None) == 111
            assert day_action_group(sched, 0, first, None) == "구역1"
            db.session.remove()

    def test_copy_is_not_placed_on_the_originals_map(self, app):
        """[I10] — 컬럼 직접 복사가 거부목록을 우회하던 자리."""
        from aot.aot_flask.extensions import db
        from aot.databases.models import Trigger
        from aot.services.tab_service import TabService

        with app.app_context():
            src = TabService.create_tab('function', name='김제')
            _make_sequence(src.unique_id)

            new_tab = TabService.duplicate_tab(src.unique_id)
            copy = Trigger.query.filter(
                Trigger.tab_id == new_tab.unique_id).one()
            assert copy.map_overlay_id is None
            assert copy.map_config_id is None
            db.session.remove()

    def test_copy_is_renamed_and_deactivated(self, app):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Trigger
        from aot.services.tab_service import TabService

        with app.app_context():
            src = TabService.create_tab('function', name='김제')
            _make_sequence(src.unique_id, name='3포장 밸브제어')

            new_tab = TabService.duplicate_tab(src.unique_id)
            copy = Trigger.query.filter(
                Trigger.tab_id == new_tab.unique_id).one()
            assert copy.name == '3포장 밸브제어 (Copy)'
            assert copy.is_activated is False

            # 두 번째 복제도 이름이 겹치지 않는다.
            third = TabService.duplicate_tab(src.unique_id)
            copy2 = Trigger.query.filter(
                Trigger.tab_id == third.unique_id).one()
            assert copy2.name == '3포장 밸브제어 (Copy 2)'
            db.session.remove()


class TestDuplicateOutputTab:
    def test_outputs_are_renamed_and_children_follow(self, app):
        from aot.aot_flask.extensions import db
        from aot.databases import set_uuid
        from aot.databases.models import (
            DeviceMeasurements, Output, OutputChannel)
        from aot.services.tab_service import TabService

        with app.app_context():
            src = TabService.create_tab('output', name='나주')

            out = Output(unique_id=set_uuid())
            out.name = 'v11'
            out.tab_id = src.unique_id
            out.output_type = 'virtual_on_off_single'
            out.map_overlay_id = 'shape-1'
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

            new_tab = TabService.duplicate_tab(src.unique_id)
            copy = Output.query.filter(Output.tab_id == new_tab.unique_id).one()

            assert copy.name == 'Copy of v11'
            assert copy.map_overlay_id is None
            assert OutputChannel.query.filter(
                OutputChannel.output_id == copy.unique_id).count() == 1
            # 측정 정의가 따라오지 않으면 사본은 아무것도 기록하지 않는다.
            assert DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id == copy.unique_id).count() == 1
            db.session.remove()


class TestDuplicateConditional:
    def test_the_copys_code_calls_the_copys_own_action(self, app):
        """재배선 없이는 사본의 코드가 **원본의 액션**을 실행한다 —
        `base_conditional.run_action()` 이 id 를 전역에서 찾기 때문이다."""
        from aot.aot_flask.extensions import db
        from aot.databases import set_uuid
        from aot.databases.models import (
            Actions, Conditional, ConditionalConditions)
        from aot.services.duplication import clone_function_entry

        with app.app_context():
            cond = Conditional(unique_id=set_uuid())
            cond.name = '고온 경보'
            db.session.add(cond)
            db.session.commit()

            act = Actions(unique_id=set_uuid())
            act.function_id = cond.unique_id
            act.action_type = 'output_on_off'
            db.session.add(act)
            cc = ConditionalConditions(unique_id=set_uuid())
            cc.conditional_id = cond.unique_id
            cc.condition_type = 'measurement'
            db.session.add(cc)
            db.session.commit()

            cond.conditional_statement = (
                f'm = self.condition("{cc.unique_id[:8]}")\n'
                f'self.run_action("{act.unique_id}")')
            db.session.commit()

            copy, id_maps = clone_function_entry(cond, name='고온 경보 (Copy)')

            new_act = Actions.query.filter(
                Actions.function_id == copy.unique_id).one()
            new_cc = ConditionalConditions.query.filter(
                ConditionalConditions.conditional_id == copy.unique_id).one()

            assert new_act.unique_id != act.unique_id
            assert new_cc.unique_id != cc.unique_id
            assert new_act.unique_id in copy.conditional_statement
            assert new_cc.unique_id[:8] in copy.conditional_statement
            assert act.unique_id not in copy.conditional_statement
            assert cc.unique_id[:8] not in copy.conditional_statement

            # 원본은 손대지 않는다.
            assert act.unique_id in cond.conditional_statement
            assert id_maps['actions'][act.unique_id] == new_act.unique_id
            db.session.remove()


class TestIndividualDuplicateNames:
    """개별 복제도 같은 이름을 두 번 만들지 않는다.

    `output_duplicate()` 는 "Copy of X" 를 무조건 붙였다. 두 번 복제하면
    화면에 똑같은 이름이 둘 생기고, 출력 목록은 이름밖에 보여 주지 않는다.
    """

    def test_second_output_copy_gets_a_distinct_name(self, app):
        from aot.aot_flask.extensions import db
        from aot.aot_flask.utils import utils_output
        from aot.databases import set_uuid
        from aot.databases.models import Output

        class _Form:
            class _Field:
                def __init__(self, data):
                    self.data = data

            def __init__(self, output_id):
                self.output_id = _Form._Field(output_id)

        with app.test_request_context():
            out = Output(unique_id=set_uuid())
            out.name = 'v11'
            out.output_type = 'virtual_on_off_single'
            db.session.add(out)
            db.session.commit()

            utils_output.output_duplicate(_Form(out.unique_id))
            utils_output.output_duplicate(_Form(out.unique_id))

            names = sorted(row[0] for row in db.session.query(Output.name).all())
            assert names == ['Copy of v11', 'Copy of v11 (2)', 'v11']
            db.session.remove()

    def test_paired_copy_does_not_share_physical_channels(self, app):
        """비우기가 저장되지 않아 조용히 되돌아가던 자리이기도 하다."""
        from aot.aot_flask.extensions import db
        from aot.aot_flask.utils import utils_output
        from aot.databases import set_uuid
        from aot.databases.models import Output, OutputChannel
        from aot.outputs.paired_actuator_common import (
            PAIRED_ACTUATOR_OUTPUT_TYPES)

        class _Form:
            class _Field:
                def __init__(self, data):
                    self.data = data

            def __init__(self, output_id):
                self.output_id = _Form._Field(output_id)

        with app.test_request_context():
            out = Output(unique_id=set_uuid())
            out.name = '측창'
            out.output_type = sorted(PAIRED_ACTUATOR_OUTPUT_TYPES)[0]
            db.session.add(out)
            db.session.commit()

            ch = OutputChannel(unique_id=set_uuid())
            ch.output_id = out.unique_id
            ch.channel = 0
            ch.custom_options = json.dumps({
                'output_open_id': 'open-a,open-b',
                'output_close_id': 'close-a,close-b',
                'last_position_pct': 100.0,
                'travel_time_open_sec': 8.0,
            })
            db.session.add(ch)
            db.session.commit()

            utils_output.output_duplicate(_Form(out.unique_id))
            db.session.commit()

            copy = Output.query.filter(Output.name == 'Copy of 측창').one()
            copy_ch = OutputChannel.query.filter(
                OutputChannel.output_id == copy.unique_id).one()
            opts = json.loads(copy_ch.custom_options)
            assert opts['output_open_id'] == ''
            assert opts['output_close_id'] == ''
            assert opts['last_position_pct'] == 0.0
            assert opts['travel_time_open_sec'] == 8.0

            # 원본은 그대로다.
            src_ch = OutputChannel.query.filter(
                OutputChannel.output_id == out.unique_id).one()
            assert json.loads(src_ch.custom_options)['output_open_id'] == 'open-a,open-b'
            db.session.remove()

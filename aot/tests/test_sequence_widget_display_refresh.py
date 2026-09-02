# coding=utf-8
"""시퀀스 위젯 설정 모달이 **저장 시점이 아니라 지금** Trigger 값을 보여준다.

## 왜 이 테스트가 있나

이 위젯의 시간·주기 필드는 Trigger 를 정본으로 삼아 복사해 둔 캐시
(`Widget.custom_options`)다. `execute_at_modification` 이 그 위젯을 **저장할
때만** Trigger 와 다시 맞춘다. 그런데 대시보드의 요일별 시간 편집기(시간휠)는
Trigger 를 직접 고친다 — 실제 관수는 그 즉시 바뀌는데, 이 위젯을 다시 저장하기
전까지 설정 모달은 저장 당시의 옛 값을 계속 보여준다.

실측(aot-004, 2026-09-02): Trigger.timer_end_time 은 15:00 이고 데몬도 15:00
으로 돌고 있었는데(라이브 RPC 로 직접 확인), 위젯 설정 모달은 16:00 을 보여주고
있었다. output_duration(0.0 대 실제 20.0)·time_offset_minutes(300 대 실제 0)
도 같이 밀려 있었다.

`refresh_display_values` 훅이 대시보드를 열 때마다 이 필드들을 Trigger 에서
다시 읽어 캐시를 대신한다. 저장하지는 않으므로 되먹임은 없다 — 사용자가 이
위젯을 저장하면 그 시점의 Trigger 값을 또 그대로 반영할 뿐이다.
"""
import pytest

from aot.config import ProdConfig


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    db_file = tmp_path / "refresh.db"

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


def _trigger(**overrides):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import Trigger

    t = Trigger(unique_id=set_uuid())
    t.trigger_type = 'trigger_sequence'
    t.name = '테스트 시퀀스'
    t.is_activated = True
    t.timer_start_time = '05:30'
    t.timer_end_time = '15:00'
    t.period = 36000.0
    t.timer_start_offset = 10
    t.output_duration = 20.0
    t.time_offset_minutes = 0
    t.resume_on_activate = True
    for k, v in overrides.items():
        setattr(t, k, v)
    db.session.add(t)
    db.session.commit()
    return t


class TestRefreshDisplayValues:

    def test_stale_end_time_is_replaced_by_the_triggers_current_value(self, app):
        """핵심 회귀. aot-004 사건을 그대로 재현한다."""
        with app.app_context():
            from aot.widgets.widget_trigger_sequence import refresh_display_values

            trigger = _trigger()
            stale = {
                'function_id': trigger.unique_id,
                'timer_start_time': '05:30',
                'timer_end_time': '16:00',       # 저장 당시 값 — 그 뒤 15:00 으로 바뀜
                'sequence_period': 36000.0,
                'timer_start_offset': 10,
                'output_duration': 0.0,          # 실제는 20.0
                'time_offset_minutes': 300,       # 실제는 0
                'resume_on_activate': 'resume',
                'refresh_seconds': 5.0,
                'show_details': 'Show',
            }

            fresh = refresh_display_values('widget-1', stale)

            assert fresh['timer_end_time'] == '15:00'
            assert fresh['output_duration'] == 20.0
            assert fresh['time_offset_minutes'] == 0

    def test_zero_is_a_real_value_not_a_missing_one(self, app):
        """`or 기본값` 이면 0 이 '없음' 으로 읽혀 기본값으로 덮인다 — 이 값들은
        전부 0 이 유효하다(교차지연 없음, 밸리디티 즉시만료 없음 등)."""
        with app.app_context():
            from aot.widgets.widget_trigger_sequence import refresh_display_values

            trigger = _trigger(timer_start_offset=0, output_duration=0.0,
                               time_offset_minutes=0)
            fresh = refresh_display_values('widget-1', {'function_id': trigger.unique_id})

            assert fresh['timer_start_offset'] == 0
            assert fresh['output_duration'] == 0.0
            assert fresh['time_offset_minutes'] == 0

    def test_fields_the_trigger_does_not_own_are_left_alone(self, app):
        """function_id·refresh_seconds·show_details 는 Trigger 소관이 아니다 —
        건드리면 위젯 고유 설정이 이유 없이 사라진다."""
        with app.app_context():
            from aot.widgets.widget_trigger_sequence import refresh_display_values

            trigger = _trigger()
            values = {
                'function_id': trigger.unique_id,
                'refresh_seconds': 12.0,
                'show_details': 'Hide',
                'timer_end_time': '16:00',
            }

            fresh = refresh_display_values('widget-1', values)

            assert fresh['refresh_seconds'] == 12.0
            assert fresh['show_details'] == 'Hide'

    def test_an_unconfigured_widget_is_left_alone(self, app):
        """function_id 가 비어 있으면(아직 시퀀스를 고르지 않은 위젯) 보여줄
        정본이 없다 — 지우거나 0 으로 덮으면 더 나쁘다."""
        with app.app_context():
            from aot.widgets.widget_trigger_sequence import refresh_display_values

            values = {'function_id': '', 'timer_end_time': '16:00', 'show_details': 'Show'}
            fresh = refresh_display_values('widget-1', values)

            assert fresh == values

    def test_a_deleted_trigger_is_left_alone(self, app):
        """가리키던 시퀀스가 지워졌다 — 없는 값으로 덮지 않는다."""
        with app.app_context():
            from aot.widgets.widget_trigger_sequence import refresh_display_values

            values = {'function_id': 'no-such-trigger', 'timer_end_time': '16:00'}
            fresh = refresh_display_values('widget-1', values)

            assert fresh == values

    def test_resume_on_activate_is_translated_to_the_widgets_vocabulary(self, app):
        """Trigger 는 불리언, 위젯은 'resume'/'restart' 문자열 — 값이 아니라
        표현이 다를 뿐이니 새로고침이 그 변환까지 해야 한다."""
        with app.app_context():
            from aot.widgets.widget_trigger_sequence import refresh_display_values

            restart_trigger = _trigger(resume_on_activate=False)
            fresh = refresh_display_values(
                'widget-1', {'function_id': restart_trigger.unique_id, 'resume_on_activate': 'resume'})
            assert fresh['resume_on_activate'] == 'restart'

    def test_missing_options_values_does_not_crash(self, app):
        with app.app_context():
            from aot.widgets.widget_trigger_sequence import refresh_display_values
            assert refresh_display_values('widget-1', None) == {}

    def test_the_input_dict_is_not_mutated_in_place(self, app):
        """호출자가 원본을 계속 쓸 수 있어야 한다 — 참조를 공유하면 다른
        곳에서 예상 못 한 변화가 보인다."""
        with app.app_context():
            from aot.widgets.widget_trigger_sequence import refresh_display_values

            trigger = _trigger()
            original = {'function_id': trigger.unique_id, 'timer_end_time': '16:00'}
            snapshot = dict(original)

            refresh_display_values('widget-1', original)

            assert original == snapshot


class TestHookIsWired:

    def test_widget_registers_the_hook(self):
        from aot.widgets.widget_trigger_sequence import WIDGET_INFORMATION
        assert 'refresh_display_values' in WIDGET_INFORMATION
        assert WIDGET_INFORMATION['refresh_display_values'].__name__ == 'refresh_display_values'

    def test_dashboard_page_calls_the_hook(self):
        """훅을 만들어 두기만 하고 부르는 자리가 없으면 아무 일도 안 일어난다."""
        import inspect
        from aot.aot_flask import routes_dashboard

        src = inspect.getsource(routes_dashboard._build_dashboard_render_context)
        assert "meta['refresh_display_values']" in src

    def test_the_hook_call_is_guarded(self):
        """위젯 하나의 새로고침이 실패해도 대시보드 전체가 죽으면 안 된다."""
        import ast
        import inspect
        from aot.aot_flask import routes_dashboard

        src = inspect.getsource(routes_dashboard._build_dashboard_render_context)
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                body_src = ast.dump(node)
                if 'refresh_display_values' in body_src:
                    found = True
        assert found, "refresh_display_values 호출이 try 블록 밖에 있다"

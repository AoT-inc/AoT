# coding=utf-8
"""새로 만든 trigger_sequence 는 "입력 유효성"(time_offset_minutes) 을 안전한
기본값으로 시작해야 한다.

## 왜 이 테스트가 있나

`Trigger.time_offset_minutes` 컬럼의 SQLAlchemy 기본값은 0 이다 — 일출/일몰
트리거에선 "오프셋 0 분" 이라는 정상값이지만, trigger_sequence 에서는 뜻이
전혀 다르다: SequenceTriggerController.get_dynamic_duration() 이 이 값을
InfluxDB 조회의 `max_age` 로 넘기고, `query_flux()` 는 `if past_sec:` 로만
판정하므로 0(과 None) 은 둘 다 range 필터 없이 **전체 이력**을 본다. 즉 0 은
"입력 유효성 즉시 만료" 가 아니라 정반대로 **"신선도 제한 없음"** 이다 —
동적 동작 시간 참조가 아무리 오래된(며칠·몇 주 전) 값이든 최신인 것처럼
받아들인다.

화면(함수 설정 모달·시퀀스 위젯)은 이 필드가 None 일 때만 300 을 보여주므로,
컬럼 기본값 그대로 생성된 새 시퀀스는 화면에 "0" 이 그대로 보이고 실제로도
신선도 제한이 꺼진 채로 동작한다 — 사용자가 한 번도 이 칸을 만지지 않았는데도
그렇다.

0 자체의 뜻(신선도 제한 없음)은 기존 사용자가 의도적으로 설정했을 수 있는
값이라 바꾸지 않는다(test_sequence_widget_display_refresh.py 의
test_zero_is_a_real_value_not_a_missing_one 참고). 대신 새 시퀀스를 만드는
시점에 명시적으로 안전한 기본값(300 초)을 넣어, 사용자가 아무것도 안 건드려도
합리적인 신선도 제한을 갖고 시작하게 한다.
"""
import pytest

from aot.config import ProdConfig


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    db_file = tmp_path / "seq_default_validity.db"

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


def test_new_sequence_gets_a_safe_input_validity_default(app):
    """create_function_tool(function_type='trigger_sequence') 로 만든 새
    시퀀스는 time_offset_minutes 가 컬럼 기본값 0 이 아니라 300 이어야 한다."""
    from aot.tools.aot_data_tool_service import AoTDataToolService
    from aot.databases.models.function import Trigger

    with app.test_request_context():
        created = AoTDataToolService.create_function_tool(function_type='trigger_sequence')
        assert not created.get('error'), created

        trig = Trigger.query.filter_by(unique_id=created['function_id']).first()
        assert trig.time_offset_minutes == 300, (
            "새 시퀀스가 여전히 컬럼 기본값 0(신선도 제한 없음)으로 만들어졌다")


def test_new_sequence_via_create_sequence_function_gets_the_same_default(app):
    """장치를 바로 붙여 만드는 create_sequence_function 경로도 같은 기본값을
    받아야 한다 — 두 생성 경로가 같은 function_add() 를 쓰지만, 그 사실에
    의존하지 않고 실제로 확인한다."""
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import Output
    from aot.tools.aot_data_tool_service import AoTDataToolService
    from aot.databases.models.function import Trigger

    with app.test_request_context():
        oid = set_uuid()
        out = Output(unique_id=oid)
        out.name = "valve-0"
        db.session.add(out)
        db.session.commit()

        created = AoTDataToolService.create_sequence_function(
            name='seq-default-validity', device_ids=[oid], state='on', step_duration=30)
        assert not created.get('error'), created

        trig = Trigger.query.filter_by(unique_id=created['function_id']).first()
        assert trig.time_offset_minutes == 300


def test_non_sequence_trigger_keeps_the_column_default(app):
    """일출/일몰 트리거 등 다른 타입은 0 이 정상값이다 — 시퀀스 전용 기본값
    주입이 다른 타입까지 건드리면 안 된다."""
    from aot.tools.aot_data_tool_service import AoTDataToolService
    from aot.databases.models.function import Trigger

    with app.test_request_context():
        created = AoTDataToolService.create_function_tool(function_type='trigger_sunrise_sunset')
        assert not created.get('error'), created

        trig = Trigger.query.filter_by(unique_id=created['function_id']).first()
        assert trig.time_offset_minutes == 0, "시퀀스가 아닌 타입의 기본값을 건드렸다"

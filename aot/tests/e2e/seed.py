# coding=utf-8
"""E2E 픽스처 시드 — **E2E 컨테이너 안에서** 돈다.

    docker compose -f docker/docker-compose.e2e.yml exec -T aot-app \
        python -m aot.tests.e2e.seed

멱등이다. 다시 돌리면 자기가 만든 것만 지우고 새로 만든다(이름으로 식별).
E2E 는 매번 같은 상태에서 시작해야 판정이 재현되므로, 테스트 사이에 이걸
다시 부를 수 있어야 한다.

**안전핀**: `AOT_E2E=1` 환경변수가 없으면 아무것도 하지 않고 종료한다.
이 파일이 실수로 개발 스택(8084)이나 운영 서버에서 실행되는 사고를 막는다.
그 환경변수는 docker-compose.e2e.yml 에만 있다.
"""
import datetime
import json
import os
import sys


def _refuse_unless_e2e_stack():
    """E2E 스택이 아니면 즉시 멈춘다."""
    if os.environ.get('AOT_E2E') != '1':
        sys.stderr.write(
            '거부: AOT_E2E=1 이 아닙니다. 이 스크립트는 E2E 전용 컨테이너\n'
            '(docker/docker-compose.e2e.yml)에서만 실행됩니다. 개발/운영\n'
            'DB 에 픽스처를 쓰지 않기 위한 안전핀입니다.\n')
        raise SystemExit(2)


_refuse_unless_e2e_stack()

from aot.aot_flask.extensions import db  # noqa: E402
from aot.databases.models import (  # noqa: E402
    Actions, Camera, EnergyUsage, GeoLayer, Method, MethodData, Conditional, Dashboard, DeviceMeasurements, Function, GeoJournal,
    GeoFacility, GeoMap, GeoPlot, GeoShape, Input, MCPConfirmation, Output, OutputChannel,
    SchedulerJobMeta, Trigger, User, Widget)
from aot.tests.e2e import fixtures as F  # noqa: E402


def _app():
    """모델만 붙인 최소 Flask 앱.

    `create_app()` 을 쓰지 않는 이유: 이미 떠 있는 앱 프로세스와 같은 파일
    DB 를 열기만 하면 되고, 전체 부팅(AI 부트스트랩·MCP 프로비저닝·스케줄러)
    을 한 번 더 도는 것은 느리고 부작용이 있다.
    """
    from flask import Flask
    from aot.config import AOT_DB_PATH
    import aot.databases.models  # noqa: F401  — 모델 등록

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = AOT_DB_PATH
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


# --------------------------------------------------------------------------
# 정리 — 이전 시드가 남긴 것만 지운다(이름으로 식별). 사람이 손으로 만든
# 것은 건드리지 않는다. 그래야 시드를 반복해도 안전하고, 디버깅 중에 만든
# 데이터가 갑자기 사라지지 않는다.
# --------------------------------------------------------------------------
def _purge():
    # 이름이 'E2E ' 로 시작하는 것은 **전부** 지운다 — 시드가 만든 것뿐 아니라
    # 여정이 만들었다 남긴 것(CRUD 검사의 임시 장치 등)까지 거둔다. 목록을
    # 이름 하나하나로 적으면 그런 잔재가 실행마다 쌓인다.
    for row in Input.query.filter(Input.name.like('E2E %')).all():
        DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == row.unique_id).delete()
        db.session.delete(row)

    # 일정에는 제목 열이 없다 — 달력 제목은 대상 장치 이름으로 만들어진다.
    # 그래서 **대상이 E2E 출력인 것**을 지운다(출력을 지우기 전에 해야 한다).
    _e2e_output_ids = [row.unique_id for row in
                       Output.query.filter(Output.name.like('E2E %')).all()]
    if _e2e_output_ids:
        SchedulerJobMeta.query.filter(
            SchedulerJobMeta.target_id.in_(_e2e_output_ids)
        ).delete(synchronize_session=False)

    # AI 승인 대기는 제목으로 고른다(대상 출력은 매번 새 id 로 다시 만들어진다).
    MCPConfirmation.query.filter(
        MCPConfirmation.title.like('E2E %')
    ).delete(synchronize_session=False)

    for row in Output.query.filter(Output.name.like('E2E %')).all():
        OutputChannel.query.filter(
            OutputChannel.output_id == row.unique_id).delete()
        DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == row.unique_id).delete()
        db.session.delete(row)

    for row in Function.query.filter(Function.name.like('E2E %')).all():
        Conditional.query.filter(
            Conditional.unique_id == row.unique_id).delete()
        Actions.query.filter(Actions.function_id == row.unique_id).delete()
        Trigger.query.filter(Trigger.unique_id == row.unique_id).delete()
        db.session.delete(row)

    for row in GeoPlot.query.filter(GeoPlot.name == F.GEO_PLOT).all():
        # 이 구획으로 만든 일지도 함께 지운다. 일지 여정이 돌 때마다 하나씩
        # 쌓이므로, 두고 보면 목록이 시험 산출물로 덮인다.
        GeoJournal.query.filter(GeoJournal.target_id == row.unique_id).delete()
        db.session.delete(row)

    # 도형은 **전부** 지운다. 이 스택에는 시드가 만든 것과 검사가 그리다 남긴
    # 것밖에 없다(AOT_E2E=1 안전핀이 개발·운영에서 이 스크립트를 막는다).
    #
    # 이름으로만 골라 지우면 그리기 여정이 남긴 도형이 실행마다 쌓인다 —
    # 사각형 하나를 그리면 본체와 라벨 보조 도형이 함께 생겨 두 개씩 는다.
    # 시드가 "같은 상태에서 시작한다" 를 보장하려면 그 잔재도 거둬야 한다.
    # 시설도 **전부** 지운다 — 시설의 외곽은 도형이라 위에서 지운 도형과 함께
    # 사라지는데, 시설 행만 남으면 외곽 없는 시설이 목록에 쌓인다. 이 스택의
    # 시설은 여정이 만든 것뿐이다(시드는 시설을 심지 않는다).
    for row in GeoFacility.query.all():
        db.session.delete(row)

    for row in GeoShape.query.all():
        db.session.delete(row)

    # 여정이 만들었다 남긴 것들. 카메라·에너지 항목은 시드가 만들지 않으므로
    # 이 스택의 것은 전부 여정의 잔재다.
    for row in Camera.query.all():
        db.session.delete(row)
    for row in EnergyUsage.query.all():
        db.session.delete(row)
    # 지도 레이어도 전부 — 추가하면 서비스 이름("GL: OpenStreetMap")으로 생겨
    # 이름으로는 고를 수 없고, 이 스택에는 시드가 심는 레이어가 없다.
    for row in GeoLayer.query.all():
        db.session.delete(row)
    for row in Method.query.filter(Method.name.like('E2E %')).all():
        MethodData.query.filter(MethodData.method_id == row.unique_id).delete()
        db.session.delete(row)
    from aot.databases.models.mcp_server import AgentMCPAccess, MCPServer
    for row in MCPServer.query.filter(MCPServer.name.like('E2E %')).all():
        AgentMCPAccess.query.filter(
            AgentMCPAccess.mcp_unique_id == row.unique_id).delete()
        db.session.delete(row)

    for row in Dashboard.query.filter(
            Dashboard.name.in_((F.DASHBOARD, F.CONTROL_DASHBOARD,
                                F.GROUP_DASHBOARD))).all():
        # 위젯이 대시보드에 매이는 열은 `tab_id` 다(이름과 달리 Tab 이 아니라
        # **대시보드의 unique_id** 가 들어간다 — dashboard.html 이
        # `table_widget.tab_id == dashboard_id` 로 거른다).
        Widget.query.filter(Widget.tab_id == row.unique_id).delete()
        db.session.delete(row)

    db.session.commit()


# --------------------------------------------------------------------------
# 사용자
# --------------------------------------------------------------------------
def _seed_users():
    made = []
    for name, password, email, role_id in (
            (F.ADMIN_USER, F.ADMIN_PASS, F.ADMIN_EMAIL, 1),   # Admin
            (F.GUEST_USER, F.GUEST_PASS, F.GUEST_EMAIL, 4),   # Guest
            (F.MONITOR_USER, F.MONITOR_PASS, F.MONITOR_EMAIL, 3),   # Monitor
            (F.EDITOR_USER, F.EDITOR_PASS, F.EDITOR_EMAIL, 2)):  # Editor
        user = User.query.filter(User.name == name).first()
        if user is None:
            user = User()
            user.name = name
            user.email = email
            user.role_id = role_id
            user.theme = '/static/css/bootstrap-4-themes/aot.css'
            made.append(name)
        # 비밀번호와 이메일은 매번 다시 건다 — 이전 실행에서 바뀌었을 수 있고,
        # 이메일이 낡으면(검증을 통과하지 못하는 주소 등) 사용자 설정 저장이
        # 폼 전체 거부로 막힌다.
        user.email = email
        user.set_password(password)
        user.is_approved = True
        user.is_enabled = True
        # 실패 카운터와 잠금을 푼다. 로그인 여정이 틀린 비밀번호를 한 번씩
        # 넣어 보므로, 쌓이면 몇 번째 실행에서 계정이 잠겨 **그 뒤 모든**
        # E2E 가 로그인부터 실패한다(잠금은 계정 단위, 기본 5회/10분).
        user.failed_login_count = 0
        user.locked_until = None
        user.save()
    return made


# --------------------------------------------------------------------------
# 입력 — 하드웨어가 없어도 실제로 값을 내는 드라이버만 쓴다.
# --------------------------------------------------------------------------
def _seed_inputs():
    ram = Input()
    ram.name = F.INPUT_RAM
    ram.device = 'AOT_RAM'
    ram.period = 60.0
    ram.is_activated = False
    ram.save()
    for ch, (meas, unit, mname) in enumerate((
            ('disk_space', 'MB', 'System RAM Free'),
            ('disk_space', 'MB', 'System RAM Used'))):
        dm = DeviceMeasurements()
        dm.name = mname
        dm.device_id = ram.unique_id
        dm.device_type = 'input'
        dm.measurement = meas
        dm.unit = unit
        dm.channel = ch
        dm.is_enabled = True
        dm.save()

    cpu = Input()
    cpu.name = F.INPUT_CPU
    cpu.device = 'RPiCPULoad'
    cpu.period = 60.0
    cpu.is_activated = False
    cpu.save()
    dm = DeviceMeasurements()
    dm.name = 'CPU Load 1m'
    dm.device_id = cpu.unique_id
    dm.device_type = 'input'
    dm.measurement = 'cpu_load'
    dm.unit = 'cpu_load'
    dm.channel = 0
    dm.is_enabled = True
    dm.save()

    # 전류(A) 채널 — 전류 기반 에너지 사용량 화면이 고를 측정. 값은
    # _seed_measurements 가 일정하게(ENERGY_INPUT_AMPS) 써 넣는다.
    dm = DeviceMeasurements()
    dm.name = F.ENERGY_INPUT_MEASUREMENT
    dm.device_id = cpu.unique_id
    dm.device_type = 'input'
    dm.measurement = 'electrical_current'
    dm.unit = 'A'
    dm.channel = 1
    dm.is_enabled = True
    dm.save()
    return [ram.unique_id, cpu.unique_id]


# --------------------------------------------------------------------------
# 출력 — **채널 0개짜리를 반드시 포함한다.**
#
# 2026 년에 실제로 났던 회귀가 정확히 그 조건에서 났다: "채널 행이 없는 출력의
# On/Off 버튼이 통째로 사라지던 것", "채널 0개 카드 빈 흰 상자". 픽스처에
# 정상 카드만 있으면 그 사고는 E2E 를 통과한다.
# --------------------------------------------------------------------------
def _seed_outputs():
    multi = Output()
    multi.name = F.OUTPUT_MULTI
    multi.output_type = 'virtual_on_off_multi'
    multi.save()
    for ch in range(F.EXPECTED_OUTPUT_MULTI_CHANNELS):
        oc = OutputChannel()
        oc.output_id = multi.unique_id
        oc.channel = ch
        oc.name = f'E2E Channel {ch}'
        # 채널 0 에만 전류를 준다 — 에너지 사용량은 전류가 있는 채널만 센다.
        oc.custom_options = json.dumps(
            {'name': '', 'amps': F.ENERGY_OUTPUT_AMPS if ch == 0 else 0.0})
        oc.save()

    bare = Output()
    bare.name = F.OUTPUT_NOCHANNEL
    bare.output_type = 'virtual_on_off_single'
    bare.save()   # 채널 행을 일부러 만들지 않는다

    pwm = Output()
    pwm.name = F.OUTPUT_PWM
    pwm.output_type = 'python_pwm'
    pwm.save()
    oc = OutputChannel()
    oc.output_id = pwm.unique_id
    oc.channel = 0
    oc.name = 'E2E PWM Channel'
    oc.save()

    return [multi.unique_id, bare.unique_id, pwm.unique_id]


# --------------------------------------------------------------------------
# 함수
# --------------------------------------------------------------------------
def _seed_functions(input_ids):
    fn = Function()
    fn.name = F.FUNCTION_CONDITIONAL
    fn.function_type = 'conditional_conditional'
    fn.save()

    cond = Conditional()
    cond.unique_id = fn.unique_id
    cond.name = F.FUNCTION_CONDITIONAL
    cond.is_activated = False
    cond.save()
    return fn.unique_id


# --------------------------------------------------------------------------
# 대시보드 + 위젯 — 회귀가 잦은 위젯을 고른다(지도·측정·시퀀스).
# --------------------------------------------------------------------------
def _seed_dashboard():
    dash = Dashboard()
    dash.name = F.DASHBOARD
    dash.save()

    y = 0
    for widget_type, name, w, h in (
            ('widget_measurement', 'E2E Measurement', 4, 4),
            ('AoT_map', 'E2E Map', 8, 8),
            ('widget_notice', 'E2E Notice', 4, 4)):
        widget = Widget()
        widget.tab_id = dash.unique_id   # 위 _purge() 주석 참조
        widget.graph_type = widget_type
        widget.name = name
        widget.position_x = 0
        widget.position_y = y
        widget.width = w
        widget.height = h
        widget.custom_options = '{}'
        widget.save()
        y += h
    return dash.unique_id


def _enable_ai_menu():
    """AI 메뉴를 켠 상태로 둔다.

    `ai_enabled` 기본값은 False 이고, 그 상태에서는 AI 화면들이 403 을 받는다
    (설계대로다 — 메뉴를 끈 설치이므로). 하지만 E2E 는 **기능이 켜진 화면**을
    검사해야 의미가 있으므로 픽스처에서 켠다. 내장 모델 실행 여부
    (`ai_autonomy`)는 건드리지 않는다 — 모델을 돌리는 것은 E2E 의 일이 아니다.
    """
    from aot.databases.models import AIGlobalSettings
    settings = AIGlobalSettings.query.first()
    if settings is None:
        settings = AIGlobalSettings()
    settings.ai_enabled = True
    settings.save()


def _seed_measurements(input_ids):
    """측정값 몇 시간치를 실제로 써 넣는다.

    그래프는 값이 없으면 축도 그리지 않는다 — 데이터 없이 "기간 버튼이 축을
    바꾸는가" 를 보려 하면 아무것도 없는 화면을 재게 된다. 값은 InfluxDB 에
    들어가고, 지운 뒤 다시 심는 것이 아니라 **덮어 쓴다**(같은 시각·같은 태그면
    같은 점이다).

    실패해도 시드 전체를 막지 않는다 — 측정 DB 가 없는 환경에서도 나머지
    픽스처는 쓸 수 있어야 한다.
    """
    try:
        from aot.utils.influx import write_influxdb_value
    except Exception:                        # noqa: BLE001
        return 0

    now = datetime.datetime.utcnow()
    written = 0
    # **5일치**를 쓴다. 기간 버튼(1일·1주)이 축을 바꾸는지 보려면 데이터가 1일
    # 보다 뚜렷이 길어야 한다 — 26시간치로 했을 때는 "1일" 과 "전체" 의 폭이
    # 24h 대 25.5h 라 구별이 안 됐다.
    for offset_min in range(0, 60 * 24 * 5, 60):   # 5일치, 1시간 간격
        stamp = now - datetime.timedelta(minutes=offset_min)
        try:
            write_influxdb_value(
                input_ids[0], 'MB', 1000 + (offset_min % 120),
                measure='disk_space', channel=0, timestamp=stamp)
            written += 1
        except Exception:                    # noqa: BLE001
            return written

    # 전류 — 일정한 값이라 평균이 곧 그 값이다(검산이 쉽다). 최근 1시간 평균이
    # 비지 않도록 지난 2시간은 10분 간격으로 촘촘히.
    stamps = ([now - datetime.timedelta(minutes=m) for m in range(0, 120, 10)]
              + [now - datetime.timedelta(hours=h) for h in range(2, 24 * 5)])
    for stamp in stamps:
        try:
            write_influxdb_value(
                input_ids[1], 'A', float(F.ENERGY_INPUT_AMPS),
                measure='electrical_current', channel=1, timestamp=stamp)
            written += 1
        except Exception:                    # noqa: BLE001
            return written
    return written


def _seed_output_usage(output_ids):
    """출력이 켜져 있던 시간 — 에너지 사용량 화면이 세는 값.

    데몬은 출력을 끌 때 켜져 있던 초를 `duration_time` 으로 남긴다. 그것을
    직접 한 점(1시간) 써서 "지난 하루 1시간" 을 만든다.
    """
    try:
        from aot.utils.influx import write_influxdb_value
        # **실수로** 쓴다. 필드 형은 측정(단위)마다 처음 쓴 값으로 굳고, 데몬은
        # 켜짐 시간을 실수로 남긴다 — 정수를 쓰면 형 충돌(422)로 조용히 버려진다.
        write_influxdb_value(
            output_ids[0], 's', float(F.ENERGY_OUTPUT_SEC_ON),
            measure='duration_time', channel=0,
            timestamp=datetime.datetime.utcnow() - datetime.timedelta(hours=2))
        return True
    except Exception:                        # noqa: BLE001
        return False


def _seed_sequence(output_ids):
    """시퀀스 하나 — 단계 셋이 순서대로.

    순서의 정본은 `Actions.custom_options` 의 `gridstack_y` 다(모델의 `position`
    프로퍼티가 그것을 읽는다). 드래그 재정렬(`/function_save_order`)이 쓰는 값도
    이것이라, 시드도 같은 열에 적어야 화면이 시드 순서대로 그린다.
    """
    fn = Function()
    fn.name = F.FUNCTION_SEQUENCE
    fn.function_type = 'trigger_sequence'
    fn.save()

    trigger = Trigger()
    trigger.unique_id = fn.unique_id
    trigger.name = F.FUNCTION_SEQUENCE
    trigger.trigger_type = 'trigger_sequence'
    trigger.is_activated = False
    trigger.save()

    for index, step_name in enumerate(F.SEQUENCE_STEPS):
        action = Actions()
        action.function_id = fn.unique_id
        action.function_type = 'trigger_sequence'
        # 실제로 있는 액션 종류를 쓴다 — 없는 이름을 넣으면 화면이 카드마다
        # "Unknown Action" 을 그려, 무엇이 어느 단계인지 사람도 검사도 못 읽는다.
        action.action_type = 'output_on_off'
        action.do_unique_id = output_ids[0]
        action.do_output_state = 'on' if index % 2 == 0 else 'off'
        action.pause_duration = 5.0
        action.custom_options = json.dumps({
            # 순서의 정본. 드래그 재정렬(/function_save_order)이 쓰는 열과 같다.
            'gridstack_y': index,
            'name': step_name,
            'state': 'on' if index % 2 == 0 else 'off',
        })
        action.save()

    return fn.unique_id


def _seed_run_sequence(output_ids):
    """데몬이 실제로 돌리는 시퀀스 하나와, 그것을 보여 주는 위젯 하나.

    단계 하나 — E2E Virtual Multi 채널 1 을 SEQUENCE_RUN_STEP_SEC 동안 켠다.
    주기 SEQUENCE_RUN_PERIOD_SEC, 창은 하루 종일(시작=끝 "00:00" 은 24:00 까지로
    펼쳐진다 — weekly_schedule.from_legacy). 꺼 둔 채로 심는다 — 켜는 것은 검사다.
    """
    channel = OutputChannel.query.filter(
        OutputChannel.output_id == output_ids[0],
        OutputChannel.channel == F.SEQUENCE_RUN_CHANNEL).first()

    fn = Function()
    fn.name = F.SEQUENCE_RUN
    fn.function_type = 'trigger_sequence'
    fn.save()

    trigger = Trigger()
    trigger.unique_id = fn.unique_id
    trigger.name = F.SEQUENCE_RUN
    trigger.trigger_type = 'trigger_sequence'
    trigger.is_activated = False
    trigger.period = float(F.SEQUENCE_RUN_PERIOD_SEC)
    trigger.timer_start_time = '00:00'
    trigger.timer_end_time = '00:00'
    trigger.timer_weekday = None
    trigger.timer_start_offset = 0
    trigger.save()

    action = Actions()
    action.function_id = fn.unique_id
    action.function_type = 'trigger_sequence'
    action.action_type = 'output_on_off'
    action.custom_options = json.dumps({
        'output': f'{output_ids[0]},{channel.unique_id}',
        'state': 'on',
        'duration': 0,
        'action_duration': F.SEQUENCE_RUN_STEP_SEC,
        'sequence_mode': 'single',
        'enabled': True,
        'gridstack_y': 0,
        'name': F.SEQUENCE_RUN_STEP,
    })
    action.save()

    dash = Dashboard()
    dash.name = F.CONTROL_DASHBOARD
    dash.save()
    widget = Widget()
    widget.tab_id = dash.unique_id
    widget.graph_type = 'widget_trigger_sequence'
    widget.name = F.SEQUENCE_RUN
    widget.position_x = 0
    widget.position_y = 0
    widget.width = 12
    widget.height = 8
    widget.custom_options = json.dumps({
        'function_id': fn.unique_id, 'refresh_seconds': 5, 'show_details': True})
    widget.save()
    return fn.unique_id


def _seed_schedule(output_ids):
    """달력에 뜰 일정 하나.

    일정의 출처는 `SchedulerJobMeta` 다(노트가 아니다 — 달력은 여러 출처를
    합쳐 그린다). 승인 대기가 아니라 **확정된** 것으로 둔다: 상태에 따라
    달력에서 걸러지므로, DRAFT 로 두면 "일정이 없다" 로 보인다.
    """
    job = SchedulerJobMeta()
    job.action_type = 'output'
    job.target_id = output_ids[0]
    job.params_json = json.dumps({'state': 'on', 'duration': 60})
    job.reasoning = F.SCHEDULE_TITLE
    job.schedule_time = datetime.datetime.utcnow() + datetime.timedelta(hours=3)
    job.duration_sec = 60
    job.end_time = job.schedule_time + datetime.timedelta(seconds=60)
    job.proposed_by = 'HUMAN'
    job.approval_required = False
    # 달력이 보여 주는 상태는 정해져 있다(_CALENDAR_VISIBLE_STATES:
    # DRAFT·PENDING·RUNNING·COMPLETED·FAILED). 'APPROVED' 로 두면 저장은 되는데
    # 달력에서는 아무것도 안 보인다 — 검사가 "일정이 없다" 로 읽힌다.
    job.state = 'PENDING'
    job.save()
    return job.unique_id


def _seed_approvals(output_ids):
    """AI 가 올린 **물리 제어** 승인 대기 세 건 — 출력 켜기.

    모델 없이 만든다. 승인 대기는 모델이 무엇이었든 이 행 하나로 표현되고,
    검사가 보려는 것은 "사람이 결정하기 전에는 움직이지 않는다" 와
    "결정할 자격이 있는 사람만 결정한다" 이다 — 모델의 판단이 아니다.

    검사가 상태를 바꾸므로 쓰임새마다 한 건씩 둔다.
    """
    now = datetime.datetime.utcnow()
    for title in (F.APPROVAL_FOR_APPROVE, F.APPROVAL_FOR_REJECT,
                  F.APPROVAL_FOR_GUEST):
        row = MCPConfirmation()
        row.tool_name = 'operate_device'
        row.title = title
        row.params_json = json.dumps({'device_id': output_ids[0],
                                      'state': 'on'})
        row.reason = 'E2E'
        row.agent_id = 'e2e'
        row.status = 'pending'
        # 대기 목록을 읽을 때 만료가 정리되므로 스위트 한 바퀴보다 넉넉히.
        row.expires_at = now + datetime.timedelta(hours=6)
        row.save()


def _seed_geo_shapes():
    """지도에 도형을 놓는다 — 부지 하나와 그 안의 구역 하나.

    도형이 하나도 없으면 "도형이 사라지는" 회귀를 검사할 수 없다. 지도는
    신규 설치가 만들어 두는 설계 지도(category='design')를 그대로 쓴다.

    DB 트리거가 지키는 것(geo_integrity_ddl):
      * `type` 은 허용 어휘만
      * `feature.properties.aot_type` 키는 저장 불가 — `type` 컬럼이 정본이다
      * 폴리곤 링은 첫 점과 끝 점이 같아야 한다(열린 링은 포함 판정을 깨뜨린다)
    """
    geo_map = GeoMap.query.filter(GeoMap.category == 'design').first()
    if geo_map is None:
        geo_map = GeoMap()
        geo_map.name = 'E2E Design Map'
        geo_map.category = 'design'
        geo_map.save()

    def _polygon(lon, lat, size=0.0012):
        ring = [[lon, lat], [lon + size, lat], [lon + size, lat + size],
                [lon, lat + size], [lon, lat]]   # 닫힌 링
        return {'type': 'Polygon', 'coordinates': [ring]}

    site = GeoShape()
    site.geo_id = geo_map.unique_id
    site.type = 'site'
    site.feature = {
        'type': 'Feature',
        'geometry': _polygon(127.0, 37.0, 0.004),
        'properties': {'name': F.GEO_SITE},
    }
    site.save()

    zone = GeoShape()
    zone.geo_id = geo_map.unique_id
    zone.type = 'zone'
    zone.parent_id = site.id
    zone.feature = {
        'type': 'Feature',
        'geometry': _polygon(127.001, 37.001),
        'properties': {'name': F.GEO_ZONE},
    }
    zone.save()

    # 구획 — 일지·목표·자원 화면이 고르는 대상이다. 구획이 없으면 그 화면들의
    # 선택 목록이 비어, 검사가 "고를 것이 없어서" 통과해 버린다.
    plot = GeoPlot()
    plot.geo_id = geo_map.unique_id
    plot.name = F.GEO_PLOT
    plot.subject = F.GEO_PLOT_SUBJECT
    plot.kind = 'vegetation'
    plot.started_on = datetime.date.today() - datetime.timedelta(days=30)
    plot.feature = {
        'type': 'Feature',
        'geometry': _polygon(127.0015, 37.0015, 0.0008),
        'properties': {'name': F.GEO_PLOT},
    }
    plot.save()

    return geo_map.unique_id


def _seed_group_sequence(output_ids):
    """그룹이 있는 시퀀스 하나와, 그것을 보여 주는 위젯 하나.

    단독 · 그룹(둘) · 단독 순서. 위젯은 같은 그룹 이름의 단계를 한 블록으로
    묶어 **블록째로만** 끌게 한다 — 그 불변식을 드래그 검사가 본다. 꺼 둔 채로
    심는다(위젯은 데몬이 모르는 시퀀스도 DB 로 그린다).
    """
    channel = OutputChannel.query.filter(
        OutputChannel.output_id == output_ids[0],
        OutputChannel.channel == 0).first()

    fn = Function()
    fn.name = F.GROUP_SEQUENCE
    fn.function_type = 'trigger_sequence'
    fn.save()

    trigger = Trigger()
    trigger.unique_id = fn.unique_id
    trigger.name = F.GROUP_SEQUENCE
    trigger.trigger_type = 'trigger_sequence'
    trigger.is_activated = False
    trigger.period = 600.0
    trigger.timer_start_time = '00:00'
    trigger.timer_end_time = '00:00'
    trigger.timer_weekday = None
    trigger.timer_start_offset = 0
    trigger.save()

    for index, (step_name, group_name) in enumerate(F.GROUP_SEQUENCE_STEPS):
        action = Actions()
        action.function_id = fn.unique_id
        action.function_type = 'trigger_sequence'
        action.action_type = 'output_on_off'
        action.custom_options = json.dumps({
            'output': f'{output_ids[0]},{channel.unique_id}',
            'state': 'on',
            'duration': 0,
            'action_duration': 10,
            'sequence_mode': 'single',
            'group_name': group_name,
            'enabled': True,
            'gridstack_y': index,
            'name': step_name,
            'display_name': step_name,
        })
        action.save()

    dash = Dashboard()
    dash.name = F.GROUP_DASHBOARD
    dash.save()
    widget = Widget()
    widget.tab_id = dash.unique_id
    widget.graph_type = 'widget_trigger_sequence'
    widget.name = F.GROUP_SEQUENCE
    widget.position_x = 0
    widget.position_y = 0
    widget.width = 12
    # 단계 목록까지 한 화면에 — 잘리면 끌어 놓을 자리가 화면 밖이라 드래그가 안 된다.
    widget.height = 40
    widget.custom_options = json.dumps({
        # 'Show' 라야 단계 목록이 펼쳐진다 — 템플릿은 이 문자열만 본다(True 는 접힘).
        'function_id': fn.unique_id, 'refresh_seconds': 5, 'show_details': 'Show'})
    widget.save()
    return fn.unique_id


def main():
    app = _app()
    with app.app_context():
        _purge()
        _enable_ai_menu()
        users = _seed_users()
        input_ids = _seed_inputs()
        output_ids = _seed_outputs()
        _seed_functions(input_ids)
        _seed_sequence(output_ids)
        _seed_run_sequence(output_ids)
        _seed_group_sequence(output_ids)
        measurement_points = _seed_measurements(input_ids)
        _seed_output_usage(output_ids)
        _seed_schedule(output_ids)
        _seed_approvals(output_ids)
        _seed_geo_shapes()
        _seed_dashboard()
        db.session.commit()

    print('E2E 시드 완료')
    print(f'  사용자 신규 생성: {users or "(이미 있음 — 비밀번호만 재설정)"}')
    print(f'  입력 {len(input_ids)} · 출력 {len(output_ids)}'
          f'(채널 0개 1건 포함) · 함수 1 · 시퀀스 3(순서·실행·그룹) · '
          f'대시보드 3(위젯 3·시퀀스·그룹) · 도형 2(부지·구역) · 구획 1')


if __name__ == '__main__':
    main()

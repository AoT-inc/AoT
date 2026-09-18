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
    Actions, Conditional, Dashboard, DeviceMeasurements, Function, GeoJournal,
    GeoMap, GeoPlot, GeoShape, Input, Output, OutputChannel, SchedulerJobMeta,
    Trigger, User, Widget)
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
    for row in GeoShape.query.all():
        db.session.delete(row)

    for row in Dashboard.query.filter(Dashboard.name == F.DASHBOARD).all():
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
            (F.GUEST_USER, F.GUEST_PASS, F.GUEST_EMAIL, 4)):  # Guest
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
    for offset_min in range(0, 60 * 26, 30):   # 26시간치, 30분 간격
        stamp = now - datetime.timedelta(minutes=offset_min)
        try:
            write_influxdb_value(
                input_ids[0], 'MB', 1000 + (offset_min % 120),
                measure='disk_space', channel=0, timestamp=stamp)
            written += 1
        except Exception:                    # noqa: BLE001
            return written
    return written


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
        measurement_points = _seed_measurements(input_ids)
        _seed_schedule(output_ids)
        _seed_geo_shapes()
        _seed_dashboard()
        db.session.commit()

    print('E2E 시드 완료')
    print(f'  사용자 신규 생성: {users or "(이미 있음 — 비밀번호만 재설정)"}')
    print(f'  입력 {len(input_ids)} · 출력 {len(output_ids)}'
          f'(채널 0개 1건 포함) · 함수 1 · 시퀀스 1(단계 3) · '
          f'대시보드 1(위젯 3) · 도형 2(부지·구역) · 구획 1')


if __name__ == '__main__':
    main()

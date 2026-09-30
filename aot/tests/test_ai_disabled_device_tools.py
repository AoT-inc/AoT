# coding=utf-8
"""'AI 판단에 포함' 을 끈 장치(is_ai_enabled=False)는 AI 도구의 조회·제어 대상이 아니다.

매뉴얼 docs/ai/overview.md#device-ai-toggle. 예전에는 인앱 컨텍스트 조립만 이
값을 봤고, AI 도구(aot/tools — 외부 MCP·인앱 도구 호출)는 보지 않아 끈 장치를
그대로 찾고 움직였다. 판정은 공용 헬퍼(`device_resolver`) 하나이고, 사람 경로
(`resolve_output` 기본값 ai=False)는 영향이 없어야 한다.
"""
import pytest

from aot.config import ProdConfig


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    db_file = tmp_path / "ai_toggle.db"

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


@pytest.fixture
def ctx(app):
    with app.test_request_context():
        yield app


def _output(name, ai=True):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import Output, OutputChannel

    out = Output(unique_id=set_uuid())
    out.name = name
    out.output_type = 'virtual_on_off_single'
    out.is_ai_enabled = ai
    db.session.add(out)
    ch = OutputChannel(unique_id=set_uuid())
    ch.output_id = out.unique_id
    ch.channel = 0
    db.session.add(ch)
    db.session.commit()
    return out


def _input(name, ai=True):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import DeviceMeasurements, Input

    inp = Input(unique_id=set_uuid())
    inp.name = name
    inp.device = 'MQTT_PAHO_JSON'
    inp.is_activated = True
    inp.is_ai_enabled = ai
    db.session.add(inp)
    m = DeviceMeasurements(unique_id=set_uuid())
    m.device_id = inp.unique_id
    m.channel = 0
    m.measurement = 'temperature'
    m.unit = 'C'
    db.session.add(m)
    db.session.commit()
    return inp


def _no_daemon(monkeypatch):
    """제어가 데몬까지 가면 실패시킨다 — 거절은 그 앞에서 나야 한다."""
    import aot.aot_client as client

    class _Boom:
        def __init__(self, *a, **k):
            raise AssertionError("daemon must not be reached")
    monkeypatch.setattr(client, 'DaemonControl', _Boom)


# ── 공용 해석기 ────────────────────────────────────────────────────────────

def test_resolver_refuses_disabled_output_only_on_the_ai_path(ctx):
    from aot.services.resolvers.device_resolver import AI_EXCLUDED, resolve_output
    off = _output('ai-off valve', ai=False)

    ai = resolve_output(off.unique_id, ai=True)
    assert ai.row is None
    assert ai.reason == AI_EXCLUDED
    assert 'ai-off valve' in ai.error and 'Include in AI judgment' in ai.error

    # 사람 경로(기본값)는 그대로 찾는다.
    human = resolve_output(off.unique_id)
    assert human.row is not None and human.error is None


def test_disabled_twin_does_not_make_the_ai_name_ambiguous(ctx):
    from aot.services.resolvers.device_resolver import resolve_output
    on = _output('twin', ai=True)
    _output('twin', ai=False)

    assert resolve_output('twin', ai=True).row.unique_id == on.unique_id
    # 사람 경로는 예전처럼 겹침을 되묻는다.
    assert resolve_output('twin').error is not None


def test_null_toggle_counts_as_enabled(ctx):
    from aot.services.resolvers.device_resolver import ai_excluded
    row = _output('legacy', ai=True)
    row.is_ai_enabled = None
    assert not ai_excluded(row)


# ── 제어 도구 ─────────────────────────────────────────────────────────────

def test_operate_device_refuses_with_reason(ctx, monkeypatch):
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    _no_daemon(monkeypatch)
    off = _output('pump off-ai', ai=False)

    for token in (off.unique_id, 'pump off-ai'):
        out = S.operate_device_tool(token, 'on')
        assert out['reason_code'] == 'ai_excluded'
        assert out['dispatched'] is False
        assert 'Include in AI judgment' in out['error']


def test_schedule_device_control_refuses_with_reason(ctx):
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    off = _output('mist off-ai', ai=False)
    out = S.schedule_device_control_tool(off.unique_id, delay_seconds=60,
                                         state='on')
    assert out.get('reason_code') == 'ai_excluded', out
    assert out['dispatched'] is False


def test_native_set_output_state_refuses_with_reason(ctx, monkeypatch):
    from aot.tools import providers
    from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N

    def _never(*a, **k):
        raise AssertionError("action service must not be reached")
    monkeypatch.setattr(providers, 'get', lambda name: type(
        'X', (), {'execute_action': staticmethod(_never)}))
    off = _output('fan off-ai', ai=False)
    out = N.execute('set_output_state', {'device_id': off.unique_id,
                                         'state': 'on'})
    assert out['status'] == 'error'
    assert out['reason_code'] == 'ai_excluded'
    assert out['dispatched'] is False


def test_control_is_refused_before_the_approval_queue(ctx):
    """승인 큐에 넣기 전에 거절한다 — 어차피 실행에서 막힐 요청이 사람을 기다리지 않게."""
    from aot.tools import tool_execution as te
    off = _output('valve off-ai', ai=False)
    on = _output('valve on-ai', ai=True)

    for tool in ('operate_device', 'schedule_device_control', 'set_output_state'):
        out = te._pre_gate_validation(tool, {'device_id': off.unique_id,
                                             'state': 'on'})
        assert out is not None, tool
        assert out['reason_code'] == 'ai_excluded', tool
        assert 'Include in AI judgment' in out['message']
        assert te._pre_gate_validation(
            tool, {'device_id': on.unique_id, 'state': 'on'}) is None, tool


# ── 조회 도구 ─────────────────────────────────────────────────────────────

def test_lists_leave_out_disabled_devices(ctx):
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
    on_in, off_in = _input('probe shown'), _input('probe hidden', ai=False)
    on_out, off_out = _output('relay shown'), _output('relay hidden', ai=False)
    shown = {on_in.unique_id, on_out.unique_id}
    hidden = {off_in.unique_id, off_out.unique_id}

    listed = {r['id'] for r in S.get_device_list_tool()['results']}
    assert shown <= listed and not (hidden & listed)

    for query in ('probe', 'relay'):
        found = {r['id'] for r in S.search_devices(query=query)['results']}
        assert found and not (hidden & found)
    by_meas = {r['id'] for r in
               S.search_devices(measurement_type='temperature')['results']}
    assert on_in.unique_id in by_meas and off_in.unique_id not in by_meas

    native = {d['device_id'] for d in
              N.execute('list_available_devices', {})['devices']}
    assert shown <= native and not (hidden & native)

    fresh = S.get_device_freshness(include_fresh=True)
    seen = {e['device_id'] for k in ('stale_devices', 'no_data_devices',
                                     'inactive_devices', 'fresh_devices')
            for e in fresh.get(k) or []}
    assert on_in.unique_id in seen and off_in.unique_id not in seen


def test_targeted_reads_refuse_with_reason(ctx):
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
    off_in = _input('probe off-ai', ai=False)
    off_out = _output('relay off-ai', ai=False)

    results = [
        S.get_device_detail(off_in.unique_id),
        S.get_device_detail('relay off-ai'),
        S.get_device_measurements(off_in.unique_id),
        S.get_output_state(off_out.unique_id),
        S.get_sensor_detail(off_in.unique_id),
        S.get_sensor_detail('probe off-ai'),
        S.get_device_location(off_out.unique_id),
        N.execute('get_sensor_reading', {'device_id': off_in.unique_id}),
    ]
    for out in results:
        assert out.get('reason_code') == 'ai_excluded', out

    fr = S.get_device_freshness(device_id=off_in.unique_id)
    assert fr['reason_code'] == 'ai_excluded'


def test_spatial_tree_drops_disabled_device_nodes(ctx):
    from aot.ai.services.ai_context_service import AIContextService
    off = _output('hidden on map', ai=False)
    on = _output('shown on map', ai=True)
    tree = [{'name': 'site', 'type': 'site', 'children': [
        {'name': 'a', 'type': 'device', 'device_id': off.unique_id,
         'children': []},
        {'name': 'b', 'type': 'device', 'device_id': on.unique_id,
         'children': []},
    ]}]
    out = AIContextService._without_ai_excluded_nodes(tree)
    kids = [c['device_id'] for c in out[0]['children']]
    assert kids == [on.unique_id]
    # 캐시로 쓰이는 원본은 그대로다.
    assert len(tree[0]['children']) == 2

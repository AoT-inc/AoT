# coding=utf-8
"""물 회로 사전 계산(W5) — `measure.water_estimate` 와 승인 문구는 `planned_water` 의 같은 숫자를 읽는다."""
from aot.utils.timekit import FARM, today_at
import json
from unittest import mock

import pytest

from aot.tests.geo.test_water_net_link import EPOCH, _map, _Plot, linkdb  # noqa: F401  (linkdb 는 픽스처)
from aot.utils import water_estimate as WE

FLOWS = {'v1': {'lph': 3600.0, 'share': 1.0, 'source': 'map-equipment'}}


def _env():
    """구획 안 밸브 v1 만 물을 대고 면적은 100 m² — `_map(rated=30)` 의 펌프는 30 L/min, 밸브 수요는 60 L/min 이다."""
    stack = mock.patch('aot.aot_flask.geo.plot_journal.irrigation_flow_for_plot', return_value=FLOWS)
    area = mock.patch('aot.space.plot_context.area_m2', return_value=100.0)
    records = mock.patch('aot.utils.runtime.get_operational_intervals',
                         side_effect=AssertionError('사전 계산은 작동 기록을 읽지 않는다'))
    return stack, area, records


class _Env:
    def __enter__(self):
        self.ms = _env()
        for m in self.ms:
            m.start()

    def __exit__(self, *exc):
        for m in self.ms:
            m.stop()


def test_estimate_is_the_planned_water_calculation_with_the_assumptions_written(linkdb):
    _map(rated=30)
    with _Env():
        out = WE.estimate(_Plot(), ['v1'], 600, now=EPOCH)
    assert out['litres'] == 300.0 and out['design_litres'] == 600.0
    assert out['mm'] == 3.0                       # 합친 물량 ÷ 면적
    assert out['basis'] == 'estimated' and out['network_rev']
    assert out['window'] == {'from': EPOCH, 'to': EPOCH + 600} and out['outputs'] == ['v1']
    assert 'Other outputs on this circuit stay off' in out['assumptions'] and 'tank' in out['assumptions']
    assert any(c.startswith('pump-over-demand') for c in out['caveats'])
    assert any(c.startswith('water-supply-limited') for c in out['caveats'])   # 경고는 알릴 뿐 막지 않는다
    json.dumps(out)


def test_depth_is_litres_over_area_not_the_sum_of_rounded_run_depths(linkdb):
    _map(rated=30)
    with _Env():
        out = WE.estimate(_Plot(), ['v1'], 7, now=EPOCH)       # 3.5 L → 0.035 mm (실행별 mm 은 0.04 로 반올림된다)
    assert out['litres'] == 3.5
    assert out['mm'] == round(3.5 / 100.0, 2)


def test_estimate_refuses_what_it_cannot_answer(linkdb):
    _map(rated=30)
    with _Env():
        with pytest.raises(WE.EstimateError):
            WE.estimate(_Plot(), ['v1'], 0, now=EPOCH)
        with pytest.raises(WE.EstimateError):
            WE.estimate(_Plot(), ['v2'], 600, now=EPOCH)        # 이 구획에 물을 대지 않는 밸브


def test_a_failed_calculation_is_an_error_not_the_design_value(linkdb):
    _map(rated=30)
    with _Env(), mock.patch('aot.utils.water_net_link.planned_water', side_effect=RuntimeError('boom')):
        out = WE.estimate_or_error(_Plot(), ['v1'], 600, now=EPOCH)
    assert out['status'] == 'error' and 'no design-value fallback' in out['message'] and 'litres' not in out


def test_compare_lines_the_estimate_up_with_the_recorded_run():
    est = {'litres': 300.0, 'mm': 3.0, 'network_rev': 'abc'}
    same = WE.compare(est, {'litres': 280.0, 'mm': 2.8, 'network_rev': 'abc'})
    assert same['same_network'] and same['litres'] == {'estimated': 300.0, 'actual': 280.0, 'diff': -20.0}
    assert WE.compare(est, {'litres': 280.0, 'mm': 2.8, 'network_rev': 'xyz'})['same_network'] is False
    # 회로 해시가 한쪽에라도 없으면(공급 부품이 없는 지도) 모르는 것이다 — 도면이 바뀐 것처럼 False 로 내지 않는다.
    assert WE.compare({'litres': 1.0, 'network_rev': None}, {'litres': 1.0, 'network_rev': None})['same_network'] is None
    assert WE.compare(est, {'litres': 1.0, 'network_rev': None})['same_network'] is None


def test_recent_runs_report_a_missing_circuit_hash_as_none():
    from aot.utils import water_net_link
    from aot.utils.water_store import NO_REV
    assert water_net_link._rev_or_none(NO_REV) is None and water_net_link._rev_or_none('') is None
    assert water_net_link._rev_or_none('abc') == 'abc'


def test_estimate_and_the_recorded_run_agree_through_delivered_summary_fields(linkdb):
    """같은 구간이면 사전 계산과 기록으로 푼 값이 같다 — 나란히 놓을 때 `network_rev`·물량이 일치한다."""
    from aot.tests.geo.test_water_net_link import _plot_water
    _map(rated=30)
    with _Env():
        est = WE.estimate(_Plot(), ['v1'], 600, now=EPOCH)
    seen = _plot_water({'v1': [(EPOCH, EPOCH + 600)]}, full=True, stored=False)
    run = seen.result['runs'][0]
    diff = WE.compare(est, {'litres': run['litres'], 'mm': seen.result['totals']['mm'],
                            'network_rev': seen.result['network_rev']})
    assert diff['same_network'] and diff['litres']['diff'] == 0.0 and diff['mm']['diff'] == 0.0


# ── 승인 문구 ────────────────────────────────────────────────────────────

def _args(**kw):
    return dict({'device_id': 'v1', 'state': 'on', 'duration_seconds': 600}, **kw)


def test_approval_note_carries_litres_mm_and_warnings(linkdb):
    _map(rated=30)
    with _Env(), mock.patch.object(WE, 'plots_for_outputs', return_value=[(_Plot(), ['v1'])]):
        note = WE.approval_note('operate_device', _args())
    assert '300 L' in note and '3.0 mm' in note and '[추정]' in note and 'pump-over-demand' in note


def test_approval_note_says_so_when_the_estimate_fails_and_does_not_raise(linkdb):
    _map(rated=30)
    with _Env(), mock.patch.object(WE, 'plots_for_outputs', return_value=[(_Plot(), ['v1'])]), \
            mock.patch('aot.utils.water_net_link.planned_water', side_effect=RuntimeError('boom')):
        note = WE.approval_note('operate_device', _args())
    assert '예상 물량 없음' in note


def test_approval_note_without_a_run_time_says_there_is_no_estimate(linkdb):
    with mock.patch.object(WE, 'plots_for_outputs', return_value=[(_Plot(), ['v1'])]):
        assert '예상 물량 없음' in WE.approval_note('operate_device', {'device_id': 'v1', 'state': 'on'})
        assert '예상 물량 없음' in WE.approval_note('set_output_state', {'device_id': 'v1', 'state': 'on', 'duration': 0})


def test_approval_note_is_empty_for_devices_off_the_water_circuit_and_for_off(linkdb):
    with mock.patch.object(WE, 'plots_for_outputs', return_value=[]):
        assert WE.approval_note('operate_device', _args()) == ''
    assert WE.approval_note('operate_device', _args(state='off')) == ''
    assert WE.approval_note('schedule_device_control', _args()) == ''
    assert WE.approval_note('operate_device', {}) == ''


def test_read_back_reads_back_plainly_outside_the_water_circuit_and_adds_the_note_inside(linkdb):
    from aot.tools import mcp_safety_gate as gate
    with mock.patch.object(gate, '_resolve_device_display_name', return_value='밸브1'), \
            mock.patch.object(WE, 'plots_for_outputs', return_value=[]):
        plain = gate.read_back_text('operate_device', _args())
    assert plain == '밸브1 을 10분 동안 켜기'
    _map(rated=30)
    with _Env(), mock.patch.object(gate, '_resolve_device_display_name', return_value='밸브1'), \
            mock.patch.object(WE, 'plots_for_outputs', return_value=[(_Plot(), ['v1'])]):
        text = gate.read_back_text('operate_device', _args())
    assert text.startswith(plain) and '300 L' in text


# ── MCP 표면 ─────────────────────────────────────────────────────────────

def test_water_estimate_is_a_read_op_on_existing_names_and_adds_no_schema_arg():
    from aot.tools.domain.registry_data import OPS
    op = next(o for o in OPS if (o.tool, o.op) == ('measure', 'water_estimate'))
    assert op.effect == 'read' and set(op.inner.values()) == {'get_plot'}
    assert all(d == {'detail': 'water_estimate'} for d in op.defaults_by_kind.values())
    assert not op.shown                                   # 스키마에 인자를 싣지 않는다 — help 가 이름을 준다


def test_get_plot_water_estimate_resolves_plots_from_outputs_and_reports_errors(linkdb):
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    _map(rated=30)
    with _Env(), mock.patch.object(S, '_read_device', return_value=(mock.Mock(unique_id='v1'), 'output', None)), \
            mock.patch.object(WE, 'plots_for_outputs', return_value=[(_Plot(), ['v1'])]):
        out = S.get_plot(detail='water_estimate', device_ids=['v1'], duration_minutes=10)
        missing = S.get_plot(detail='water_estimate', device_ids=['v1'])
    assert out['status'] == 'success' and out['litres'] > 0 and out['basis'] == 'estimated'
    assert missing['status'] == 'error' and 'duration' in missing['message']


def test_get_plot_water_estimate_asks_which_valve_when_a_plot_has_several(linkdb):
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    two = dict(FLOWS, v2={'lph': 3600.0, 'share': 1.0, 'source': 'map-equipment'})
    with mock.patch.object(S, '_read_plot', return_value=(_Plot(), None)), \
            mock.patch('aot.aot_flask.geo.plot_journal.irrigation_flow_for_plot', return_value=two):
        out = S.get_plot(plot_id='p1', detail='water_estimate', duration_seconds=60)
    assert out['status'] == 'error' and out['outputs'] == ['v1', 'v2']


# ── 재배 중인 구획만, 이름으로, 물과 무관한 장치에는 문구 없이 ────────────────────────────

def _grow(uid, subject='콩', ended_on=None, name=None, geo_id='wnl-map-1'):
    from datetime import date, timedelta
    from aot.databases.models import GeoPlot
    GeoPlot(unique_id=uid, geo_id=geo_id, subject=subject, name=name, kind='vegetation',
            started_on=today_at(FARM) - timedelta(days=60), ended_on=ended_on,
            feature=_Plot.feature).save()


def _ended():
    from datetime import date, timedelta
    return today_at(FARM) - timedelta(days=3)


def test_only_plots_being_grown_are_considered(linkdb):
    _map(rated=30)
    _grow('p-now', subject='콩')
    _grow('p-old', subject='상추', ended_on=_ended())
    with _Env():
        found = WE.plots_for_outputs(['v1'])
    assert [p.unique_id for p, _ids in found] == ['p-now']


def test_the_label_is_the_plot_name_or_crop_never_the_uuid(linkdb):
    _map(rated=30)
    _grow('3b42f23a-0000-0000-0000-000000000000', subject='콩')
    with _Env():
        note = WE.approval_note('operate_device', _args())
    assert '콩 예상 약 300 L' in note and '3b42f23a' not in note
    named = type('P', (), {'name': '평안', 'subject': '콩', 'unique_id': 'abcdef12-0'})()
    unnamed = type('P', (), {'name': None, 'subject': None, 'unique_id': 'abcdef12-0'})()
    assert WE.plot_label(named) == '평안' and WE.plot_label(unnamed) == '구획' and 'abcdef12' not in WE.plot_label(unnamed)


def test_an_ended_plot_cannot_be_estimated(linkdb):
    from aot.databases.models import GeoPlot
    _map(rated=30)
    _grow('p-old', ended_on=_ended())
    with _Env():
        with pytest.raises(WE.EstimateError, match='not being grown'):
            WE.estimate(GeoPlot.query.filter_by(unique_id='p-old').first(), ['v1'], 600, now=EPOCH)


def test_a_device_off_the_water_circuit_gets_no_text_and_costs_no_flow_reads(linkdb):
    """조명·창은 담당 폴리곤이 없다 — 구획을 풀지 않고 빈 문구다. 구획이 몇 개든 같다(상한 문구가 붙지 않는다)."""
    from aot.databases.models import Output
    _map(rated=30)
    Output(unique_id='lamp', name='lamp').save()
    for i in range(WE.MAX_PLOTS_SCANNED + 5):
        _grow('p%d' % i)
    with mock.patch('aot.aot_flask.geo.plot_journal.irrigation_flow_for_plot',
                    side_effect=AssertionError('물과 무관한 장치는 흐름을 풀지 않는다')):
        assert WE.approval_note('operate_device', _args(device_id='lamp')) == ''
        assert WE.plots_for_outputs(['lamp']) == []


def test_many_plots_never_put_a_cap_message_on_the_approval(linkdb, monkeypatch):
    _map(rated=30)
    monkeypatch.setattr(WE, 'MAX_PLOTS_SCANNED', 2)
    for i in range(5):
        _grow('p%d' % i)
    with _Env():
        note = WE.approval_note('operate_device', _args())
    assert '구획이 많아' not in note and '300 L' in note


def test_get_plot_water_estimate_refuses_an_ended_plot(linkdb):
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    _map(rated=30)
    _grow('p-old', ended_on=_ended())
    with _Env():
        out = S.get_plot(plot_id='p-old', detail='water_estimate', device_ids=['v1'], duration_minutes=10)
    assert out['status'] == 'error' and 'not being grown' in out['message']

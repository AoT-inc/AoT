# coding=utf-8
"""물 회로 글루 — DB 에서 지도를 풀고, API 게이트를 지키고, MCP 응답 모양을 지킨다."""
import json
from unittest import mock

import pytest

from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoShape
from aot.functions.utils.water_net import adapters as A

MAP = 'wnl-map-1'
FRAME = A.LocalFrame(128.0, 35.0)


def _lnglat(x, z):
    return FRAME.to_lnglat((x, 0.0, z))


def _line(pid, *xz, sub='pipe_branch'):
    return {'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': [_lnglat(x, z) for x, z in xz]},
            'properties': {'sub_type': sub, 'node_id': pid, 'aot_type': 'equipment'}}


def _cov(pid, x, z, flow=850):
    lng, lat = _lnglat(x, z)
    return {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [[[lng, lat]] * 4]},
            'properties': {'sub_type': 'sprinkler_coverage', 'node_id': pid, 'flow': flow,
                           'center_lat': lat, 'center_lng': lng}}


def _part(pid, kind, x, z):
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': _lnglat(x, z)},
            'properties': {'sub_type': kind, 'node_id': pid, 'name': pid}}


def _ring(x0, z0, x1, z1):
    return [_lnglat(x0, z0), _lnglat(x1, z0), _lnglat(x1, z1), _lnglat(x0, z1), _lnglat(x0, z0)]


def _zone(uid, name, ring, kind='zone'):
    GeoShape(unique_id=uid, geo_id=MAP, type=kind,
             feature={'type': 'Feature', 'properties': {'name': name, 'node_id': uid},
                      'geometry': {'type': 'Polygon', 'coordinates': [ring]}}).save()


def _seed(extra=()):
    feats = [_line('main', (0, 0), (40, 0), sub='pipe_main'), _line('b', (20, 0), (20, 30)),
             _cov('c1', 20, 10), _cov('c2', 20, 20), _part('pump', 'pump', 0, 0),
             _part('V', 'valve_inline', 20, 5)] + list(extra)
    GeoShape(unique_id='wnl-eq', geo_id=MAP, type='equipment_collection',
             feature={'type': 'FeatureCollection', 'features': feats}).save()


@pytest.fixture()
def linkdb():
    from flask import Flask
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    from flask_babel import Babel
    Babel(app)
    with app.app_context():
        db.create_all()
        GeoMap(unique_id=MAP, name='M').save()
        yield db
        db.session.remove()
        db.drop_all()


def _report():
    from aot.utils import water_net_link
    return water_net_link.report_for_map(MAP)


def test_report_for_an_empty_map(linkdb):
    report = _report()
    assert report['summary'] is None and report['checks'] == [] and report['networks'] == []


def test_report_is_json_and_gives_paths_and_counts(linkdb):
    _seed()
    report = _report()
    json.dumps(report)
    assert report['summary']['emitter_attached_pct'] == 100.0
    assert report['summary']['branch_joined_pct'] == 100.0
    assert report['networks'][0]['supplied'] is True
    assert [s['id'] for s in report['networks'][0]['sources']] == ['pump']
    valve = next(p for p in report['parts'] if p['id'] == 'V')
    assert [s['id'] for s in valve['path']] == ['pump', 'main', 'b']
    assert valve['downstream_emitters'] == 2
    assert report['check_counts'] == {}


def test_report_does_not_write(linkdb):
    _seed()
    before = GeoShape.query.filter_by(unique_id='wnl-eq').first().feature
    _report()
    db.session.rollback()
    assert GeoShape.query.filter_by(unique_id='wnl-eq').first().feature == before


def test_unsupplied_circuit_gets_no_path(linkdb):
    GeoShape(unique_id='wnl-eq', geo_id=MAP, type='equipment_collection',
             feature={'type': 'FeatureCollection',
                      'features': [_line('main', (0, 0), (40, 0), sub='pipe_main'),
                                   _cov('c1', 20, 0)]}).save()
    _zone('z1', 'A', _ring(10, -5, 30, 5))
    report = _report()
    assert report['check_counts'] == {'no-source': 1}
    circuit = report['areas'][0]['circuits'][0]
    assert circuit['supplied'] is False and circuit['path'] == [] and circuit['sources'] == []


def test_area_membership_is_by_location(linkdb):
    _seed()
    _zone('z1', 'A', _ring(15, 8, 25, 12))
    _zone('s1', 'Site', _ring(-5, -5, 45, 35), kind='site')
    report = _report()
    rows = {r['name']: r for r in report['areas']}
    assert rows['A']['emitters'] == 1 and rows['Site']['emitters'] == 2
    assert [s['id'] for s in rows['A']['circuits'][0]['path']] == ['pump', 'main', 'b', 'V', 'b']


def test_flow_defaulted_by_the_zone_is_counted_apart(linkdb):
    _seed([_cov('c3', 20, 25, flow=0)])
    GeoShape(unique_id='z1', geo_id=MAP, type='zone',
             feature={'type': 'Feature',
                      'properties': {'name': 'A', 'gen_config_sprinkler': {'flow': 500}},
                      'geometry': {'type': 'Polygon', 'coordinates': [_ring(15, 22, 25, 28)]}}).save()
    row = next(c for c in _report()['checks'] if c['code'] == 'emitter-no-flow')
    assert row['emitters'] == 1 and row['zone_default'] == 1


def test_area_path_is_short_and_counts_unsupplied_circuits(linkdb):
    from aot.utils import water_net_link
    _seed([_line('far', (100, 0), (100, 20)), _cov('c9', 100, 10)])
    _zone('z1', 'A', _ring(-5, -5, 120, 35))
    out = water_net_link.area_water_path(MAP, 'z1')
    assert out['circuits'] == 2 and out['no_source'] == 1
    assert out['supplied'] == [{'sources': ['pump'], 'path': ['pump', 'main', 'branch', 'V', 'branch']}]


def test_area_path_without_nozzles_is_none(linkdb):
    from aot.utils import water_net_link
    _seed()
    _zone('z1', 'A', _ring(500, 500, 510, 510))
    assert water_net_link.area_water_path(MAP, 'z1') is None


def _marker(uid, device_id, x, z):
    GeoShape(unique_id=uid, geo_id=MAP, type='aot_device', device_id=device_id,
             feature={'type': 'Feature', 'properties': {},
                      'geometry': {'type': 'Point', 'coordinates': _lnglat(x, z)}}).save()


def test_part_links_a_marker_without_a_binding_row(linkdb):
    """현재 바인딩이 없고 옛 컬럼만 있는 마커도 Output·Input 이면 연결된다."""
    from aot.databases.models import Output
    Output(unique_id='wnl-out', name='v1').save()
    _seed()
    _marker('m1', 'wnl-out', 21, 5)
    valve = next(p for p in _report()['parts'] if p['id'] == 'V')
    assert valve['device'] == 'wnl-out' and valve['device_name'] == 'v1'


def test_two_markers_at_a_part_leave_it_unlinked(linkdb):
    from aot.databases.models import Input, Output
    Output(unique_id='wnl-out', name='v1').save()
    Input(unique_id='wnl-in', name='s1').save()
    _seed()
    _marker('m1', 'wnl-out', 21, 5)
    _marker('m2', 'wnl-in', 19, 5)
    report = _report()
    assert next(p for p in report['parts'] if p['id'] == 'V')['device'] is None
    row = next(c for c in report['checks'] if c['code'] == 'part-device-ambiguous')
    assert sorted(row['candidates']) == ['s1', 'v1']


# ── 구획 물량 ──────────────────────────────────────────────────────────────

class _Plot:
    unique_id = 'p1'
    geo_id = MAP
    facility_uuid = None
    feature = {'type': 'Feature', 'properties': {},
               'geometry': {'type': 'Polygon', 'coordinates': [_ring(10, 8, 30, 12)]}}


T0, T1 = '2026-10-01T00:00:00Z', '2026-10-03T00:00:00Z'
EPOCH = 1790812800.0          # 2026-10-01T00:00:00Z


def _area(uid, device_id, ring):
    GeoShape(unique_id=uid, geo_id=MAP, type='device', device_id=device_id,
             feature={'type': 'Feature', 'properties': {},
                      'geometry': {'type': 'Polygon', 'coordinates': [ring]}}).save()


def _pump_feature(rated, x=0, z=0, pid='pump'):
    row = _part(pid, 'pump', x, z)
    if rated:
        row['properties']['rated_lpm'] = rated
    return row


def _map(rated=30):
    """주관 하나, 노즐 넷(각 1800 L/h = 30 L/min). 밸브 v1 은 구획 안 c1·c2, v2 는 구획 밖 c3·c4."""
    from aot.databases.models import Output
    Output(unique_id='v1', name='v1').save()
    Output(unique_id='v2', name='v2').save()
    feats = [_line('main', (0, 0), (60, 0), sub='pipe_main'), _line('b', (20, 0), (20, 30)),
             _line('b2', (40, 0), (40, 30)), _cov('c1', 20, 10, 1800), _cov('c2', 20, 11, 1800),
             _cov('c3', 40, 10, 1800), _cov('c4', 40, 11, 1800), _pump_feature(rated)]
    GeoShape(unique_id='wnl-eq', geo_id=MAP, type='equipment_collection',
             feature={'type': 'FeatureCollection', 'features': feats}).save()
    _area('a1', 'v1', _ring(15, 5, 25, 15))
    _area('a2', 'v2', _ring(35, 5, 45, 15))


def _plot_water(runs, flows=None, plot=None, **kw):
    from aot.utils import water_net_link
    flows = {'v1': {'lph': 3600.0, 'share': 1.0, 'source': 'map-equipment'}} \
        if flows is None else flows

    def _read(oid, *_a, **_k):
        return runs.get(oid, [])

    with mock.patch('aot.aot_flask.geo.plot_journal.irrigation_flow_for_plot', return_value=flows), \
         mock.patch('aot.utils.runtime.get_operational_intervals', side_effect=_read), \
         mock.patch('aot.aot_flask.geo.plot_context.area_m2', return_value=100.0):
        return water_net_link.plot_water(plot or _Plot(), T0, T1, 'UTC', **kw)


def _key(day=1):
    from datetime import date
    return date(2026, 10, day)


def test_map_without_supply_never_solves_the_graph(linkdb):
    from aot.databases.models import Output
    from aot.utils import water_net_link
    Output(unique_id='v1', name='v1').save()
    GeoShape(unique_id='wnl-eq', geo_id=MAP, type='equipment_collection',
             feature={'type': 'FeatureCollection', 'features': [_line('main', (0, 0), (40, 0))]}).save()
    with mock.patch.object(water_net_link, 'network_for_map') as solved:
        water = _plot_water({'v1': [(EPOCH, EPOCH + 600)]})
    solved.assert_not_called()
    assert water.ratios == {} and water.result is None and water.caveats == []
    assert water.cell('v1', _key(), 600) == {
        'litres': 600.0, 'share': 1.0, 'estimated': True, 'source': 'map-equipment'}


def test_facility_plot_keeps_its_value(linkdb):
    from aot.utils import water_net_link

    class _Facility(_Plot):
        facility_uuid = 'f1'

    with mock.patch.object(water_net_link, '_map_features') as read:
        water = _plot_water({}, plot=_Facility())
    read.assert_not_called()
    assert water.cell('v1', _key(), 600)['litres'] == 600.0


def test_circuit_without_supply_keeps_its_value(linkdb):
    """공급 부품이 다른 회로에만 있으면 이 구획의 값은 그대로다."""
    _map(rated=30)
    GeoShape.query.filter_by(unique_id='wnl-eq').delete()
    from aot.aot_flask.extensions import db as _db
    _db.session.commit()
    GeoShape(unique_id='wnl-eq', geo_id=MAP, type='equipment_collection',
             feature={'type': 'FeatureCollection',
                      'features': [_line('b', (20, 0), (20, 30)), _cov('c1', 20, 10, 1800),
                                   _line('far', (500, 0), (520, 0)),
                                   _pump_feature(30, x=500)]}).save()
    water = _plot_water({'v1': [(EPOCH, EPOCH + 600)]})
    assert 'design_litres' not in water.cell('v1', _key(), 600)
    assert water.result is None


def test_pump_limits_the_plot_and_keeps_the_design_value(linkdb):
    # v1 수요 60 L/min, 펌프 30. 600초 설계 600 L, 전달 300 L, 비율 0.5.
    _map(rated=30)
    water = _plot_water({'v1': [(EPOCH, EPOCH + 600)]})
    cell = water.cell('v1', _key(), 600)
    assert cell['litres'] == 300.0 and cell['design_litres'] == 600.0
    assert cell['delivered_ratio'] == 0.5
    assert water.caveats[:2] == ['water-supply-limited:300.0:600.0', 'pump-over-demand:10']
    assert 'pump-state-unknown' in water.caveats


def test_a_valve_outside_the_plot_shares_the_pump(linkdb):
    # v1(60)·v2(60) 겹침, 펌프 90. 구획 밖 v2 도 같은 펌프를 쓴다 → v1 은 45 L/min, 비율 0.75.
    _map(rated=90)
    water = _plot_water({'v1': [(EPOCH, EPOCH + 600)], 'v2': [(EPOCH, EPOCH + 600)]})
    assert water.cell('v1', _key(), 600)['delivered_ratio'] == 0.75
    assert water.cell('v1', _key(), 600)['litres'] == 450.0


def test_demand_is_the_whole_polygon_not_the_plot_part(linkdb):
    # v1 폴리곤에 구획 밖 노즐 c5 를 더하면 수요가 90 이 된다. 구획 몫은 그대로 2/3 이 아니라
    # 비율로 깎인다: 펌프 45 / 수요 90 = 0.5.
    _map(rated=45)
    row = GeoShape.query.filter_by(unique_id='wnl-eq').first()
    feats = list(row.feature['features']) + [_cov('c5', 20, 14, 1800)]
    row.feature = {'type': 'FeatureCollection', 'features': feats}
    row.save()
    water = _plot_water({'v1': [(EPOCH, EPOCH + 600)]})
    assert water.cell('v1', _key(), 600)['delivered_ratio'] == 0.5


def test_output_across_two_circuits_splits_by_nozzle_flow(linkdb):
    # c1 은 펌프 회로(30 L/min 공급, 수요 30 → 비율 1 이 아니라 아래처럼 15), c2 는 공급 없는 끊긴 회로.
    # 펌프 15 / c1 30 = 0.5. 구획 몫 c1 1/2 · c2 1/2 → 0.5×0.5 + 1×0.5 = 0.75.
    from aot.databases.models import Output
    Output(unique_id='v1', name='v1').save()
    feats = [_line('a', (0, 10), (15, 10)), _cov('c1', 15, 10, 1800), _pump_feature(15, 0, 10),
             _line('z', (22, 11), (40, 11)), _cov('c2', 22, 11, 1800)]
    GeoShape(unique_id='wnl-eq', geo_id=MAP, type='equipment_collection',
             feature={'type': 'FeatureCollection', 'features': feats}).save()
    _area('a1', 'v1', _ring(12, 5, 28, 15))
    water = _plot_water({'v1': [(EPOCH, EPOCH + 600)]})
    assert water.cell('v1', _key(), 600)['delivered_ratio'] == 0.75


def test_days_get_their_own_ratio_and_totals_agree(linkdb):
    # 1일은 혼자(비율 0.5), 2일은 v2 와 겹침(펌프 30 / 수요 120 = 0.25).
    _map(rated=30)
    day2 = EPOCH + 86400
    water = _plot_water({'v1': [(EPOCH, EPOCH + 600), (day2, day2 + 600)],
                         'v2': [(day2, day2 + 600)]})
    assert water.cell('v1', _key(1), 600)['litres'] == 300.0
    assert water.cell('v1', _key(2), 600)['litres'] == 150.0
    assert water.litres('v1', {_key(1): 600, _key(2): 600}) == 450.0
    assert water.result['runs'][0]['mm'] == 3.0


def test_run_is_booked_on_the_bucket_of_its_start(linkdb):
    # 일지처럼 켠 시각의 날짜에 싣는다. 자정을 넘긴 실행도 전날이다.
    from aot.utils import water_net_link
    assert water_net_link._bucket_key(EPOCH - 1, 3600, 'UTC', 'day').isoformat() == '2026-09-30'
    assert water_net_link._bucket_key(EPOCH, 3600, 'UTC', 'day').isoformat() == '2026-10-01'


def test_failed_run_read_falls_back_and_says_so(linkdb):
    _map(rated=30)
    water = _plot_water({'v1': None})
    assert water.caveats == ['water-supply-not-read'] and water.result is None
    assert water.cell('v1', _key(), 600)['litres'] == 600.0


def test_result_contract_is_json_and_carries_rev(linkdb):
    _map(rated=30)
    res = _plot_water({'v1': [(EPOCH, EPOCH + 600)]}).result
    json.dumps(res)
    assert res['target'] == {'kind': 'plot', 'id': 'p1'} and res['level'] == 'L0'
    assert len(res['network_rev']) == 12
    assert res['supply'][0]['delivered_ratio'] == 0.5
    run = res['runs'][0]
    assert (run['seconds'], run['demand_lpm'], run['delivered_lpm']) == (600, 60.0, 30.0)
    assert (run['litres'], run['mm']) == (300.0, 3.0)


def test_output_linked_to_a_pump_is_a_supply_output(linkdb):
    from aot.databases.models import Output
    _map(rated=30)
    Output(unique_id='npump', name='N').save()
    _marker('m1', 'npump', 1, 0)
    water = _plot_water({'v1': [(EPOCH, EPOCH + 600)], 'npump': [(EPOCH, EPOCH + 600)]})
    assert water.supply_outputs == {'npump'}
    assert 'pump-state-unknown' not in water.caveats


def test_pump_off_is_read_from_its_output(linkdb):
    from aot.databases.models import Output
    _map(rated=100)
    Output(unique_id='npump', name='N').save()
    _marker('m1', 'npump', 1, 0)
    water = _plot_water({'v1': [(EPOCH, EPOCH + 600)], 'npump': []})
    assert water.cell('v1', _key(), 600)['litres'] == 0.0
    assert 'valve-without-pump:10' in water.caveats


def test_tank_level_comes_from_its_input(linkdb):
    # 수위 % × 용량. 50% × 1000 L = 500 L, 60 L/min 600초 → 500 L 에서 바닥(500초).
    from aot.databases.models import DeviceMeasurements, Input
    _map(rated=100)
    row = GeoShape.query.filter_by(unique_id='wnl-eq').first()
    tank = _part('tank', 'tank', 5, 0)
    tank['properties']['capacity_l'] = 1000
    row.feature = {'type': 'FeatureCollection', 'features': list(row.feature['features']) + [tank]}
    row.save()
    Input(unique_id='lvl', name='L').save()
    DeviceMeasurements(unique_id='dm1', device_id='lvl', measurement='level', unit='percent',
                       channel=0).save()
    _marker('m2', 'lvl', 6, 0)
    with mock.patch('aot.utils.influx.read_influxdb_list', return_value=[(EPOCH - 60, 50.0)]):
        water = _plot_water({'v1': [(EPOCH, EPOCH + 600)]})
    assert water.result['supply'][0]['tank']['start_l'] == 500.0
    assert water.cell('v1', _key(), 600)['litres'] == 500.0
    assert any(c.startswith('tank-empty:10-01 00:08') for c in water.caveats)


def test_length_level_is_not_guessed_into_litres(linkdb):
    from aot.databases.models import DeviceMeasurements, Input
    from aot.utils import water_net_link
    Input(unique_id='lvl', name='L').save()
    DeviceMeasurements(unique_id='dm1', device_id='lvl', measurement='level', unit='m',
                       channel=0).save()
    assert water_net_link._read_levels('lvl', 1000.0, T0, T1) is None


def test_drip_without_spacing_has_no_flow_and_says_so(linkdb):
    from aot.functions.utils.water_net import result as R
    from aot.utils import water_net_link
    drip = _line('d', (0, 0), (40, 0))
    drip['properties'].update(is_drip=True, drip_config={'flow': 2.0})
    net = A.from_map_features([drip, _part('pump', 'pump', 0, 0)])
    assert [em.flow_lph for em in net.emitters] == [None]
    assert water_net_link._extra_caveats(net, [net.component_id('pump')]) == [R.DRIP_FLOW_UNKNOWN]


def test_pump_upstream_of_the_tank_is_flagged(linkdb):
    from aot.functions.utils.water_net import result as R
    from aot.utils import water_net_link
    net = A.from_map_features([_line('m', (0, 0), (40, 0)), _part('s', 'source_well', 0, 0),
                               _part('pump', 'pump', 10, 0), _part('tank', 'tank', 20, 0)])
    assert water_net_link._extra_caveats(net, [0]) == [R.PUMP_BEFORE_TANK]


def test_pump_is_not_counted_as_missing_water():
    from aot.aot_flask.geo.plot_journal.calc import outputs_without_water
    rows = [{'output_id': 'v1', 'water': {'litres': 1.0}}, {'output_id': 'pump'}, {'output_id': 'v9'}]
    assert outputs_without_water(rows) == {'pump', 'v9'}
    assert outputs_without_water(rows, {'pump'}) == {'v9'}


def test_fold_adds_design_and_recomputes_the_ratio():
    from aot.aot_flask.geo.plot_journal import calc
    days = [{'key': '2026-10-01', 'date_label': 'a', 'env': [], 'notes': [], 'control': [
                {'output_id': 'v', 'name': 'v', 'hours': 1.0, 'seconds': 3600,
                 'water': {'litres': 50.0, 'share': 1.0, 'estimated': True, 'source': 'x',
                           'design_litres': 100.0, 'delivered_ratio': 0.5}}]},
            {'key': '2026-10-02', 'date_label': 'b', 'env': [], 'notes': [], 'control': [
                {'output_id': 'v', 'name': 'v', 'hours': 1.0, 'seconds': 3600,
                 'water': {'litres': 100.0, 'share': 1.0, 'estimated': True, 'source': 'x',
                           'design_litres': 100.0, 'delivered_ratio': 1.0}}]}]
    row = calc.fold_buckets(days, to="week")[0]['control'][0]
    assert row['water']['litres'] == 150.0 and row['water']['design_litres'] == 200.0
    assert row['water']['delivered_ratio'] == 0.75


def test_fold_of_plain_rows_gains_no_new_keys():
    from aot.aot_flask.geo.plot_journal import calc
    days = [{'key': '2026-10-01', 'date_label': 'a', 'env': [], 'notes': [], 'control': [
        {'output_id': 'v', 'name': 'v', 'hours': 1.0, 'seconds': 3600,
         'water': {'litres': 50.0, 'share': 1.0, 'estimated': True, 'source': 'x'}}]}]
    water = calc.fold_buckets(days, to="week")[0]['control'][0]['water']
    assert water == {'litres': 50.0, 'share': 1.0, 'estimated': True, 'source': 'x'}


@pytest.mark.parametrize('key', [
    'water-supply-limited:300.0:600.0', 'pump-over-demand:10', 'source-over-demand:10',
    'valve-without-pump:10', 'pump-dead-head:10', 'tank-empty:10-01 00:08', 'supply-unknown',
    'pump-state-unknown', 'tank-level-unknown', 'pump-before-tank', 'drip-flow-unknown',
    'water-supply-not-read'])
def test_every_new_caveat_has_a_sentence(key):
    from aot.aot_flask.geo.plot_journal import render
    text = render.caveat_text(key)
    assert text != key and '%(' not in text
    assert key.partition(':')[2].partition(':')[0] in text


# ── API ────────────────────────────────────────────────────────────────────

def _unwrap(fn):
    while hasattr(fn, '__wrapped__'):
        fn = fn.__wrapped__
    return fn


def _status(result):
    return result[1] if isinstance(result, tuple) else result.status_code


class _Gate:
    """라우트 게이트를 직접 부른다(`test_geo_api_write_gates` 와 같은 방식)."""

    def __init__(self, permission=True, operate=True):
        self.permission, self.operate = permission, operate

    def call(self, query):
        from flask import current_app
        from aot.aot_flask import routes_geo_map as R
        from aot.aot_flask.access import scope
        from aot.aot_flask.utils import utils_general
        view = _unwrap(R.api_geo_water_net)
        with current_app.test_request_context('/api/geo/water_net' + query), \
                mock.patch.object(utils_general, 'user_has_permission',
                                  return_value=self.permission), \
                mock.patch.object(scope, 'can_operate', return_value=self.operate) as gate, \
                mock.patch.object(scope, 'deny_message', return_value='no'):
            self.gate = gate
            return view()


def test_api_needs_a_map(linkdb):
    assert _status(_Gate().call('')) == 400


def test_api_refuses_a_role_without_the_design_permission(linkdb):
    _seed()
    gate = _Gate(permission=False)
    assert _status(gate.call('?map_uuid=' + MAP)) == 403
    gate.gate.assert_not_called()


def test_api_refuses_outside_the_group_scope(linkdb):
    _seed()
    gate = _Gate(operate=False)
    assert _status(gate.call('?map_uuid=' + MAP)) == 403
    gate.gate.assert_called_once_with('geo_map', MAP)


def test_api_says_when_the_map_is_gone(linkdb):
    assert _status(_Gate().call('?map_uuid=nope')) == 404


def test_api_answers_with_the_report(linkdb):
    _seed()
    res = _Gate().call('?map_uuid=' + MAP)
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True and body['summary']['networks'] == 1


# ── MCP ────────────────────────────────────────────────────────────────────

def _space():
    from aot.tools.aot_data_tool_service import AoTDataToolService
    return AoTDataToolService


def test_target_answer_carries_the_path(linkdb):
    S = _space()
    _seed()
    _zone('z1', 'A', _ring(15, 5, 25, 25))
    with mock.patch.object(S, '_exact_area_target', return_value=('zone', 'z1')), \
            mock.patch.object(S, '_with_target'):
        out = S.get_map_equipment_tool(area_name='A', brief=True)
    assert out['water_path'] == {'circuits': 1, 'supplied': [
        {'sources': ['pump'], 'path': ['pump', 'main', 'branch', 'V', 'branch']}]}
    assert len(json.dumps(out['water_path'])) < 300


def test_one_line_answer_keeps_its_shape(linkdb):
    S = _space()
    _seed()
    _zone('z1', 'A', _ring(15, 5, 25, 25))
    out = S.get_map_equipment_tool(brief=True)
    assert 'water_path' not in out and 'areas' in out


def test_a_broken_network_never_breaks_the_equipment_answer(linkdb):
    S = _space()
    _seed()
    _zone('z1', 'A', _ring(15, 5, 25, 25))
    from aot.utils import water_net_link
    with mock.patch.object(S, '_exact_area_target', return_value=('zone', 'z1')), \
            mock.patch.object(S, '_with_target'), \
            mock.patch.object(water_net_link, 'area_water_path', side_effect=ValueError):
        out = S.get_map_equipment_tool(area_name='A')
    assert out['status'] == 'success' and 'water_path' not in out

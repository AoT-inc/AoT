# coding=utf-8
"""프로필 정의와 화면 파싱 시험 — 서버 없이."""
from aot.tests.dashboard_bench import profiles as P


def test_profile_composition_matches_proposal():
    # P0 빈 화면
    assert P.widget_total('P0') == 0
    # P1: 측정값·지표 10 + 출력 2
    c1 = P.profile_counts('P1')
    assert c1['widget_measurement'] + c1['widget_indicator'] + c1['widget_gauge_solid'] == 10
    assert c1['AoT_output_pwm'] == 2 and sum(c1.values()) == 12
    # P2: P1 + 시계열 차트 3 + 타이머 1 + 시퀀스 1
    c2 = P.profile_counts('P2')
    assert {k: c2[k] - c1.get(k, 0) for k in c2 if c2[k] != c1.get(k, 0)} == {
        'AoT_graph': 3, 'AoT_timer': 1, 'widget_trigger_sequence': 1}
    # P3: P2 + 지도 1 + 시설 3D 1 + 카메라 1
    c3 = P.profile_counts('P3')
    assert {k: c3[k] - c2.get(k, 0) for k in c3 if c3[k] != c2.get(k, 0)} == {
        'AoT_map': 1, 'AoT_facility': 1, 'camera': 1}


def test_increment_profiles_add_exactly_one_kind_to_empty():
    assert P.profile_counts('I-chart') == {'AoT_graph': 1}
    assert P.profile_counts('I-map') == {'AoT_map': 1}
    assert P.profile_counts('I-facility') == {'AoT_facility': 1}
    assert P.profile_counts('I-camera') == {'camera': 1}


def test_heavy_widgets_come_first_in_p3():
    # 화면 위쪽 = 먼저 추가. 무거운 위젯이 접힌 곳에 있으면 지연 로딩에 걸려 안 그려진다.
    assert [t for t, _n in P.PROFILES['P3'][:3]] == ['AoT_map', 'AoT_facility', 'camera']


def test_every_profile_has_description():
    assert set(P.PROFILES) == set(P.DESCRIPTIONS)


_HTML = '''
<form id="add_widget_form"><input type="hidden" name="widget_type" value="widget_measurement">
<select name="measurement"><option value="">Select One</option>
<option value="in1,m1">[Input 01 CH0] BENCH CPU (CPU Load)</option>
<option value="in1,m2">[Input 01 CH1] BENCH CPU (5)</option></select></form>
<form id="add_widget_form"><input type="hidden" name="widget_type" value="AoT_timer">
<select name="output"><option value="">Select One</option><option value="o1,c1">Out [CH0]</option></select></form>
<form id="add_widget_form"><input type="hidden" name="widget_type" value="AoT_map">
<select name="map_uuid"><option value="">Select One</option></select></form>
'''


def test_parse_widget_choices_is_per_widget_and_skips_blank():
    ch = P.parse_widget_choices(_HTML)
    assert [v for v, _l in ch['widget_measurement']['measurement']] == ['in1,m1', 'in1,m2']
    assert ch['AoT_timer']['output'] == [('o1,c1', 'Out [CH0]')]
    assert ch['AoT_map']['map_uuid'] == []


def test_parse_dashboard_tabs_dedups():
    html = ('<a class="dropdown-item" href="/dashboard/11111111-1111-1111-1111-111111111111">'
            '<span class="d-none d-md-inline">BENCH P1</span></a>'
            '<a href="/dashboard/11111111-1111-1111-1111-111111111111"><span class="d-none d-md-inline">BENCH P1</span></a>'
            '<a href="/dashboard/22222222-2222-2222-2222-222222222222"><span class="d-none d-md-inline">Default</span></a>')
    assert P.parse_dashboard_tabs(html) == [
        ('11111111-1111-1111-1111-111111111111', 'BENCH P1'),
        ('22222222-2222-2222-2222-222222222222', 'Default')]


def _prep():
    prep = P.Prepared()
    prep.measurements = ['i,m1', 'i,m2', 'i,m3']
    prep.pwm_channels = ['p,c1', 'p2,c1']
    prep.onoff_channels = ['o,c0']
    prep.sequence = 'seq'
    prep.map_uuid = 'map'
    prep.camera = 'cam'
    prep.facility_ready = True
    return prep


def test_widget_fields_rotate_measurements_and_set_camera_refresh():
    prep = _prep()
    f0 = dict(P.widget_form_fields('widget_measurement', 0, prep))
    f4 = dict(P.widget_form_fields('widget_measurement', 4, prep))
    assert f0['measurement'] == 'i,m1' and f4['measurement'] == 'i,m2'
    assert f0['measurement_max_age'] == str(P.MAX_AGE_S)
    cam = dict(P.widget_form_fields('AoT_camera', 0, prep))
    assert cam['refresh_rate'] == '1' and cam['display_mode'] == 'snapshot'
    legacy = _prep()
    legacy.camera_legacy = 'old'
    assert dict(P.widget_form_fields('widget_camera', 0, legacy))['refresh_seconds'] == '1'


def test_widget_fields_none_when_prerequisite_missing():
    prep = P.Prepared()
    for wtype in ('widget_measurement', 'AoT_output_pwm', 'AoT_graph', 'AoT_timer',
                  'widget_trigger_sequence', 'AoT_map', 'AoT_facility', 'AoT_camera', 'widget_camera'):
        assert P.widget_form_fields(wtype, 0, prep) is None, wtype


def test_refuses_dev_server_port():
    import pytest
    with pytest.raises(SystemExit):
        P.main(['--url', 'http://127.0.0.1:8084'])

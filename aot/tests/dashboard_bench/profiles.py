# coding=utf-8
"""프로필 대시보드 생성기 — 대상 서버 URL 을 받아 같은 구성을 만든다(멱등).

    python -m aot.tests.dashboard_bench.profiles --url http://127.0.0.1:8085

만드는 대시보드(이름은 `BENCH <키>`):

    P0  빈 화면(위젯 0)
    P1  가벼움 — 측정값·지표 위젯 10 + 출력 2
    P2  표준   — P1 + 시계열 차트 3 + 타이머 1 + 시퀀스 1
    P3  무거움 — P2 + 지도 1 + 시설 3D 1 + 카메라 1(1초 갱신)
    I-chart / I-map / I-facility / I-camera
        — P0 에 위젯 **한 종류만** 더한 증분 대시보드(위젯별 한계 비용)

전부 **HTTP 로** 만든다(화면과 같은 폼 POST). 그래서 로컬 E2E 스택(8085)이든 맥미니든
파이든 URL 만 바꾸면 된다. 이 서버의 DB 를 직접 만지지 않으므로 이 스크립트가 일으키는
쓰기는 "대시보드·위젯 추가", "벤치용 장치 추가", "입력 활성화"뿐이다.

멱등: 같은 이름(`BENCH …`)의 대시보드가 있으면 지우고 다시 만든다. 장치는 이미 충분히
있으면 새로 만들지 않는다(필요한 만큼만 부족분을 만든다).

위젯이 **실제로 데이터를 받게** 하려고 입력(CPU 부하·남은 디스크 — 하드웨어 없이 값을 내는
드라이버)을 활성화하고, 측정 위젯은 그 측정값에, 출력 위젯은 PWM·온오프 출력에,
시퀀스는 시퀀스 함수에, 카메라는 URL 카메라(앱의 정적 이미지)에 묶는다.
쓰기 시험은 E2E 스택(8085)에서만 하라 — 개발 서버(8084)와 운영 서버에는 쓰지 않는다.
"""
import argparse
import json
import os
import re
import sys
import time

from aot.tests.dashboard_bench.aotclient import (
    AotClient, DEFAULT_URL, csrf_from_html)

NAME_PREFIX = 'BENCH '

# 프로필 정의 ---------------------------------------------------------------
# 한 줄 = (위젯 종류, 개수). 위쪽 위젯이 먼저 놓인다 — 지도·3D 같은 무거운 것은
# 화면 위쪽에 둬서 지연 로딩(IntersectionObserver)에 걸려 안 그려지는 일이 없게 한다.
HEAVY = [('AoT_map', 1), ('AoT_facility', 1), ('camera', 1)]
LIGHT = [('widget_measurement', 6), ('widget_indicator', 2),
         ('widget_gauge_solid', 2), ('AoT_output_pwm', 2)]
STANDARD_EXTRA = [('AoT_graph', 3), ('AoT_timer', 1),
                  ('widget_trigger_sequence', 1)]

PROFILES = {
    'P0': [],
    'P1': LIGHT,
    'P2': LIGHT + STANDARD_EXTRA,
    'P3': HEAVY + LIGHT + STANDARD_EXTRA,
    'I-chart': [('AoT_graph', 1)],
    'I-map': [('AoT_map', 1)],
    'I-facility': [('AoT_facility', 1)],
    'I-camera': [('camera', 1)],
}

DESCRIPTIONS = {
    'P0': '빈 화면(위젯 0)',
    'P1': '가벼움: 측정값·지표 10 + 출력 2',
    'P2': '표준: P1 + 차트 3 + 타이머 1 + 시퀀스 1',
    'P3': '무거움: P2 + 지도 1 + 시설 3D 1 + 카메라 1초 갱신 1',
    'I-chart': 'P0 + 차트 1',
    'I-map': 'P0 + 지도 1',
    'I-facility': 'P0 + 시설 3D 1',
    'I-camera': 'P0 + 카메라 1초 갱신 1',
}

#: 측정 위젯이 낡은 값을 비우지 않게 하는 최대 나이(초). 입력 주기(60초)보다 넉넉히.
MAX_AGE_S = 3600
#: 벤치 입력의 측정 주기(초) — 입력 폼의 최솟값은 5.
INPUT_PERIOD_S = 10
BENCH_CPU = 'BENCH CPU'
BENCH_DISK = 'BENCH DISK'

SAMPLE_IMAGE = 'http://127.0.0.1/static/img/aot-hero-dashboard-v2.jpg'


def profile_counts(key):
    """프로필의 위젯 종류별 개수 — 테스트와 README 표가 쓴다."""
    out = {}
    for wtype, n in PROFILES[key]:
        out[wtype] = out.get(wtype, 0) + n
    return out


def widget_total(key):
    return sum(n for _t, n in PROFILES[key])


# 화면 파싱 -----------------------------------------------------------------
_FORM_MARK = re.compile(r'name="widget_type"\s+value="([A-Za-z_0-9]+)"')
_SELECT = re.compile(r'<select\b[^>]*\bname="([A-Za-z_0-9]+)"[^>]*>(.*?)</select>', re.S)
_OPTION = re.compile(r'<option\b[^>]*\bvalue="([^"]*)"[^>]*>(.*?)</option>', re.S)


def parse_widget_choices(html):
    """위젯 종류 → {select 이름 → [(값, 라벨)]}.

    대시보드 화면은 위젯 종류마다 추가 폼(`<input name="widget_type" value="X">` 뒤에
    옵션 selects)을 싣는다. 그 폼의 선택지가 곧 "그 위젯이 지금 고를 수 있는 것"이다.
    빈 값('Select One')은 뺀다.
    """
    marks = [(m.start(), m.group(1)) for m in _FORM_MARK.finditer(html)]
    out = {}
    for i, (start, wtype) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(html)
        selects = out.setdefault(wtype, {})
        for sm in _SELECT.finditer(html[start:end]):
            name = sm.group(1)
            if name == 'widget_type':
                continue
            opts = []
            for value, label in _OPTION.findall(sm.group(2)):
                if value == '':
                    continue
                opts.append((value, re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', label)).strip()))
            selects.setdefault(name, opts)
    return out


_TAB = re.compile(
    r'href="/dashboard/([0-9a-f-]{36})"[^>]*>\s*<span class="d-none d-md-inline">([^<]*)</span>')


def parse_dashboard_tabs(html):
    """탭 줄의 (unique_id, 이름) 목록. 같은 대시보드가 두 번 나오면 한 번만."""
    seen, out = set(), []
    for uid, name in _TAB.findall(html):
        if uid not in seen:
            seen.add(uid)
            out.append((uid, name.strip()))
    return out


# 장치 준비 -----------------------------------------------------------------
class Prepared:
    """프로필을 만들 때 위젯 옵션에 넣을 값들(없으면 None/빈 목록)."""

    def __init__(self):
        self.measurements = []     # "input,measure" 값
        self.pwm_channels = []     # PWM 출력 채널 값
        self.onoff_channels = []   # 타이머가 쓸 온오프 채널 값
        self.sequence = None
        self.map_uuid = None
        self.camera = None          # 모던 카메라 위젯용 카메라 id
        self.camera_legacy = None   # 옛 카메라 위젯용 카메라 id(옛 드라이버 종류만 받는다)
        self.facility_ready = False
        self.notes = []


def _form_post(client, path, data, **kw):
    data = dict(data)
    data['csrf_token'] = csrf_from_html(client.get(kw.pop('csrf_page', path)).text)
    return client.post(path, data=data, **kw)


def fetch_choices(client, dashboard_id=None):
    path = f'/dashboard/{dashboard_id}' if dashboard_id else '/dashboard'
    return parse_widget_choices(client.get(path).text)


def _prefer_live(measurements):
    """CPU 부하(값이 늘 있다)를 앞에 — 측정 위젯이 가장 먼저 쓴다."""
    def key(item):
        label = item[1].lower()
        return (0 if 'cpu' in label else 1 if 'ram' in label else 2)
    return sorted(measurements, key=key)


def ensure_devices(client, log=print, activate_inputs=True):
    """데이터를 받을 장치가 모자라면 만들고, 위젯 옵션에 쓸 값을 모아 돌려준다."""
    prep = Prepared()
    ch = fetch_choices(client)

    # 입력 — 벤치 전용 입력 둘(CPU 부하, 남은 디스크). 하드웨어·추가 패키지 없이 값을 내는 드라이버다
    # (RAM 드라이버는 psutil 이 필요해 빼 두었다).
    # 다른 입력은 쓰지 않는다: 서버마다 달라 비교가 안 되고, 어떤 입력은 위젯을 깨뜨린다
    # (E2E 시드의 'cpu_load' 측정은 게이지 위젯 템플릿에서 500 을 낸다).
    for label, itype in ((BENCH_CPU, 'RPiCPULoad,'), (BENCH_DISK, 'RPiFreeSpace,')):
        if not _has_measurement_label(ch, label):
            _make_input(client, label, itype, log)
            ch = fetch_choices(client)

    # 출력 — PWM 채널 2개, 온오프 채널 1개
    if len(ch.get('AoT_output_pwm', {}).get('output', [])) < 2:
        need = 2 - len(ch.get('AoT_output_pwm', {}).get('output', []))
        for _ in range(need):
            r = _form_post(client, '/output_submit',
                           {'output_type': 'python_pwm,PYTHON', 'output_add': 'Add'},
                           csrf_page='/output')
            log(f'  PWM 출력 추가 → {r.status_code}')
    if not ch.get('AoT_timer', {}).get('output'):
        r = _form_post(client, '/output_submit',
                       {'output_type': 'virtual_on_off_multi,', 'output_add': 'Add'},
                       csrf_page='/output')
        log(f'  온오프 출력 추가 → {r.status_code}')

    # 시퀀스 함수
    if not ch.get('widget_trigger_sequence', {}).get('function_id'):
        r = _form_post(client, '/function_submit',
                       {'function_type': 'trigger_sequence', 'function_add': 'Add'},
                       csrf_page='/function')
        log(f'  시퀀스 함수 추가 → {r.status_code}')

    # 카메라 — 앱의 정적 이미지를 URL 카메라로 찍는다
    if not ch.get('AoT_camera', {}).get('camera_id'):
        _make_camera(client, 'ip_camera', 'BENCH Camera', log)

    ch = fetch_choices(client)
    # 출력(PWM 의 듀티 등)의 측정도 같은 목록에 섞여 온다 — 벤치 입력의 측정만 쓴다.
    prep.measurements = [v for v, _l in _prefer_live(
        [o for o in ch.get('widget_measurement', {}).get('measurement', [])
         if o[1].startswith('[Input') and ('BENCH ' in o[1])])]
    prep.pwm_channels = [v for v, _l in ch.get('AoT_output_pwm', {}).get('output', [])]
    prep.onoff_channels = [v for v, _l in ch.get('AoT_timer', {}).get('output', [])]
    seq = ch.get('widget_trigger_sequence', {}).get('function_id', [])
    prep.sequence = seq[0][0] if seq else None
    maps = ch.get('AoT_map', {}).get('map_uuid', [])
    prep.map_uuid = maps[0][0] if maps else None
    cams = ch.get('AoT_camera', {}).get('camera_id', [])
    prep.camera = cams[0][0] if cams else None

    if prep.camera:
        _ensure_camera_image(client, prep.camera, log)
    if activate_inputs:
        _activate_inputs(client, prep.measurements, log)
    prep.facility_ready = _ensure_facility(client, prep, log)

    if not prep.measurements:
        prep.notes.append('벤치 입력의 측정이 없습니다 — 측정·차트 위젯을 건너뜁니다')
    if not prep.pwm_channels:
        prep.notes.append('PWM 출력 채널이 없습니다 — 출력 위젯을 건너뜁니다')
    if not prep.onoff_channels:
        prep.notes.append('온오프 출력 채널이 없습니다 — 타이머를 건너뜁니다')
    if not prep.sequence:
        prep.notes.append('시퀀스 함수가 없습니다 — 시퀀스 위젯을 건너뜁니다')
    if not prep.map_uuid:
        prep.notes.append('지도가 없습니다 — 지도 위젯을 건너뜁니다(서버에 지도를 먼저 만들 것)')
    if not prep.camera:
        prep.notes.append('카메라가 없습니다 — 카메라 위젯을 건너뜁니다')
    return prep


def _has_measurement_label(ch, label):
    return any(f'] {label} ' in l or l.endswith(label)
               for _v, l in ch.get('widget_measurement', {}).get('measurement', []))


def _make_input(client, name, itype, log):
    """입력을 만들고 이름·주기를 정한다. 만든 입력의 id 를 돌려준다."""
    r = _form_post(client, '/input_submit', {'input_type': itype, 'input_add': 'Add'},
                   csrf_page='/input')
    data = (r.json() or {}).get('data') or {}
    iid = data.get('input_id')
    if not iid:
        log(f'  입력 추가 실패 {itype}: {data.get("messages")}')
        return None
    _form_post(client, '/input_submit', {
        'input_id': iid, 'unique_id': iid, 'name': name,
        'period': str(INPUT_PERIOD_S), 'input_mod': 'Save'}, csrf_page='/input')
    log(f'  입력 추가 {name} ({itype.rstrip(",")}) {iid[:8]}')
    return iid


def _ensure_camera_image(client, camera_id, log):
    """마지막 이미지가 없으면 한 장 찍어 둔다 — 없으면 카메라 위젯이 이미지 대신 오류만 받는다."""
    r = client.get(f'/camera/last_image/{camera_id}')
    if r.ok and r.headers.get('content-type', '').startswith('image/'):
        return True
    client.post(f'/camera/capture/{camera_id}', headers={'X-CSRFToken': client.csrf_token()})
    r = client.get(f'/camera/last_image/{camera_id}')
    ok = r.ok and r.headers.get('content-type', '').startswith('image/')
    log(f'  카메라 첫 사진 {"찍음 " + str(len(r.content)) + "바이트" if ok else "실패 — 카메라 위젯이 오류 이미지만 받습니다"}')
    return ok


def _make_camera(client, camera_type, name, log):
    before = set(re.findall(r'gs-id="([0-9a-f-]{36})"', client.get('/camera').text))
    r = _form_post(client, '/camera', {'camera_type': camera_type, 'camera_add': 'Add'})
    after = re.findall(r'gs-id="([0-9a-f-]{36})"', client.get('/camera').text)
    new = [i for i in after if i not in before]
    if not new:
        log('  카메라 추가 실패')
        return None
    cid = new[0]
    _form_post(client, '/camera', {
        'camera_id': cid, 'camera_mod': '1', 'name': name,
        'ip_address': SAMPLE_IMAGE, 'width': '640', 'height': '480', 'fps': '1',
        'capture_mode': 'snapshot'})
    _form_post(client, '/camera', {'camera_id': cid, 'camera_activate': '1'})
    log(f'  카메라 추가·활성화 {name} {cid[:8]} ({r.status_code})')
    return cid


def _activate_inputs(client, measurement_values, log):
    """측정에 쓰는 입력을 활성화한다 — 이미 켜져 있으면 서버가 알아서 넘긴다."""
    input_ids = []
    for v in measurement_values:
        iid = v.split(',')[0]
        if iid not in input_ids:
            input_ids.append(iid)
    for iid in input_ids:
        try:
            r = _form_post(client, '/input_submit',
                           {'input_id': iid, 'input_activate': 'Activate'},
                           csrf_page='/input')
            msgs = (r.json().get('data') or {}).get('messages') or {}
            err = msgs.get('error')
            log(f'  입력 활성화 {iid[:8]} → {"오류 " + str(err) if err else "ok"}')
        except Exception as exc:  # noqa: BLE001 - 활성화 실패가 프로필 생성을 막지 않는다
            log(f'  입력 활성화 {iid[:8]} 실패: {exc}')


def _ensure_facility(client, prep, log):
    """시설 위젯이 그릴 시설 — 없으면 지도 위에 작은 온실 하나를 만든다."""
    try:
        listing = client.get('/api/geo/facility/list').json()
    except Exception:  # noqa: BLE001
        return False
    items = listing.get('facilities') if isinstance(listing, dict) else listing
    if items:
        return True
    if not prep.map_uuid:
        return False
    lng, lat = 127.0025, 37.0005
    dx, dy = 0.00012, 0.00005
    ring = [[lng - dx, lat - dy], [lng + dx, lat - dy], [lng + dx, lat + dy],
            [lng - dx, lat + dy], [lng - dx, lat - dy]]
    made = client.json_post('/api/geo/facility', {
        'geo_id': prep.map_uuid, 'name': 'BENCH Facility',
        'preset': 'standard_arch', 'structure': 'single', 'bay_count': 1,
        'outer_geometry': {'type': 'Polygon', 'coordinates': [ring]},
        'geometry_3d': {'span_width_m': 10, 'eave_height_m': 3, 'ridge_height_m': 6,
                        'length_m': 20, 'orientation_deg': 90, 'roof_type': 'arch',
                        'spacing_m': 1, 'center_lng': lng, 'center_lat': lat},
        'envelope': {'layers': [{'id': 'outer', 'type': 'full', 'role': 'outer',
                                 'cover': 'vinyl_single'}]},
        'fittings': []})
    ok = made.ok and (made.json() or {}).get('ok')
    log(f'  시설 추가 → {"ok" if ok else made.text[:120]}')
    return bool(ok)


# 위젯 옵션 -----------------------------------------------------------------
def widget_form_fields(wtype, index, prep):
    """위젯 추가 폼에 실을 (필드, 값) 목록. 건너뛸 위젯이면 None."""
    f = [('refresh_duration', '30')]
    ms = prep.measurements
    if wtype in ('widget_measurement', 'widget_indicator', 'widget_gauge_solid'):
        if not ms:
            return None
        f.append(('measurement', ms[index % len(ms)]))
        f.append(('measurement_max_age' if wtype != 'widget_gauge_solid'
                  else 'max_measure_age', str(MAX_AGE_S)))
        f.append(('refresh_seconds', '10'))
    elif wtype == 'AoT_output_pwm':
        if not prep.pwm_channels:
            return None
        f.append(('output', prep.pwm_channels[index % len(prep.pwm_channels)]))
        f.append(('refresh_seconds', '10'))
    elif wtype == 'AoT_graph':
        if not ms:
            return None
        # 차트마다 측정 하나씩 번갈아 — 같은 쿼리를 3번 하지 않게
        f.append(('measurements_input', ms[index % len(ms)]))
        f.append(('refresh_seconds', '30'))
        f.append(('x_axis_duration', '1'))
        f.append(('x_axis_duration_unit', 'day'))
    elif wtype == 'AoT_timer':
        if not prep.onoff_channels:
            return None
        f.append(('output', prep.onoff_channels[0]))
        f.append(('refresh_seconds', '5'))
    elif wtype == 'widget_trigger_sequence':
        if not prep.sequence:
            return None
        f.append(('function_id', prep.sequence))
        f.append(('refresh_seconds', '5'))
    elif wtype == 'AoT_map':
        if not prep.map_uuid:
            return None
        f.append(('map_uuid', prep.map_uuid))
    elif wtype == 'AoT_facility':
        if not prep.facility_ready:
            return None
    elif wtype == 'AoT_camera':
        # 모던 카메라 위젯 — 스냅숏을 1초마다 받는다(카메라 비용의 핵심).
        if not prep.camera:
            return None
        f.append(('camera_id', prep.camera))
        f.append(('display_mode', 'snapshot'))
        f.append(('refresh_rate', '1'))
    elif wtype == 'widget_camera':
        # 옛 카메라 위젯 — 매초 새 사진을 찍어 받는다. 옛 드라이버 카메라만 받는다.
        if not prep.camera_legacy:
            return None
        f.append(('camera_id', prep.camera_legacy))
        f.append(('camera_image_type', 'new_img'))
        f.append(('refresh_seconds', '1'))
    return f


# 대시보드 생성 --------------------------------------------------------------
def list_tabs(client):
    return parse_dashboard_tabs(client.get('/dashboard').text)


def delete_dashboard(client, dashboard_id):
    page = client.get(f'/dashboard/{dashboard_id}').text
    token = csrf_from_html(page)
    client.post(f'/dashboard/{dashboard_id}', allow_redirects=False,
                data={'csrf_token': token, 'dashboard_id': dashboard_id,
                      'dash_delete': 'Delete'})


def create_dashboard(client, name):
    token = csrf_from_html(client.get('/dashboard').text)
    r = client.post('/dashboard-add', data={'csrf_token': token}, allow_redirects=False)
    loc = r.headers.get('Location', '')
    m = re.search(r'/dashboard/([0-9a-f-]{36})', loc)
    if not m:
        raise RuntimeError(f'대시보드를 만들지 못했습니다: HTTP {r.status_code} {loc}')
    dash_id = m.group(1)
    page = client.get(f'/dashboard/{dash_id}').text
    r = client.post(f'/dashboard/{dash_id}', allow_redirects=False, data={
        'csrf_token': csrf_from_html(page), 'dashboard_id': dash_id,
        'name': name, 'dash_modify': 'Save'})
    return dash_id


def add_widget(client, dash_id, wtype, name, fields):
    page = client.get(f'/dashboard/{dash_id}').text
    data = [('csrf_token', csrf_from_html(page)), ('dashboard_id', dash_id),
            ('widget_type', wtype), ('name', name), ('widget_add', 'Add')]
    data.extend(fields)
    r = client.post(f'/dashboard/{dash_id}', data=data, allow_redirects=False)
    loc = r.headers.get('Location', '')
    return r.status_code, loc


def _widgets_on_page(client, dash_id):
    return len(re.findall(r'gs-id=', client.get(f'/dashboard/{dash_id}').text))


def add_camera_widget(client, dash_id, prep, log):
    """카메라 위젯 하나 — 모던 위젯을 먼저, 서버가 거부하면(의존성 없음) 옛 위젯으로.

    저장이 거부되면 HTTP 는 똑같이 302 라 화면의 위젯 개수가 늘었는지로 판정한다.
    """
    for wtype in ('AoT_camera', 'widget_camera'):
        if wtype == 'widget_camera' and not prep.camera_legacy:
            prep.camera_legacy = _make_camera(client, 'url_requests', 'BENCH Camera (legacy)', log)
        fields = widget_form_fields(wtype, 0, prep)
        if fields is None:
            continue
        before = _widgets_on_page(client, dash_id)
        add_widget(client, dash_id, wtype, f'{wtype} 1', fields)
        if _widgets_on_page(client, dash_id) > before:
            return wtype
        log(f'  {wtype} 저장이 거부됐습니다 — 다음 종류를 시도합니다')
    return None


def build_profile(client, key, prep, log=print):
    name = NAME_PREFIX + key
    dash_id = create_dashboard(client, name)
    added, skipped, reload_needed = {}, [], False
    for wtype, n in PROFILES[key]:
        for i in range(n):
            if wtype == 'camera':
                kind = add_camera_widget(client, dash_id, prep, log)
                if kind:
                    added[kind] = added.get(kind, 0) + 1
                else:
                    skipped.append('camera')
                continue
            fields = widget_form_fields(wtype, i, prep)
            if fields is None:
                skipped.append(wtype)
                continue
            status, loc = add_widget(client, dash_id, wtype, f'{wtype} {i + 1}', fields)
            if 'reload_flask' in loc:
                reload_needed = True
            if status not in (200, 302, 303):
                log(f'  {key}: {wtype} 추가 HTTP {status}')
                skipped.append(wtype)
            else:
                added[wtype] = added.get(wtype, 0) + 1
    # 화면이 실제로 그 개수를 그리는지 — HTTP 302 만으로는 저장 거부(예: 위젯이 카메라 종류를
    # 못 받음)를 알 수 없다. 거부된 위젯은 화면에 없다.
    on_page = len(re.findall(r'gs-id=', client.get(f'/dashboard/{dash_id}').text))
    if on_page != sum(added.values()):
        log(f'  경고: {key} 에 위젯 {sum(added.values())}개를 보냈지만 화면에는 {on_page}개뿐입니다')
    return dict(key=key, name=name, id=dash_id, path=f'/dashboard/{dash_id}',
                description=DESCRIPTIONS[key], widgets=added, skipped=skipped,
                widget_total=sum(added.values()), widgets_on_page=on_page), reload_needed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--url', default=DEFAULT_URL, help='대상 서버 (기본 E2E 스택 8085)')
    ap.add_argument('--user')
    ap.add_argument('--password')
    ap.add_argument('--profiles', default=','.join(PROFILES),
                    help='만들 프로필 키(쉼표). 기본 전부')
    ap.add_argument('--out', default='.local/bench/profiles.json', help='만든 대시보드 목록 저장 경로')
    ap.add_argument('--no-activate-inputs', action='store_true',
                    help='입력을 활성화하지 않는다(값이 안 들어와 위젯이 비어 보일 수 있음)')
    ap.add_argument('--no-reload', action='store_true',
                    help='새 위젯 종류를 처음 쓸 때 서버가 요구하는 화면 새로고침(/reload_flask)을 하지 않는다')
    ap.add_argument('--delete-only', action='store_true', help='BENCH 대시보드만 지운다')
    args = ap.parse_args(argv)
    if '8084' in args.url:
        sys.exit('거부: 8084(로컬 개발 서버)에는 쓰지 않습니다.')

    client = AotClient(args.url, args.user, args.password)
    keys = [k.strip() for k in args.profiles.split(',') if k.strip()]
    unknown = [k for k in keys if k not in PROFILES]
    if unknown:
        sys.exit(f'알 수 없는 프로필: {unknown} (가능: {list(PROFILES)})')

    for uid, name in list_tabs(client):
        if name.startswith(NAME_PREFIX):
            print(f'기존 {name} 삭제')
            delete_dashboard(client, uid)
    if args.delete_only:
        return 0

    print('장치 준비')
    prep = ensure_devices(client, activate_inputs=not args.no_activate_inputs)
    for note in prep.notes:
        print('  주의:', note)

    results, reload_needed = [], False
    for key in keys:
        print(f'{key} 만드는 중 — {DESCRIPTIONS[key]}')
        info, rel = build_profile(client, key, prep)
        reload_needed = reload_needed or rel
        results.append(info)
        print(f'  → {info["path"]} 위젯 {info["widget_total"]}개 {info["widgets"]}'
              + (f' 건너뜀 {info["skipped"]}' if info['skipped'] else ''))

    if reload_needed and not args.no_reload:
        print('새 위젯 종류가 처음 쓰였습니다 — 화면 새로고침(/reload_flask)을 요청하고 기다립니다')
        client.get(f'/reload_flask/{results[0]["id"]}')
        _wait_alive(client)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump({'url': args.url, 'profiles': results,
                   'notes': prep.notes}, fh, ensure_ascii=False, indent=1)
    print('저장:', args.out)
    return 0


def _wait_alive(client, secs=90):
    time.sleep(12)
    end = time.time() + secs
    while time.time() < end:
        try:
            if client.get('/login_password', timeout=5).ok:
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)


if __name__ == '__main__':
    sys.exit(main())

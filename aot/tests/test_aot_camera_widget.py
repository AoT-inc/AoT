# coding=utf-8
"""모던 카메라 위젯(AoT_camera)이 실제로 동작하는 경로에 연결돼 있는지 고정한다.

- 카메라 목록: `select_device` + `Camera` 가 아니면 선택지가 비어 위젯에 카메라가
  하나도 안 나온다(에러 없이 빈 목록).
- 화면 소스: 서버에 등록돼 있지 않은 `/api/camera/...` 가 아니라 등록된
  `/video_feed`, `/camera/last_image` 여야 한다.
- 종속성: 검사는 `find_spec(두 번째 값)` 이라 PyPI 이름이 아니라 import 이름이어야 한다.
"""
from aot.widgets import AoT_camera


def _option(option_id):
    return next(o for o in AoT_camera.WIDGET_INFORMATION['custom_options']
                if o['id'] == option_id)


def test_camera_list_is_populated_from_camera_table():
    option = _option('camera_id')
    assert option['type'] == 'select_device'
    assert option['options_select'] == ['Camera']


def test_widget_uses_registered_routes():
    js = AoT_camera.WIDGET_INFORMATION['widget_dashboard_js']
    assert '/video_feed/' in js
    assert '/camera/last_image/' in js
    assert '/api/camera/' not in js


def test_dependency_names_are_import_names():
    deps = {(kind, name): spec
            for kind, name, spec in AoT_camera.WIDGET_INFORMATION['dependencies_module']}
    assert ('pip-pypi', 'cv2') in deps
    assert ('pip-pypi', 'onvif') in deps
    assert deps[('pip-pypi', 'onvif')].startswith('onvif-zeep')


def test_global_js_has_no_per_widget_variables():
    """`widget_dashboard_js` 는 위젯 종류당 한 번, 위젯 반복문 밖에서 그려진다.
    each_widget / widget_options 를 쓰면 대시보드 전체가 500 이 된다(2026-11-02)."""
    js = AoT_camera.WIDGET_INFORMATION['widget_dashboard_js']
    assert 'each_widget' not in js
    assert 'widget_options' not in js
    ready_end = AoT_camera.WIDGET_INFORMATION['widget_dashboard_js_ready_end']
    assert 'each_widget.id' in ready_end


def test_snapshot_revalidates_instead_of_busting_cache():
    """스냅숏을 `?t=시각` 으로 부르면 같은 사진을 매번 통째로 받는다(1초·100KB 면
    시간당 약 360MB). 같은 주소를 재검증하고, ETag 가 같으면 그림을 바꾸지 않는다."""
    js = AoT_camera.WIDGET_INFORMATION['widget_dashboard_js']
    assert "'/camera/last_image/' + cameraId + '?t='" not in js
    assert "cache: 'no-cache'" in js
    assert 'snapEtag' in js
    assert 'revokeObjectURL' in js


def test_live_stream_is_cut_while_tab_hidden():
    """MJPEG <img> 는 숨긴 탭에서도 프레임을 계속 받는다. 숨으면 src 를 지워 끊고,
    그 끊김을 실패로 세어 다시 붙지 않는다."""
    js = AoT_camera.WIDGET_INFORMATION['widget_dashboard_js']
    assert "img.removeAttribute('src')" in js
    error_handler = js.split("img.addEventListener('error'")[1].split('});')[0]
    assert 'document.hidden' in error_handler


def test_live_stream_reconnects_after_layout_change_and_errors():
    """MJPEG 는 <img> 하나가 연결 하나라, 화면 폭 전환·탭 전환에서 브라우저가
    끊으면 멈춘 채 남는다(2026-11-02 모바일 전체폭 전환에서 재현). 이벤트마다
    다시 열고, 실패가 이어질 때는 재시도 간격을 늘려야 카메라를 두드리지 않는다."""
    js = AoT_camera.WIDGET_INFORMATION['widget_dashboard_js']
    for event in ("'resize'", "'visibilitychange'", "'error'", "'load'"):
        assert event in js
    assert 'Math.pow(2' in js and '60000' in js

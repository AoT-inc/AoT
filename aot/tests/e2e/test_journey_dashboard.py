# coding=utf-8
"""L2 · J2 — 대시보드 위젯 배치가 저장되고 다시 열어도 남아 있는가.

이 여정이 첫 번째인 이유: 대시보드는 사람이 가장 자주 보는 화면이고, 배치
저장은 **조용히 실패하기 딱 좋은 경로**다. 드래그 → 디바운스 250ms → AJAX
POST → DB 라 어디가 끊겨도 화면은 그대로 옳아 보인다. 새로고침해야 드러난다.

실제로 2026 년에 이 계열에서만 여러 번 깨졌다 — 번역문 아포스트로피가 인라인
JS 를 깨뜨려 그리드스택이 통째로 죽은 일, 시퀀스 위젯 순서가 저장되지 않던 일.
"""
import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.journeys import drag_widget_by, open_dashboard, widget_boxes

pytestmark = pytest.mark.e2e


def test_the_seeded_widgets_are_on_the_board(page, base_url):
    """먼저 화면에 위젯이 실제로 그려지는지 본다.

    뒤의 단언들이 "위젯이 하나도 없어서" 통과하는 일을 막는 받침이다.
    """
    open_dashboard(page, base_url, F.DASHBOARD)
    boxes = widget_boxes(page)
    assert len(boxes) >= 3, f'위젯이 {len(boxes)}개만 그려졌습니다: {list(boxes)}'
    assert any('Measurement' in name for name in boxes), (
        f'측정 위젯이 안 보입니다: {list(boxes)}')


def test_a_dragged_widget_keeps_its_place_after_a_reload(page, base_url):
    """드래그 → 저장 → 새로고침 → 그 자리에 있는가."""
    open_dashboard(page, base_url, F.DASHBOARD)
    before = widget_boxes(page)
    target = next(name for name in before if 'Measurement' in name)

    # 저장 요청이 실제로 나갔는지까지 본다. 화면만 보면 "옮겨진 것처럼" 보이는
    # 상태와 진짜 저장된 상태를 구분할 수 없다.
    with page.expect_response(
            lambda r: '/save_dashboard_layout' in r.url and r.request.method == 'POST',
            timeout=15000) as saved:
        drag_widget_by(page, target, dx=360, dy=0)   # 24열 기준 여러 칸
    assert saved.value.status == 200, (
        f'배치 저장이 HTTP {saved.value.status} 로 끝났습니다')

    moved = widget_boxes(page)[target]
    assert moved['x'] != before[target]['x'], (
        f"화면에서 위젯이 움직이지 않았습니다 (x={moved['x']}). "
        f"드래그 손잡이가 덮였거나 그리드가 죽었을 수 있습니다")

    page.reload(wait_until='domcontentloaded')
    page.wait_for_selector('.grid-stack-item', timeout=20000)
    page.wait_for_timeout(800)
    after = widget_boxes(page)[target]

    assert after['x'] == moved['x'] and after['y'] == moved['y'], (
        f"새로고침 뒤 자리가 되돌아갔습니다 — 저장이 반영되지 않았습니다. "
        f"드래그 직후 ({moved['x']}, {moved['y']}) → "
        f"새로고침 뒤 ({after['x']}, {after['y']})")
    assert after['w'] == before[target]['w'] and after['h'] == before[target]['h'], (
        f"옮기기만 했는데 크기가 바뀌었습니다: "
        f"{before[target]['w']}x{before[target]['h']} → {after['w']}x{after['h']}")

# coding=utf-8
"""L2 · J14 — 예약한 일이 달력에 보이는가.

일정은 "언제 무엇이 돌 것인가" 를 사람이 확인하는 자리다. 저장은 됐는데
달력에 안 뜨면, 사람은 예약이 없다고 믿고 손으로 다시 하거나 손을 놓는다.

⚠ **달력이 보여 주는 상태는 정해져 있다** (`_CALENDAR_VISIBLE_STATES`:
DRAFT·PENDING·RUNNING·COMPLETED·FAILED). 시드를 'APPROVED' 로 넣었을 때 저장은
됐는데 달력은 비어 있었다 — 검사가 "일정이 없다" 로 읽혔다. 상태 어휘와
달력이 어긋나는 것 자체가 사고이므로, 여기서는 **보이는 상태**로 넣고
"넣은 것이 보이는가" 를 본다.
"""
import datetime

import pytest

from aot.tests.e2e import fixtures as F

pytestmark = pytest.mark.e2e


def _timeline(admin_http, base_url, days_back=5, days_ahead=10):
    """달력이 부르는 그 API 를 그대로 부른다."""
    today = datetime.date.today()
    resp = admin_http.get(
        f'{base_url}/api/v1/scheduler/timeline',
        params={
            'start': f'{today - datetime.timedelta(days=days_back)}T00:00:00',
            'end': f'{today + datetime.timedelta(days=days_ahead)}T00:00:00',
        },
        timeout=30, headers={'Accept': 'application/json'})
    assert resp.status_code == 200, (
        f'일정 조회가 HTTP {resp.status_code} 를 냈습니다')
    return resp.json()


def test_the_seeded_schedule_is_in_the_calendar_feed(admin_http, base_url):
    """서버가 그 일정을 달력에 내보내는가."""
    events = _timeline(admin_http, base_url)
    mine = [e for e in events
            if F.SCHEDULE_TITLE in str(e.get('extendedProps', {}))
            or F.SCHEDULE_TITLE in str(e.get('title', ''))]
    assert mine, (
        f'시드 일정이 달력 자료에 없습니다(받은 일정 {len(events)}건). '
        f'상태가 달력이 보여 주는 값인지 확인하세요')

    event = mine[0]
    assert event.get('start'), f'일정에 시작 시각이 없습니다: {event}'
    assert event.get('title'), '일정에 제목이 없습니다 — 달력에 빈 칸으로 뜹니다'


def test_the_schedule_page_draws_the_calendar(page, base_url):
    """화면에서도 달력이 그려지고, 그 일정이 보이는가.

    자료가 와도 달력이 안 그려지면 사람은 못 본다. 반대로 달력만 있고 일정이
    없어도 마찬가지다 — 둘 다 본다.
    """
    page.goto(f'{base_url}/scheduler', wait_until='domcontentloaded')
    page.wait_for_selector('.fc', timeout=25000)
    # 일정은 비동기로 실려 온다. 나타날 때까지 기다린 뒤에 본다.
    page.wait_for_function(
        "() => document.querySelectorAll('.fc-event').length > 0",
        timeout=30000)

    events = page.evaluate(
        "() => Array.from(document.querySelectorAll('.fc-event'))"
        "  .map(e => (e.innerText || '').trim())")
    assert events, '달력에 일정이 하나도 그려지지 않았습니다'
    assert any(F.OUTPUT_MULTI in text or F.SCHEDULE_TITLE in text
               for text in events), (
        f'시드 일정이 달력에 보이지 않습니다(그려진 것: {events[:3]})')

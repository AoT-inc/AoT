# coding=utf-8
"""
Calendar event provider registry — pure, framework-free adapters that turn a
data source into a common calendar-event shape for the /api/v1/scheduler/
calendar_events endpoint (aot/aot_flask/routes_scheduler.py) and the calendar
dashboard widget (aot/widgets/widget_calendar.py).

This module owns NO Flask (`request`/`jsonify`) or AI-tool concerns — it is a
plain (source_key -> normalized_event_list) registry, matching the style of
other framework-free helpers in this package (widgets.py, time_utils.py).

Only 'schedule' is implemented today. 'notice'/'note' are documented
extension points (see CALENDAR_EVENT_PROVIDERS below) — the widget's UI and
this registry are both designed so adding a new source later is additive
(new function + one registry line), not a redesign.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# @ANCHOR: SCHEDULE_CATEGORY_COLOR_MAP — deterministic action_type -> one of
# the 6 reactive --aot-chart-* tokens (aot-theme-variables.css), so widget CSS
# never has to hardcode a color per category; it just reads data-category.
_CATEGORY_COLOR_HINT = {
    'human': 'chart-1',
    'control_output': 'chart-6',
    'automated_fire': 'chart-3',
}
_DEFAULT_COLOR_HINT = 'chart-2'
# 노트·공지는 일정과 **다른 종류로 읽혀야** 한다 — 같은 팔레트를 쓰되 일정이
# 쓰지 않는 칸을 준다(chart-1/3/6 은 위에서 이미 쓴다).
_NOTE_COLOR_HINT = 'chart-4'
_NOTICE_COLOR_HINT = 'chart-5'

# Canonical bucket for a schedule action_type — the ONE mapping used everywhere:
# the calendar-widget picker's AoT sections, the Google category-calendar
# routing (calendar_sync_service imports this), and event filtering. Deliberately
# domain-neutral (this system runs at farms, factories, labs, buildings — never
# assume "farm").
#   automated_fire → 'ai'      (AI-authored / automated)
#   control_output / pid / function / activate / deactivate → 'device'
#   human (+ anything else)     → 'user'
_DEVICE_ACTIONS = ('control_output', 'pid', 'function', 'activate', 'deactivate')


def action_category(action_type):
    if action_type == 'automated_fire':
        return 'ai'
    if action_type in _DEVICE_ACTIONS:
        return 'device'
    return 'user'


# Representative color per bucket (default chart palette hexes; per-event colors
# still come from the reactive --aot-chart-* tokens, this is just a picker dot).
_BUCKET_COLOR = {'ai': '#93B261', 'user': '#FEA60B', 'device': '#008DDE',
                 'note': '#8E7CC3', 'notice': '#E06C75'}

# Job states shown on the calendar. ARCHIVED (cancelled/superseded) is
# deliberately excluded — a cancelled event cluttering a calendar view is
# noise, not signal (matches the scheduler page's own "History" vs "Active"
# split intent, though DRAFT/PENDING/RUNNING/COMPLETED/FAILED are all still
# calendar-relevant unlike the read-only /timeline endpoint's narrower set).
_CALENDAR_VISIBLE_STATES = ('DRAFT', 'PENDING', 'RUNNING', 'COMPLETED', 'FAILED')


def _parse_range_bound(value):
    """Parse a FullCalendar-supplied start/end query param (ISO 8601, usually
    with an offset) into a naive-UTC datetime — matching how schedule_time is
    stored (SQLite has no tz type; naive-stored == UTC by this project's own
    convention, see aot/utils/tz_utils.py). Returns None on missing/bad input
    so the caller can fall back to an open-ended bound rather than erroring."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def provide_schedule_events(start=None, end=None, limit=500, category=None):
    """Registered provider for source key 'schedule'. `category` (optional:
    'ai'|'user'|'device') filters to one bucket via action_category(), so the
    calendar widget can offer AI/User/Device as separate toggle-able sources
    that mirror the Google category calendars. Queries SchedulerJobMeta
    with schedule_time in [start, end) (either bound optional — an unbounded
    query is still capped by `limit`), reuses
    AoTDataToolService._schedule_summary() for content/location resolution
    (same enrichment as _enrich_job_display in routes_scheduler.py — imported,
    not duplicated), and returns a list of normalized calendar-event dicts:

        {id, jobId, title, start, end, allDay, sourceType, category, state,
         colorHint, content, location, worker, rowEditable, rowDeletable, deepLink}

    `jobId` is the raw integer SchedulerJobMeta.id (not the `id` field's
    "schedule-<uuid>" DOM-safe string) — the widget's edit/delete UI needs it
    verbatim to call PUT/DELETE /api/v1/scheduler/jobs/<int:job_id>.
    `editable`/`deletable` mirror SchedulerJobMeta.is_editable/is_deletable —
    per-row flags, not just a permission check (e.g. an already-fired device
    command is correctly locked even for an editor).
    """
    from aot.databases.models.scheduler import SchedulerJobMeta
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    from aot.utils.time_utils import serialize_ts

    start_dt = _parse_range_bound(start)
    end_dt = _parse_range_bound(end)

    query = SchedulerJobMeta.query.filter(
        SchedulerJobMeta.state.in_(_CALENDAR_VISIBLE_STATES)
    )
    if start_dt is not None:
        query = query.filter(SchedulerJobMeta.schedule_time >= start_dt)
    if end_dt is not None:
        query = query.filter(SchedulerJobMeta.schedule_time < end_dt)
    # Rows with no schedule_time at all (rare, but action_type='human' rows
    # created without a time are possible) have nothing to place on a
    # calendar — exclude them here rather than letting them collapse onto
    # created_at, which would misrepresent "when" this is actually happening.
    query = query.filter(SchedulerJobMeta.schedule_time.isnot(None))

    rows = query.order_by(SchedulerJobMeta.schedule_time.asc()).limit(limit).all()

    events = []
    for row in rows:
        bucket = action_category(row.action_type)
        if category and bucket != category:
            continue
        try:
            summary = AoTDataToolService._schedule_summary(row)
        except Exception:
            logger.exception("provide_schedule_events: _schedule_summary failed for job %s", row.id)
            continue

        title = summary['content']
        if summary['location']:
            title = f"{title} · {summary['location']}"

        end_iso = None
        if row.end_time is not None:
            end_iso = serialize_ts(row.end_time)

        events.append({
            'id': f"schedule-{row.unique_id}",
            'jobId': row.id,
            'title': title,
            'start': serialize_ts(row.schedule_time),
            'end': end_iso,
            'allDay': False,
            'sourceType': 'schedule',
            'category': row.action_type,
            'bucket': bucket,
            'state': row.state,
            'colorHint': _CATEGORY_COLOR_HINT.get(row.action_type, _DEFAULT_COLOR_HINT),
            'content': summary['content'],
            'location': summary['location'],
            'worker': summary['worker'],
            # NOT named 'editable'/'deletable': FullCalendar reserves the
            # top-level 'editable' key for drag/resize interactivity — a
            # same-named field here gets consumed as THAT flag instead of
            # landing in extendedProps (the widget's Edit button silently
            # stopped rendering this way; caught in browser testing). Prefixed
            # to sidestep FullCalendar's whole reserved-key surface, not just
            # the one collision found so far.
            'rowEditable': summary['editable'],
            'rowDeletable': summary['deletable'],
            'deepLink': '/scheduler',
        })
    return events


# --- 노트 / 공지 provider ---------------------------------------------------
#
# 세 소스는 **서로 다른 정보가 아니다.** 같은 것(문장 + 어디 + 언제)에 붙은 세
# 개의 저장 위치이고, 경계는 실제 데이터에서 이미 양방향으로 새고 있다:
# `SchedulerJobMeta.action_type='note'` 2건 · `Notes.category='schedule'` 3건.
# 그래서 한 화면에서 시간축으로 함께 보이는 것이 맞다.
#
# 다만 **기계가 남긴 실행 기록은 섞지 않는다** — 실측 323건 중 249건(77%)이
# `automated_fire` 라, 그것을 사람 글과 한 목록에 쏟으면 사람이 쓴 13건이 묻힌다.
# 소스를 켜고 끄는 축(bucket)이 그래서 필요하다.

def provide_notice_events(start=None, end=None, limit=500, category=None):
    """`NoticePost` → 캘린더 이벤트.

    공지는 **기록과 별개로 남긴다**(사용자 결정, 2026-08-18): 게시·만료
    (`publish_at`/`expire_at`)와 읽음·투표(`NoticePoll`)라는 다른 계약을 갖는다.
    여기서는 **읽기만** 합친다 — 달력에 함께 보이되 편집은 /notice 에서.

    시각은 `publish_at` 이 있으면 그것, 없으면 작성 시각이다. 게시 예정일이
    곧 "언제부터 사람들이 보는가" 이므로 달력에서 의미 있는 지점은 그쪽이다.
    """
    from aot.databases.models.notice import NoticePost
    from aot.utils.time_utils import serialize_ts
    from sqlalchemy import func

    # `category` 는 버킷 필터(ai|user|device|note|notice)다. 다른 버킷을
    # 요구하면 이 소스는 해당 없음이다 — 무시하면 "사용자 일정만" 을 골라도
    # notice 가 따라 나온다.
    if category and category != 'notice':
        return []

    start_dt = _parse_range_bound(start)
    end_dt = _parse_range_bound(end)

    # publish_at 이 비면 date_time 으로 대체해 정렬·필터한다 — 두 컬럼을 한
    # 식으로 다루지 않으면 "예정 공지만 사라지는" 창이 생긴다.
    when = func.coalesce(NoticePost.publish_at, NoticePost.date_time)
    query = NoticePost.query
    if start_dt is not None:
        query = query.filter(when >= start_dt)
    if end_dt is not None:
        query = query.filter(when < end_dt)

    events = []
    for row in query.order_by(when.asc()).limit(limit).all():
        at = row.publish_at or row.date_time
        if at is None:
            continue
        events.append({
            'id': 'notice-%s' % row.unique_id,
            'jobId': None,
            'title': row.title or '',
            'start': serialize_ts(at),
            'end': serialize_ts(row.expire_at) if row.expire_at else None,
            # 공지는 시각보다 "그날 걸려 있다" 가 맞다 — 종일로 둔다.
            'allDay': True,
            'sourceType': 'notice',
            'category': row.category or 'notice',
            'bucket': 'notice',
            'state': 'PINNED' if row.pinned else 'ACTIVE',
            'colorHint': _NOTICE_COLOR_HINT,
            'content': row.title or '',
            'location': None,
            'worker': None,
            # 편집은 /notice 의 계약(게시기간·읽음)을 지나야 한다 — 달력에서
            # 고치게 하면 그 계약을 우회하는 두 번째 경로가 생긴다.
            'rowEditable': False,
            'rowDeletable': False,
            'deepLink': '/notice',
        })
    return events


def provide_note_events(start=None, end=None, limit=500, category=None):
    """`Notes` → 캘린더 이벤트.

    노트는 시각이 **쓴 때**다(예정이 아니다). 그래도 달력에 올리는 이유는,
    "그날 무슨 일이 있었나" 를 예정과 나란히 봐야 계획이 서기 때문이다 —
    노트와 `action_type='human'` 일정은 시각의 성격만 다르고 정체가 같다.

    보관(`is_archived`)된 것은 뺀다. 시스템이 만든 것(`context_state=
    'system_generated'`)도 뺀다 — AI 요약·로그가 사람 글을 묻는다.
    """
    from aot.databases.models import Notes
    from aot.utils.time_utils import serialize_ts

    # `category` 는 버킷 필터(ai|user|device|note|notice)다. 다른 버킷을
    # 요구하면 이 소스는 해당 없음이다 — 무시하면 "사용자 일정만" 을 골라도
    # note 가 따라 나온다.
    if category and category != 'note':
        return []

    start_dt = _parse_range_bound(start)
    end_dt = _parse_range_bound(end)

    query = Notes.query.filter(Notes.date_time.isnot(None))
    # is_archived 는 NULL 인 옛 행이 있어 `!= True` 로 본다 — `== False` 로
    # 쓰면 그 행들이 통째로 사라진다.
    query = query.filter((Notes.is_archived.is_(None)) | (Notes.is_archived != True))  # noqa: E712
    if start_dt is not None:
        query = query.filter(Notes.date_time >= start_dt)
    if end_dt is not None:
        query = query.filter(Notes.date_time < end_dt)

    events = []
    for row in query.order_by(Notes.date_time.asc()).limit(limit).all():
        if (row.context_state or '') == 'system_generated' and \
                (row.category or '') != 'general':
            continue
        title = (row.name or '').strip() or (row.note or '').strip()
        if not title:
            continue
        events.append({
            'id': 'note-%s' % row.unique_id,
            'jobId': None,
            'title': title[:120],
            'start': serialize_ts(row.date_time),
            'end': None,
            'allDay': True,
            'sourceType': 'note',
            'category': row.category or 'general',
            'bucket': 'note',
            'state': 'LOGGED',
            'colorHint': _NOTE_COLOR_HINT,
            'content': title[:120],
            'location': None,
            'worker': None,
            # 노트 편집은 노트 UI 하나뿐이다(공용 AoTNotesBlock) — 달력에서
            # 고치게 하면 진입점이 둘이 된다.
            'rowEditable': False,
            'rowDeletable': False,
            'deepLink': '/notes',
        })
    return events


# --- 구획 단계 provider -------------------------------------------------
#
# 단계 경계(시작일 · "다음 단계 시작일 - 1일"인 종료일)는 저장값이 아니라
# `plot_context.stage_schedule_view` 가 매번 다시 세운 파생값이다(정본:
# `plot_context.py` 모듈 docstring — 이 도메인은 파생값을 물질화했다가 이미
# 여러 번 데었다). 그래서 이 provider 는 새 테이블/컬럼을 두지 않고, 요청마다
# 구획을 다시 훑어 그 자리에서 이벤트를 만든다.
#
# 버킷은 다른 provider 처럼 '카테고리'(ai|user|...)가 아니라 **부지**다 —
# 캘린더가 부지별로 켜고 끄는 화면이기 때문이다. 그래서 `category` 는
# `'site:<site_uuid>'` | `'site:unassigned'` 형태를 쓴다.
#
# 색은 한 가지만 쓴다: 부지 구분은 이미 버킷(토글)이 하고 있어서 단계마다
# 다른 색을 주면 "부지가 다른데 왜 색이 같지" 와 "부지가 같은데 왜 색이
# 다르지"가 동시에 생긴다. `_CATEGORY_COLOR_HINT`/`_NOTE_COLOR_HINT`/
# `_NOTICE_COLOR_HINT` 가 chart-1/3/4/5/6 을 이미 각자의 뜻으로 차지했으니
# (사람=1·AI=3·노트=4·공지=5·장치=6), 남는 chart-2 를 쓴다 — 스케줄
# provider 에서 chart-2 는 `_DEFAULT_COLOR_HINT` 로 등록돼 있지만 그건 "위
# 세 action_type 어디에도 안 걸리면" 만 떨어지는 잡동사니 자리라 실제로 한
# 카테고리의 대표색으로 화면에 나타나지 않는다 — 실질적으로 비어 있는 칸이다.
_PLOT_STAGE_COLOR_HINT = 'chart-2'

# 피커의 점 색도 새로 짓지 않는다. `_BUCKET_COLOR`의 ai/user/device 값은
# aot-theme-variables.css 의 --aot-chart-3/1/6 hex 를 그대로 옮긴 것이다
# (note/notice 는 그 팔레트 밖 커스텀 색). 위에서 고른 chart-2 와 같은
# 출처(같은 CSS 파일의 --aot-chart-2)를 그대로 쓴다.
_PLOT_STAGE_BUCKET_COLOR = '#8BC1C1'  # aot-theme-variables.css --aot-chart-2


def provide_plot_stage_events(start=None, end=None, limit=500, category=None):
    """구획(`GeoPlot`)의 단계 → 캘린더 이벤트.

    `category` 는 버킷 필터이되 다른 provider 처럼 고정된 이름 집합이 아니라
    `'site:<site_uuid>'`(부지 하나) | `'site:unassigned'`(부지가 안 잡히는
    구획) 이다. `'site:'` 로 시작하지 않는 요청은 이 소스와 무관하다.

    대상은 `program_uuid` 가 있는(= 단계 개념이 성립하는) 구획 중 표시 창과
    기간이 겹치는 것만이다. 프로그램이 없는 구획은 `stage_schedule_view` 가
    애초에 `[]` 를 주므로 걸러도 정보 손실이 없다.

    `programs`/`containers`/`facilities` 캐시를 루프 밖에서 만들어 넘긴다 —
    구획 수만큼 프로그램 행·지도 도형을 다시 읽으면 목록 화면 하나가 N+1이
    된다(같은 이유로 `plot_context.to_dict` 도 이 캐시들을 쓴다).
    """
    if category and not category.startswith('site:'):
        return []

    from datetime import date, timedelta

    from sqlalchemy import or_

    from aot.databases.models import GeoPlot
    from aot.aot_flask.geo import device_membership
    from aot.aot_flask.geo.plot_context import (
        geometry_of, program_brief, stage_schedule, stage_schedule_view,
    )

    start_dt = _parse_range_bound(start)
    end_dt = _parse_range_bound(end)
    start_date = start_dt.date() if start_dt is not None else None
    end_date = end_dt.date() if end_dt is not None else None

    query = GeoPlot.query.filter(GeoPlot.program_uuid.isnot(None))
    if end_date is not None:
        query = query.filter(GeoPlot.started_on <= end_date)
    if start_date is not None:
        query = query.filter(or_(GeoPlot.ended_on.is_(None),
                                 GeoPlot.ended_on >= start_date))
    plots = query.order_by(GeoPlot.started_on.asc()).limit(limit).all()

    programs = {}
    containers_cache = {}
    facilities_cache = {}

    events = []
    for plot in plots:
        try:
            program = program_brief(plot, programs=programs)
            if not program or program.get('missing'):
                continue
            sched = stage_schedule(plot, program=program, programs=programs)
            stages = stage_schedule_view(plot, sched=sched)

            containers = containers_cache.get(plot.geo_id)
            if containers is None:
                containers = device_membership.load_containers(plot.geo_id)
                containers_cache[plot.geo_id] = containers
            site = device_membership.site_for_geometry(
                plot.geo_id, geometry_of(plot, facilities=facilities_cache),
                containers=containers)
        except Exception:
            # 구획 하나의 파생이 깨져도 달력 전체를 비우지 않는다 — 다른
            # provider 들과 같은 태도.
            logger.exception("provide_plot_stage_events: 구획 %s 준비 실패",
                             getattr(plot, 'unique_id', None))
            continue

        bucket = 'site:%s' % site.unique_id if site is not None else 'site:unassigned'
        if category and bucket != category:
            continue

        plot_name = plot.name or plot.subject

        for st in stages:
            starts_on = st.get('starts_on')
            if not starts_on:
                # 앞 단계가 "끝까지"(길이 없음)라 다음 경계를 셀 수 없는
                # 경우다 — 지어내지 않고 그 칸은 건너뛴다.
                continue
            ends_on = st.get('ends_on')

            try:
                s_date = date.fromisoformat(starts_on)
                e_date = date.fromisoformat(ends_on) if ends_on else None
            except (TypeError, ValueError):
                continue
            if end_date is not None and s_date > end_date:
                continue
            if start_date is not None and e_date is not None and e_date < start_date:
                continue

            # FullCalendar 의 allDay 이벤트에서 `end` 는 배타적인데
            # `ends_on` 은 마지막 날(포함)이다 — +1일 하지 않으면 모든 단계
            # 막대가 하루씩 짧게 그려진다.
            end_exclusive = (e_date + timedelta(days=1)).isoformat() if e_date else None

            events.append({
                'id': 'plotstage-%s-%s' % (plot.unique_id, st.get('key')),
                'jobId': None,
                'title': '%s · %s' % (plot_name, st.get('name')),
                'start': starts_on,
                'end': end_exclusive,
                'allDay': True,
                'sourceType': 'plot_stage',
                'category': 'plot_stage',
                'bucket': bucket,
                'state': st.get('state'),
                'colorHint': _PLOT_STAGE_COLOR_HINT,
                'content': st.get('name'),
                'location': plot_name,
                'worker': None,
                # 드래그로 미래 단계를 옮기는 쓰기 경로는 이미 있다(다른 작업) —
                # 여기서는 `stage_schedule_view` 가 이미 판정한 `editable` 을
                # 그대로 옮길 뿐 다시 판정하지 않는다(두 번째 판정자를 만들면
                # 갈라진다).
                'rowEditable': bool(st.get('editable')),
                'rowDeletable': False,
                'deepLink': '/geo',
                'plotUuid': plot.unique_id,
                'stageKey': st.get('key'),
                'openEnd': ends_on is None,
            })

    if len(events) > limit:
        events = events[:limit]
    return events


def plot_stage_buckets():
    """구획 단계 캘린더가 켤 수 있는 **부지** 목록 → 피커 항목.

    부지마다 색을 달리하지 않는다 — 단계는 전부 `_PLOT_STAGE_COLOR_HINT`
    하나를 쓰고, 부지 구분은 이 목록 항목을 켜고 끄는 것으로 한다. 그래서
    여기서 필요한 것은 "프로그램이 걸린 구획을 가진 부지가 어디인가" 뿐이다.
    구획이 하나도 없는 부지, 즉 눌러도 빈 달력만 나오는 항목은 올리지 않는다.
    부지가 안 잡히는 구획이 하나라도 있으면 `'site:unassigned'` 를 목록
    끝에 붙인다.
    """
    from flask_babel import gettext

    from aot.databases.models import GeoPlot
    from aot.aot_flask.geo import device_membership
    from aot.aot_flask.geo.plot_context import geometry_of, _shape_name

    plots = GeoPlot.query.filter(GeoPlot.program_uuid.isnot(None)).all()

    containers_cache = {}
    facilities_cache = {}
    site_names = {}
    has_unassigned = False

    for plot in plots:
        try:
            containers = containers_cache.get(plot.geo_id)
            if containers is None:
                containers = device_membership.load_containers(plot.geo_id)
                containers_cache[plot.geo_id] = containers
            site = device_membership.site_for_geometry(
                plot.geo_id, geometry_of(plot, facilities=facilities_cache),
                containers=containers)
        except Exception:
            logger.exception("plot_stage_buckets: 구획 %s 부지 판정 실패",
                             getattr(plot, 'unique_id', None))
            continue

        if site is None:
            has_unassigned = True
            continue
        site_names.setdefault(site.unique_id, _shape_name(site) or site.unique_id[:8])

    buckets = [{'key': 'site:%s' % uuid, 'name': name,
               'color': _PLOT_STAGE_BUCKET_COLOR}
              for uuid, name in site_names.items()]
    buckets.sort(key=lambda b: b['name'])
    if has_unassigned:
        buckets.append({'key': 'site:unassigned',
                        'name': gettext('Unassigned site'),
                        'color': _PLOT_STAGE_BUCKET_COLOR})
    return buckets


CALENDAR_EVENT_PROVIDERS = {
    'schedule': provide_schedule_events,
    'notice': provide_notice_events,
    'note': provide_note_events,
    'plot_stage': provide_plot_stage_events,
}

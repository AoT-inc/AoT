# coding=utf-8
"""
Calendar widget — dashboard-embeddable view of aot/utils/calendar_event_providers.py's
event feed (MVP source: scheduler jobs; see that module's registry for how
notice/note sources get added later without redesigning this widget).

Clicking an editable event (viewer has `permission_edit_settings` AND the
row's own SchedulerJobMeta.is_editable allows it — some rows, e.g.
already-fired device commands, are correctly locked even for an editor) goes
straight to the edit modal, like a normal calendar app — no intermediate
"Edit" button. Anything else falls back to a small read-only popover with a
deep link to /scheduler. Dragging an editable event to a new day/time
reschedules it, and dragging its bottom edge resizes its duration — both via
the same PUT, just a narrower payload (date/time, or duration_minutes) than a
full modal save. All of this calls the *same*
PUT/DELETE /api/v1/scheduler/jobs/<id> endpoints and field set
(location/content/worker/time/duration) as scheduler.html's own per-job modal
(duration is new there too — edit_schedule_tool previously only moved the
start time) — a second, lightweight presentation of the identical backend
contract (see
aot/aot_flask/templates/pages/ai/scheduler.html's modal_job_* blocks). One
edit modal per widget instance, populated on demand — not one per event, since
events are paginated/dynamic (mirrors widget_notice.py's compose modal, not
scheduler.html's per-row modals). Structure mirrors widget_notice.py (guard
pattern, custom_options shape, js_ready_end per-instance init).

FullCalendar itself is vendored locally (static/vendor/fullcalendar-5.11.5/,
same version as scheduler.html's own instance) rather than pulled from a CDN
or wired through the geo/ rollup build — the npm "fullcalendar" package is
already a self-contained UMD+CSS bundle with nothing to tree-shake, so vendoring
it verbatim (like maplibre-gl) is simpler than adding module resolution to a
build pipeline that has no other reason to touch this widget. Instance glue
lives in static/js/widgets/widget_calendar/aot-calendar-widget.js.
"""
from flask_babel import lazy_gettext

from aot.utils.constraints_pass import constraints_pass_positive_value


WIDGET_INFORMATION = {
    'widget_name_unique': 'widget_calendar',
    'widget_name': lazy_gettext('Calendar'),
    'widget_library': '',
    'no_class': True,
    'mobile_full_width': True,  # a day-grid at a fractional mobile column width is unusable

    'message': lazy_gettext('Shows scheduled events (from the Scheduler) on a calendar, '
                'split by category (AI / User / Device), and any Google calendars you connect. '
                'Click an event for details or to edit; open the full Scheduler for more.'),

    'dependencies_module': [],

    'widget_width': 12,
    'widget_height': 14,

    'custom_options': [
        {
            'id': 'include_schedule',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show Scheduled Events'),
            'phrase': lazy_gettext('Include scheduled jobs on the calendar')
        },
        {
            # 등록된 소스마다 토글이 하나씩 있어야 한다 — 이 모듈의 원래
            # 주석이 요구한 짝이다("a toggle for a source with no registered
            # provider is dead UI"). 이제 provider 가 셋 다 있다.
            'id': 'include_note',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show Notes'),
            'phrase': lazy_gettext('Include notes on the calendar (read-only)')
        },
        {
            'id': 'include_notice',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show Notice'),
            'phrase': lazy_gettext('Include notice posts on the calendar (read-only)')
        },
        {
            'id': 'default_view',
            'type': 'select',
            'default_value': 'dayGridMonth',
            'options_select': [
                ('dayGridMonth', lazy_gettext('Month')),
                ('timeGridWeek', lazy_gettext('Week')),
                ('listWeek', lazy_gettext('List (Week)')),
            ],
            'name': lazy_gettext('Default View'),
            'phrase': lazy_gettext('Calendar view shown when there is enough room; a narrow card or small screen still switches to a list automatically')
        },
        {
            'id': 'refresh_seconds',
            'type': 'integer',
            'default_value': 60,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Refresh (seconds)'),
            'phrase': lazy_gettext('How often to re-fetch events for the currently visible range')
        },
        {
            'id': 'days_ahead_list',
            'type': 'integer',
            'default_value': 30,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('List View Look-ahead (days)'),
            'phrase': lazy_gettext('How many days ahead the List view queries')
        },
    ],

    'widget_dashboard_head': """{% if "aot_calendar_render" not in dashboard_dict %}
  {% set _dummy = dashboard_dict.update({"aot_calendar_render": 1}) %}
<link rel="stylesheet" href="/static/vendor/fullcalendar-5.11.5/main.min.css?v=20260814a">
<script src="/static/vendor/fullcalendar-5.11.5/main.min.js?v=20260814a"></script>
<link rel="stylesheet" href="/static/css/widget/aot-calendar-widget.css?v=9">
<script src="/static/js/widgets/widget_calendar/aot-calendar-widget.js?v=11"></script>
{% endif %}
<style>
  .aot-calendar-widget-outer { height: 100%; display: flex; flex-flow: column; overflow: hidden; }
  .aot-calendar-widget-container { padding: 8px; flex: 1 1 auto; overflow: hidden; min-height: 0; }
</style>""",

    'widget_dashboard_title_bar': """<span class="widget-title-bar aot-w-title">{{each_widget.name}}</span>""",

    'widget_dashboard_body': """
<div class="aot-calendar-widget-outer">
  <div id="calendar-widget-{{each_widget.unique_id}}" class="aot-calendar-widget-container">
    <div class="text-muted small">{{_('Loading...')}}</div>
  </div>
</div>
{% if permission_edit_settings %}
<div class="modal fade aot-option-modal" id="calendar-edit-modal-{{each_widget.unique_id}}" tabindex="-1" role="dialog" aria-hidden="true">
  <div class="modal-dialog aot-modal-dialog" role="document">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">{{_('Edit Schedule')}}</h5>
        <button type="button" class="close" data-dismiss="modal" aria-label="{{_('Close')}}"><span aria-hidden="true">&times;</span></button>
      </div>
      <div class="modal-body">
        <div id="calendar-edit-map-wrap-{{each_widget.unique_id}}" class="aot-cal-edit-map-wrap d-none">
          <div id="calendar-edit-map-{{each_widget.unique_id}}" class="aot-cal-edit-map"></div>
        </div>
        <div class="aot-modal-container">
          <div class="aot-modal-option-row">
            <label class="aot-modal-option-label">{{_('Location')}}</label>
            <div class="aot-modal-option-control">
              <input type="text" class="form-control aot-modern-input" id="calendar-edit-location-{{each_widget.unique_id}}" placeholder="{{_('e.g. 3-1, Zone A')}}">
            </div>
          </div>
          <div class="aot-modal-option-row">
            <label class="aot-modal-option-label">{{_('Content')}}</label>
            <div class="aot-modal-option-control">
              <input type="text" class="form-control aot-modern-input" id="calendar-edit-content-{{each_widget.unique_id}}">
            </div>
          </div>
          <div class="aot-modal-option-row">
            <label class="aot-modal-option-label">{{_('Worker')}}</label>
            <div class="aot-modal-option-control">
              <input type="text" class="form-control aot-modern-input" id="calendar-edit-worker-{{each_widget.unique_id}}">
            </div>
          </div>
          <div class="aot-modal-option-row">
            <label class="aot-modal-option-label">{{_('Schedule Time')}}</label>
            <div class="aot-modal-option-control">
              <input type="datetime-local" class="form-control aot-modern-input" id="calendar-edit-time-{{each_widget.unique_id}}">
            </div>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn aot-pill-btn aot-pill-btn-danger mr-auto" id="calendar-edit-delete-{{each_widget.unique_id}}">{{_('Delete')}}</button>
        <button type="button" class="btn aot-pill-btn aot-pill-btn-secondary" data-dismiss="modal">{{_('Close')}}</button>
        <button type="button" class="btn aot-pill-btn aot-pill-btn-primary" id="calendar-edit-save-{{each_widget.unique_id}}">{{_('Save')}}</button>
      </div>
    </div>
  </div>
</div>
{% endif %}""",

    'widget_dashboard_js': """
""",

    'widget_dashboard_js_ready': """<!-- No JS ready content -->""",

    'widget_dashboard_js_ready_end': """
aotCalendarWidgetInit('{{each_widget.unique_id}}', {
  includeSchedule: {{widget_options['include_schedule']|lower}},
  includeNote: {{widget_options['include_note']|lower}},
  includeNotice: {{widget_options['include_notice']|lower}},
  defaultView: {{widget_options['default_view']|tojson}},
  refreshSeconds: {{widget_options['refresh_seconds']}},
  daysAheadList: {{widget_options['days_ahead_list']}},
  locale: {{ session.get('language', 'en')|tojson }},
  canEdit: {{ 'true' if permission_edit_settings else 'false' }},
  i18nStart: {{_('Start')|tojson}},
  i18nLocation: {{_('Location')|tojson}},
  i18nWorker: {{_('Worker')|tojson}},
  i18nState: {{_('State')|tojson}},
  i18nOpenScheduler: {{_('Open in Scheduler')|tojson}},
  i18nDelete: {{_('Delete')|tojson}},
  i18nDeletePrompt: {{_('Cancellation reason (optional):')|tojson}},
  i18nSaveFailed: {{_('Save failed')|tojson}},
  i18nDeleteFailed: {{_('Delete failed')|tojson}},
  i18nCalendars: {{_('Calendars')|tojson}},
  i18nGoogle: {{_('Google Calendar')|tojson}},
  i18nLoading: {{_('Loading...')|tojson}}
});
""",
}

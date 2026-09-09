# coding=utf-8
from flask_babel import lazy_gettext

from aot.utils.constraints_pass import constraints_pass_positive_value


def generate_page_variables(widget_unique_id, widget_options):
    """물리 제어 도구 목록은 게이트가 정본이다(routes_mcp_api.mcp_review_page와
    동일한 이유) — 위젯에 하드코딩하면 도구가 늘 때 조용히 어긋나고, 그 어긋남이
    곧 "확인 없이 밸브가 열리는" 상태가 된다. 함수 안에서 import 하는 이유도
    같은 파일의 라우트들과 동일 — 위젯 스캔 시점의 앱 초기화 순서 문제를 피한다."""
    from aot.ai.services import mcp_safety_gate as gate
    return {'physical_tools': sorted(gate.PHYSICAL_TOOLS)}


WIDGET_INFORMATION = {
    'widget_name_unique': 'widget_mcp_review',
    'widget_name': lazy_gettext('MCP Approval Requests'),
    'widget_library': '',
    'no_class': True,
    'mobile_full_width': True,

    'message': lazy_gettext(
        'Shows how many external AI write requests are waiting for approval. Click the count to open '
        'the list and approve, reject, or edit-then-approve them one at a time, or select several and '
        'approve/reject them in bulk. Approving runs the request immediately with exactly the values shown.'),

    'dependencies_module': [],

    'widget_width': 4,
    'widget_height': 3,

    'generate_page_variables': generate_page_variables,

    'custom_options': [
        {
            'id': 'refresh_seconds',
            'type': 'integer',
            'default_value': 15,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Refresh (seconds)'),
            'phrase': lazy_gettext('How often to refresh the pending count'),
        },
        {
            'id': 'max_items',
            'type': 'integer',
            'default_value': 20,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Max items shown'),
            'phrase': lazy_gettext('Cap on how many pending requests the list modal shows at once'),
        },
    ],

    # 실제 목록/승인/거부/수정 로직은 전부 공용 모듈(번들 widget-mcp-approval,
    # 소스는 js/common/aot-mcp-approval.js + css/widget/aot-mcp-approval.css)에
    # 있다 — 이 위젯은 그 모듈을 부르는
    # 가장 얇은 소비자일 뿐이다. 다른 위젯도 같은 두 파일을 로드하고
    # AoTMcpApproval.mount(containerId, opts)를 호출하기만 하면 똑같은
    # 요약+목록+수정 UI를 그대로 재사용할 수 있다.
    'widget_dashboard_head': """{% if "css_sensor_label" not in dashboard_dict %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/widget/aot-sensor-label.css') }}">
{% set _dummy = dashboard_dict.update({"css_sensor_label": 1}) %}
{% endif %}
{% if "css_mcp_approval" not in dashboard_dict %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/widget/aot-mcp-approval.css') }}">
{% set _dummy = dashboard_dict.update({"css_mcp_approval": 1}) %}
{% endif %}
{% if "js_mcp_approval" not in dashboard_dict %}
<script src="{{ asset('widget-mcp-approval') }}"></script>
{% set _dummy = dashboard_dict.update({"js_mcp_approval": 1}) %}
{% endif %}""",

    'widget_dashboard_body': """<div id="mcprev-slot-{{each_widget.unique_id}}"></div>""",

    'widget_dashboard_js_ready_end': """
AoTMcpApproval.mount('#mcprev-slot-{{each_widget.unique_id}}', {
  refreshSeconds: {{widget_options['refresh_seconds']}},
  maxItems: {{widget_options.get('max_items', 20)}},
  physicalTools: {{ widget_variables.get('physical_tools', []) | tojson }},
  labels: {
    count_fmt: {{ _('{n} pending approval')|tojson }},
    view: {{ _('View')|tojson }},
    none_pending: {{ _('No control requests are waiting.')|tojson }},
    loading: {{ _('Loading...')|tojson }},
    list_title: {{ _('Control requests awaiting approval')|tojson }},
    select_all: {{ _('Select all')|tojson }},
    // 배치 버튼은 카드 안 승인/거부와 같은 짧은 단어를 재사용한다 —
    // "선택 항목 승인" 처럼 길면 모바일 좁은 폭에서 모달 푸터를 벗어나
    // 잘린다(2026-09-09 실제 확인). 22개 언어를 지원하므로 번역이 길어질
    // 여지가 있는 새 문구를 만들기보다 이미 짧다고 검증된 기존 문구를
    // 그대로 쓴다 — 옆의 "전체 선택 (N)" 이 이미 대상 범위를 보여주므로
    // 뜻은 그대로 통한다.
    approve_selected: {{ _('Approve')|tojson }},
    reject_selected: {{ _('Reject')|tojson }},
    approve: {{ _('Approve')|tojson }},
    reject: {{ _('Reject')|tojson }},
    modify: {{ _('Edit')|tojson }},
    expires_fmt: {{ _('expires in {sec}s')|tojson }},
    view_details: {{ _('View details')|tojson }},
    physical_warning: {{ _('This runs real equipment (valves, pumps).')|tojson }},
    confirm_physical: {{ _('This moves real equipment (valves, pumps) as soon as you approve. Run it now?')|tojson }},
    executed: {{ _('Approved and carried out.')|tojson }},
    exec_failed: {{ _('Approved, but it failed to run')|tojson }},
    failed: {{ _('Request failed')|tojson }},
    batch_summary: {{ _('{ok}/{total} succeeded')|tojson }},
    invalid_json: {{ _("Invalid value in field '{field}'")|tojson }},
    edit_title: {{ _('Edit and approve')|tojson }},
    close: {{ _('Close')|tojson }},
    cancel: {{ _('Cancel')|tojson }},
    save_approve: {{ _('Save & approve')|tojson }},
    // "수정" 모달의 필드 라벨 — 일반 사용자에게 device_id/state 같은 내부
    // 파라미터 이름을 그대로 보여주지 않기 위함. 여기 없는 키는 JS가 자체
    // 폴백표를 쓰거나, 그마저 없으면 원본 키를 그대로 보여준다.
    field_labels: {
      device_id: {{ _('Device')|tojson }},
      state: {{ _('State')|tojson }},
      duration: {{ _('Duration (sec)')|tojson }},
      duration_minutes: {{ _('Duration (min)')|tojson }},
      scheduled_time: {{ _('Scheduled time')|tojson }},
      function_id: {{ _('Function')|tojson }},
      action_id: {{ _('Step')|tojson }},
      title: {{ _('Title')|tojson }},
      body: {{ _('Body')|tojson }},
      content: {{ _('Content')|tojson }},
      time: {{ _('Time')|tojson }},
      target_name: {{ _('Target')|tojson }},
      worker: {{ _('Worker')|tojson }},
      start: {{ _('Start')|tojson }},
      end: {{ _('End')|tojson }},
      period_seconds: {{ _('Period (sec)')|tojson }}
    }
  }
});
"""
}

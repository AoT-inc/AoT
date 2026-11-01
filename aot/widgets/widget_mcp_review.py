# coding=utf-8
# @manual ai/overview#safety-approval-model
from flask_babel import lazy_gettext


WIDGET_INFORMATION = {
    'widget_name_unique': 'widget_mcp_review',
    'widget_name': lazy_gettext('MCP Approval Requests'),
    'widget_library': '',
    'no_class': True,
    'mobile_full_width': True,

    'message': lazy_gettext(
        'Shows how many external AI write requests are waiting for approval. Click View to open the approval '
        'window at the bottom of the screen, where you can approve, reject, or edit-then-approve them. '
        'Approving runs the request immediately with exactly the values shown.'),

    'dependencies_module': [],

    'widget_width': 4,
    'widget_height': 3,

    # 목록·승인·거부·수정은 하단 AI 창구의 승인 모달(js/common/aot-ai-approvals.js)이 맡는다(2026-10-23).
    # 이 위젯은 건수 요약과 [보기] 뿐이고, 갱신 주기는 모달의 대기 목록 읽기(보이는 탭 15초)가 정한다 —
    # 그래서 예전의 '갱신 주기'·'목록 최대 개수' 옵션은 뺐다.
    'custom_options': [],

    'widget_dashboard_head': "",

    'widget_dashboard_body': """<div id="mcprev-slot-{{each_widget.unique_id}}"></div>""",

    'widget_dashboard_js_ready_end': """
if (window.AoTAIApprovals) {
  window.AoTAIApprovals.mountSummary('#mcprev-slot-{{each_widget.unique_id}}', {
    count_fmt: {{ _('{n} pending approval')|tojson }},
    none_pending: {{ _('No control requests are waiting.')|tojson }},
    loading: {{ _('Loading...')|tojson }},
    load_failed: {{ _('Could not load control requests')|tojson }},
    view: {{ _('View')|tojson }}
  });
}
"""
}

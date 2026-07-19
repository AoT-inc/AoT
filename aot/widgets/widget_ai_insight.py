# coding=utf-8
import logging
from flask import jsonify, request
from flask_babel import lazy_gettext
from aot.widgets.base_widget import AbstractWidget
from aot.ai.services.ai_reasoning_service import AIReasoningService
from aot.ai.services.ai_action_service import AIActionService

logger = logging.getLogger(__name__)

def ai_get_reasoning():
    """Endpoint for the widget to fetch AI reasoning results."""
    goal = request.args.get('goal', 'Optimize system for energy efficiency')
    agent_id = request.args.get('agent_id')
    try:
        # Pass agent_id if explicitly selected in widget options
        result = AIReasoningService.run_reasoning_cycle(goal=goal, agent_id=agent_id)
        return jsonify(result)
    except Exception as e:
        logger.exception("Error in ai_get_reasoning endpoint")
        return jsonify({"status": "error", "message": str(e)}), 500

def ai_execute_proposed_action():
    """Endpoint for the widget to execute a specific proposed action."""
    data = request.json or {}
    history_id = data.get('history_id')
    action_index = data.get('action_index', 0)
    
    # Fallback for legacy Phase 4 actions (no history_id)
    if not history_id:
        action_type = data.get('action_type')
        target_id = data.get('target_id')
        params = data.get('params', {})
        if not action_type or not target_id:
            return jsonify({"status": "error", "message": "Missing action details"}), 400
        return jsonify(AIActionService.execute_action(action_type, target_id, params))
        
    try:
        from aot.ai.services.ai_agent_service import AIAgentService
        result = AIAgentService.execute_logged_action(history_id, action_index)
        return jsonify(result)
    except Exception as e:
        logger.exception("Error in ai_execute_proposed_action endpoint")
        return jsonify({"status": "error", "message": str(e)}), 500

class AIInsightWidget(AbstractWidget):
    def __init__(self, widget, testing=False):
        super().__init__(widget, testing=testing, name=__name__)

    def execute_refresh(self):
        # This widget is primarily driven by JS-side polling or manual triggers
        pass

WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_ai_insight',
    'widget_name': lazy_gettext('AI Reasoning Insight'),
    'widget_library': 'ai',
    'no_class': True,
    'message': lazy_gettext('AI-driven analysis and intelligent action recommendations.'),
    'widget_width': 24,
    'widget_height': 12,

    'endpoints': [
        ("/ai_widget/reason", "ai_widget_reason", ai_get_reasoning, ["GET"]),
        ("/ai_widget/execute", "ai_widget_execute", ai_execute_proposed_action, ["POST"])
    ],

    'custom_options': [
        {
            'id': 'agent_id',
            'type': 'text',
            'default_value': '',
            'name': lazy_gettext('Selected AI Agent ID'),
            'phrase': lazy_gettext('Unique ID of the agent to use. Leave empty for default.')
        },
        {
            'id': 'default_goal',
            'type': 'text',
            'default_value': 'Optimize resources and energy efficiency',
            'name': lazy_gettext('Default Analysis Goal'),
            'phrase': lazy_gettext('Initial goal for AI reasoning when the widget loads.')
        },
        {
            'id': 'refresh_minutes',
            'type': 'integer',
            'default_value': 30,
            'name': lazy_gettext('Auto-Analyze Refresh (Minutes)'),
            'phrase': lazy_gettext('Interval to automatically re-run AI reasoning. Set 0 to disable.')
        }
    ],

    'widget_dashboard_head': """
    <style>
        .ai-insight-container {
            padding: 15px;
            font-family: 'Inter', sans-serif;
            /* 이 위젯은 고정 다크 글래스 카드(반투명 흰색 오버레이)라 흰색/밝은
               회색 텍스트를 리터럴로 유지 — 라이트모드 전역 텍스트 토큰과 무관 */
            color: #fff;
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            height: 100%;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .ai-goal-section {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }

        .ai-goal-input {
            flex-grow: 1;
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 8px;
            color: #fff;
            padding: 8px 12px;
            outline: none;
            transition: border-color 0.3s;
        }

        .ai-goal-input:focus {
            border-color: #007bff;
        }

        .btn-ai-analyze {
            background: linear-gradient(135deg, #007bff, #00c6ff);
            border: none;
            border-radius: 8px;
            color: var(--text-color-tertiary, white);
            padding: 8px 16px;
            cursor: pointer;
            font-weight: var(--aot-fw-semibold);
            transition: transform 0.2s, opacity 0.2s;
        }

        .btn-ai-analyze:hover {
            transform: translateY(-1px);
            opacity: 0.9;
        }

        .ai-status-loader {
            display: none;
            margin-left: 10px;
            align-items: center;
        }

        .ai-content-scroll {
            flex-grow: 1;
            overflow-y: auto;
            padding-right: 5px;
        }

        .ai-insight-card {
            background: rgba(255, 255, 255, 0.08);
            border-left: 4px solid #00c6ff;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 15px;
        }

        .ai-insight-text {
            font-size: var(--aot-fs-body);
            line-height: var(--aot-lh-base);
            color: #e0e0e0;
        }

        .ai-action-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .ai-action-card {
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: background 0.3s;
        }

        .ai-action-card:hover {
            background: rgba(255, 255, 255, 0.05);
        }

        .ai-action-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .ai-action-desc {
            font-weight: var(--aot-fw-medium);
            font-size: var(--aot-fs-body);
        }

        .ai-action-meta {
            font-size: var(--aot-fs-caption);
            color: #aaa;
        }

        .btn-ai-execute {
            background: rgba(40, 167, 69, 0.2);
            border: 1px solid #28a745;
            color: var(--aot-color-success, #28a745);
            border-radius: 20px;
            padding: 5px 15px;
            font-size: var(--aot-fs-label);
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-ai-execute:hover {
            background: #28a745;
            color: var(--text-color-tertiary, white);
        }

        /* Scrollbar styling */
        .ai-content-scroll::-webkit-scrollbar {
            width: 6px;
        }
        .ai-content-scroll::-webkit-scrollbar-track {
            background: transparent;
        }
        .ai-content-scroll::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 3px;
        }
    </style>
    """,

    'widget_dashboard_body': """
    <div class="ai-insight-container" id="ai-container-{{each_widget.unique_id}}">
        <div class="ai-goal-section">
            <input type="text" class="ai-goal-input" id="ai-goal-{{each_widget.unique_id}}" 
                   placeholder="{{ _('Envision a goal (e.g., Save energy in Zone A)') }}" 
                   value="{{ widget_options.get('default_goal', '') }}">
            <button class="btn-ai-analyze" onclick="runAIReasoning('{{each_widget.unique_id}}', '{{ widget_options.get('agent_id', '') }}')">
                {{ _('Analyze') }}
            </button>
            <div class="ai-status-loader" id="ai-loader-{{each_widget.unique_id}}">
                <i class="fas fa-circle-notch fa-spin"></i>
            </div>
        </div>

        <div id="ai-active-agent-{{each_widget.unique_id}}" class="small text-muted mb-2" style="display:none; padding: 0 5px;">
             <i class="fas fa-robot mr-1"></i> <span class="agent-name"></span>
        </div>

        <div class="ai-content-scroll">
            <div id="ai-insight-display-{{each_widget.unique_id}}">
                <div style="text-align: center; color: #888; margin-top: 40px;">
                    <i class="fas fa-brain fa-3x" style="margin-bottom: 15px; opacity: 0.3;"></i>
                    <p>{{ _('Ready for intelligent analysis.') }}</p>
                </div>
            </div>
            
            <div id="ai-actions-container-{{each_widget.unique_id}}" style="margin-top: 20px;">
                <!-- Actions will be injected here -->
            </div>
        </div>
    </div>
    """,

    'widget_dashboard_js': """
    function runAIReasoning(wid, agentId) {
        const goalInput = document.getElementById('ai-goal-' + wid);
        const loader = document.getElementById('ai-loader-' + wid);
        const display = document.getElementById('ai-insight-display-' + wid);
        const actionsContainer = document.getElementById('ai-actions-container-' + wid);
        const agentStatus = document.getElementById('ai-active-agent-' + wid);

        const goal = goalInput.value || 'Optimize system';
        
        loader.style.display = 'flex';
        
        $.ajax({
            url: `/ai_widget/reason?goal=${encodeURIComponent(goal)}&agent_id=${agentId}`,
            type: 'GET',
            success: function(data) {
                loader.style.display = 'none';
                if (data.status === 'error') {
                    window.showToast(data.message, 'error');
                    return;
                }

                // Show active agent info
                if(data.agent_name) {
                    $(agentStatus).show().find('.agent-name').text(data.agent_name);
                }

                // Render Insight
                display.innerHTML = `
                    <div class="ai-insight-card">
                        <div class="ai-insight-text">
                            ${data.insight || data.reasoning_insight}
                        </div>
                    </div>
                `;

                // Render Actions
                let actionsHtml = '';
                const historyId = data.history_id || '';
                const actions = data.proposed_actions || [];

                if (actions.length > 0) {
                    actionsHtml = `<h5>${window._('Proposed Actions')}</h5><div class="ai-action-list">`;
                    actions.forEach((action, index) => {
                        actionsHtml += `
                            <div class="ai-action-card">
                                <div class="ai-action-info">
                                    <span class="ai-action-desc">${action.description}</span>
                                    <span class="ai-action-meta">${action.action_type.toUpperCase()} | Target: ${action.target_id}</span>
                                </div>
                                <button class="btn-ai-execute" onclick='executeAIAction("${wid}", ${index}, "${historyId}", ${JSON.stringify(action)})'>
                                    ${window._('Execute')}
                                </button>
                            </div>
                        `;
                    });
                    actionsHtml += '</div>';
                }
                actionsContainer.innerHTML = actionsHtml;
                
                window.showToast(window._('Analysis complete'), 'success');
            },
            error: function(err) {
                loader.style.display = 'none';
                window.showToast('{{_("AI analysis failed")}}', 'error');
            }
        });
    }

    function executeAIAction(wid, index, historyId, legacyAction) {
        if (!confirm(`${window._('Execute following action?')}\\n\\n${legacyAction.description}`)) {
            return;
        }

        const payload = historyId ? { history_id: historyId, action_index: index } : legacyAction;

        $.ajax({
            url: '/ai_widget/execute',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(payload),
            success: function(resp) {
                if (resp.status === 'success') {
                    window.showToast(window._('Action executed effectively'), 'success');
                } else {
                    window.showToast(resp.message || '{{_("Execution failed")}}', 'error');
                }
            },
            error: function() {
                window.showToast('{{_("Communication error")}}', 'error');
            }
        });
    }
    """,

    'widget_dashboard_js_ready_end': """
    // Optional: Initial analysis if refresh is set or just to show data
    // runAIReasoning('{{each_widget.unique_id}}');
    """
}

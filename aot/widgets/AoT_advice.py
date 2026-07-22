# coding=utf-8
"""
AoT Periodic Advice Widget — Variant A (Standalone)

Surfaces pre-generated AISystemSummary records in a size-adaptive
three-tier layout (Small / Medium / Large) driven by ResizeObserver.
Operator learning input is persisted via AIMemoryManager.buffer_memory.

plan_ref: 2603_AoT_ai/Tasks/5_docker/AI/2026_03_28_ADVICE_WIDGET_PLAN/005_plan_v2.yaml
"""
import json
import logging

from flask import jsonify, request
from flask_babel import lazy_gettext

from aot.widgets.base_widget import AbstractWidget

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data-layer endpoint: GET /widget/advice/latest
# ---------------------------------------------------------------------------
def advice_get_latest():
    """Return the most recent AISystemSummary for the requested scope.

    @phase active
    @stability stable
    @dependency AISummaryService
    """
    scope_type = request.args.get('scope_type', 'system')
    scope_id = request.args.get('scope_id') or None
    try:
        from aot.ai.services.ai_summary_service import AISummaryService
        summary = AISummaryService.get_latest_summary(
            scope_type=scope_type,
            scope_id=scope_id,
        )
        if not summary:
            return jsonify({'status': 'ok', 'data': None})

        change_items = []
        if summary.change_summary:
            try:
                change_items = json.loads(summary.change_summary)
            except (ValueError, TypeError):
                change_items = []

        return jsonify({
            'status': 'ok',
            'data': {
                'id': summary.id,
                'unique_id': summary.unique_id,
                'scope_type': summary.scope_type,
                'scope_id': summary.scope_id,
                'summary_text': summary.summary_text,
                'change_items': change_items,
                'alert_level': summary.alert_level,
                'anomaly_detected': summary.anomaly_detected,
                'quality_score': summary.quality_score,
                'timestamp': (
                    summary.timestamp.isoformat()
                    if summary.timestamp else None
                ),
                'version': summary.version,
            },
        })
    except Exception:
        logger.exception("Error in advice_get_latest")
        return jsonify({'status': 'error', 'message': 'Unable to retrieve advice'}), 500


# ---------------------------------------------------------------------------
# Data-layer endpoint: GET /widget/advice/history
# ---------------------------------------------------------------------------
def advice_get_history():
    """Return the N most recent AISystemSummary records for the requested scope.

    @phase active
    @stability stable
    @dependency AISummaryService
    """
    scope_type = request.args.get('scope_type', 'system')
    scope_id = request.args.get('scope_id') or None
    try:
        limit = int(request.args.get('limit', 5))
    except (TypeError, ValueError):
        limit = 5

    try:
        from aot.ai.services.ai_summary_service import AISummaryService
        records = AISummaryService.get_summary_history(
            scope_type=scope_type,
            scope_id=scope_id,
            limit=limit,
        )
        items = []
        for s in records:
            items.append({
                'id': s.id,
                'unique_id': s.unique_id,
                'summary_text': s.summary_text,
                'alert_level': s.alert_level,
                'quality_score': s.quality_score,
                'timestamp': s.timestamp.isoformat() if s.timestamp else None,
                'version': s.version,
            })
        return jsonify({'status': 'ok', 'data': items})
    except Exception:
        logger.exception("Error in advice_get_history")
        return jsonify({'status': 'error', 'message': 'Unable to retrieve history'}), 500


# ---------------------------------------------------------------------------
# Data-layer endpoint: POST /widget/advice/learn
# ---------------------------------------------------------------------------
def advice_submit_learning():
    """Persist a free-text operator note via AIMemoryManager.buffer_memory so
    it may inform future AI synthesis cycles.

    Body: { "summary_id": <int|null>, "note_text": <str>, "facility_id": <str> }
    Response: { "status": "ok" }

    Implementation note: buffer_memory requires (user_id, memory_type, key,
    value, source). The plan assumed the signature was (text, source=...) but
    the actual signature differs. user_id is resolved from current_user.
    """
    data = request.json or {}
    note_text = data.get('note_text', '').strip()
    facility_id = data.get('facility_id', '')

    if not note_text:
        return jsonify({'status': 'error', 'message': 'note_text is required'}), 400
    if len(note_text) > 500:
        return jsonify({'status': 'error', 'message': 'Note exceeds 500 characters'}), 400

    try:
        from flask_login import current_user
        if not current_user.is_authenticated:
            return jsonify({'status': 'error', 'message': 'Authentication required'}), 401
        user_id = current_user.id

        from aot.ai.services.ai_memory_manager import AIMemoryManager
        key = (
            'operator_note_{}'.format(facility_id)
            if facility_id else 'operator_note'
        )
        AIMemoryManager.buffer_memory(
            user_id=user_id,
            memory_type='operator_note',
            key=key,
            value=note_text,
            source='operator_widget',
        )
        return jsonify({'status': 'ok'})
    except Exception:
        logger.exception("Error in advice_submit_learning")
        return jsonify({'status': 'error', 'message': 'Unable to save note'}), 500


# ---------------------------------------------------------------------------
# Widget class
# ---------------------------------------------------------------------------
class AoTAdviceWidget(AbstractWidget):
    """
    Standalone Periodic AI Advice Widget.
    Content depth adapts to GridStack size via ResizeObserver (client-side).
    No server round-trip is required for tier switching.
    """

    def __init__(self, widget, testing=False):
        super().__init__(widget, testing=testing, name=__name__)

    def execute_refresh(self):
        # Refresh is driven by client-side polling (setInterval / manual button).
        pass


# ---------------------------------------------------------------------------
# Widget registration metadata
# ---------------------------------------------------------------------------
WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_advice',
    'widget_name': 'AI Periodic Advice',
    'widget_library': 'ai',
    'no_class': True,
    'message': (
        'Displays pre-generated periodic AI analysis. '
        'Content depth adapts to widget size automatically.'
    ),
    'widget_width': 12,
    'widget_height': 5,

    'endpoints': [
        ('/widget/advice/latest', 'advice_latest', advice_get_latest, ['GET']),
        ('/widget/advice/history', 'advice_history', advice_get_history, ['GET']),
        ('/widget/advice/learn', 'advice_learn', advice_submit_learning, ['POST']),
    ],

    'custom_options': [
        {
            'id': 'scope_type',
            'type': 'text',
            'default_value': 'system',
            'name': lazy_gettext('Scope Type'),
            'phrase': lazy_gettext(
                'Hierarchy level for advice: system, farm, device_group, or device.'
            ),
        },
        {
            'id': 'scope_id',
            'type': 'text',
            'default_value': '',
            'name': lazy_gettext('Scope ID'),
            'phrase': lazy_gettext(
                'Unique identifier of the target scope entity. '
                'Leave empty to use the top-level system scope.'
            ),
        },
        {
            'id': 'advice_scope',
            'type': 'select',
            'default_value': 'facility',
            'options_select': [
                ('facility', lazy_gettext('Facility')),
                ('zone', lazy_gettext('Zone')),
                ('device', lazy_gettext('Device')),
            ],
            'name': lazy_gettext('Advice Scope'),
            'phrase': lazy_gettext('Scope level for AI advice display.'),
        },
        {
            'id': 'refresh_interval_minutes',
            'type': 'select',
            'default_value': '10',
            'options_select': [
                ('5', lazy_gettext('5 minutes')),
                ('10', lazy_gettext('10 minutes')),
                ('30', lazy_gettext('30 minutes')),
            ],
            'name': lazy_gettext('Refresh Interval'),
            'phrase': lazy_gettext('How often the widget polls for new advice.'),
        },
        {
            'id': 'min_alert_level',
            'type': 'select',
            'default_value': 'info',
            'options_select': [
                ('info', lazy_gettext('Info')),
                ('warning', lazy_gettext('Warning')),
                ('critical', lazy_gettext('Critical')),
            ],
            'name': lazy_gettext('Minimum Alert Level'),
            'phrase': lazy_gettext(
                'Advice below this alert level will be treated as empty.'
            ),
        },
        {
            'id': 'max_change_items',
            'type': 'integer',
            'default_value': 5,
            'name': lazy_gettext('Max Change Items'),
            'phrase': lazy_gettext(
                'Maximum number of change summary items to display (1-20).'
            ),
        },
        {
            'id': 'show_confidence_score',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show Confidence Score'),
            'phrase': lazy_gettext(
                'Display the AI confidence (quality) score in the widget.'
            ),
        },
    ],

    # ------------------------------------------------------------------
    # Head: CSS — tier-switching, text-centric, no icons, no gradients
    # ------------------------------------------------------------------
    'widget_dashboard_head': """
<style>
  /* ---------- Alert-level palette CSS custom properties ---------- */
  .aot-advice--none     { --aot-bg: #1A202C; --aot-text: #CBD5E0; --aot-border: #4A5568; }
  .aot-advice--info     { --aot-bg: #1A365D; --aot-text: #90CDF4; --aot-border: #3182CE; }
  .aot-advice--warning  { --aot-bg: #2D2A00; --aot-text: #F6E05E; --aot-border: #D69E2E; }
  .aot-advice--critical { --aot-bg: #2D0F0F; --aot-text: #FEB2B2; --aot-border: #E53E3E; }

  /* ---------- container ---------- */
  /* 이 위젯은 항상 어두운 배경(--aot-bg, 기본 #1A202C)의 자체 알림-레벨 색상
     체계(--aot-bg/--aot-text/--aot-border)를 쓴다. 아래 회색 계열 텍스트색은
     그 어두운 배경 위에서의 가독성을 위해 조정된 값으로, 라이트모드 전역
     텍스트 토큰(--aot-color-text-*)과 무관하게 리터럴로 유지한다. */
  .aot-advice-container {
    position: relative;
    height: 100%;
    padding: 8px 10px;
    box-sizing: border-box;
    overflow: hidden;
    font-size: var(--aot-fs-body);
    font-family: var(--aot-font-family);
    line-height: var(--aot-lh-base);
    color: #ddd;
  }

  /* ---------- CSS variables applied via alert-level class ---------- */
  .aot-advice {
    background-color: var(--aot-bg, #1A202C);
    color: var(--aot-text, #CBD5E0);
    border-color: var(--aot-border, #4A5568);
  }

  /* ---------- tier visibility ---------- */
  .aot-advice-tier { display: none; height: 100%; overflow: hidden; }
  .aot-advice--small  .aot-advice-tier-small  { display: flex; flex-direction: column; }
  .aot-advice--medium .aot-advice-tier-medium { display: flex; flex-direction: column; }
  .aot-advice--large  .aot-advice-tier-large  { display: flex; flex-direction: column; }

  /* ---------- small tier ---------- */
  .aot-advice-tier-small .advice-summary-line {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 1;
    min-width: 0;
  }
  .aot-advice-tier-small .advice-ts-label {
    font-size: var(--aot-fs-caption);
    color: #888;
    white-space: nowrap;
  }
  .advice-small-row {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    min-width: 0;
  }

  /* ---------- medium / large shared ---------- */
  .advice-summary-block {
    font-weight: var(--aot-fw-medium);
    margin-bottom: 6px;
  }
  .advice-detail-block {
    color: #bbb;
    margin-bottom: 6px;
    overflow-y: auto;
    flex-shrink: 1;
  }
  .advice-meta-row {
    display: flex;
    gap: 12px;
    font-size: var(--aot-fs-caption);
    color: #888;
    margin-top: 4px;
  }
  .advice-alert-badge {
    font-size: var(--aot-fs-caption);
    padding: 1px 5px;
    border-radius: 3px;
    border: 1px solid #666;
    color: #aaa;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .advice-alert-badge.warning { border-color: #a07800; color: #f0b800; }
  .advice-alert-badge.critical { border-color: #8b0000; color: #ff4444; }

  /* ---------- anomaly list (large only) ---------- */
  .advice-anomaly-list {
    list-style: none;
    padding: 0;
    margin: 4px 0 6px;
    font-size: var(--aot-fs-label);
    color: #bbb;
    overflow-y: auto;
    flex-shrink: 1;
  }
  .advice-anomaly-list li::before {
    content: "- ";
  }

  /* ---------- refresh link ---------- */
  .advice-refresh-link {
    position: absolute;
    top: 6px;
    right: 10px;
    font-size: var(--aot-fs-caption);
    color: #666;
    cursor: pointer;
    user-select: none;
  }
  .advice-refresh-link:hover { color: #999; }

  /* ---------- learning input (large only) ---------- */
  .advice-learn-section {
    margin-top: auto;
    padding-top: 6px;
    border-top: 1px solid #333;
  }
  .advice-learn-toggle {
    font-size: var(--aot-fs-caption);
    color: #667;
    cursor: pointer;
    user-select: none;
  }
  .advice-learn-toggle:hover { color: #99a; }
  .advice-learn-form { margin-top: 4px; }
  .advice-learn-textarea {
    width: 100%;
    height: 56px;
    background: rgba(255,255,255,0.05);
    border: 1px solid #444;
    border-radius: 4px;
    color: #ccc;
    font-size: var(--aot-fs-label);
    padding: 4px 6px;
    resize: vertical;
    box-sizing: border-box;
  }
  .advice-learn-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 4px;
  }
  .advice-learn-submit {
    background: transparent;
    border: 1px solid #555;
    border-radius: 4px;
    color: #bbb;
    padding: 3px 10px;
    font-size: var(--aot-fs-caption);
    cursor: pointer;
  }
  .advice-learn-submit:hover { border-color: #888; color: #ddd; }
  .advice-learn-cancel {
    font-size: var(--aot-fs-caption);
    color: #666;
    cursor: pointer;
    user-select: none;
  }
  .advice-learn-cancel:hover { color: #999; }
  .advice-learn-msg {
    font-size: var(--aot-fs-caption);
    margin-top: 3px;
    min-height: 1em;
  }
  .advice-learn-msg.ok { color: #6a9; }
  .advice-learn-msg.err { color: #c66; }

  /* ---------- Typography token scale ---------- */
  .aot-advice__summary   { font-size: var(--aot-fs-title);   font-weight: var(--aot-fw-semibold); }
  .aot-advice__detail    { font-size: var(--aot-fs-body);    font-weight: var(--aot-fw-regular); }
  .aot-advice__action    { font-size: var(--aot-fs-body);    font-weight: var(--aot-fw-regular); text-decoration: underline; }
  .aot-advice__timestamp { font-size: var(--aot-fs-caption); font-weight: var(--aot-fw-regular); opacity: 0.6; }

  /* ---------- Alert level badge ---------- */
  .aot-advice__badge {
    font-weight: var(--aot-fw-bold);
    font-family: monospace;
    color: var(--aot-text);
    margin-left: 0.5em;
    white-space: nowrap;
  }

  /* ---------- Tier separator (medium and large) ---------- */
  .aot-advice--medium .aot-advice__detail,
  .aot-advice--large  .aot-advice__detail {
    border-top: 1px solid var(--aot-border);
    padding-top: 0.5em;
    margin-top: 0.5em;
  }

  /* ---------- Empty state ---------- */
  .aot-advice__empty { display: none; }
  .aot-advice--empty .aot-advice__empty {
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0.7;
    font-size: var(--aot-fs-body);
    text-align: center;
    padding: 1rem;
  }

  /* ---------- Loading state ---------- */
  .aot-advice--refreshing .aot-advice__timestamp::after {
    content: " \00B7 {{_('Updating...')}}";
    opacity: 0.5;
    font-size: var(--aot-fs-caption);
  }

  /* ---------- Error state ---------- */
  .aot-advice__error-msg {
    display: none;
    color: var(--aot-text);
    opacity: 0.6;
    font-size: var(--aot-fs-body);
  }
  .aot-advice--error .aot-advice__error-msg { display: block; }
  .aot-advice__retry {
    display: none;
    text-decoration: underline;
    font-size: var(--aot-fs-body);
  }
  .aot-advice--error .aot-advice__retry { display: inline; }

  /* ---------- Tier transition signal ---------- */
  .aot-advice--tier-changed { transition: opacity 0.2s ease; opacity: 0.85; }
</style>
""",

    # ------------------------------------------------------------------
    # Body: all three tier blocks — JS assigns active tier class
    # ------------------------------------------------------------------
    'widget_dashboard_body': """
<div class="aot-advice-container aot-advice aot-advice--none"
     id="aot-advice-{{each_widget.unique_id}}"
     data-scope-type="{{ widget_options.get('scope_type', 'system') }}"
     data-scope-id="{{ widget_options.get('scope_id', '') }}"
     data-advice-scope="{{ widget_options.get('advice_scope', 'facility') }}"
     data-refresh-interval-minutes="{{ widget_options.get('refresh_interval_minutes', '10') }}"
     data-min-alert-level="{{ widget_options.get('min_alert_level', 'info') }}"
     data-max-change-items="{{ widget_options.get('max_change_items', 5) }}"
     data-show-confidence-score="{{ 'true' if widget_options.get('show_confidence_score', True) else 'false' }}">

  <span class="advice-refresh-link"
        onclick="fetchAdviceData('{{each_widget.unique_id}}')">{{_('Refresh')}}</span>

  <!-- ─── Empty state ─────────────────────────────────────────── -->
  <div class="aot-advice__empty" aria-live="polite">{{_('No AI analysis available. Analysis runs automatically — check back shortly.')}}</div>

  <!-- ─── Error state ─────────────────────────────────────────── -->
  <div class="aot-advice__error-msg" id="advice-error-msg-{{each_widget.unique_id}}"></div>
  <a class="aot-advice__retry" href="#"
     id="advice-retry-{{each_widget.unique_id}}"
     onclick="fetchAdviceData('{{each_widget.unique_id}}'); return false;">{{_('Retry')}}</a>

  <!-- ─── Small tier ─────────────────────────────────────────── -->
  <div class="aot-advice-tier aot-advice-tier-small">
    <div class="advice-small-row">
      <span class="advice-summary-line aot-advice__summary"
            id="advice-sum-sm-{{each_widget.unique_id}}">{{_('Loading...')}}</span>
      <span class="aot-advice__badge"
            id="advice-badge-sm-{{each_widget.unique_id}}"></span>
      <span class="advice-ts-label aot-advice__timestamp"
            id="advice-ts-sm-{{each_widget.unique_id}}"></span>
    </div>
  </div>

  <!-- ─── Medium tier ────────────────────────────────────────── -->
  <div class="aot-advice-tier aot-advice-tier-medium">
    <div class="advice-summary-block aot-advice__summary"
         id="advice-sum-md-{{each_widget.unique_id}}">
      <span class="aot-advice__badge"
            id="advice-badge-md-{{each_widget.unique_id}}"></span>
    </div>
    <div class="advice-detail-block aot-advice__detail"
         id="advice-detail-md-{{each_widget.unique_id}}"></div>
    <div class="advice-meta-row">
      <span class="aot-advice__timestamp" id="advice-ts-md-{{each_widget.unique_id}}"></span>
      <span id="advice-conf-md-{{each_widget.unique_id}}"></span>
    </div>
  </div>

  <!-- ─── Large tier ─────────────────────────────────────────── -->
  <div class="aot-advice-tier aot-advice-tier-large">
    <div class="advice-summary-block aot-advice__summary"
         id="advice-sum-lg-{{each_widget.unique_id}}">
      <span class="aot-advice__badge"
            id="advice-badge-lg-{{each_widget.unique_id}}"></span>
    </div>
    <div class="advice-detail-block aot-advice__detail"
         id="advice-detail-lg-{{each_widget.unique_id}}"></div>
    <ul class="advice-anomaly-list"
        id="advice-anomalies-lg-{{each_widget.unique_id}}"></ul>
    <div class="advice-meta-row">
      <span class="aot-advice__timestamp" id="advice-ts-lg-{{each_widget.unique_id}}"></span>
      <span id="advice-conf-lg-{{each_widget.unique_id}}"></span>
      <span class="advice-alert-badge"
            id="advice-alert-lg-{{each_widget.unique_id}}"></span>
    </div>

    <!-- Learning input affordance (large tier only) -->
    <div class="advice-learn-section">
      <span class="advice-learn-toggle"
            onclick="toggleAdviceLearn('{{each_widget.unique_id}}')">{{_('Teach AI')}}</span>
      <div class="advice-learn-form"
           id="advice-learn-form-{{each_widget.unique_id}}"
           style="display:none">
        <textarea class="advice-learn-textarea"
                  id="advice-learn-text-{{each_widget.unique_id}}"
                  maxlength="500"
                  placeholder="{{_('Add a note to help the AI understand this facility...')}}"></textarea>
        <div class="advice-learn-actions">
          <button class="advice-learn-submit"
                  onclick="submitAdviceNote('{{each_widget.unique_id}}')">{{_('Submit')}}</button>
          <span class="advice-learn-cancel"
                onclick="toggleAdviceLearn('{{each_widget.unique_id}}')">{{_('Cancel')}}</span>
        </div>
        <div class="advice-learn-msg"
             id="advice-learn-msg-{{each_widget.unique_id}}"></div>
      </div>
    </div>
  </div>

</div>
""",

    # ------------------------------------------------------------------
    # JavaScript
    # ------------------------------------------------------------------
    'widget_dashboard_js': """
/* ── AoT Advice Widget helpers ─────────────────────────────────────── */

var _adviceResizeTimers = {};
var _advicePollIntervals = {};
var _adviceCurrentSummaryId = {};
var _advicePrevTier = {};

/* Alert level ordering for threshold comparison */
var ALERT_LEVEL_ORDER = { none: 0, info: 1, warning: 2, critical: 3 };
var ALERT_LABELS = { none: 'Normal', info: 'Info', warning: 'Warning', critical: 'Critical' };

/* Read widget options from data attributes */
function getAdviceOptions(wid) {
  var container = document.getElementById('aot-advice-' + wid);
  if (!container) return {};
  return {
    refreshIntervalMinutes: parseInt(container.dataset.refreshIntervalMinutes || '10', 10),
    minAlertLevel: container.dataset.minAlertLevel || 'info',
    maxChangeItems: parseInt(container.dataset.maxChangeItems || '5', 10),
    showConfidenceScore: container.dataset.showConfidenceScore !== 'false',
  };
}

/* Compute tier from pixel height and apply CSS class to container */
function setAdviceTier(wid, heightPx) {
  var ROW_H = 48;
  var rows = Math.floor(heightPx / ROW_H);
  var el = document.getElementById('aot-advice-' + wid);
  if (!el) return;

  var newTier;
  if (rows <= 3) {
    newTier = 'small';
  } else if (rows <= 6) {
    newTier = 'medium';
  } else {
    newTier = 'large';
  }

  var prevTier = _advicePrevTier[wid];
  el.classList.remove('aot-advice--small', 'aot-advice--medium', 'aot-advice--large');
  el.classList.add('aot-advice--' + newTier);

  /* Emit tier transition signal when tier changes */
  if (prevTier && prevTier !== newTier) {
    el.classList.add('aot-advice--tier-changed');
    setTimeout(function() { el.classList.remove('aot-advice--tier-changed'); }, 400);
  }
  _advicePrevTier[wid] = newTier;
}

/* Format ISO timestamp as "N hours ago" */
function adviceTimeAgo(isoString) {
  if (!isoString) return '';
  var now = new Date();
  var past = new Date(isoString);
  var diffMs = now - past;
  if (isNaN(diffMs)) return '';
  var diffHrs = Math.floor(diffMs / 3600000);
  if (diffHrs < 1) return '{{_("recently")}}';
  if (diffHrs === 1) return '{{_("1 hour ago")}}';
  if (diffHrs < 24) return diffHrs + ' {{_("hours ago")}}';
  return Math.floor(diffHrs / 24) + ' {{_("days ago")}}';
}

/* Format ISO timestamp as "YYYY-MM-DD HH:MM" */
function adviceFmtDatetime(isoString) {
  if (!isoString) return '';
  try {
    var d = new Date(isoString);
    var y = d.getFullYear();
    var mo = String(d.getMonth() + 1).padStart(2, '0');
    var dy = String(d.getDate()).padStart(2, '0');
    var h  = String(d.getHours()).padStart(2, '0');
    var mi = String(d.getMinutes()).padStart(2, '0');
    return y + '-' + mo + '-' + dy + ' ' + h + ':' + mi;
  } catch(e) { return ''; }
}

/* Render advisory data into all tier slots */
function renderAdviceData(wid, data) {
  var root = document.getElementById('aot-advice-' + wid);
  var opts = getAdviceOptions(wid);

  /* Clear error state on successful render */
  if (root) {
    root.classList.remove('aot-advice--error');
  }

  if (!data) {
    /* Empty state */
    if (root) root.classList.add('aot-advice--empty');
    var smSum = document.getElementById('advice-sum-sm-' + wid);
    if (smSum) smSum.textContent = '{{_("No analysis available yet.")}}';
    return;
  }

  /* Check min_alert_level threshold */
  var alertLevel = data.alert_level || 'none';
  var alertOrder = ALERT_LEVEL_ORDER[alertLevel] != null ? ALERT_LEVEL_ORDER[alertLevel] : 0;
  var minOrder   = ALERT_LEVEL_ORDER[opts.minAlertLevel] != null ? ALERT_LEVEL_ORDER[opts.minAlertLevel] : 0;
  if (alertOrder < minOrder) {
    /* Treat as empty state — below threshold */
    if (root) root.classList.add('aot-advice--empty');
    var smSum2 = document.getElementById('advice-sum-sm-' + wid);
    if (smSum2) smSum2.textContent = '{{_("No analysis available yet.")}}';
    return;
  }

  /* Data present — remove empty state */
  if (root) root.classList.remove('aot-advice--empty');

  _adviceCurrentSummaryId[wid] = data.id;

  var summaryText = data.summary_text || '';
  var allChangeItems = data.change_items || [];
  /* Limit change items per max_change_items option */
  var changeItems = allChangeItems.slice(0, opts.maxChangeItems);
  var qScore = (data.quality_score != null)
               ? Math.round(data.quality_score * 100) + '%'
               : null;
  var ts = data.timestamp || null;

  /* Update alert-level class on root for palette CSS variables */
  if (root) {
    root.classList.remove('aot-advice--none', 'aot-advice--info', 'aot-advice--warning', 'aot-advice--critical');
    root.classList.add('aot-advice--' + (alertLevel || 'none'));
  }

  /* Badge label text */
  var badgeText = '[' + (ALERT_LABELS[alertLevel] || 'Normal') + ']';

  /* ── Small tier ── */
  var smSum = document.getElementById('advice-sum-sm-' + wid);
  var smBadge = document.getElementById('advice-badge-sm-' + wid);
  var smTs  = document.getElementById('advice-ts-sm-' + wid);
  if (smSum) smSum.textContent = summaryText;
  if (smBadge) smBadge.textContent = badgeText;
  if (smTs)  smTs.textContent  = adviceTimeAgo(ts);

  /* ── Medium tier ── */
  var mdSum    = document.getElementById('advice-sum-md-' + wid);
  var mdBadge  = document.getElementById('advice-badge-md-' + wid);
  var mdDetail = document.getElementById('advice-detail-md-' + wid);
  var mdTs     = document.getElementById('advice-ts-md-' + wid);
  var mdConf   = document.getElementById('advice-conf-md-' + wid);
  if (mdSum) {
    /* Set summary text as first text node, keeping badge span intact */
    var firstChild = mdSum.firstChild;
    if (firstChild && firstChild.nodeType === Node.TEXT_NODE) {
      firstChild.textContent = summaryText + ' ';
    } else {
      mdSum.insertBefore(document.createTextNode(summaryText + ' '), mdSum.firstChild);
    }
  }
  if (mdBadge) mdBadge.textContent = badgeText;
  if (mdDetail) mdDetail.textContent = changeItems.length
    ? '{{_("Changes observed:")}} ' + changeItems.map(function(c) {
        return (typeof c === 'string') ? c : (c.description || JSON.stringify(c));
      }).join('; ')
    : '';
  if (mdTs)   mdTs.textContent   = adviceFmtDatetime(ts);
  if (mdConf) {
    if (opts.showConfidenceScore && qScore) {
      mdConf.textContent = '{{_("Confidence:")}} ' + qScore;
      mdConf.style.display = '';
    } else {
      mdConf.textContent = '';
      mdConf.style.display = 'none';
    }
  }

  /* ── Large tier ── */
  var lgSum      = document.getElementById('advice-sum-lg-' + wid);
  var lgBadge    = document.getElementById('advice-badge-lg-' + wid);
  var lgDetail   = document.getElementById('advice-detail-lg-' + wid);
  var lgList     = document.getElementById('advice-anomalies-lg-' + wid);
  var lgTs       = document.getElementById('advice-ts-lg-' + wid);
  var lgConf     = document.getElementById('advice-conf-lg-' + wid);
  var lgAlert    = document.getElementById('advice-alert-lg-' + wid);
  if (lgSum) {
    var lgFirstChild = lgSum.firstChild;
    if (lgFirstChild && lgFirstChild.nodeType === Node.TEXT_NODE) {
      lgFirstChild.textContent = summaryText + ' ';
    } else {
      lgSum.insertBefore(document.createTextNode(summaryText + ' '), lgSum.firstChild);
    }
  }
  if (lgBadge) lgBadge.textContent = badgeText;
  if (lgDetail) lgDetail.textContent = changeItems.length
    ? '{{_("The analysis may suggest the following changes occurred:")}}'
    : '';

  /* Render anomaly items as plain text list */
  if (lgList) {
    lgList.innerHTML = '';
    changeItems.forEach(function(c) {
      var li = document.createElement('li');
      li.textContent = (typeof c === 'string') ? c : (c.description || JSON.stringify(c));
      lgList.appendChild(li);
    });
  }
  if (lgTs)   lgTs.textContent   = adviceFmtDatetime(ts);
  if (lgConf) {
    if (opts.showConfidenceScore && qScore) {
      lgConf.textContent = '{{_("Confidence:")}} ' + qScore;
      lgConf.style.display = '';
    } else {
      lgConf.textContent = '';
      lgConf.style.display = 'none';
    }
  }
  if (lgAlert) {
    lgAlert.textContent = (alertLevel && alertLevel !== 'none') ? alertLevel : '';
    lgAlert.className = 'advice-alert-badge ' + (alertLevel || '');
  }
}

/* Fetch latest advice from the server */
function fetchAdviceData(wid) {
  var container = document.getElementById('aot-advice-' + wid);
  if (!container) return;
  var scopeType = container.dataset.scopeType || 'system';
  var scopeId   = container.dataset.scopeId   || '';

  /* Loading state: add refreshing class */
  container.classList.add('aot-advice--refreshing');

  /* tier_small: set timestamp to "Updating..." */
  var smTs = document.getElementById('advice-ts-sm-' + wid);
  var smTsPrev = smTs ? smTs.textContent : '';
  if (smTs) smTs.textContent = '{{_("Updating...")}}';

  $.ajax({
    url: '/widget/advice/latest',
    type: 'GET',
    data: { scope_type: scopeType, scope_id: scopeId },
    success: function(resp) {
      container.classList.remove('aot-advice--refreshing');
      container.classList.remove('aot-advice--error');
      if (smTs && smTs.textContent === '{{_("Updating...")}}') smTs.textContent = smTsPrev;
      if (resp && resp.status === 'ok') {
        renderAdviceData(wid, resp.data);
      }
    },
    error: function() {
      container.classList.remove('aot-advice--refreshing');
      if (smTs && smTs.textContent === '{{_("Updating...")}}') smTs.textContent = smTsPrev;

      /* Error state */
      container.classList.add('aot-advice--error');
      var errMsg = document.getElementById('advice-error-msg-' + wid);
      if (errMsg) {
        errMsg.textContent = '{{_("Unable to load advice. Check connection.")}}';
      }
    }
  });
}

/* Toggle the learning input affordance (large tier) */
function toggleAdviceLearn(wid) {
  var form = document.getElementById('advice-learn-form-' + wid);
  if (!form) return;
  var visible = form.style.display !== 'none';
  form.style.display = visible ? 'none' : 'block';
  if (visible) {
    /* Clear message and textarea when collapsing */
    var msg  = document.getElementById('advice-learn-msg-' + wid);
    var text = document.getElementById('advice-learn-text-' + wid);
    if (msg)  { msg.textContent = ''; msg.className = 'advice-learn-msg'; }
    if (text) text.value = '';
  }
}

/* POST operator note to /widget/advice/learn */
function submitAdviceNote(wid) {
  var textEl  = document.getElementById('advice-learn-text-' + wid);
  var msgEl   = document.getElementById('advice-learn-msg-' + wid);
  var container = document.getElementById('aot-advice-' + wid);
  if (!textEl || !msgEl || !container) return;

  var noteText   = textEl.value.trim();
  var facilityId = container.dataset.scopeId || '';
  var summaryId  = _adviceCurrentSummaryId[wid] || null;

  if (!noteText) {
    msgEl.textContent = '{{_("Please enter a note before submitting.")}}';
    msgEl.className = 'advice-learn-msg err';
    return;
  }

  $.ajax({
    url: '/widget/advice/learn',
    type: 'POST',
    contentType: 'application/json',
    data: JSON.stringify({
      note_text:   noteText,
      facility_id: facilityId,
      summary_id:  summaryId
    }),
    success: function(resp) {
      if (resp && resp.status === 'ok') {
        msgEl.textContent = '{{_("Note saved - will inform the next AI cycle.")}}';
        msgEl.className = 'advice-learn-msg ok';
        textEl.value = '';
        setTimeout(function() { toggleAdviceLearn(wid); }, 3000);
      } else {
        msgEl.textContent = (resp && resp.message) ? resp.message : '{{_("Submission failed.")}}';
        msgEl.className = 'advice-learn-msg err';
      }
    },
    error: function() {
      msgEl.textContent = '{{_("Unable to save note. Please try again.")}}';
      msgEl.className = 'advice-learn-msg err';
    }
  });
}

/* Initialise widget: ResizeObserver + initial tier + configurable polling */
function initAdviceWidget(wid) {
  var container = document.getElementById('aot-advice-' + wid);
  if (!container) return;

  var gridContent = container.closest('.gridstack-item-content');
  if (!gridContent) gridContent = container.parentElement;

  /* Set initial tier from current height */
  setAdviceTier(wid, gridContent.clientHeight);

  /* ResizeObserver with 50ms debounce to avoid mid-transition flicker */
  if (typeof ResizeObserver !== 'undefined') {
    // Disconnect the previous observer for this widget so a live-preview re-init
    // doesn't stack observers (each would re-fire setAdviceTier).
    window._adviceResizeObservers = window._adviceResizeObservers || {};
    if (window._adviceResizeObservers[wid]) {
      try { window._adviceResizeObservers[wid].disconnect(); } catch (e) {}
    }
    var ro = new ResizeObserver(function(entries) {
      var h = entries[0].contentRect.height;
      clearTimeout(_adviceResizeTimers[wid]);
      _adviceResizeTimers[wid] = setTimeout(function() {
        setAdviceTier(wid, h);
      }, 50);
    });
    ro.observe(gridContent);
    window._adviceResizeObservers[wid] = ro;
  }

  /* Initial data fetch */
  fetchAdviceData(wid);

  /* Configurable polling interval from widget option (refresh_interval_minutes) */
  if (_advicePollIntervals[wid]) {
    clearInterval(_advicePollIntervals[wid]);
  }
  var opts = getAdviceOptions(wid);
  var intervalMs = (opts.refreshIntervalMinutes || 10) * 60000;
  _advicePollIntervals[wid] = setInterval(function() {
    fetchAdviceData(wid);
  }, intervalMs);
}
""",

    # ------------------------------------------------------------------
    # JS ready end: bootstrap the widget after the page is ready
    # ------------------------------------------------------------------
    'widget_dashboard_js_ready_end': """
initAdviceWidget('{{each_widget.unique_id}}');
""",
}

# coding=utf-8
"""
routes_ai_monitoring.py - Phase 7 Monitoring Endpoints

Flask Blueprint for internal/admin monitoring of AI system health and learning effectiveness.

These endpoints are for internal use only — require admin authentication.
They power the monitoring dashboard and scheduled health checks.

Blueprint: ai_monitoring_bp (url_prefix="/ai/internal/monitoring")

Endpoints:
- GET /ai/internal/monitoring/health → System-wide learning health
- GET /ai/internal/monitoring/confidence-agreement → Confidence calibration analysis
- POST /ai/internal/monitoring/scan-stalled → Background job to detect stalled learning
"""

import logging
import functools
from flask import Blueprint, jsonify
from flask_login import login_required
from aot.ai.services.ai_monitoring_service import AIMonitoringService


def auth_admin(f):
    """Placeholder admin guard — enforces login_required; extend when role model is ready."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated

logger = logging.getLogger(__name__)

# Blueprint definition
ai_monitoring_bp = Blueprint(
    'ai_monitoring',
    __name__,
    url_prefix='/ai/internal/monitoring'
)


# ============================================================================
# ROUTE: GET /ai/internal/monitoring/health
# ============================================================================
@ai_monitoring_bp.route('/health', methods=['GET'])
@login_required
@auth_admin
def endpoint_health():
    """
    Get system-wide AI learning health metrics.

    Response:
    {
      "total_facilities": <int>,
      "active_learning_facilities": <int>,
      "stalled_facilities": [<facility_id>, ...],
      "avg_feedback_rate_per_day": <float>,
      "total_feedback_events_last_30_days": <int>,
      "facilities_with_zero_feedback_7d": [<facility_id>, ...]
    }

    Authentication: Admin only
    """
    try:
        health_data = AIMonitoringService.get_system_health()
        return jsonify({
            "status": "success",
            "data": health_data
        }), 200
    except Exception as e:
        logger.error(f"[AIMonitoring] /health endpoint failed: {e}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


# ============================================================================
# ROUTE: GET /ai/internal/monitoring/confidence-agreement
# ============================================================================
@ai_monitoring_bp.route('/confidence-agreement', methods=['GET'])
@login_required
@auth_admin
def endpoint_confidence_agreement():
    """
    Get confidence agreement analysis (cases where HIGH confidence was wrong).

    Response:
    {
      "high_confidence_rejections_30d": <int>,
      "high_confidence_confirmations_30d": <int>,
      "agreement_rate": <float>,  # 0.0-1.0
      "most_rejected_parameters": [<parameter_name>, ...]
    }

    Purpose: Identify parameters where system confidence is miscalibrated.

    Authentication: Admin only
    """
    try:
        report = AIMonitoringService.get_confidence_agreement_report()
        return jsonify({
            "status": "success",
            "data": report
        }), 200
    except Exception as e:
        logger.error(f"[AIMonitoring] /confidence-agreement endpoint failed: {e}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


# ============================================================================
# ROUTE: POST /ai/internal/monitoring/scan-stalled
# ============================================================================
@ai_monitoring_bp.route('/scan-stalled', methods=['POST'])
@login_required
@auth_admin
def endpoint_scan_stalled():
    """
    Background job: scan all facilities and detect stalled learning.

    Response:
    {
      "status": "success",
      "stalled_facility_count": <int>,
      "stalled_facilities": [<facility_id>, ...]
    }

    Purpose: Called by scheduled job (cron or APScheduler) to proactively
    detect facilities where learning has stopped and update monitoring state.

    Authentication: Admin only

    Side Effects:
    - Updates AIFacilityLearning.stalled_since for affected facilities
    - Logs stalled detection
    """
    try:
        stalled_ids = AIMonitoringService.record_stalled_facilities()
        return jsonify({
            "status": "success",
            "stalled_facility_count": len(stalled_ids),
            "stalled_facilities": stalled_ids
        }), 200
    except Exception as e:
        logger.error(f"[AIMonitoring] /scan-stalled endpoint failed: {e}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

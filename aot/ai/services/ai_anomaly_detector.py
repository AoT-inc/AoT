# coding=utf-8
import logging
import json
from typing import Optional, Dict, Any, List
from datetime import datetime

from aot.databases.models.ai_summary import AISystemSummary
# @ANCHOR: DECOUPLED_VIA_AI_CALLER_INTERFACE (IMP-003)
# AIAgentService is accessed via lazy import inside _analyze_patterns_with_ai()
# to prevent circular dependency. Direct top-level import removed per SBS-002_V2.

logger = logging.getLogger(__name__)

class AIAnomalyDetector:
    """
    v26.0: AI-powered Anomaly Detection for systems snapshots.
    Combines rule-based threshold checks and AI-driven pattern recognition.

    @phase active
    @stability unstable
    @dependency AISystemSummary
    """

    @staticmethod
    def detect_anomalies(
        current_data: Dict[str, Any],
        previous_summary: Optional[AISystemSummary] = None
    ) -> Dict[str, Any]:
        """
        Main entry point for anomaly detection.
        Returns a dict with 'anomaly_detected', 'alert_level', and 'anomalies' list.
        """
        results = {
            'anomaly_detected': False,
            'alert_level': 'none',
            'anomalies': [],
            'metrics': {}
        }

        # 1. Rule-based checks
        rule_violations = AIAnomalyDetector._check_threshold_violations(current_data, previous_summary)
        if rule_violations:
            results['anomalies'].extend(rule_violations)
            results['anomaly_detected'] = True
            # Determine highest alert level from rules
            results['alert_level'] = AIAnomalyDetector._determine_alert_level(rule_violations)

        # 2. AI-based pattern analysis (Optional, triggered by rules or manual)
        if results['anomaly_detected'] or not previous_summary:
             # If rules found something, use AI to analyze patterns deeper
             ai_patterns = AIAnomalyDetector._analyze_patterns_with_ai(current_data, previous_summary)
             if ai_patterns:
                 results['anomalies'].extend(ai_patterns)
                 # Re-evaluate alert level
                 results['alert_level'] = AIAnomalyDetector._determine_alert_level(results['anomalies'])

        return results

    @staticmethod
    def _check_threshold_violations(current_data: Dict[str, Any], previous_summary: Optional[AISystemSummary]) -> List[Dict[str, Any]]:
        """Rule-based threshold violations."""
        violations = []
        metrics = current_data.get('metrics', {})
        
        # Thresholds (Configurable later)
        MAX_OFFLINE_RATIO = 0.2 # 20%
        MAX_ERROR_RATE = 0.5 # 50%

        active = metrics.get('active_devices', 0)

        # Devices genuinely not answering, out of those able to report at all.
        # Previously this was computed as (total - active)/total, i.e. from
        # is_activated — the operator's on/off intent — so switching a few
        # devices off for maintenance raised a "device-offline" alarm while a
        # truly dead device raised none. comm_* (io_link_health_infra_plan.md)
        # provides the real signal; devices that cannot observe their own link
        # are excluded rather than counted as healthy.
        comm_capable = metrics.get('comm_capable_devices', 0)
        comm_offline = metrics.get('comm_offline_devices', 0)
        if comm_capable > 0:
            offline_ratio = comm_offline / comm_capable
            if offline_ratio > MAX_OFFLINE_RATIO:
                violations.append({
                    'type': 'offline_devices',
                    'level': 'warning' if offline_ratio < 0.5 else 'critical',
                    'message': (f"{comm_offline} of {comm_capable} reachable-checkable "
                                f"devices are not responding ({offline_ratio:.1%})")
                })

        # Compare with previous if available
        if previous_summary:
            try:
                prev_metrics = json.loads(previous_summary.metadata_json).get('metrics', {})
                # A sudden rise in genuinely-unreachable devices. Was keyed off
                # active_devices, which only ever meant "someone deactivated
                # things", not a connectivity event.
                prev_offline = prev_metrics.get('comm_offline_devices', 0)
                if comm_capable > 0 and comm_offline > prev_offline:
                    jump = comm_offline - prev_offline
                    if jump >= max(2, comm_capable * 0.2):
                        violations.append({
                            'type': 'connectivity_drop',
                            'level': 'critical',
                            'message': (f"Sharp rise in unreachable devices: "
                                        f"{prev_offline} -> {comm_offline}")
                        })
                # Kept separately and named for what it is, so a maintenance
                # shutdown is still visible but never reported as connectivity.
                prev_active = prev_metrics.get('active_devices', 0)
                if prev_active > 0 and active < prev_active * 0.8: # 20% drop
                    violations.append({
                        'type': 'devices_deactivated',
                        'level': 'info',
                        'message': f"Devices deactivated: {prev_active} -> {active} enabled"
                    })
            except:
                pass

        return violations

    @staticmethod
    def _determine_alert_level(violations: List[Dict[str, Any]]) -> str:
        levels = [v.get('level', 'none') for v in violations]
        if 'critical' in levels: return 'critical'
        if 'warning' in levels: return 'warning'
        if 'info' in levels: return 'info'
        return 'none'

    @staticmethod
    def _analyze_patterns_with_ai(current_data: Dict[str, Any], previous_summary: Optional[AISystemSummary]) -> List[Dict[str, Any]]:
        """
        Use AI to find subtle patterns or correlate anomalies.
        Analyzes trends and patterns that rule-based detection might miss.
        """
        if not previous_summary:
            return []  # Need historical data for pattern analysis
        
        try:
            from aot.ai.services.ai_agent_service import AIAgentService
            from aot.databases.models import AIAgent
            
            # Get a lightweight AI agent for pattern analysis
            agent = AIAgent.query.filter_by(role='router').first()
            if not agent:
                logger.warning("No AI agent available for pattern analysis")
                return []
            
            engine = AIAgentService.get_engine(agent.unique_id)
            if not engine:
                return []
            
            # Build analysis prompt
            try:
                prev_metrics = json.loads(previous_summary.metadata_json).get('metrics', {})
            except:
                prev_metrics = {}
            
            current_metrics = current_data.get('metrics', {})
            
            from aot.utils.time_utils import get_local_now, to_local
            current_time = get_local_now()
            # previous_summary.timestamp is stored naive-UTC (SQLite column) — must
            # go through the SAME local conversion as current_time, or the two
            # "Timestamp" fields in this prompt look like the same clock while
            # actually being ~9h apart (KST), misleading "unusual timing" analysis.
            previous_time = to_local(previous_summary.timestamp)

            prompt = f"""
Analyze the following system metrics for anomalies or concerning patterns:

Previous State:
- Total Devices: {prev_metrics.get('total_devices', 0)}
- Active Devices: {prev_metrics.get('active_devices', 0)}
- Timestamp: {previous_time}

Current State:
- Total Devices: {current_metrics.get('total_devices', 0)}
- Active Devices: {current_metrics.get('active_devices', 0)}
- Timestamp: {current_time}

Previous Summary: {previous_summary.summary_text[:200]}

Task: Identify any subtle patterns, trends, or correlations that might indicate:
1. Gradual degradation
2. Unusual timing patterns
3. Correlated failures
4. Resource exhaustion trends

Respond with ONLY a JSON array of anomalies (empty array if none found):
[
  {{
    "type": "pattern_type",
    "level": "info|warning|critical",
    "message": "description"
  }}
]
"""
            
            context = {"current_time": current_time.isoformat()}
            result = engine.run_reasoning(context, prompt)
            
            # Parse AI response
            insight = result.get('insight', '[]')
            
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\[.*\]', insight, re.DOTALL)
            if json_match:
                patterns = json.loads(json_match.group(0))
                if isinstance(patterns, list):
                    logger.info(f"AI pattern analysis found {len(patterns)} patterns")
                    return patterns
            
            return []
            
        except Exception as e:
            logger.error(f"AI pattern analysis failed: {e}", exc_info=True)
            return []

    @staticmethod
    def trigger_alerts(anomaly_results: Dict[str, Any], scope_info: Dict[str, Any], summary_text: str = None):
        """
        Integrate with Notification Service.
        Sends email notifications for Warning/Critical anomalies.
        
        Args:
            anomaly_results: Dict with 'anomaly_detected', 'alert_level', 'anomalies'
            scope_info: Dict with 'scope_type', 'scope_id', 'scope_name'
            summary_text: Optional summary text for context
        """
        if not anomaly_results.get('anomaly_detected'):
            return {'status': 'skipped', 'reason': 'no_anomaly'}

        level = anomaly_results.get('alert_level', 'none')
        if level in ['warning', 'critical']:
            logger.warning(f"ALERT TRIGGERED [{level.upper()}]: {anomaly_results['anomalies']}")
            
            # Send notifications via NotificationService
            try:
                from aot.ai.services.notification_service import NotificationService
                
                result = NotificationService.send_anomaly_alert(
                    anomaly_results=anomaly_results,
                    scope_info=scope_info,
                    summary_text=summary_text
                )

                # Real-time WebUI toast via SSE
                scope_name = scope_info.get('scope_name', scope_info.get('scope_type', 'System'))
                toast_level = 'error' if level == 'critical' else 'warning'
                NotificationService.send_webui_toast(
                    user_id='broadcast',
                    message=f"[{level.upper()}] Anomaly detected: {scope_name}",
                    level=toast_level,
                    duration=8000 if level == 'critical' else 5000
                )

                logger.info(f"Notification result: {result}")
                return result
                
            except Exception as e:
                logger.error(f"Failed to send notifications: {e}", exc_info=True)
                return {'status': 'error', 'reason': str(e)}
        
        return {'status': 'skipped', 'reason': 'low_severity'}

# coding=utf-8
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from aot.databases.models import SMTP, User
from aot.utils.send_data import send_email

logger = logging.getLogger(__name__)

class NotificationService:
    """
    v26.3: Unified notification service for AI anomaly alerts and system notifications.
    Supports Email, WebUI (future), and SMS (future).
    """

    @staticmethod
    def send_anomaly_alert(
        anomaly_results: Dict[str, Any],
        scope_info: Dict[str, Any],
        summary_text: str = None
    ) -> Dict[str, Any]:
        """
        Send anomaly alert notifications to administrators.
        
        Args:
            anomaly_results: Dict with 'anomaly_detected', 'alert_level', 'anomalies'
            scope_info: Dict with 'scope_type', 'scope_id', 'scope_name'
            summary_text: Optional summary text for context
            
        Returns:
            Dict with 'status', 'sent_count', 'errors'
        """
        if not anomaly_results.get('anomaly_detected'):
            return {'status': 'skipped', 'reason': 'no_anomaly'}
        
        alert_level = anomaly_results.get('alert_level', 'none')
        
        # Only send for warning or critical
        if alert_level not in ['warning', 'critical']:
            return {'status': 'skipped', 'reason': 'low_severity'}
        
        # Get SMTP configuration
        smtp_config = SMTP.query.first()
        if not smtp_config:
            logger.error("SMTP configuration not found. Cannot send alert.")
            return {'status': 'error', 'reason': 'smtp_not_configured'}
        
        # Get admin users (role_id == 1)
        admin_users = User.query.filter_by(role_id=1).all()
        if not admin_users:
            logger.warning("No admin users found to send alerts.")
            return {'status': 'error', 'reason': 'no_recipients'}
        
        # Build email content
        subject = NotificationService._build_alert_subject(alert_level, scope_info)
        body = NotificationService._build_alert_body(
            anomaly_results, 
            scope_info, 
            summary_text
        )
        
        # Send to all admins
        sent_count = 0
        errors = []
        
        for admin in admin_users:
            if not admin.email:
                continue
                
            try:
                result = send_email(
                    smtp_host=smtp_config.host,
                    smtp_protocol=smtp_config.protocol,
                    smtp_port=smtp_config.port,
                    smtp_user=smtp_config.user,
                    smtp_pass=smtp_config.passw,
                    smtp_email_from=smtp_config.email_from,
                    email_to=admin.email,
                    message_body=body,
                    subject=subject
                )
                
                if result == 0:  # Success (0 is success from send_email)
                    sent_count += 1
                    logger.info(f"Alert sent to {admin.email}")
                else:
                    error_msg = f"Send failed with code {result}"
                    errors.append(f"{admin.email}: {error_msg}")
                    logger.error(f"Failed to send alert to {admin.email}: {error_msg}")
                    
            except Exception as e:
                errors.append(f"{admin.email}: {str(e)}")
                logger.error(f"Exception sending alert to {admin.email}: {e}", exc_info=True)
        
        return {
            'status': 'success' if sent_count > 0 else 'error',
            'sent_count': sent_count,
            'errors': errors
        }

    @staticmethod
    def _build_alert_subject(alert_level: str, scope_info: Dict[str, Any]) -> str:
        """Build email subject line."""
        level_emoji = {
            'warning': '⚠️',
            'critical': '🚨'
        }
        
        emoji = level_emoji.get(alert_level, '📊')
        scope_name = scope_info.get('scope_name', scope_info.get('scope_type', 'System'))
        
        return f"{emoji} [{alert_level.upper()}] AoT System Alert: {scope_name}"

    @staticmethod
    def _build_alert_body(
        anomaly_results: Dict[str, Any],
        scope_info: Dict[str, Any],
        summary_text: str = None
    ) -> str:
        """Build email body content."""
        anomalies = anomaly_results.get('anomalies', [])
        alert_level = anomaly_results.get('alert_level', 'unknown')
        
        scope_type = scope_info.get('scope_type', 'system')
        scope_name = scope_info.get('scope_name', 'System')
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        body = f"""
AoT System Anomaly Alert
========================

Alert Level: {alert_level.upper()}
Scope: {scope_name} ({scope_type})
Timestamp: {timestamp}

Detected Anomalies:
-------------------
"""
        
        for i, anomaly in enumerate(anomalies, 1):
            anom_type = anomaly.get('type', 'unknown')
            anom_level = anomaly.get('level', 'info')
            anom_message = anomaly.get('message', 'No details')
            
            body += f"\n{i}. [{anom_level.upper()}] {anom_type}\n"
            body += f"   {anom_message}\n"
        
        if summary_text:
            body += f"\n\nSystem Summary:\n"
            body += f"---------------\n"
            body += f"{summary_text[:500]}"
            if len(summary_text) > 500:
                body += "...\n"
        
        body += f"\n\n---\n"
        body += f"This is an automated alert from AoT AI System.\n"
        body += f"Please check the dashboard for more details.\n"
        
        return body

    @staticmethod
    def send_webui_toast(
        user_id: str,
        message: str,
        level: str = 'info',
        duration: int = 5000
    ) -> Dict[str, Any]:
        """Retired no-op. Kept so existing callers don't break.

        The WebUI toast used a persistent SSE stream (/api/alerts/stream) that
        held a gthread worker thread per browser tab and exhausted the worker
        pool (blank widgets / app-wide stalls). That endpoint and its frontend
        consumer were removed on 2026-07-19; in-app toasts are no longer pushed.
        Deliver alerts via Conditional Functions + the Send Email action instead.
        """
        logger.debug("[WebUI Toast] retired no-op (%s): %s", level, message)
        return {'status': 'disabled'}

    @staticmethod
    def send_sms(
        phone_number: str,
        message: str
    ) -> Dict[str, Any]:
        """
        Send SMS notification (Future implementation).
        
        Args:
            phone_number: Target phone number
            message: SMS message content
            
        Returns:
            Dict with 'status'
        """
        # TODO: Integrate with SMS gateway (Twilio, AWS SNS, etc.)
        logger.info(f"[SMS] to {phone_number}: {message}")
        return {'status': 'not_implemented'}

"""실시간 감시 작업: 이메일 발송 + 중복 억제."""
import unittest
from unittest import mock

from aot.ai.services import ai_scheduler_service as sched


class RealtimeAlertEmailTest(unittest.TestCase):
    def setUp(self):
        sched._realtime_alert_last_sent.clear()
        sched._realtime_alert_last_state.clear()
        sched._flask_app = mock.MagicMock()

    def _run(self, violations, level='warning'):
        with mock.patch('aot.ai.services.ai_runtime_state.ai_autonomy_enabled', return_value=True), \
             mock.patch('aot.ai.services.ai_summary_service.AISummaryService.gather_scope_data', return_value={}), \
             mock.patch('aot.ai.services.ai_anomaly_detector.AIAnomalyDetector._check_threshold_violations', return_value=violations), \
             mock.patch('aot.ai.services.ai_anomaly_detector.AIAnomalyDetector._determine_alert_level', return_value=level), \
             mock.patch('aot.ai.services.notification_service.NotificationService.send_anomaly_alert', return_value={'status': 'sent'}) as send:
            sched._realtime_alert_check_job()
            return send

    def test_sends_email_once_for_same_violations(self):
        v = [{'type': 'offline_devices', 'level': 'warning', 'message': 'x'}]
        self.assertEqual(1, self._run(v).call_count)
        sched._realtime_alert_last_sent.clear()  # 쿨다운 경과 가정
        self.assertEqual(0, self._run(v).call_count)  # 같은 내용은 재발송 안 함

    def test_new_violation_sends_again(self):
        v1 = [{'type': 'offline_devices', 'level': 'warning', 'message': 'x'}]
        v2 = v1 + [{'type': 'connectivity_drop', 'level': 'critical', 'message': 'y'}]
        self._run(v1)
        sched._realtime_alert_last_sent.clear()
        self.assertEqual(1, self._run(v2, 'critical').call_count)


if __name__ == '__main__':
    unittest.main()

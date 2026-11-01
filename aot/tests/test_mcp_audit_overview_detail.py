# coding=utf-8
"""overview·detail·cultivate 응답 정리(2026-10-28 MCP 점검 D).

- overview.failure 문구 / overview.brief 의 anomalies 중복 / control_state 의 detail 스키마
- detail.map_equipment 가 머리마다 같은 규격을 되풀이하던 것
- cultivate.stage_reschedule 응답이 단계마다 지침·목표값을 싣던 것, plot_resources 의 빈 결과
"""
import inspect
import unittest

from aot.tools.aot_data_tool_service import AoTDataToolService


class RegistryTest(unittest.TestCase):

    def test_control_state_detail_is_in_the_schema(self):
        # 응답이 "detail=true 로 다시 부르라" 고 하는데 스키마에 없던 인자 — 모델은 스키마에 없는
        # 인자를 넣지 않는다.
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        o = find_op(OPS, 'overview', 'control_state')
        self.assertIn('detail', o.shown)
        self.assertIn('detail', o.extra_args)


class SourceShapeTest(unittest.TestCase):
    """DB 없이 소스 모양으로 지키는 것 — 응답 문구 자체는 8084 에서 확인한다."""

    def test_failure_names_the_server_instead_of_saying_all(self):
        src = inspect.getsource(AoTDataToolService.analyze_system_failure_tool)
        self.assertNotIn('All MCP servers are offline', src)
        self.assertIn('The only active MCP server', src)

    def test_failure_does_not_call_a_server_offline_when_this_process_cannot_tell(self):
        # MCP 컨테이너는 서버 자식 프로세스를 직접 띄우지 않아 활성 목록이 비어 있다 — 그걸 '오프라인' 으로 읽던 오류(10-29).
        src = inspect.getsource(AoTDataToolService.analyze_system_failure_tool)
        self.assertIn('if active_ids else None', src)
        self.assertIn('unknown, not offline', src)

    def test_brief_embeds_an_anomaly_summary_not_the_whole_body(self):
        src = inspect.getsource(AoTDataToolService.get_system_brief)
        self.assertIn('_anomaly_summary', src)
        self.assertNotIn('brief["anomalies"] = _safe("이상 상태", lambda: S.get_anomalies())', src)

    def test_reschedule_trims_the_schedule_to_date_columns(self):
        src = inspect.getsource(AoTDataToolService.reschedule_plot_stage)
        self.assertIn("'starts_on', 'ends_on'", src)

    def test_empty_plot_resources_say_why(self):
        src = inspect.getsource(AoTDataToolService.apply_plot_resources)
        self.assertIn('Nothing was started', src)


if __name__ == '__main__':
    unittest.main()

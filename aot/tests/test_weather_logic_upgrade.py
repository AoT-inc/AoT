# coding=utf-8
"""
Tests for patch 001_WEATHER_LOGIC_UPGRADE

Covers:
  - device_capability_registry.py  — WeatherTag enum, tag_weather_device(), is_weather_device()
  - ai_doc_service.py              — classify_weather_device()
  - ai_routing_service.py          — format_weather_tool_result()
  - ai_planning_service.py         — _WEATHER_KW / _ANALYTICAL_KW → _weather_query_rule generation
  - ai_scheduler_service.py        — _weather_summary_job module-level existence, init_app() job registration

All external I/O (DB, APScheduler, Flask app) is mocked.
No real API calls or sensor reads are made.
"""
import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Path bootstrap — mirrors every other test in this package
# ---------------------------------------------------------------------------
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir))
)

# Prevent automatic Alembic migration during import
os.environ.setdefault("ALEMBIC_RUNNING", "1")


# ===========================================================================
# 1. device_capability_registry — WeatherTag, tag_weather_device, is_weather_device
# ===========================================================================

from aot.ai.services.device_capability_registry import (
    DeviceCapabilityRegistry,
    WeatherTag,
)


class TestWeatherTagEnum(unittest.TestCase):
    """WeatherTag enum value contract."""

    def test_weather_tag_has_weather_member(self):
        self.assertEqual(WeatherTag.WEATHER.value, "WEATHER")

    def test_weather_tag_has_environment_member(self):
        self.assertEqual(WeatherTag.ENVIRONMENT.value, "ENVIRONMENT")

    def test_weather_tag_is_str_enum(self):
        """WeatherTag inherits str so comparison to bare string works."""
        self.assertEqual(WeatherTag.WEATHER, "WEATHER")
        self.assertEqual(WeatherTag.ENVIRONMENT, "ENVIRONMENT")


class TestTagWeatherDevice(unittest.TestCase):
    """DeviceCapabilityRegistry.tag_weather_device() classification logic."""

    def setUp(self):
        # Each test starts with a clean cache to prevent cross-test pollution.
        DeviceCapabilityRegistry._weather_cache.clear()

    # --- Happy path: Korean weather keywords ---------------------------------

    def test_korean_weather_keyword_날씨_returns_WEATHER(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out01", device_name="날씨 센서")
        self.assertEqual(tag, WeatherTag.WEATHER)

    def test_korean_keyword_기온_returns_WEATHER(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out02", device_name="기온 측정기")
        self.assertEqual(tag, WeatherTag.WEATHER)

    def test_korean_keyword_강수_returns_WEATHER(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out03", device_name="강수량 센서")
        self.assertEqual(tag, WeatherTag.WEATHER)

    def test_korean_keyword_풍속_returns_WEATHER(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out04", device_name="풍속계")
        self.assertEqual(tag, WeatherTag.WEATHER)

    def test_korean_keyword_온도_returns_WEATHER(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out05", device_name="온도 센서")
        self.assertEqual(tag, WeatherTag.WEATHER)

    def test_korean_keyword_습도_returns_WEATHER(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out06", device_name="습도 센서")
        self.assertEqual(tag, WeatherTag.WEATHER)

    # --- Happy path: English weather keywords ---------------------------------

    def test_english_keyword_weather_returns_WEATHER(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out10", device_name="Weather Station")
        self.assertEqual(tag, WeatherTag.WEATHER)

    def test_english_keyword_temperature_returns_WEATHER(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out11", device_name="temperature sensor")
        self.assertEqual(tag, WeatherTag.WEATHER)

    def test_english_keyword_humidity_returns_WEATHER(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out12", device_name="humidity probe")
        self.assertEqual(tag, WeatherTag.WEATHER)

    def test_english_keyword_wind_returns_WEATHER(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out13", device_name="wind anemometer")
        self.assertEqual(tag, WeatherTag.WEATHER)

    def test_english_keyword_rain_returns_WEATHER(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out14", device_name="rain gauge")
        self.assertEqual(tag, WeatherTag.WEATHER)

    # --- ENVIRONMENT path: indoor/greenhouse notes override ------------------

    def test_indoor_note_keyword_returns_ENVIRONMENT(self):
        tag = DeviceCapabilityRegistry.tag_weather_device(
            "out20", device_name="온도 센서", notes="indoor greenhouse"
        )
        self.assertEqual(tag, WeatherTag.ENVIRONMENT)

    def test_korean_온실_note_returns_ENVIRONMENT(self):
        tag = DeviceCapabilityRegistry.tag_weather_device(
            "out21", device_name="습도 센서", notes="온실 내부 측정"
        )
        self.assertEqual(tag, WeatherTag.ENVIRONMENT)

    def test_재배_note_returns_ENVIRONMENT(self):
        tag = DeviceCapabilityRegistry.tag_weather_device(
            "out22", device_name="temperature", notes="재배 환경"
        )
        self.assertEqual(tag, WeatherTag.ENVIRONMENT)

    # --- Non-weather devices -------------------------------------------------

    def test_non_weather_device_returns_None(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out30", device_name="밸브 제어")
        self.assertIsNone(tag)

    def test_empty_name_and_notes_returns_None(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out31", device_name="", notes="")
        self.assertIsNone(tag)

    def test_unrelated_english_name_returns_None(self):
        tag = DeviceCapabilityRegistry.tag_weather_device("out32", device_name="water pump")
        self.assertIsNone(tag)

    # --- Cache behaviour -----------------------------------------------------

    def test_same_name_and_notes_uses_cache_not_reclassify(self):
        """Second call with identical name+notes must hit cache (no reclassification)."""
        DeviceCapabilityRegistry.tag_weather_device("out40", device_name="날씨 센서", notes="")
        # Introduce a sentinel to detect if the classification code runs again.
        # We monkeypatch _WEATHER_NAME_KEYWORDS to an empty set — a cache hit
        # bypasses the keyword scan entirely, so the result should still be WEATHER.
        original_keywords = DeviceCapabilityRegistry._WEATHER_NAME_KEYWORDS
        DeviceCapabilityRegistry._WEATHER_NAME_KEYWORDS = frozenset()
        try:
            tag = DeviceCapabilityRegistry.tag_weather_device("out40", device_name="날씨 센서", notes="")
            self.assertEqual(tag, WeatherTag.WEATHER)
        finally:
            DeviceCapabilityRegistry._WEATHER_NAME_KEYWORDS = original_keywords

    def test_changed_device_name_triggers_reclassification(self):
        """A different device_name must bypass cache and reclassify."""
        # Prime cache with weather name
        DeviceCapabilityRegistry.tag_weather_device("out41", device_name="날씨 센서", notes="")
        # Now call with a non-weather name for the same output_id
        tag = DeviceCapabilityRegistry.tag_weather_device("out41", device_name="water pump", notes="")
        self.assertIsNone(tag)

    def test_changed_notes_triggers_reclassification(self):
        """Changing only notes (which changes cache_key) must reclassify."""
        DeviceCapabilityRegistry.tag_weather_device("out42", device_name="온도 센서", notes="")
        # Add indoor note → should now be ENVIRONMENT
        tag = DeviceCapabilityRegistry.tag_weather_device("out42", device_name="온도 센서", notes="indoor")
        self.assertEqual(tag, WeatherTag.ENVIRONMENT)


class TestIsWeatherDevice(unittest.TestCase):
    """DeviceCapabilityRegistry.is_weather_device() thin wrapper contract."""

    def setUp(self):
        DeviceCapabilityRegistry._weather_cache.clear()

    def test_weather_device_returns_True(self):
        self.assertTrue(
            DeviceCapabilityRegistry.is_weather_device("o01", device_name="weather station")
        )

    def test_non_weather_device_returns_False(self):
        self.assertFalse(
            DeviceCapabilityRegistry.is_weather_device("o02", device_name="valve controller")
        )

    def test_environment_device_also_returns_True(self):
        """ENVIRONMENT is still a weather-family device → is_weather_device must be True."""
        self.assertTrue(
            DeviceCapabilityRegistry.is_weather_device(
                "o03", device_name="온도 센서", notes="indoor"
            )
        )


# ===========================================================================
# 2. ai_doc_service — classify_weather_device()
# ===========================================================================

from aot.ai.services.ai_doc_service import AiDocService


class TestAiDocServiceClassifyWeatherDevice(unittest.TestCase):
    """AiDocService.classify_weather_device() keyword matching — no file I/O needed."""

    # --- Korean keywords -------------------------------------------------------

    def test_korean_날씨_in_name_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("날씨 측정 장치"))

    def test_korean_기상_in_name_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("기상 관측소"))

    def test_korean_기온_in_name_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("기온 센서"))

    def test_korean_강수_in_name_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("강수량 게이지"))

    def test_korean_풍속_in_name_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("풍속 측정기"))

    def test_korean_온도_in_name_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("온도 센서"))

    def test_korean_습도_in_name_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("습도계"))

    # --- English keywords ------------------------------------------------------

    def test_english_weather_in_name_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("Weather Station"))

    def test_english_temperature_in_name_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("temperature probe"))

    def test_english_humidity_in_name_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("humidity sensor"))

    def test_english_wind_in_name_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("wind speed monitor"))

    def test_english_rain_in_name_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("rain gauge"))

    # --- Keyword in notes only -------------------------------------------------

    def test_keyword_in_notes_only_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("Sensor A", notes="weather observation"))

    def test_keyword_in_notes_korean_returns_True(self):
        self.assertTrue(AiDocService.classify_weather_device("입력 장치", notes="온도 측정용"))

    # --- Non-weather devices --------------------------------------------------

    def test_unrelated_device_returns_False(self):
        self.assertFalse(AiDocService.classify_weather_device("water pump"))

    def test_valve_device_returns_False(self):
        self.assertFalse(AiDocService.classify_weather_device("밸브 제어기"))

    def test_empty_name_returns_False(self):
        self.assertFalse(AiDocService.classify_weather_device(""))

    def test_empty_name_and_empty_notes_returns_False(self):
        self.assertFalse(AiDocService.classify_weather_device("", notes=""))

    # --- Case insensitivity ---------------------------------------------------

    def test_mixed_case_english_is_case_insensitive(self):
        self.assertTrue(AiDocService.classify_weather_device("WEATHER STATION"))

    def test_mixed_case_temperature_is_case_insensitive(self):
        self.assertTrue(AiDocService.classify_weather_device("Temperature"))


# ===========================================================================
# 3. ai_routing_service — format_weather_tool_result()
# ===========================================================================

from aot.ai.services.ai_routing_service import AIRoutingService


class TestFormatWeatherToolResult(unittest.TestCase):
    """AIRoutingService.format_weather_tool_result() output contract."""

    def _make_action(self, tool_name: str, action_type: str = "virtual_tool_call") -> dict:
        return {
            "action_type": action_type,
            "params": {"tool_name": tool_name},
        }

    # --- Weather tool keywords → tagged output --------------------------------

    def test_weather_tool_name_includes_WEATHER_DATA_tag(self):
        action = self._make_action("get_weather")
        result = AIRoutingService.format_weather_tool_result(action, {"temp": 22})
        self.assertIn("[WEATHER_DATA]", result)

    def test_weather_tool_name_includes_TRUTH_SOURCE_tag(self):
        action = self._make_action("get_weather")
        result = AIRoutingService.format_weather_tool_result(action, {"temp": 22})
        self.assertIn("[TRUTH_SOURCE]", result)

    def test_sensor_tool_name_includes_weather_tags(self):
        action = self._make_action("get_sensor")
        result = AIRoutingService.format_weather_tool_result(action, {"value": 55.2})
        self.assertIn("[WEATHER_DATA]", result)
        self.assertIn("[TRUTH_SOURCE]", result)

    def test_temperature_tool_name_includes_weather_tags(self):
        action = self._make_action("read_temperature")
        result = AIRoutingService.format_weather_tool_result(action, {"celsius": 18.5})
        self.assertIn("[WEATHER_DATA]", result)

    def test_humidity_tool_name_includes_weather_tags(self):
        action = self._make_action("humidity_reader")
        result = AIRoutingService.format_weather_tool_result(action, {"rh": 70})
        self.assertIn("[WEATHER_DATA]", result)

    def test_measurement_tool_name_includes_weather_tags(self):
        action = self._make_action("measurement_fetch")
        result = AIRoutingService.format_weather_tool_result(action, {})
        self.assertIn("[WEATHER_DATA]", result)

    # --- Result dict is JSON-encoded in output --------------------------------

    def test_weather_result_dict_is_json_encoded(self):
        payload = {"temp": 22, "unit": "C"}
        action = self._make_action("get_weather")
        result = AIRoutingService.format_weather_tool_result(action, payload)
        self.assertIn(json.dumps(payload, ensure_ascii=False), result)

    def test_non_weather_result_dict_is_json_encoded(self):
        payload = {"status": "ok", "output_id": "v01"}
        action = self._make_action("operate_device")
        result = AIRoutingService.format_weather_tool_result(action, payload)
        self.assertIn(json.dumps(payload, ensure_ascii=False), result)

    # --- Non-weather actions → plain format, no tags -------------------------

    def test_non_weather_tool_does_not_include_WEATHER_DATA_tag(self):
        action = self._make_action("operate_device")
        result = AIRoutingService.format_weather_tool_result(action, {"status": "ok"})
        self.assertNotIn("[WEATHER_DATA]", result)
        self.assertNotIn("[TRUTH_SOURCE]", result)

    def test_non_weather_tool_uses_plain_prefix(self):
        action = self._make_action("create_schedule")
        result = AIRoutingService.format_weather_tool_result(action, {"id": 1})
        self.assertTrue(result.startswith("Auto-RAG Action"))

    def test_action_type_appears_in_plain_output(self):
        action = self._make_action("operate_device", action_type="virtual_tool_call")
        result = AIRoutingService.format_weather_tool_result(action, {})
        self.assertIn("virtual_tool_call", result)

    # --- tool_name can live at top-level (alternate dict shape) ---------------

    def test_top_level_tool_name_key_is_also_recognised(self):
        """action dict with top-level tool_name (not nested in params) must work."""
        action = {
            "action_type": "virtual_tool_call",
            "tool_name": "get_weather",
        }
        result = AIRoutingService.format_weather_tool_result(action, {"temp": 10})
        self.assertIn("[WEATHER_DATA]", result)

    # --- Empty result dict produces valid output without error ---------------

    def test_empty_result_dict_for_weather_tool(self):
        action = self._make_action("weather_fetch")
        result = AIRoutingService.format_weather_tool_result(action, {})
        self.assertIn("[WEATHER_DATA]", result)
        self.assertIn("{}", result)

    def test_empty_result_dict_for_non_weather_tool(self):
        action = self._make_action("light_toggle")
        result = AIRoutingService.format_weather_tool_result(action, {})
        self.assertNotIn("[WEATHER_DATA]", result)


# ===========================================================================
# 4. ai_planning_service — _weather_query_rule generation
# ===========================================================================

class TestWeatherQueryRuleGeneration(unittest.TestCase):
    """
    Verify that _WEATHER_KW / _ANALYTICAL_KW keyword matching produces the
    correct _weather_query_rule injected into the planner prompt.

    AIPlanningService.run_planner() calls out to LLM engines and DB — we test
    the keyword/rule logic in isolation by calling run_planner() with heavy
    mocking so only the _weather_query_rule branch executes.
    """

    # Helper: call run_planner with all heavy dependencies mocked
    @staticmethod
    def _get_planner_prompt(command_text: str, intent: str = "DATA_QUERY") -> str:
        """
        Returns the prompt string passed to engine.run_reasoning().

        run_planner() uses local imports inside its body, so patches must target
        the *source* modules (aot.ai.services.ai_agent_service, etc.) rather than
        the planning service module namespace.
        """
        from aot.ai.services.ai_planning_service import AIPlanningService

        mock_agent = MagicMock()
        mock_agent.unique_id = "planner_01"
        mock_engine = MagicMock()

        captured = {}

        def capture_reasoning(ctx, prompt):
            captured["prompt"] = prompt
            return {"steps": [], "strategy": "sequential"}

        mock_engine.run_reasoning.side_effect = capture_reasoning

        with patch("aot.ai.services.ai_agent_service.AIAgentService.get_cached_agent",
                   return_value=mock_agent), \
             patch("aot.ai.services.ai_agent_service.AIAgentService.get_engine",
                   return_value=mock_engine), \
             patch("aot.ai.services.ai_action_service.AIActionService.get_action_manifest",
                   return_value={}), \
             patch("aot.ai.services.ai_doc_service.AiDocService.search",
                   return_value=[]):
            AIPlanningService.run_planner(
                intent=intent,
                command_text=command_text,
                context={},
                manifest={},
                chat_history=[],
            )

        return captured.get("prompt", "")

    # --- Current weather request → limit=1 rule ------------------------------

    def test_korean_날씨_query_generates_current_rule_with_limit1(self):
        prompt = self._get_planner_prompt("현재 날씨 알려줘")
        self.assertIn("limit=1", prompt)

    def test_english_weather_query_generates_current_rule_with_limit1(self):
        prompt = self._get_planner_prompt("what is the current weather")
        self.assertIn("limit=1", prompt)

    def test_korean_온도_query_generates_limit1(self):
        prompt = self._get_planner_prompt("지금 온도 몇도야")
        self.assertIn("limit=1", prompt)

    def test_korean_습도_query_generates_limit1(self):
        prompt = self._get_planner_prompt("현재 습도 알려줘")
        self.assertIn("limit=1", prompt)

    def test_english_temperature_query_generates_limit1(self):
        prompt = self._get_planner_prompt("show me the temperature")
        self.assertIn("limit=1", prompt)

    # --- Analytical weather request → duration=24h rule ----------------------

    def test_weather_with_평균_generates_duration_rule(self):
        prompt = self._get_planner_prompt("어제 날씨 평균 온도 알려줘")
        # The analytical rule text contains: arguments.duration='24h'
        self.assertIn("WEATHER ANALYTICAL RULE", prompt)
        self.assertIn("24h", prompt)
        # The CURRENT rule (which tells the planner to use limit=1 as instruction) must NOT appear
        self.assertNotIn("WEATHER CURRENT RULE", prompt)

    def test_weather_with_최대_generates_duration_rule(self):
        prompt = self._get_planner_prompt("이번 주 최대 풍속 얼마야")
        self.assertIn("WEATHER ANALYTICAL RULE", prompt)
        self.assertIn("24h", prompt)

    def test_weather_with_비교_generates_duration_rule(self):
        prompt = self._get_planner_prompt("오늘과 어제 습도 비교")
        self.assertIn("WEATHER ANALYTICAL RULE", prompt)
        self.assertIn("24h", prompt)

    def test_english_average_weather_generates_duration_rule(self):
        prompt = self._get_planner_prompt("average temperature over the past 24 hours")
        self.assertIn("WEATHER ANALYTICAL RULE", prompt)
        self.assertIn("24h", prompt)

    def test_english_history_weather_generates_duration_rule(self):
        prompt = self._get_planner_prompt("show weather history")
        self.assertIn("WEATHER ANALYTICAL RULE", prompt)
        self.assertIn("24h", prompt)

    # --- Non-weather queries → _weather_query_rule is empty ------------------

    def test_valve_control_command_has_no_weather_rule(self):
        prompt = self._get_planner_prompt("밸브 1번 켜줘", intent="CONTROL")
        self.assertNotIn("WEATHER", prompt.upper().replace("_WEATHER_", ""))
        # More specific: neither limit=1 nor duration=24h injected as weather rule
        self.assertNotIn("WEATHER CURRENT RULE", prompt)
        self.assertNotIn("WEATHER ANALYTICAL RULE", prompt)

    def test_schedule_command_has_no_weather_rule(self):
        prompt = self._get_planner_prompt("내일 오전 8시에 펌프 켜줘", intent="SCHEDULE")
        self.assertNotIn("WEATHER CURRENT RULE", prompt)
        self.assertNotIn("WEATHER ANALYTICAL RULE", prompt)

    def test_chat_query_has_no_weather_rule(self):
        prompt = self._get_planner_prompt("안녕 잘 지내", intent="CHAT")
        self.assertNotIn("WEATHER CURRENT RULE", prompt)
        self.assertNotIn("WEATHER ANALYTICAL RULE", prompt)


# ===========================================================================
# 5. ai_scheduler_service — module-level _weather_summary_job + init_app() job registration
# ===========================================================================

import aot.ai.services.ai_scheduler_service as _sched_mod
from aot.ai.services.ai_scheduler_service import AISchedulerService


class TestWeatherSummaryJobModuleLevel(unittest.TestCase):
    """
    APScheduler serialises jobs by module-level qualified name.
    _weather_summary_job MUST exist at module level (not inside a class or closure).
    """

    def test_weather_summary_job_is_module_level_callable(self):
        self.assertTrue(
            callable(getattr(_sched_mod, "_weather_summary_job", None)),
            "_weather_summary_job must be a callable at module level in ai_scheduler_service"
        )

    def test_weather_summary_job_has_correct_qualified_name(self):
        """Function __qualname__ must not contain '<locals>' (would break APScheduler pickle)."""
        func = getattr(_sched_mod, "_weather_summary_job")
        self.assertNotIn(
            "<locals>", func.__qualname__,
            "_weather_summary_job appears to be a closure; APScheduler cannot serialize it"
        )


class TestInitAppRegistersWeatherSummaryJob(unittest.TestCase):
    """
    AISchedulerService.init_app() must register a job with
      id='ai_scheduler_weather_summary' and trigger interval hours=6.
    """

    def _run_init_app_with_mock_scheduler(self):
        """
        Returns the list of add_job() calls captured on the mock scheduler.

        trigger_fired / conditional_fired are imported *inside* init_app() via
        'from aot.utils.signals import …', so they are patched at their source
        module rather than at the scheduler module namespace.
        _on_trigger_fired / _on_conditional_fired may be defined later in the
        file; use create=True so the patch works regardless of import order.
        """
        mock_scheduler = MagicMock()
        mock_scheduler.running = False  # triggers scheduler.start()
        mock_app = MagicMock()

        with patch("aot.ai.services.ai_scheduler_service.get_scheduler",
                   return_value=mock_scheduler), \
             patch("aot.utils.signals.trigger_fired", MagicMock()), \
             patch("aot.utils.signals.conditional_fired", MagicMock()), \
             patch("aot.ai.services.ai_scheduler_service._on_trigger_fired",
                   MagicMock(), create=True), \
             patch("aot.ai.services.ai_scheduler_service._on_conditional_fired",
                   MagicMock(), create=True):
            AISchedulerService.init_app(mock_app)

        return mock_scheduler.add_job.call_args_list

    def test_weather_summary_job_is_registered(self):
        calls = self._run_init_app_with_mock_scheduler()
        job_ids = [
            c.kwargs.get("id") or (c.args[1] if len(c.args) > 1 else None)
            for c in calls
        ]
        # Flatten: add_job may use keyword or positional 'id'
        kwarg_ids = [c.kwargs.get("id") for c in calls]
        self.assertIn(
            "ai_scheduler_weather_summary",
            kwarg_ids,
            f"Expected 'ai_scheduler_weather_summary' in add_job id kwargs; got: {kwarg_ids}"
        )

    def test_weather_summary_job_registered_with_interval_trigger(self):
        calls = self._run_init_app_with_mock_scheduler()
        weather_calls = [
            c for c in calls if c.kwargs.get("id") == "ai_scheduler_weather_summary"
        ]
        self.assertTrue(weather_calls, "No add_job call found for ai_scheduler_weather_summary")
        wc = weather_calls[0]
        self.assertEqual(wc.kwargs.get("trigger"), "interval",
                         "Weather summary job must use 'interval' trigger")

    def test_weather_summary_job_registered_with_6_hour_interval(self):
        calls = self._run_init_app_with_mock_scheduler()
        weather_calls = [
            c for c in calls if c.kwargs.get("id") == "ai_scheduler_weather_summary"
        ]
        self.assertTrue(weather_calls)
        wc = weather_calls[0]
        self.assertEqual(wc.kwargs.get("hours"), 6,
                         "Weather summary job must fire every 6 hours")

    def test_weather_summary_job_registered_with_correct_func(self):
        """The func argument must be the module-level _weather_summary_job."""
        calls = self._run_init_app_with_mock_scheduler()
        weather_calls = [
            c for c in calls if c.kwargs.get("id") == "ai_scheduler_weather_summary"
        ]
        self.assertTrue(weather_calls)
        wc = weather_calls[0]
        registered_func = wc.kwargs.get("func")
        self.assertIs(
            registered_func,
            _sched_mod._weather_summary_job,
            "func kwarg must be the module-level _weather_summary_job function"
        )

    def test_weather_summary_job_has_replace_existing_true(self):
        calls = self._run_init_app_with_mock_scheduler()
        weather_calls = [
            c for c in calls if c.kwargs.get("id") == "ai_scheduler_weather_summary"
        ]
        self.assertTrue(weather_calls)
        wc = weather_calls[0]
        self.assertTrue(wc.kwargs.get("replace_existing"),
                        "replace_existing must be True to allow hot-reload without duplicate jobs")


if __name__ == "__main__":
    unittest.main()

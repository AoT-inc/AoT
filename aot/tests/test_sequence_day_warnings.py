# coding=utf-8
"""요일별 시퀀스 경고(잘림·재시작·하루 여러 번 반복)가 번역되어 웹 UI에
그대로 나오는지.

## 왜 이 테스트가 있나

2026-09-25 이전에는 `SequenceTriggerController.plan_for_day()` 가 계산하는
세 가지 경고(한 회차가 창보다 길어 잘림, 주기보다 길어 재시작, 하루 여러 번
반복)가 MCP/AI 도구(get_function_detail, configure_sequence_day)에만
영어로 노출되고, 웹 UI(함수 설정 모달·시퀀스 위젯)는 "period > window"
하나만(그것도 번역 없이) 보여줬다.

고친 방식은 plan_for_day 의 슬롯 계산은 그대로 두고, 그 결과에서 이미 뽑아낸
사실(경과 초·창 길이·주기·반복 횟수)을 `warning_codes` 라는 구조화된 데이터로
같이 내보내는 것이다 — `warnings`(AI 도구용 영어 문장)는 그 데이터를 그대로
포맷한 것이라 절대 서로 어긋나지 않는다. 이 파일은 그 포맷팅과, 웹 쪽
번역·요일별 취합(`sequence_schedule_day_warnings`)이 올바른지만 본다 —
슬롯 계산 자체(어느 스텝이 몇 초를 차지하는가)는 기존 스위트가 이미 덮는다.
"""
import pytest

from aot.config import ProdConfig
from aot.controllers.controller_trigger_sequence import _format_plan_warning_en


# ---- _format_plan_warning_en: AI 도구가 보는 영어 문장은 그대로여야 한다 ----

def test_format_empty():
    assert _format_plan_warning_en({"code": "empty"}) == (
        "No step runs on this day — the window opens but nothing happens.")


def test_format_window_cutoff():
    msg = _format_plan_warning_en({"code": "window_cutoff", "span": 700.0, "window_sec": 300})
    assert msg == ("One pass takes 700s but the window is only 300s — "
                    "it will be cut off before finishing.")


def test_format_period_restart():
    msg = _format_plan_warning_en({"code": "period_restart", "span": 700.0, "period": 300.0})
    assert msg == ("One pass takes 700s but the cycle restarts every 300s — "
                    "it will restart before finishing.")


def test_format_repeats_per_day():
    msg = _format_plan_warning_en(
        {"code": "repeats_per_day", "period": 300.0, "window_sec": 36000, "repeats": 120})
    assert msg == ("The cycle repeats every 300s inside a 36000s window, "
                    "so it runs about 120 times that day rather than once.")


def test_format_unknown_code_returns_empty_string():
    """모르는 code 로 문구가 깨지지 않아야 한다 — 조용히 빈 문자열."""
    assert _format_plan_warning_en({"code": "does-not-exist"}) == ""


# ---- translate_sequence_plan_warning: 웹 UI 는 같은 사실을 번역해 보여준다 ----

@pytest.fixture
def app():
    from aot.aot_flask.app import create_app

    application = create_app(config=ProdConfig)
    application.config['TESTING'] = True
    return application


class TestTranslateSequencePlanWarning:

    def test_translates_to_korean(self, app):
        from flask_babel import force_locale
        from aot.utils.sequence_warnings import translate_sequence_plan_warning

        with app.test_request_context():
            with force_locale('ko'):
                msg = translate_sequence_plan_warning(
                    {"code": "window_cutoff", "span": 700.0, "window_sec": 300})
                assert msg == "한 회차는 700초가 걸리는데 시간창은 300초뿐입니다 — 끝나기 전에 잘립니다."

    def test_translates_to_japanese(self, app):
        from flask_babel import force_locale
        from aot.utils.sequence_warnings import translate_sequence_plan_warning

        with app.test_request_context():
            with force_locale('ja'):
                msg = translate_sequence_plan_warning(
                    {"code": "repeats_per_day", "period": 300.0, "window_sec": 36000, "repeats": 120})
                assert msg == (
                    "周期(300秒)が時間枠(36000秒)の中で繰り返されるため、"
                    "この曜日は1回ではなく約120回実行されます。")

    def test_unknown_code_returns_none(self, app):
        from aot.utils.sequence_warnings import translate_sequence_plan_warning

        with app.test_request_context():
            assert translate_sequence_plan_warning({"code": "does-not-exist"}) is None


# ---- sequence_schedule_day_warnings: 요일별 취합 ----

class _FakeTrigger:
    unique_id = 'seq-fake-0000'


class TestSequenceScheduleDayWarnings:

    def _patch_plan_for_day(self, monkeypatch, plans_by_day):
        import aot.controllers.controller_trigger_sequence as seq_mod

        def _fake(unique_id, day_idx):
            return plans_by_day[day_idx]

        monkeypatch.setattr(seq_mod.SequenceTriggerController, 'plan_for_day',
                             staticmethod(_fake))

    def test_skips_days_that_do_not_run(self, app, monkeypatch):
        from aot.utils.sequence_warnings import sequence_schedule_day_warnings

        plans = {i: {"runs": False} for i in range(7)}
        self._patch_plan_for_day(monkeypatch, plans)

        with app.test_request_context():
            per_day, flat = sequence_schedule_day_warnings(_FakeTrigger())

        assert per_day == {}
        assert flat == []

    def test_skips_days_with_no_warnings(self, app, monkeypatch):
        from aot.utils.sequence_warnings import sequence_schedule_day_warnings

        plans = {i: {"runs": True, "warning_codes": []} for i in range(7)}
        self._patch_plan_for_day(monkeypatch, plans)

        with app.test_request_context():
            per_day, flat = sequence_schedule_day_warnings(_FakeTrigger())

        assert per_day == {}
        assert flat == []

    def test_aggregates_translated_messages_per_day(self, app, monkeypatch):
        from flask_babel import force_locale
        from aot.utils.sequence_warnings import sequence_schedule_day_warnings

        plans = {i: {"runs": True, "warning_codes": []} for i in range(7)}
        # Monday (0): 잘림. Friday (4): 재시작 + 하루 여러 번 반복(두 개).
        plans[0]["warning_codes"] = [
            {"code": "window_cutoff", "span": 700.0, "window_sec": 300}]
        plans[4]["warning_codes"] = [
            {"code": "period_restart", "span": 700.0, "period": 300.0},
            {"code": "repeats_per_day", "period": 300.0, "window_sec": 36000, "repeats": 120},
        ]
        self._patch_plan_for_day(monkeypatch, plans)

        with app.test_request_context():
            with force_locale('ko'):
                per_day, flat = sequence_schedule_day_warnings(_FakeTrigger())

        assert set(per_day.keys()) == {0, 4}
        assert len(per_day[0]) == 1
        assert len(per_day[4]) == 2
        # 요일 이름도 번역돼 있어야 한다 (Mon -> 월, Fri -> 금).
        assert any(m.startswith("월:") for m in flat)
        assert any(m.startswith("금:") for m in flat)
        assert len(flat) == 3

    def test_a_plan_for_day_failure_is_skipped_not_raised(self, app, monkeypatch):
        """한 요일 계산이 예외를 던져도 나머지 요일 배지는 살아야 한다."""
        from aot.utils.sequence_warnings import sequence_schedule_day_warnings
        import aot.controllers.controller_trigger_sequence as seq_mod

        def _fake(unique_id, day_idx):
            if day_idx == 2:
                raise RuntimeError("boom")
            return {"runs": True, "warning_codes": [{"code": "empty"}]} if day_idx == 0 else {"runs": False}

        monkeypatch.setattr(seq_mod.SequenceTriggerController, 'plan_for_day',
                             staticmethod(_fake))

        with app.test_request_context():
            per_day, flat = sequence_schedule_day_warnings(_FakeTrigger())

        assert 0 in per_day
        assert 2 not in per_day

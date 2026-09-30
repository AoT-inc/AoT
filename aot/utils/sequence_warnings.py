# coding=utf-8
"""시퀀스 요일별 경고의 번역·취합 (웹 화면용).

plan_for_day() 의 구조화된 warning_codes 를 현재 로케일로 번역한다. 웹 계층이
컨트롤러를 직접 import 하지 못하는 규칙(ARCHITECTURE.md §4) 때문에 aot.utils 에 둔다.
호출은 반드시 Flask 요청 컨텍스트 안에서 해야 한다(flask_babel).
"""
import logging

from flask_babel import gettext

from aot.utils.weekly_schedule import DAY_NAMES

logger = logging.getLogger(__name__)


def translate_sequence_plan_warning(warning_code):
    """Localize one SequenceTriggerController.plan_for_day() warning code.

    Mirrors `_format_plan_warning_en` in controller_trigger_sequence.py so the
    function settings modal and the sequence widget show the exact same
    findings the AI tools (get_function_detail, configure_sequence_day)
    already surface in English — only the language differs.
    """
    code = warning_code.get("code")
    if code == "empty":
        return gettext("No step runs on this day — the window opens but nothing happens.")
    if code == "window_cutoff":
        return gettext(
            "One pass takes %(span)ds but the window is only %(window)ds — "
            "it will be cut off before finishing.",
            span=int(round(warning_code["span"])), window=int(warning_code["window_sec"]))
    if code == "period_restart":
        return gettext(
            "One pass takes %(span)ds but the cycle restarts every %(period)ds — "
            "it will restart before finishing.",
            span=int(round(warning_code["span"])), period=int(round(warning_code["period"])))
    if code == "repeats_per_day":
        return gettext(
            "The cycle repeats every %(period)ds inside a %(window)ds window, "
            "so it runs about %(repeats)s times that day rather than once.",
            period=int(round(warning_code["period"])), window=int(warning_code["window_sec"]),
            repeats=warning_code["repeats"])
    return None


def sequence_schedule_day_warnings(trigger):
    """Per-weekday warnings for a Sequence trigger's *current, saved* schedule.

    Reuses SequenceTriggerController.plan_for_day's structured
    `warning_codes` — the same slot maths the AI tools already surface in
    English (get_function_detail, configure_sequence_day) — so the function
    settings modal and the sequence widget never show a different picture
    than the AI does. Before 2026-09-25 the web UI only ever checked
    "period > window" (weekly_schedule.build_warnings); this also catches a
    pass that restarts mid-run and a cycle that repeats several times a day.

    Reads from the DB (one Actions query per weekday) — call this only on a
    deliberate save or an initial page render, never from a polled endpoint
    (this trigger's schedule is already polled every few seconds by the
    widget for live status — see function_status_activated's own comment
    about not adding queries to that path).

    :returns: (per_day, flat) — per_day maps day index (int) to a list of
        translated messages for days that have at least one warning; flat is
        the same content flattened to "Mon: message" strings for a toast.
    """
    from aot.controllers.controller_trigger_sequence import SequenceTriggerController

    per_day = {}
    flat = []
    for day_idx in range(7):
        try:
            plan = SequenceTriggerController.plan_for_day(trigger.unique_id, day_idx)
        except Exception as exc:
            logger.warning(f"[sequence_schedule_day_warnings] plan_for_day({day_idx}) failed: {exc}")
            continue
        if not plan.get('runs'):
            continue
        messages = [m for m in (translate_sequence_plan_warning(w)
                                 for w in plan.get('warning_codes') or []) if m]
        if not messages:
            continue
        per_day[day_idx] = messages
        day_name = gettext(DAY_NAMES[day_idx])
        flat.extend(f"{day_name}: {m}" for m in messages)
    return per_day, flat

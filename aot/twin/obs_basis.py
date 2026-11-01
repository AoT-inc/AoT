# coding=utf-8
"""관측이 아닌 입력 판정 — 동기화(노지 EnKF·시설 UKF)가 관측값으로 쓰는 계열에서 예보·모델값·시뮬레이터를 뺀다.

**입력 모듈이 이미 밝힌 성질만** 본다(새 설정 칸도, 장치 이름·제공자 이름 비교도 없다 — 2026-10-26 사용자 결정):

| 이유 | 모듈이 밝힌 것 |
|---|---|
| `forecast`  | `INPUT_INFORMATION['data_time'] == 'forecast'`(값이 미래 시각) 또는 채널 메타 `forecast_lead_d` |
| `model`     | `INPUT_INFORMATION['data_origin'] == 'model'`(값이 모델·재분석 격자 값, 예: 격자 날씨) |
| `simulated` | 시뮬레이션 드라이버(`aot.tools.sim_marker.is_simulated` 의 `driver_test` — 모듈 표식. 이름 접두는 보지 않는다) |

미러 센서(현장 실측의 사본)와 실측 센서는 어느 것에도 걸리지 않아 그대로 쓴다. 순수 함수 — DB 를 읽지 않고,
호출하는 쪽이 `parse_input_information()` 결과(`info`)를 넘긴다.
"""
from __future__ import annotations

from typing import Mapping, Optional

FORECAST = "forecast"
MODEL = "model"
SIMULATED = "simulated"
REASONS = (FORECAST, MODEL, SIMULATED)

#: 사람이 읽는 이유(한국어 — 계보·로그용. 화면 문구는 번역 키를 따로 쓴다).
REASON_KO = {FORECAST: "예보", MODEL: "모델값", SIMULATED: "시뮬레이터"}
#: 트윈 결과·화면이 같은 말로 읽는 한 줄.
EXCLUDED_LINE = "관측이 아님 — 동기화에서 제외"


def _channel_meta(mod: Mapping, channel) -> Optional[Mapping]:
    md = mod.get("measurements_dict") or {}
    if not isinstance(md, Mapping):
        return None
    meta = md.get(channel)
    if meta is None and channel is not None:
        meta = md.get(str(channel))
        if meta is None and str(channel).lstrip("-").isdigit():
            meta = md.get(int(channel))
    return meta if isinstance(meta, Mapping) else None


def non_observation_reason(module: str, info: Optional[Mapping], channel=None) -> Optional[str]:
    """이 입력 모듈(의 채널)이 관측이 아니면 이유(`forecast`·`model`·`simulated`), 관측이면 None.

    `info` = 입력 모듈 정보(`parse_input_information()`), `module` = 입력 장치의 드라이버 이름(`Input.device`).
    모듈 정보를 못 읽었거나(None) 모르는 모듈이면 관측으로 본다 — 기존 입력을 이유 없이 거부하지 않는다.
    """
    if not module:
        return None
    from aot.tools.sim_marker import is_simulated
    if is_simulated("input", module, "")[0]:
        return SIMULATED
    mod = (info or {}).get(module)
    if not isinstance(mod, Mapping):
        return None
    meta = _channel_meta(mod, channel)
    if mod.get("data_time") == "forecast" or (meta is not None and meta.get("forecast_lead_d") is not None):
        return FORECAST
    if mod.get("data_origin") == "model":
        return MODEL
    return None


def excluded_line(key_label: str, reason: str, name: str = "") -> str:
    """결과 한 줄 — 예: `관측이 아님 — 동기화에서 제외: 비(모델값, SIM 김제 기상대)`."""
    why = REASON_KO.get(reason, reason)
    return f"{EXCLUDED_LINE}: {key_label}({why}{', ' + name if name else ''})"

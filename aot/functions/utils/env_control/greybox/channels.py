# coding=utf-8
"""
greybox/channels.py — actuator kind ↔ greybox 명령 채널 매핑 (단일 출처).

greybox 모델(model.py)은 5개 집약 채널만 입력으로 받는다:
    heat, cool, vent, fog, co2_inj
실제 시설의 다양한 actuator kind 를 이 채널로 사상한다. 매핑이 없는 kind
(shade/curtain/lighting/circulation_fan/dehumidifier 등)는 greybox 가 물리적으로
모델링하지 않으므로 None 으로 분류되어, 제어 경로에서 레거시 effect 로 폴백된다.

shadow 집계와 effect 어댑터·MPC 가 모두 이 모듈을 공유해 일관성을 보장한다.
"""

from __future__ import annotations

from typing import Dict, Optional

# greybox 모델 명령 채널
CHANNELS = ('heat', 'cool', 'vent', 'fog', 'co2_inj')

# actuator kind → greybox 채널. 누락 kind 는 None (미모델).
KIND_TO_CHANNEL: Dict[str, str] = {
    # 난방
    'heater':         'heat',
    # 냉방
    'cooler':         'cool',
    'ac':             'cool',
    # 환기(외기 교환) — 개구부·환기팬
    'opening':        'vent',
    'vent':           'vent',
    'side_vent':      'vent',
    'roof_vent':      'vent',
    'window':         'vent',
    'exhaust_fan':    'vent',
    'intake_fan':     'vent',
    # 가습/포그
    'fogger':         'fog',
    'humidifier':     'fog',
    # CO2 주입
    'co2_injector':   'co2_inj',
}

# greybox 가 모델링하지 않는 kind (명시적 — 가독성/문서화용)
UNMODELED_KINDS = frozenset({
    'shade', 'curtain', 'lighting', 'supplemental_light',
    'circulation_fan', 'dehumidifier', 'co2_scrubber',
})


def channel_for_kind(kind: Optional[str]) -> Optional[str]:
    """actuator kind 에 대응하는 greybox 채널. 미모델이면 None."""
    if not kind:
        return None
    return KIND_TO_CHANNEL.get(str(kind).lower())


def _channel_from_id(aid: str) -> Optional[str]:
    """kind 정보가 없을 때의 폴백 — actuator_id 키워드 추정(하위 호환)."""
    s = (aid or '').lower()
    if 'heat' in s:
        return 'heat'
    if 'cool' in s or 'ac' in s:
        return 'cool'
    if 'vent' in s or 'opening' in s or 'window' in s or 'fan' in s:
        return 'vent'
    if 'fog' in s or 'humid' in s:
        return 'fog'
    if 'co2' in s:
        return 'co2_inj'
    return None


def aggregate_cmds_by_kind(
    cmds_pct: Dict[str, float],
    kind_by_aid: Optional[Dict[str, str]] = None,
) -> Dict[str, float]:
    """actuator_id→pct 를 greybox 채널별 최대값으로 집계.

    kind_by_aid 가 주어지면 kind 매핑을 우선 사용하고, 없거나 미모델 kind 면
    actuator_id 키워드로 폴백 추정한다. 'fan' 키워드 폴백은 외기교환 환기팬을
    겨냥하나, circulation_fan 처럼 kind 가 명시되면(미모델) 채널에 잡히지 않는다.
    """
    result = {ch: 0.0 for ch in CHANNELS}
    kind_by_aid = kind_by_aid or {}
    for aid, pct in cmds_pct.items():
        kind = kind_by_aid.get(aid)
        ch = channel_for_kind(kind)
        # kind 가 없을 때만(미상) id 키워드로 폴백. 명시적 미모델 kind 는 폴백 안 함.
        if ch is None and kind is None:
            ch = _channel_from_id(aid)
        if ch is not None:
            result[ch] = max(result[ch], float(pct or 0.0))
    return result

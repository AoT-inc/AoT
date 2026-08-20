# coding=utf-8
"""
GrowthStageResolver — Derives current growth_stage from planting_date.

Resolves:
    OI-DS-01 (013_DATA_SOURCES.yaml): planting_date per facility → growth_stage
    GAP-03: growth_stage undefined in context modules

Algorithm:
    1. Calculate days_after_planting = today - planting_date
    2. Map days to stage using STAGE_DURATION_MAP[crop_type]
    3. Return matched English stage_id (from ext_translation_table.GROWTH_STAGE_MAP)

Phase 2a: static STAGE_DURATION_MAP (crop-level day ranges).
Phase 2b: replace with RDA API-provided stage duration data when available.
"""
import logging
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# @ANCHOR: STAGE_DURATION_MAP
# Crop-type → ordered list of (stage_id, max_days_after_plot).
# Stages are matched by first entry where days_after_planting <= max_days.
# Source: RDA greenhouse management guidelines (static Phase 2a fallback).
#
# ⚠ 'seedling' 은 옮겨심는(transplant) 작물에는 없다 (2026-08-21 결정).
#
# 이 표의 day-0 은 GeoPlot.started_on 이다 — 그 구획에 그 대상이 **있기 시작한
# 날**(program-layer.md 참조). 옮겨심는 작물은 육묘를 대개 다른 장소(육묘장·
# 별도 트레이)에서 하고, 그 육묘가 "이 구획"의 기하에 있었던 적이 없다. 그런데
# day-0 을 파종일로 두고 'seedling' 을 첫 단계로 얹으면, 정식한 그 구획이 정식
# 당일부터 며칠 동안 "아직 육묘기" 로 읽힌다 — 실제로 이 구획에 없었던 기간을
# 이 구획의 경과일로 세는 것.
#
# 그래서 옮겨심는 6종은 'transplant' 를 day-0 단계로 삼고, 원래 자료(파종일
# 기준 누적일)에서 육묘 기간만큼을 빼서 다시 앵커링했다 — 값을 새로 지어낸
# 것이 아니라 같은 경계를 기준점만 바꿔 다시 읽은 것이다. 직파(直播) 작물인
# 시금치는 파종 자리가 곧 이 구획이므로 'seedling' 을 그대로 둔다. 자기 시설
# 안에서 트레이 육묘를 하는 농가도 있지만, 트레이가 있는 자리와 정식할 두둑은
# 별개의 기하라 여전히 다른 GeoPlot 이다.
# ---------------------------------------------------------------------------

STAGE_DURATION_MAP: dict[str, list[tuple[str, int]]] = {
    # Fruiting vegetables
    "tomato": [
        ("transplant",     7),   # 정식 원자료 28 − 육묘 21
        ("vegetative",    35),   # 56 − 21
        ("flowering",     63),   # 84 − 21
        ("fruit_set",     84),   # 105 − 21
        ("fruiting",     119),   # 140 − 21
        ("harvest",      999),
    ],
    "cherry_tomato": [
        ("transplant",     7),   # 28 − 21
        ("vegetative",    35),   # 56 − 21
        ("flowering",     63),   # 84 − 21
        ("fruit_set",     84),   # 105 − 21
        ("fruiting",     109),   # 130 − 21
        ("harvest",      999),
    ],
    "paprika": [
        ("transplant",     7),   # 35 − 28
        ("vegetative",    42),   # 70 − 28
        ("flowering",     72),   # 100 − 28
        ("fruit_set",     92),   # 120 − 28
        ("fruiting",     132),   # 160 − 28
        ("harvest",      999),
    ],
    "cucumber": [
        ("transplant",     7),   # 21 − 14
        ("vegetative",    28),   # 42 − 14
        ("flowering",     42),   # 56 − 14
        ("fruiting",      66),   # 80 − 14
        ("harvest",      999),
    ],
    "strawberry": [
        ("transplant",    14),   # 35 − 21
        ("vegetative",    49),   # 70 − 21
        ("flower_initiation", 69),   # 90 − 21
        ("flowering",     89),   # 110 − 21
        ("fruiting",     119),   # 140 − 21
        ("harvest",      999),
    ],
    "lettuce": [
        ("transplant",     7),   # 17 − 10
        ("vegetative",    25),   # 35 − 10
        ("harvest",      999),
    ],
    # 직파 — 파종한 그 자리가 곧 이 구획이라 'seedling' 이 실제로 이 구획의
    # 첫 단계다(위 anchor 설명 참조).
    "spinach": [
        ("seedling",      7),
        ("vegetative",   30),
        ("harvest",     999),
    ],
    # Default fallback used when crop_type not in map — 옮겨심는지 직파인지
    # 모르는 작물이라 'seedling' 을 그대로 둔다(더 안전한 쪽으로 fallback).
    "_default": [
        ("seedling",     21),
        ("vegetative",    60),
        ("flowering",     90),
        ("fruiting",     120),
        ("harvest",      999),
    ],
}


# ---------------------------------------------------------------------------
# @ANCHOR: GROWTH_STAGE_RESOLVER
# ---------------------------------------------------------------------------

class GrowthStageResolver:
    """
    Derives current growth stage and optimal environment ranges from
    planting_date and crop_type, using EXT-KR-01 cached setpoints.

    Call Hierarchy
    --------------
    Parent  : DomainContextLoader._resolve_operational_state()
    Children: cls._calc_days(), cls._map_to_stage(), ExtSmartfarmClient.get_setpoint()
    """

    @classmethod
    def resolve(
        cls,
        crop_type: str,
        planting_date,  # str "YYYY-MM-DD" | date | None
    ) -> dict:
        """
        Resolve growth_stage and return a dict suitable for merging into
        operational_state.

        Returns:
            {
                'growth_stage': str | None,
                'days_after_planting': int | None,
                'optimal_ranges': dict | None,   # from EXT-KR-01 cache
                'growth_stage_source': str,      # 'ext_kr_01' | 'static' | 'unavailable'
            }

        Call Hierarchy
        --------------
        Parent  : DomainContextLoader._resolve_operational_state()
        Children: cls._calc_days(), cls._map_to_stage(),
                  ExtSmartfarmClient.get_setpoint()
        """
        result = {
            'growth_stage':         None,
            'days_after_planting':  None,
            'optimal_ranges':       None,
            'growth_stage_source':  'unavailable',
        }

        if not planting_date or not crop_type:
            return result

        days = cls._calc_days(planting_date)
        if days is None:
            return result

        result['days_after_planting'] = days
        stage = cls._map_to_stage(crop_type, days)
        result['growth_stage'] = stage
        result['growth_stage_source'] = 'static'

        # Enrich with EXT-KR-01 setpoints
        try:
            from aot.ai.context.ext.smartfarm_client import ExtSmartfarmClient
            setpoint = ExtSmartfarmClient.get_setpoint(crop_type, stage)
            if setpoint:
                result['optimal_ranges'] = {
                    'temperature': [setpoint['opt_temp_min'], setpoint['opt_temp_max']],
                    'humidity':    [setpoint['opt_humidity_min'], setpoint['opt_humidity_max']],
                    'co2':         [setpoint['opt_co2_min'], setpoint['opt_co2_max']],
                    'light':       [setpoint['opt_light_min'], setpoint['opt_light_max']],
                }
                result['growth_stage_source'] = 'ext_kr_01'
        except Exception as exc:
            logger.warning("GrowthStageResolver: EXT-KR-01 enrichment failed: %s", exc)

        return result

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @classmethod
    def _calc_days(cls, planting_date) -> Optional[int]:
        """
        Calculate days elapsed since planting_date.

        Call Hierarchy
        --------------
        Parent  : cls.resolve()
        Children: (none — pure computation)
        """
        try:
            if isinstance(planting_date, str):
                pd = date.fromisoformat(planting_date)
            elif isinstance(planting_date, datetime):
                pd = planting_date.date()
            elif isinstance(planting_date, date):
                pd = planting_date
            else:
                return None
            return (date.today() - pd).days
        except Exception as exc:
            logger.warning("GrowthStageResolver: invalid planting_date %r: %s", planting_date, exc)
            return None

    @classmethod
    def _map_to_stage(cls, crop_type: str, days: int) -> str:
        """
        Map days_after_planting to stage_id using STAGE_DURATION_MAP.
        Falls back to '_default' if crop_type not registered.

        Call Hierarchy
        --------------
        Parent  : cls.resolve()
        Children: (none — pure lookup)
        """
        stage_list = STAGE_DURATION_MAP.get(crop_type, STAGE_DURATION_MAP['_default'])
        for stage_id, max_days in stage_list:
            if days <= max_days:
                return stage_id
        return 'harvest'

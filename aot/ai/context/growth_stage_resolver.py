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
# Crop-type → ordered list of (stage_id, max_days_after_planting).
# Stages are matched by first entry where days_after_planting <= max_days.
# Source: RDA greenhouse management guidelines (static Phase 2a fallback).
# ---------------------------------------------------------------------------

STAGE_DURATION_MAP: dict[str, list[tuple[str, int]]] = {
    # Fruiting vegetables
    "tomato": [
        ("seedling",     21),
        ("transplanting",28),
        ("vegetative",   56),
        ("flowering",    84),
        ("fruit_set",   105),
        ("fruiting",    140),
        ("harvest",     999),
    ],
    "cherry_tomato": [
        ("seedling",     21),
        ("transplanting",28),
        ("vegetative",   56),
        ("flowering",    84),
        ("fruit_set",   105),
        ("fruiting",    130),
        ("harvest",     999),
    ],
    "paprika": [
        ("seedling",     28),
        ("transplanting",35),
        ("vegetative",   70),
        ("flowering",   100),
        ("fruit_set",   120),
        ("fruiting",    160),
        ("harvest",     999),
    ],
    "cucumber": [
        ("seedling",     14),
        ("transplanting",21),
        ("vegetative",   42),
        ("flowering",    56),
        ("fruiting",     80),
        ("harvest",     999),
    ],
    "strawberry": [
        ("seedling",     21),
        ("transplanting",35),
        ("vegetative",   70),
        ("flower_initiation", 90),
        ("flowering",   110),
        ("fruiting",    140),
        ("harvest",     999),
    ],
    "lettuce": [
        ("seedling",     10),
        ("transplanting",17),
        ("vegetative",   35),
        ("harvest",     999),
    ],
    "spinach": [
        ("seedling",      7),
        ("vegetative",   30),
        ("harvest",     999),
    ],
    # Default fallback used when crop_type not in map
    "_default": [
        ("seedling",     21),
        ("vegetative",   60),
        ("flowering",    90),
        ("fruiting",    120),
        ("harvest",     999),
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

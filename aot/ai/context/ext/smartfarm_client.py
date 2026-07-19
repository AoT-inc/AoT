# coding=utf-8
"""
ExtSmartfarmClient — EXT-KR-01 data client.

Source      : RDA SmartFarm Productivity Model
              (스마트팜 생산성 향상 모델)
API base    : https://api.data.go.kr/openapi/tn_pubr_public_smartfarm_prdtvty_api
Auth        : RDA_API_KEY (via GeoSetting.keys — see get_geo_setting_key())
Cache       : SQLite table ext_smartfarm_setpoints, TTL=7d
NRM-01      : Temperature in Celsius, Humidity in %, CO2 in ppm, no conversion.
              optTmpMin → opt_temp_min, optTmpMax → opt_temp_max
              optHmtMin → opt_humidity_min, optHmtMax → opt_humidity_max
              optCo2Min → opt_co2_min, optCo2Max → opt_co2_max
              optIlmnMin → opt_light_min, optIlmnMax → opt_light_max
NRM-04      : Korean crop/stage names translated at ingestion via ext_translation_table.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from aot.ai.services.domain_context_loader import get_geo_setting_key
from aot.ai.context.ext_translation_table import translate_kr

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_BASE = "https://api.data.go.kr/openapi/tn_pubr_public_smartfarm_prdtvty_api"
_TTL_DAYS = 7
_REQUEST_TIMEOUT = 10  # seconds


# ---------------------------------------------------------------------------
# @ANCHOR: EXT_SMARTFARM_CLIENT
# ---------------------------------------------------------------------------

class ExtSmartfarmClient:
    """
    Fetches and caches EXT-KR-01 setpoints in ext_smartfarm_setpoints.

    Usage:
        rows = ExtSmartfarmClient.get_setpoints(crop_type="tomato")
        row  = ExtSmartfarmClient.get_setpoint(crop_type="tomato", growth_stage="flowering")
    """

    @classmethod
    def get_setpoints(cls, crop_type: str) -> list[dict]:
        """
        Return all cached setpoints for a crop_type.
        Triggers a refresh if cache is stale (> 7 days) or empty.

        Call Hierarchy
        --------------
        Parent  : GrowthStageResolver.get_optimal_ranges()
        Children: cls._is_cache_fresh(), cls._refresh_cache(), cls._read_cache()
        """
        if not cls._is_cache_fresh(crop_type):
            cls._refresh_cache(crop_type)
        return cls._read_cache(crop_type)

    @classmethod
    def get_setpoint(cls, crop_type: str, growth_stage: str) -> Optional[dict]:
        """
        Return setpoints for a specific crop_type + growth_stage combination.
        Returns None if not available.

        Call Hierarchy
        --------------
        Parent  : GrowthStageResolver.get_optimal_ranges()
        Children: cls.get_setpoints()
        """
        rows = cls.get_setpoints(crop_type)
        for row in rows:
            if row.get('growth_stage') == growth_stage:
                return row
        return None

    # @ANCHOR: EXT_SMARTFARM_SYNC
    @classmethod
    def sync(cls, facility_id: str, config: dict) -> list[dict]:
        """
        Bridge ext_smartfarm_setpoints cache into AIContextRecord-ready entries.

        Called by utils_ai_context_source dispatch layer (task 020).
        Reads crop_type from config; defaults to 'tomato' if not set.
        Returns list[dict] consumed by _write_context_records().

        Parameter name scheme: "smartfarm.{crop_type}.{growth_stage}.{metric}"
        Example: "smartfarm.tomato.flowering.opt_temp_min"

        Call Hierarchy
        --------------
        Parent  : utils_ai_context_source._dispatch_ext()
        Children: cls.get_setpoints()
        """
        # Metric field → unit suffix mapping (NRM-01 units)
        _METRIC_UNITS: list[tuple[str, str]] = [
            ('opt_temp_min',     ' °C'),
            ('opt_temp_max',     ' °C'),
            ('opt_humidity_min', ' %'),
            ('opt_humidity_max', ' %'),
            ('opt_co2_min',      ' ppm'),
            ('opt_co2_max',      ' ppm'),
            ('opt_light_min',    ' µmol/m²/s'),
            ('opt_light_max',    ' µmol/m²/s'),
        ]

        try:
            crop_type = config.get('crop_type') or 'tomato'
            rows = cls.get_setpoints(crop_type=crop_type)

            records: list[dict] = []
            for row in rows:
                crop  = row.get('crop_type', crop_type)
                stage = row.get('growth_stage', '')
                for metric, unit in _METRIC_UNITS:
                    raw = row.get(metric)
                    if raw is None:
                        continue
                    records.append({
                        'parameter_name': f"smartfarm.{crop}.{stage}.{metric}",
                        'value':          f"{raw}{unit}",
                    })

            logger.info(
                "EXT-KR-01 sync(): crop_type=%r, rows=%d, records=%d",
                crop_type, len(rows), len(records),
            )
            return records

        except Exception as exc:
            logger.error("EXT-KR-01 sync() failed: %s", exc)
            return []

    # -----------------------------------------------------------------------
    # Cache management
    # -----------------------------------------------------------------------

    @classmethod
    def _is_cache_fresh(cls, crop_type: str) -> bool:
        """Check whether the cache for crop_type is within TTL."""
        try:
            from aot.databases.models.ext_smartfarm_setpoints import ExtSmartfarmSetpoints
            from aot.databases.utils import session_scope
            from aot.config import AOT_DB_PATH

            cutoff = datetime.now(timezone.utc) - timedelta(days=_TTL_DAYS)
            with session_scope(AOT_DB_PATH) as session:
                row = (
                    session.query(ExtSmartfarmSetpoints)
                    .filter(
                        ExtSmartfarmSetpoints.crop_type == crop_type,
                        ExtSmartfarmSetpoints.fetched_at >= cutoff,
                    )
                    .first()
                )
                return row is not None
        except Exception as exc:
            logger.warning("EXT-KR-01 cache freshness check failed: %s", exc)
            return False

    @classmethod
    def _refresh_cache(cls, crop_type: str) -> None:
        """
        Fetch data from RDA API and upsert into ext_smartfarm_setpoints.
        On any API error, log a warning and leave existing cache intact.

        Call Hierarchy
        --------------
        Parent  : cls._is_cache_fresh() (indirectly via get_setpoints)
        Children: cls._fetch_from_api(), cls._upsert_rows()
        """
        api_key = get_geo_setting_key('RDA_API_KEY')
        if not api_key:
            logger.warning("EXT-KR-01: RDA_API_KEY not configured — using cached data.")
            return

        rows = cls._fetch_from_api(crop_type, api_key)
        if rows:
            cls._upsert_rows(rows)
        else:
            logger.warning("EXT-KR-01: API returned no rows for crop_type=%r", crop_type)

    @classmethod
    def _fetch_from_api(cls, crop_type: str, api_key: str) -> list[dict]:
        """
        Call the RDA SmartFarm Productivity Model API.

        Response schema (공공데이터포털 standard):
            response.body.items[].{
                cropsNm, growthStageCd, optTmpMin, optTmpMax,
                optHmtMin, optHmtMax, optCo2Min, optCo2Max,
                optIlmnMin, optIlmnMax
            }

        Korean crop/stage values are translated via ext_translation_table
        before storage (NRM-04).

        Call Hierarchy
        --------------
        Parent  : cls._refresh_cache()
        Children: (none — HTTP I/O only)
        """
        # Map internal crop_type back to Korean for API query
        # Reverse lookup in CROP_NAME_MAP
        from aot.ai.context.ext_translation_table import CROP_NAME_MAP
        kr_crop = next((k for k, v in CROP_NAME_MAP.items() if v == crop_type), crop_type)

        params = {
            'serviceKey': api_key,
            'pageNo':     '1',
            'numOfRows':  '100',
            'type':       'json',
            'cropsNm':    kr_crop,
        }

        try:
            resp = requests.get(_API_BASE, params=params, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("EXT-KR-01 API request failed: %s", exc)
            return []

        try:
            items = data['response']['body']['items']
            if isinstance(items, dict):
                items = items.get('item', [])
            if not isinstance(items, list):
                items = [items]
        except (KeyError, TypeError) as exc:
            logger.error("EXT-KR-01 unexpected response structure: %s", exc)
            return []

        now = datetime.now(timezone.utc)
        normalized: list[dict] = []
        for item in items:
            crop_en  = translate_kr(item.get('cropsNm', ''), 'crop')
            stage_en = translate_kr(item.get('growthStageCd', ''), 'growth_stage')
            normalized.append({
                'crop_type':        crop_en,
                'growth_stage':     stage_en,
                'opt_temp_min':     _safe_float(item.get('optTmpMin')),
                'opt_temp_max':     _safe_float(item.get('optTmpMax')),
                'opt_humidity_min': _safe_float(item.get('optHmtMin')),
                'opt_humidity_max': _safe_float(item.get('optHmtMax')),
                'opt_co2_min':      _safe_float(item.get('optCo2Min')),
                'opt_co2_max':      _safe_float(item.get('optCo2Max')),
                'opt_light_min':    _safe_float(item.get('optIlmnMin')),
                'opt_light_max':    _safe_float(item.get('optIlmnMax')),
                'fetched_at':       now,
            })
        return normalized

    @classmethod
    def _upsert_rows(cls, rows: list[dict]) -> None:
        """
        Insert or update rows in ext_smartfarm_setpoints.
        Existing rows with same (crop_type, growth_stage) are overwritten.

        Call Hierarchy
        --------------
        Parent  : cls._refresh_cache()
        Children: (none — DB I/O only)
        """
        try:
            from aot.databases.models.ext_smartfarm_setpoints import ExtSmartfarmSetpoints
            from aot.databases.utils import session_scope
            from aot.config import AOT_DB_PATH

            with session_scope(AOT_DB_PATH) as session:
                for row_data in rows:
                    existing = (
                        session.query(ExtSmartfarmSetpoints)
                        .filter_by(
                            crop_type=row_data['crop_type'],
                            growth_stage=row_data['growth_stage'],
                        )
                        .first()
                    )
                    if existing:
                        for key, val in row_data.items():
                            setattr(existing, key, val)
                    else:
                        session.add(ExtSmartfarmSetpoints(**row_data))
        except Exception as exc:
            logger.error("EXT-KR-01 cache upsert failed: %s", exc)

    @classmethod
    def _read_cache(cls, crop_type: str) -> list[dict]:
        """
        Read all cached rows for crop_type from ext_smartfarm_setpoints.

        Call Hierarchy
        --------------
        Parent  : cls.get_setpoints()
        Children: (none — DB read only)
        """
        try:
            from aot.databases.models.ext_smartfarm_setpoints import ExtSmartfarmSetpoints
            from aot.databases.utils import session_scope
            from aot.config import AOT_DB_PATH

            with session_scope(AOT_DB_PATH) as session:
                rows = (
                    session.query(ExtSmartfarmSetpoints)
                    .filter(ExtSmartfarmSetpoints.crop_type == crop_type)
                    .all()
                )
                return [
                    {
                        'crop_type':        r.crop_type,
                        'growth_stage':     r.growth_stage,
                        'opt_temp_min':     r.opt_temp_min,
                        'opt_temp_max':     r.opt_temp_max,
                        'opt_humidity_min': r.opt_humidity_min,
                        'opt_humidity_max': r.opt_humidity_max,
                        'opt_co2_min':      r.opt_co2_min,
                        'opt_co2_max':      r.opt_co2_max,
                        'opt_light_min':    r.opt_light_min,
                        'opt_light_max':    r.opt_light_max,
                        'fetched_at':       r.fetched_at.isoformat() if r.fetched_at else None,
                    }
                    for r in rows
                ]
        except Exception as exc:
            logger.warning("EXT-KR-01 cache read failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value) -> Optional[float]:
    """Convert API string/int/None to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

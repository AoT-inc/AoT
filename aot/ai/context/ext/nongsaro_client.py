# coding=utf-8
"""
NongsaroClient — EXT-KR-02 data client.

Source      : Nongsaro Open API (농사로 오픈API)
              Crop cultivation guides and weekly farming calendars
API base    : https://api.nongsaro.go.kr/service
Auth        : NONGSARO_API_KEY (via config dict key 'api_key' or env var NONGSARO_API_KEY)
Cache       : SQLite table ext_nongsaro_guides, TTL=24h
NRM-04      : Korean crop names translated at ingestion via ext_translation_table.
              cropNm → translate_kr(text, 'crop') at fetch time.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from aot.ai.context.ext_translation_table import translate_kr

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_BASE = "https://api.nongsaro.go.kr/service"
_TTL_HOURS = 24
_REQUEST_TIMEOUT = 10  # seconds
_DEFAULT_CROP_SEQ = 101  # tomato (토마토)
_MAX_CONTENT_LEN = 500  # max chars per record value (task spec)

_MONTH_LABELS: dict[int, str] = {
    1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr',
    5: 'may', 6: 'jun', 7: 'jul', 8: 'aug',
    9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec',
}


def _month_range_label(from_m: int, to_m: int) -> str:
    """Return a season label like 'jan_feb' or 'mar' from month integers."""
    f = _MONTH_LABELS.get(from_m, str(from_m))
    t = _MONTH_LABELS.get(to_m, str(to_m))
    return f if f == t else f"{f}_{t}"


# ---------------------------------------------------------------------------
# @ANCHOR: EXT_NONGSARO_CLIENT
# ---------------------------------------------------------------------------

class NongsaroClient:
    """
    Fetches and caches EXT-KR-02 guides in ext_nongsaro_guides.

    Usage:
        records = NongsaroClient.sync(facility_id="fac01", config={"api_key": "...", "crop_seq": 101})
        guides  = NongsaroClient.get_guides(crop_type="tomato")
        guide   = NongsaroClient.get_guide(crop_type="tomato", guide_type="cultivation")
    """

    # @ANCHOR: EXT_NONGSARO_SYNC
    @classmethod
    def sync(cls, facility_id: str, config: dict) -> list[dict]:
        """
        Bridge ext_nongsaro_guides cache into AIContextRecord-ready entries.

        Called by utils_ai_context_source dispatch layer (task 020).
        Reads api_key from config['api_key'] or env var NONGSARO_API_KEY.
        Reads crop_seq from config['crop_seq']; defaults to 101 (tomato) if absent.
        Returns list[dict] consumed by _write_context_records().

        Parameter name scheme: "nongsaro.{crop_name_en}.{data_type}"
        Examples:
          "nongsaro.tomato.cultivation_guide"
          "nongsaro.tomato.farm_calendar.jan_feb"

        Call Hierarchy
        --------------
        Parent  : utils_ai_context_source._dispatch_ext()
        Children: cls._is_cache_fresh(), cls._refresh_cache(), cls._read_cache()
        """
        api_key = config.get('api_key', '') or os.environ.get('NONGSARO_API_KEY', '')
        if not api_key:
            return [{'parameter_name': 'nongsaro.status',
                     'value': 'API key not configured. Set NONGSARO_API_KEY.'}]

        crop_seq = int(config.get('crop_seq') or _DEFAULT_CROP_SEQ)

        try:
            if not cls._is_cache_fresh():
                cls._refresh_cache(crop_seq, api_key)

            rows = cls._read_cache()
            records: list[dict] = []
            for row in rows:
                crop = row.get('crop_type', 'unknown')
                guide_type = row.get('guide_type', '')
                content = (row.get('content') or '').strip()
                if not content:
                    continue

                if guide_type == 'cultivation':
                    param_name = f"nongsaro.{crop}.cultivation_guide"
                else:
                    # guide_type stored as 'calendar_{season}', e.g. 'calendar_jan_feb'
                    season = guide_type.replace('calendar_', '', 1)
                    param_name = f"nongsaro.{crop}.farm_calendar.{season}"

                records.append({
                    'parameter_name': param_name,
                    'value':          content[:_MAX_CONTENT_LEN],
                })

            logger.info(
                "EXT-KR-02 sync(): crop_seq=%r, cached_rows=%d, records=%d",
                crop_seq, len(rows), len(records),
            )
            return records

        except Exception as exc:
            logger.error("EXT-KR-02 sync() failed: %s", exc)
            return []

    @classmethod
    def get_guides(cls, crop_type: str) -> list[dict]:
        """
        Return all cached guides for a crop_type.
        Triggers a refresh if cache is stale (> 24h) or empty.

        Call Hierarchy
        --------------
        Parent  : (utility — direct callers)
        Children: cls._is_cache_fresh(), cls._refresh_cache(), cls._read_cache_by_crop()
        """
        if not cls._is_cache_fresh():
            api_key = os.environ.get('NONGSARO_API_KEY', '')
            if api_key:
                cls._refresh_cache(_DEFAULT_CROP_SEQ, api_key)
        return cls._read_cache_by_crop(crop_type)

    @classmethod
    def get_guide(cls, crop_type: str, guide_type: str) -> Optional[dict]:
        """
        Return a specific guide for crop_type + guide_type.
        Returns None if not available.

        Call Hierarchy
        --------------
        Parent  : (utility — direct callers)
        Children: cls.get_guides()
        """
        for row in cls.get_guides(crop_type):
            if row.get('guide_type') == guide_type:
                return row
        return None

    # -----------------------------------------------------------------------
    # Cache management
    # -----------------------------------------------------------------------

    @classmethod
    def _is_cache_fresh(cls) -> bool:
        """Return True if any ext_nongsaro_guides row was fetched within TTL."""
        try:
            from aot.databases.models.ext_nongsaro_guides import ExtNongsaroGuides
            from aot.databases.utils import session_scope
            from aot.config import AOT_DB_PATH

            cutoff = datetime.now(timezone.utc) - timedelta(hours=_TTL_HOURS)
            with session_scope(AOT_DB_PATH) as session:
                row = (
                    session.query(ExtNongsaroGuides)
                    .filter(ExtNongsaroGuides.fetched_at >= cutoff)
                    .first()
                )
                return row is not None
        except Exception as exc:
            logger.warning("EXT-KR-02 cache freshness check failed: %s", exc)
            return False

    @classmethod
    def _refresh_cache(cls, crop_seq: int, api_key: str) -> None:
        """
        Fetch cultivation guide and farming calendar from Nongsaro API
        and upsert into ext_nongsaro_guides.
        On any API error, log a warning and leave existing cache intact.

        Call Hierarchy
        --------------
        Parent  : cls.sync(), cls.get_guides()
        Children: cls._fetch_crop_detail(), cls._fetch_farm_calendar(), cls._upsert_rows()
        """
        rows: list[dict] = []

        guide_rows = cls._fetch_crop_detail(crop_seq, api_key)
        rows.extend(guide_rows)

        calendar_rows = cls._fetch_farm_calendar(crop_seq, api_key)
        rows.extend(calendar_rows)

        if rows:
            cls._upsert_rows(rows)
        else:
            logger.warning("EXT-KR-02: API returned no data for crop_seq=%r", crop_seq)

    @classmethod
    def _fetch_crop_detail(cls, crop_seq: int, api_key: str) -> list[dict]:
        """
        Fetch cultivation guide from /cropSvc/cropDetail.

        Response schema (Nongsaro):
            response.body.items.item.{
                cropNm, mainCultivationInfo, growthCharacteristic,
                cropCharacteristic, sowingInfo, harvestInfo, ...
            }

        Call Hierarchy
        --------------
        Parent  : cls._refresh_cache()
        Children: (none — HTTP I/O only)
        """
        params = {
            'cropSeq': str(crop_seq),
            'apiKey':  api_key,
            'format':  'json',
        }
        try:
            resp = requests.get(
                f"{_API_BASE}/cropSvc/cropDetail",
                params=params,
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("EXT-KR-02 cropDetail request failed: %s", exc)
            return []

        try:
            item = data['response']['body']['items']['item']
            if isinstance(item, list):
                item = item[0] if item else {}
        except (KeyError, TypeError, IndexError) as exc:
            logger.error("EXT-KR-02 cropDetail unexpected response structure: %s", exc)
            return []

        crop_kr = item.get('cropNm', '')
        crop_en = translate_kr(crop_kr, 'crop') if crop_kr else 'unknown'

        # Try common text-bearing fields in priority order
        summary = ''
        for field in ('mainCultivationInfo', 'growthCharacteristic',
                      'cropCharacteristic', 'sowingInfo', 'harvestInfo'):
            summary = (item.get(field) or '').strip()
            if summary:
                break

        if not summary:
            logger.warning(
                "EXT-KR-02 cropDetail: no text content found for crop_seq=%r", crop_seq)
            return []

        now = datetime.now(timezone.utc)
        return [{
            'crop_type':  crop_en,
            'guide_type': 'cultivation',
            'title':      crop_kr or crop_en,
            'content':    summary,
            'season':     None,
            'fetched_at': now,
        }]

    @classmethod
    def _fetch_farm_calendar(cls, crop_seq: int, api_key: str) -> list[dict]:
        """
        Fetch farming calendar from /farmCalendar/farmWorkList.

        Response schema (Nongsaro):
            response.body.items.item[].{
                cropNm, farmWorkNm, farmWorkDetail,
                workMonthFrom, workMonthTo
            }

        Each work item is stored as one row keyed by (crop_type, calendar_{season}).

        Call Hierarchy
        --------------
        Parent  : cls._refresh_cache()
        Children: (none — HTTP I/O only)
        """
        params = {
            'cropSeq': str(crop_seq),
            'apiKey':  api_key,
            'format':  'json',
        }
        try:
            resp = requests.get(
                f"{_API_BASE}/farmCalendar/farmWorkList",
                params=params,
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("EXT-KR-02 farmWorkList request failed: %s", exc)
            return []

        try:
            items = data['response']['body']['items']
            if isinstance(items, dict):
                items = items.get('item', [])
            if not isinstance(items, list):
                items = [items] if items else []
        except (KeyError, TypeError) as exc:
            logger.error("EXT-KR-02 farmWorkList unexpected response structure: %s", exc)
            return []

        now = datetime.now(timezone.utc)
        rows: list[dict] = []
        for item in items:
            crop_kr = item.get('cropNm', '')
            crop_en = translate_kr(crop_kr, 'crop') if crop_kr else 'unknown'

            from_m = _safe_int(item.get('workMonthFrom'))
            to_m   = _safe_int(item.get('workMonthTo'))
            if from_m is None:
                continue
            if to_m is None:
                to_m = from_m

            season_label = _month_range_label(from_m, to_m)
            guide_type   = f"calendar_{season_label}"

            work_name   = (item.get('farmWorkNm', '') or '').strip()
            work_detail = (item.get('farmWorkDetail', '') or '').strip()
            content = f"{work_name}: {work_detail}".strip(': ') if work_name else work_detail

            rows.append({
                'crop_type':  crop_en,
                'guide_type': guide_type,
                'title':      work_name,
                'content':    content,
                'season':     season_label,
                'fetched_at': now,
            })

        return rows

    @classmethod
    def _upsert_rows(cls, rows: list[dict]) -> None:
        """
        Insert or update rows in ext_nongsaro_guides.
        Existing rows with same (crop_type, guide_type) are overwritten.

        Call Hierarchy
        --------------
        Parent  : cls._refresh_cache()
        Children: (none — DB I/O only)
        """
        try:
            from aot.databases.models.ext_nongsaro_guides import ExtNongsaroGuides
            from aot.databases.utils import session_scope
            from aot.config import AOT_DB_PATH

            with session_scope(AOT_DB_PATH) as session:
                for row_data in rows:
                    existing = (
                        session.query(ExtNongsaroGuides)
                        .filter_by(
                            crop_type=row_data['crop_type'],
                            guide_type=row_data['guide_type'],
                        )
                        .first()
                    )
                    if existing:
                        for key, val in row_data.items():
                            setattr(existing, key, val)
                    else:
                        session.add(ExtNongsaroGuides(**row_data))
        except Exception as exc:
            logger.error("EXT-KR-02 cache upsert failed: %s", exc)

    @classmethod
    def _read_cache(cls) -> list[dict]:
        """
        Read all cached rows from ext_nongsaro_guides within TTL window.
        Used by sync() to build parameter records across all crops.

        Call Hierarchy
        --------------
        Parent  : cls.sync()
        Children: (none — DB read only)
        """
        try:
            from aot.databases.models.ext_nongsaro_guides import ExtNongsaroGuides
            from aot.databases.utils import session_scope
            from aot.config import AOT_DB_PATH

            cutoff = datetime.now(timezone.utc) - timedelta(hours=_TTL_HOURS)
            with session_scope(AOT_DB_PATH) as session:
                rows = (
                    session.query(ExtNongsaroGuides)
                    .filter(ExtNongsaroGuides.fetched_at >= cutoff)
                    .all()
                )
                return [
                    {
                        'crop_type':  r.crop_type,
                        'guide_type': r.guide_type,
                        'title':      r.title,
                        'content':    r.content,
                        'season':     r.season,
                        'fetched_at': r.fetched_at.isoformat() if r.fetched_at else None,
                    }
                    for r in rows
                ]
        except Exception as exc:
            logger.warning("EXT-KR-02 cache read failed: %s", exc)
            return []

    @classmethod
    def _read_cache_by_crop(cls, crop_type: str) -> list[dict]:
        """
        Read cached rows for a specific crop_type from ext_nongsaro_guides.
        Used by get_guides() utility method.

        Call Hierarchy
        --------------
        Parent  : cls.get_guides()
        Children: (none — DB read only)
        """
        try:
            from aot.databases.models.ext_nongsaro_guides import ExtNongsaroGuides
            from aot.databases.utils import session_scope
            from aot.config import AOT_DB_PATH

            with session_scope(AOT_DB_PATH) as session:
                rows = (
                    session.query(ExtNongsaroGuides)
                    .filter(ExtNongsaroGuides.crop_type == crop_type)
                    .all()
                )
                return [
                    {
                        'crop_type':  r.crop_type,
                        'guide_type': r.guide_type,
                        'title':      r.title,
                        'content':    r.content,
                        'season':     r.season,
                        'fetched_at': r.fetched_at.isoformat() if r.fetched_at else None,
                    }
                    for r in rows
                ]
        except Exception as exc:
            logger.warning("EXT-KR-02 cache read by crop failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_int(value) -> Optional[int]:
    """Convert API string/None to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

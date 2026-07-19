# coding=utf-8
"""
PestManagementClient — EXT-KR-03 data client.

Source      : National Pest Management System (국가병해충관리시스템 — NCPMS)
API base    : https://ncpms.rda.go.kr/npmsAPI/service
Auth        : NCPMS_API_KEY (via config dict or environment variable)
Cache       : SQLite table ext_pest_alerts, TTL=6h
NRM-04      : Korean pest/crop names translated at ingestion via ext_translation_table.
              pestNm → PEST_NAME_MAP, cropNm → CROP_NAME_MAP, forecastCd → SEVERITY_MAP
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import requests

from aot.ai.context.ext_translation_table import PEST_NAME_MAP, CROP_NAME_MAP, SEVERITY_MAP

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_BASE     = "https://ncpms.rda.go.kr/npmsAPI/service"
_ENDPOINT     = "DS04005"
_TTL_HOURS    = 6
_REQUEST_TIMEOUT = 10  # seconds
_DESC_MAX_LEN = 300


# ---------------------------------------------------------------------------
# @ANCHOR: PEST_MANAGEMENT_CLIENT
# ---------------------------------------------------------------------------

class PestManagementClient:
    """
    Fetches and caches EXT-KR-03 pest forecast alerts in ext_pest_alerts.

    Interface contract (matches utils_ai_context_source dispatch layer):
        sync(self, facility_id: str, config: dict) -> list[dict]
        Return format: list of {'parameter_name': str, 'value': str}
        parameter_name scheme: "pest_alert.{crop_en}.{pest_en}"
        Example: "pest_alert.tomato.aphid"

    Call Hierarchy
    --------------
    Parent  : utils_ai_context_source._dispatch_ext_client()
    Children: cls._is_cache_fresh(), cls._refresh_cache(), cls._read_cache()
    """

    # @ANCHOR: PEST_MANAGEMENT_SYNC
    def sync(self, facility_id: str, config: dict) -> list[dict]:
        """
        Sync NCPMS pest forecast data and return AIContextRecord-ready entries.

        Steps:
            1. Resolve api_key from config or NCPMS_API_KEY env var.
            2. Resolve year_month from config or current month.
            3. Check cache freshness; refresh if stale.
            4. Return list[dict] with parameter_name/value pairs.

        Call Hierarchy
        --------------
        Parent  : utils_ai_context_source._dispatch_ext_client()
        Children: self._is_cache_fresh(), self._refresh_cache(), self._read_cache()
        """
        try:
            api_key    = config.get('api_key', '') or os.environ.get('NCPMS_API_KEY', '')
            year_month = config.get('year_month', None) or datetime.now().strftime('%Y%m')

            if not api_key:
                logger.warning("EXT-KR-03: NCPMS_API_KEY not configured.")
                return [
                    {
                        'parameter_name': 'pest_alert.status',
                        'value':          'API key not configured. Set NCPMS_API_KEY.',
                    }
                ]

            if not self._is_cache_fresh():
                self._refresh_cache(api_key, year_month)

            records = self._read_cache()
            logger.info(
                "EXT-KR-03 sync(): facility_id=%r, ym=%s, records=%d",
                facility_id, year_month, len(records),
            )
            return records

        except Exception as exc:
            logger.exception("EXT-KR-03 sync() failed: %s", exc)
            return []

    # -----------------------------------------------------------------------
    # Cache management
    # -----------------------------------------------------------------------

    def _is_cache_fresh(self) -> bool:
        """Return True if any ext_pest_alerts row is within TTL."""
        try:
            from aot.databases.models.ext_pest_alerts import ExtPestAlerts
            from aot.databases.utils import session_scope
            from aot.config import AOT_DB_PATH

            cutoff = datetime.now(timezone.utc) - timedelta(hours=_TTL_HOURS)
            with session_scope(AOT_DB_PATH) as session:
                row = (
                    session.query(ExtPestAlerts)
                    .filter(ExtPestAlerts.fetched_at >= cutoff)
                    .first()
                )
                return row is not None
        except Exception as exc:
            logger.warning("EXT-KR-03 cache freshness check failed: %s", exc)
            return False

    def _refresh_cache(self, api_key: str, year_month: str) -> None:
        """
        Fetch pest forecast from NCPMS API and upsert into ext_pest_alerts.
        On any API error, logs a warning and leaves existing cache intact.

        Call Hierarchy
        --------------
        Parent  : self.sync()
        Children: self._fetch_from_api(), self._upsert_rows()
        """
        rows = self._fetch_from_api(api_key, year_month)
        if rows:
            self._upsert_rows(rows)
        else:
            logger.warning("EXT-KR-03: API returned no rows for ym=%s", year_month)

    def _fetch_from_api(self, api_key: str, year_month: str) -> list[dict]:
        """
        Call NCPMS DS04005 (pest forecast list) endpoint.

        Response schema (NCPMS standard):
            body.list[].{
                pestNm, cropNm, forecastCd, forecastContents
            }

        Korean pest/crop values are translated via ext_translation_table
        before storage (NRM-04).

        Call Hierarchy
        --------------
        Parent  : self._refresh_cache()
        Children: (none — HTTP I/O only)
        """
        url = f"{_API_BASE}/{_ENDPOINT}"
        params = {
            'rptYm':  year_month,
            'apiKey': api_key,
            'format': 'json',
        }

        try:
            resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("EXT-KR-03 API request failed: %s", exc)
            return []

        try:
            items = data.get('body', {}).get('list', [])
            if not isinstance(items, list):
                items = [items] if items else []
        except (KeyError, TypeError, AttributeError) as exc:
            logger.error("EXT-KR-03 unexpected response structure: %s", exc)
            return []

        now = datetime.now(timezone.utc)
        normalized: list[dict] = []

        for item in items:
            pest_kr = item.get('pestNm', '')
            crop_kr = item.get('cropNm', '')
            severity_kr = item.get('forecastCd', '')
            description = (item.get('forecastContents') or '')[:_DESC_MAX_LEN]

            pest_en = PEST_NAME_MAP.get(pest_kr, pest_kr.lower().replace(' ', '_'))
            crop_en = CROP_NAME_MAP.get(crop_kr, crop_kr.lower().replace(' ', '_'))
            severity_en = SEVERITY_MAP.get(severity_kr, severity_kr.lower())

            if not pest_en or not crop_en:
                continue

            normalized.append({
                'crop_type':     crop_en,
                'pest_code':     pest_en,
                'pest_name':     pest_en,
                'severity':      severity_en,
                'region':        None,
                'control_method': description,
                'fetched_at':    now,
                # Keep parameter_name and value for _read_cache output
                '_parameter_name': f"pest_alert.{crop_en}.{pest_en}",
                '_value':          f"{severity_en} — {description}" if description else severity_en,
            })

        return normalized

    def _upsert_rows(self, rows: list[dict]) -> None:
        """
        Insert or update rows in ext_pest_alerts.
        Existing rows with same (crop_type, pest_code) are overwritten.

        Call Hierarchy
        --------------
        Parent  : self._refresh_cache()
        Children: (none — DB I/O only)
        """
        try:
            from aot.databases.models.ext_pest_alerts import ExtPestAlerts
            from aot.databases.utils import session_scope
            from aot.config import AOT_DB_PATH

            with session_scope(AOT_DB_PATH) as session:
                for row_data in rows:
                    db_row = {k: v for k, v in row_data.items()
                              if not k.startswith('_')}
                    existing = (
                        session.query(ExtPestAlerts)
                        .filter_by(
                            crop_type=db_row['crop_type'],
                            pest_code=db_row['pest_code'],
                        )
                        .first()
                    )
                    if existing:
                        for key, val in db_row.items():
                            setattr(existing, key, val)
                    else:
                        session.add(ExtPestAlerts(**db_row))
        except Exception as exc:
            logger.error("EXT-KR-03 cache upsert failed: %s", exc)

    # -----------------------------------------------------------------------
    # Utility methods (for domain_context_loader)
    # -----------------------------------------------------------------------

    @classmethod
    def get_alerts(cls, crop_type: str) -> list[dict]:
        """
        Return cached pest alerts for a crop_type, filtered to severity,
        pest_code, pest_name, and control_method fields.

        Triggers a refresh if the cache is stale (> 6h) or empty.

        Call Hierarchy
        --------------
        Parent  : domain_context_loader._resolve_operational_state() (EXT-KR-03)
        Children: cls._is_cache_fresh(), cls._refresh_cache(), cls._read_cache_by_crop()
        """
        if not cls._is_cache_fresh():
            api_key = os.environ.get('NCPMS_API_KEY', '')
            if api_key:
                year_month = datetime.now().strftime('%Y%m')
                cls._refresh_cache(api_key, year_month)
        return cls._read_cache_by_crop(crop_type)

    def _read_cache(self) -> list[dict]:
        """
        Read all fresh cached rows from ext_pest_alerts and return
        as list[{'parameter_name': str, 'value': str}] for the dispatch layer.

        Call Hierarchy
        --------------
        Parent  : self.sync()
        Children: (none — DB read only)
        """
        try:
            from aot.databases.models.ext_pest_alerts import ExtPestAlerts
            from aot.databases.utils import session_scope
            from aot.config import AOT_DB_PATH

            cutoff = datetime.now(timezone.utc) - timedelta(hours=_TTL_HOURS)
            with session_scope(AOT_DB_PATH) as session:
                rows = (
                    session.query(ExtPestAlerts)
                    .filter(ExtPestAlerts.fetched_at >= cutoff)
                    .all()
                )
                records: list[dict] = []
                for r in rows:
                    crop = r.crop_type or ''
                    pest = r.pest_code or ''
                    if not crop or not pest:
                        continue
                    severity = r.severity or ''
                    description = r.control_method or ''
                    value = f"{severity} — {description}" if description else severity
                    records.append({
                        'parameter_name': f"pest_alert.{crop}.{pest}",
                        'value':          value,
                    })
                return records

        except Exception as exc:
            logger.warning("EXT-KR-03 cache read failed: %s", exc)
            return []

    def _read_cache_by_crop(self, crop_type: str) -> list[dict]:
        """
        Read cached pest alert rows for a specific crop_type from ext_pest_alerts.
        Returns a list of dicts filtered to severity, pest_code, pest_name,
        and control_method fields.

        Call Hierarchy
        --------------
        Parent  : cls.get_alerts()
        Children: (none — DB read only)
        """
        try:
            from aot.databases.models.ext_pest_alerts import ExtPestAlerts
            from aot.databases.utils import session_scope
            from aot.config import AOT_DB_PATH

            cutoff = datetime.now(timezone.utc) - timedelta(hours=_TTL_HOURS)
            with session_scope(AOT_DB_PATH) as session:
                rows = (
                    session.query(ExtPestAlerts)
                    .filter(ExtPestAlerts.crop_type == crop_type)
                    .filter(ExtPestAlerts.fetched_at >= cutoff)
                    .all()
                )
                return [
                    {
                        'severity':       r.severity or '',
                        'pest_code':      r.pest_code or '',
                        'pest_name':      r.pest_name or r.pest_code or '',
                        'control_method': r.control_method or '',
                    }
                    for r in rows
                ]
        except Exception as exc:
            logger.warning("EXT-KR-03 cache read by crop failed: %s", exc)
            return []

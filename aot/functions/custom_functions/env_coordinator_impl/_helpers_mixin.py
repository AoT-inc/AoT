# coding=utf-8
"""
_helpers_mixin.py — HelpersMixin: small per-cycle helpers.
"""

import json
import time
from datetime import datetime, timezone as _tz

from aot.databases.models import Actions
from aot.functions.utils.env_control import (
    CH_DISPATCH_FAIL,
    write_decision_log,
)
from aot.utils.database import db_retrieve_table_daemon


class HelpersMixin:
    """Mixin: VPD setpoint, time window, end behaviors, sensor collection, gate env, dispatch."""

    _CACHED_TZ_SENTINEL = object()  # sentinel to distinguish "cache not yet resolved" state

    # ── Growth Schedule ───────────────────────────────────────────────────────

    def _get_weeks_elapsed(self) -> float:
        """Return fractional weeks elapsed since schedule_start_time + week_offset.

        Wall-clock policy: missed downtime is NOT compensated automatically.
        Use schedule_week_offset (positive = fast-forward) for manual adjustment.

        Input formats:
          - date only (YYYY-MM-DD): interpreted as facility-timezone midnight 00:00.
            If the facility timezone is unset, the system local timezone is used.
            (Farmers do not think in terms of UTC, so never assume UTC.)
          - date+time (ISO 8601 with tz): used as-is.
        Returns 0.0 when schedule_start_time is not set.
        """
        start_raw = (self.schedule_start_time or '').strip()
        if not start_raw:
            return 0.0
        try:
            import re as _re
            from dateutil.parser import isoparse

            # Detect date-only input: YYYY-MM-DD pattern (no time component)
            date_only = bool(_re.fullmatch(r'\d{4}-\d{2}-\d{2}', start_raw))

            # Resolve timezone from device location coordinates (farmers have no UTC concept)
            fac_tz = self._get_facility_tz()

            if date_only:
                # Date-only input -> interpret as device-location-timezone midnight 00:00
                if fac_tz is None:
                    self.logger.warning(
                        '_get_weeks_elapsed: no device location coordinates — '
                        'cannot resolve schedule_start_time timezone. '
                        'Set location coordinates on the device or link a GeoFacility.')
                    return 0.0
                import datetime as _dt
                year, month, day = map(int, start_raw.split('-'))
                local_midnight = _dt.datetime(year, month, day, 0, 0, 0)
                try:
                    start_dt = fac_tz.localize(local_midnight)
                except AttributeError:
                    start_dt = local_midnight.replace(tzinfo=fac_tz)
            else:
                start_dt = isoparse(start_raw)
                if start_dt.tzinfo is None:
                    # Time present but no tz -> interpret in device-location timezone
                    if fac_tz is not None:
                        try:
                            start_dt = fac_tz.localize(start_dt)
                        except AttributeError:
                            start_dt = start_dt.replace(tzinfo=fac_tz)
                    else:
                        self.logger.warning(
                            '_get_weeks_elapsed: no device location, falling back to UTC')
                        start_dt = start_dt.replace(tzinfo=_tz.utc)

            now_utc = datetime.now(_tz.utc)
            elapsed_sec = (now_utc - start_dt).total_seconds()
            offset = float(self.schedule_week_offset or 0.0)
            return max(0.0, elapsed_sec / (7 * 86400) + offset)
        except Exception as exc:
            self.logger.warning('_get_weeks_elapsed parse error: %s', exc)
            return 0.0

    def _parse_schedule_dt(self, raw: str):
        """Parse a Growth Schedule date string into a timezone-aware datetime.

        Accepts the same formats as schedule_start_time:
          - date only (YYYY-MM-DD): facility-local midnight 00:00.
          - date+time ISO 8601: used as-is; naive times → facility-local tz.
        Returns None when raw is empty or the timezone cannot be resolved.
        """
        raw = (raw or '').strip()
        if not raw:
            return None
        import re as _re
        from dateutil.parser import isoparse

        date_only = bool(_re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw))
        fac_tz = self._get_facility_tz()

        if date_only:
            if fac_tz is None:
                self.logger.warning(
                    '_parse_schedule_dt: no device location coordinates — '
                    'cannot resolve date timezone. Set location coordinates or a GeoFacility.')
                return None
            import datetime as _dt
            year, month, day = map(int, raw.split('-'))
            local_midnight = _dt.datetime(year, month, day, 0, 0, 0)
            try:
                return fac_tz.localize(local_midnight)
            except AttributeError:
                return local_midnight.replace(tzinfo=fac_tz)

        dt = isoparse(raw)
        if dt.tzinfo is None:
            if fac_tz is not None:
                try:
                    return fac_tz.localize(dt)
                except AttributeError:
                    return dt.replace(tzinfo=fac_tz)
            self.logger.warning('_parse_schedule_dt: no device location, falling back to UTC')
            return dt.replace(tzinfo=_tz.utc)
        return dt

    def _schedule_ended(self) -> bool:
        """Return True when schedule_end_time is set and the current time is past it.

        End date marks the harvest / cycle end. After it passes, the coordinator
        stops control (actuators return to their end-behavior, cycles halt).
        Returns False when no end date is configured or it cannot be parsed.
        """
        raw = (getattr(self, 'schedule_end_time', None) or '').strip()
        if not raw:
            return False
        try:
            end_dt = self._parse_schedule_dt(raw)
            if end_dt is None:
                return False
            return datetime.now(_tz.utc) >= end_dt
        except Exception as exc:
            self.logger.warning('_schedule_ended parse error: %s', exc)
            return False

    def _get_facility_tz(self):
        """Resolve the timezone from device/facility location coordinates and return a pytz object.

        If a value resolved at initialize() is present in _cached_tz, return it immediately.
        (Zero per-cycle cost for DB queries and TimezoneFinder creation.)

        Priority:
          1. This Function itself (CustomController): timezone column -> latitude/longitude
          2. Linked GeoFacility -> GeoShape centroid coordinates
          3. Linked actuator Output device's timezone/coordinates
          4. Linked sensor Input device's timezone/coordinates (via Actions)
          5. None (handled by the caller — farmers have no UTC concept, so no UTC fallback is used)

        Uses aot.utils.device_tz.resolve_tz_from_coords to share the module cache.
        """
        # Cache hit — after initialize(), every cycle returns immediately here
        # _CACHED_TZ_SENTINEL: not yet resolved / None: resolved but no coordinates
        cached = getattr(self, '_cached_tz', self._CACHED_TZ_SENTINEL)
        if cached is not self._CACHED_TZ_SENTINEL:
            return cached

        import pytz
        from aot.utils.device_tz import resolve_tz_from_coords
        from aot.utils.database import db_retrieve_table_daemon

        def _tz_from_row(row):
            """Return a pytz object from a row (having a timezone column or latitude/longitude columns)."""
            if row is None:
                return None
            tz_name = getattr(row, 'timezone', None)
            if not tz_name:
                tz_name = resolve_tz_from_coords(
                    getattr(row, 'latitude', None),
                    getattr(row, 'longitude', None),
                )
            if tz_name:
                try:
                    return pytz.timezone(tz_name)
                except Exception:
                    pass
            return None

        # ── 1. Function itself (CustomController record) ────────────────────
        try:
            from aot.databases.models.controller import CustomController as CC
            row = db_retrieve_table_daemon(CC, unique_id=self.unique_id)
            tz = _tz_from_row(row)
            if tz:
                return tz
        except Exception as exc:
            self.logger.warning('_get_facility_tz function-coord error: %s', exc)

        # ── 2. Linked GeoFacility ─────────────────────────────────────────
        # resolve_timezone() accesses self.shape (a lazy relationship), so it
        # must be called with an open session (using session_scope directly).
        facility_id = getattr(self, 'geo_facility_id_device_id', None) or ''
        if facility_id:
            try:
                from aot.databases.models.geo import GeoFacility
                from aot.config import AOT_DB_PATH
                from aot.databases.utils import session_scope
                with session_scope(AOT_DB_PATH) as sess:
                    fac = sess.query(GeoFacility).filter(
                        GeoFacility.unique_id == facility_id).first()
                    if fac is not None:
                        tz_obj = fac.resolve_timezone()
                        sess.expunge_all()
                        if tz_obj:
                            return tz_obj
            except Exception as exc:
                self.logger.debug('_get_facility_tz facility error: %s', exc)

        # ── 3. Linked actuator Output device ─────────────────────────────
        try:
            from aot.databases.models.output import Output
            profiles = getattr(self, '_profiles', [])
            for profile in profiles:
                act_id = getattr(profile, 'actuator_id', None)
                if not act_id:
                    continue
                out = db_retrieve_table_daemon(Output, unique_id=act_id)
                tz = _tz_from_row(out)
                if tz:
                    return tz
        except Exception as exc:
            self.logger.debug('_get_facility_tz actuator-coord error: %s', exc)

        # ── 4. Linked sensor Input device (via Actions) ──────────────────────
        try:
            from aot.databases.models.input import Input
            from aot.databases.models.function import Actions
            import json as _json
            actions = db_retrieve_table_daemon(Actions, entry='all',
                                               custom_name='function_id',
                                               custom_value=self.unique_id)
            for action in (actions or []):
                try:
                    opts = _json.loads(action.custom_options or '{}')
                    input_id = (opts.get('input_id')
                                or opts.get('measurement_device_id') or '')
                    if not input_id:
                        continue
                    inp = db_retrieve_table_daemon(Input, unique_id=input_id)
                    tz = _tz_from_row(inp)
                    if tz:
                        return tz
                except Exception:
                    continue
        except Exception as exc:
            self.logger.debug('_get_facility_tz input-coord error: %s', exc)

        return None

    # ── CO₂ setpoint ─────────────────────────────────────────────────────────

    def _get_co2_setpoint(self):
        """Return current CO₂ target (ppm) from static value or Method curve.

        Returns None when CO₂ control is disabled (target_co2 = 0 or no method configured).
        CO₂ sensor source is determined by geo/facility fittings (measurement_type='co2').
        """
        sp_type = self.co2_sp_type or 'static'

        if sp_type == 'static':
            val = self.target_co2
            return float(val) if val and float(val) > 0 else None

        if sp_type == 'method':
            method_id = self.co2_method_id_device_id or ''
            if not method_id:
                return self._co2_last_sp

            if getattr(self, '_co2_loaded_method_id', None) != method_id:
                self._co2_method_handler = None
                self._co2_loaded_method_id = method_id

            if self._co2_method_handler is None:
                try:
                    from aot.utils.method import load_method_handler
                    self._co2_method_handler = load_method_handler(method_id, self.logger)
                except Exception as exc:
                    self.logger.error(
                        'CO₂ method load failed (%s): %s', method_id, exc)
                    return self._co2_last_sp

            try:
                weeks_elapsed = self._get_weeks_elapsed() or None
                facility_tz   = self._get_facility_tz()
                sp_val, ended = self._co2_method_handler.calculate_setpoint(
                    time.time(),
                    weeks_elapsed=weeks_elapsed,
                    facility_tz=facility_tz,
                )
                if ended:
                    sp_val = self._co2_last_sp
                if sp_val is not None:
                    self._co2_last_sp = float(sp_val)
                return self._co2_last_sp
            except Exception as exc:
                self.logger.error('CO₂ method calculate_setpoint error: %s', exc)
                return self._co2_last_sp

        return None

    # ── VPD setpoint ─────────────────────────────────────────────────────────

    def _get_vpd_setpoint(self):
        """Return current VPD target (kPa) from static value or Method curve."""
        sp_type = self.vpd_sp_type or 'static'

        if sp_type == 'static':
            val = self.target_vpd
            return float(val) if val and float(val) > 0 else None

        if sp_type == 'method':
            method_id = self.vpd_method_id_device_id or ''
            if not method_id:
                return self._vpd_last_sp

            # Detect method_id change -> reset handler
            if getattr(self, '_vpd_loaded_method_id', None) != method_id:
                self._vpd_method_handler = None
                self._vpd_method_start = None
                self._vpd_loaded_method_id = method_id

            if self._vpd_method_handler is None:
                try:
                    from aot.utils.method import load_method_handler, parse_db_time
                    from aot.databases.models import CustomController
                    from aot.utils.time_utils import utc_now
                    from aot.config import AOT_DB_PATH
                    from aot.databases.utils import session_scope

                    self._vpd_method_handler = load_method_handler(method_id, self.logger)

                    # Load method_start_time stored in the DB (if absent, store the current time)
                    with session_scope(AOT_DB_PATH) as sess:
                        ctrl = sess.query(CustomController).filter(
                            CustomController.unique_id == self.unique_id).first()
                        if ctrl is not None:
                            stored = parse_db_time(ctrl.method_start_time)
                            if stored is None:
                                stored = utc_now()
                                ctrl.method_start_time = stored.isoformat()
                                sess.commit()
                            self._vpd_method_start = stored
                            sess.expunge_all()

                    if self._vpd_method_start is None:
                        self._vpd_method_start = utc_now()

                except Exception as exc:
                    self.logger.error(
                        'VPD method load failed (%s): %s', method_id, exc)
                    return self._vpd_last_sp

            try:
                weeks_elapsed = self._get_weeks_elapsed() or None
                facility_tz   = self._get_facility_tz()
                sp_val, ended = self._vpd_method_handler.calculate_setpoint(
                    time.time(),
                    method_start_time=self._vpd_method_start,
                    weeks_elapsed=weeks_elapsed,
                    facility_tz=facility_tz,
                )
                if ended:
                    sp_val = self._vpd_last_sp
                if sp_val is not None:
                    self._vpd_last_sp = float(sp_val)
                return self._vpd_last_sp
            except Exception as exc:
                self.logger.error('VPD method calculate_setpoint error: %s', exc)
                return self._vpd_last_sp

        return None

    # ── Photoperiod / time window ─────────────────────────────────────────────

    @staticmethod
    def _hours_to_hhmm(anchor: str, offset_hours: float) -> str:
        """Shift anchor HH:MM by offset_hours and return result as HH:MM string.

        Example: anchor='12:00', offset=-7.0 → '05:00'
        Wraps within 00:00–23:59 (24h clock).
        """
        try:
            ah, am = (int(x) for x in anchor.split(':'))
        except Exception:
            ah, am = 12, 0
        total_min = ah * 60 + am + int(round(offset_hours * 60))
        total_min = total_min % (24 * 60)
        return f'{total_min // 60:02d}:{total_min % 60:02d}'

    def _get_time_window(self):
        """Return (start_hhmm, end_hhmm) for the active time window.

        When photo_method_id is set, the Method returns photoperiod length (hours)
        and the window is centred on photo_anchor. Falls back to static
        time_start / time_end when no Method is configured.
        """
        method_id = self.photo_method_id_device_id or ''
        if not method_id:
            return self.time_start or '06:00', self.time_end or '20:00'

        if getattr(self, '_photo_loaded_method_id', None) != method_id:
            self._photo_method_handler = None
            self._photo_loaded_method_id = method_id

        if self._photo_method_handler is None:
            try:
                from aot.utils.method import load_method_handler
                self._photo_method_handler = load_method_handler(method_id, self.logger)
            except Exception as exc:
                self.logger.error('Photoperiod method load failed (%s): %s', method_id, exc)
                return self.time_start or '06:00', self.time_end or '20:00'

        try:
            weeks_elapsed = self._get_weeks_elapsed() or None
            facility_tz   = self._get_facility_tz()
            photo_h, _ = self._photo_method_handler.calculate_setpoint(
                time.time(),
                weeks_elapsed=weeks_elapsed,
                facility_tz=facility_tz,
            )
            if photo_h is None or photo_h <= 0:
                return self.time_start or '06:00', self.time_end or '20:00'

            anchor = self.photo_anchor or '12:00'
            start  = self._hours_to_hhmm(anchor, -photo_h / 2.0)
            end    = self._hours_to_hhmm(anchor, +photo_h / 2.0)
            return start, end
        except Exception as exc:
            self.logger.error('Photoperiod method calculate error: %s', exc)
            return self.time_start or '06:00', self.time_end or '20:00'

    def _in_time_window(self) -> bool:
        """Return True if current time is within the active time window."""
        try:
            now   = datetime.now().strftime('%H:%M')
            start, end = self._get_time_window()
            if start <= end:
                return start <= now <= end
            else:
                return now >= start or now <= end   # overnight window
        except Exception:
            return True

    # ── Email notification helpers ─────────────────────────────────────────────────────

    def _get_email_actions(self):
        """Return the list of email actions registered on this Function (cached 5 min)."""
        now = time.time()
        cache_ts  = getattr(self, '_email_actions_ts',  0.0)
        cache_val = getattr(self, '_email_actions_cache', None)
        if cache_val is not None and (now - cache_ts) < 300:
            return cache_val

        try:
            actions = db_retrieve_table_daemon(Actions).filter(
                Actions.function_id == self.unique_id,
                Actions.action_type == 'email',
            ).all()
            self._email_actions_cache = actions
            self._email_actions_ts    = now
            return actions
        except Exception:
            return []

    def _send_critical_email(self, subject_key: str, message: str):
        """Send a critical event by email (same subject_key limited to once per day).

        subject_key: deduplication key (e.g. 'wind_gate', 'rain_gate', 'extreme_heat')
        message:     body text
        """
        now = time.time()
        if not hasattr(self, '_email_sent_ts'):
            self._email_sent_ts: dict = {}   # {subject_key: last_sent_ts}

        # Limit the same message to once per day
        last = self._email_sent_ts.get(subject_key, 0.0)
        if (now - last) < 86400:
            return

        email_actions = self._get_email_actions()
        if not email_actions:
            return

        try:
            from aot.utils.actions import parse_action_information, trigger_action
            dict_actions = parse_action_information()
            for action in email_actions:
                trigger_action(
                    dict_actions,
                    action.unique_id,
                    value={'message': message},
                )
            self._email_sent_ts[subject_key] = now
            self.logger.info(
                'EnvCoordinator: sent critical alert email [%s]', subject_key)
        except Exception as exc:
            self.logger.error(
                'EnvCoordinator: email send failed [%s] — %s', subject_key, exc)

    # ── P5-3: Authority alerts + Unattainable detection ─────────────────────────────

    def _emit_authority_alerts(self, situation):
        """State-transition / cooldown-based alerts — minimize repeat notifications.

        Design principles:
          1. Alert only on a state transition (OK->problem). Same state persisting = no alert.
          2. Non-actionable situations (NATURAL + no gradient) use a 24h cooldown.
             Nothing can be done anyway, so repeat alerts only accumulate fatigue.
          3. Actionable situations (ACTIVE/PASSIVE actuators present) use a 1h cooldown.
          4. When the state clears, reset the counter/cooldown -> alert again on next occurrence.
        """
        from aot.functions.utils.env_control.authority import (
            detect_unattainable, LEVEL_ACTIVE, LEVEL_PASSIVE, LEVEL_NATURAL,
            needed_direction_authority,
        )
        from aot.functions.utils.env_control.types import (
            MODE_NATURAL, MODE_DEGRADED,
        )

        now_ts = time.time()
        modes  = situation.modes
        auth   = situation.authority

        # ── Initialize alert cooldown state ──────────────────────────────────────────
        if not hasattr(self, '_alert_last_ts'):
            self._alert_last_ts: dict = {}    # {key: timestamp}
        if not hasattr(self, '_alert_state'):
            self._alert_state: dict = {}      # {key: bool} — current alert state

        def _should_alert(key: str, cooldown_h: float) -> bool:
            """False if within the cooldown or already alerted."""
            last = self._alert_last_ts.get(key, 0.0)
            return (now_ts - last) >= cooldown_h * 3600

        def _mark_alerted(key: str):
            self._alert_last_ts[key] = now_ts
            self._alert_state[key]   = True

        def _clear_alert(key: str):
            """Reset state when the condition clears — alert immediately on next occurrence."""
            self._alert_state.pop(key, None)
            self._alert_last_ts.pop(key, None)

        # ── 1. NATURAL/DEGRADED mode transition alerts ───────────────────────────────
        # Alert only at the moment of transition. Stay silent while the same mode persists.
        prev_modes = getattr(self, '_last_situation_modes', [])

        if MODE_NATURAL in modes and MODE_NATURAL not in prev_modes:
            self.logger.warning(
                'EnvCoordinator: no active actuators — control impossible, outdoor-tracking only')

        elif MODE_DEGRADED in modes and MODE_DEGRADED not in prev_modes:
            nat_vars = [k for k, v in auth.items() if v == LEVEL_NATURAL]
            self.logger.warning(
                'EnvCoordinator: %s uncontrollable (no actuators) — controlling remaining variables only',
                ', '.join(nat_vars))

        elif MODE_NATURAL not in modes and MODE_NATURAL in prev_modes:
            # Cleared: NATURAL -> normal
            self.logger.info('EnvCoordinator: returned to controllable state')

        self._last_situation_modes = list(modes)

        # ── 2. Unattainable detection + smart alerts ───────────────────────────────
        unattainable = detect_unattainable(
            env_target=situation.target,
            deviation_native=situation.deviation_native,
            authority=auth,
            unattainable_state=self._unattainable_state,
            threshold_cycles=10,
        )

        # Variables not unattainable this cycle -> clear counter/alert
        for var in list(self._alert_state.keys()):
            if var.startswith('unat_') and var[5:] not in (unattainable or []):
                _clear_alert(var)

        if unattainable:
            for var in unattainable:
                key = f'unat_{var}'
                tv  = situation.target.get(var)
                dev = situation.deviation_native.get(var, 0.0)

                # Decide the cooldown based on whether action is possible.
                # authority is keyed by direction ('T_up'/'CO2_down'…), so convert the
                # variable name into the direction key matching the deviation sign before
                # lookup. Looking up the raw variable name ('temperature'/'co2') always
                # falls to NATURAL, so the [action required] alert would never fire even
                # when actuators are present.
                var_auth = needed_direction_authority(auth, var, dev)
                if var_auth == LEVEL_NATURAL:
                    # No device -> 24h cooldown (block repeat alerts)
                    cooldown_h = 24.0
                    actionable = False
                else:
                    # ACTIVE/PASSIVE device present but still unreachable -> 1h cooldown
                    cooldown_h = 1.0
                    actionable = True

                if not _should_alert(key, cooldown_h):
                    continue   # within cooldown — stay silent

                if actionable:
                    self.logger.warning(
                        'EnvCoordinator: [action required] %s target %.1f unreachable '
                        '(deviation %.1f, 10+ cycles). Actuator check needed.',
                        var, tv.value if tv else 0.0, dev)
                    target_val = tv.value if tv else 0.0
                    current_val = target_val + dev
                    self._send_critical_email(
                        key,
                        f'[Environment Control Alert] {var} target ({target_val:.1f}) '
                        f'unreachable for 10+ cycles (current {current_val:.1f}, deviation {dev:+.1f}). '
                        f'Please check the relevant actuator.',
                    )
                else:
                    # No device case: once a day only, quiet info level
                    self.logger.info(
                        'EnvCoordinator: %s has no control device — current %.1f (target %.1f). '
                        'If this message repeats tomorrow, consider adding a device.',
                        var, (tv.value if tv else 0.0) + dev, tv.value if tv else 0.0)

                _mark_alerted(key)

    # ── P5-5: Cumulative Goal Tracker ─────────────────────────────────────────

    def _update_cumulative_tracker(self, internal: dict, cycle_sec: float,
                                   authority: dict):
        """Accumulate DLI/GDD and, at day rollover, save to DB + generate compensation suggestions."""
        from aot.functions.utils.env_control.cumulative_tracker import (
            DailyAccumulator, accumulate_cycle, generate_suggestions, save_daily_state,
            local_today,
        )
        from aot.functions.utils.env_control.photosynthesis import get_crop_params

        # 일별 경계는 시설 로컬 타임존 기준(다른 일별 로직과 일관). 미해석 시 UTC.
        tz = getattr(self, '_cached_tz', None)

        # Initialize (lazy) — 로컬 날짜로 초기화해 기동 직후 허위 롤오버 방지
        if self._daily_acc is None:
            self._daily_acc = DailyAccumulator(day_local=local_today(tz))

        crop = get_crop_params(self.crop_preset)
        T_base = crop.T_base

        # DLI/GDD 목표는 함수 옵션값을 단일 출처로 사용한다(작물 프리셋 선택 시
        # _sync_crop_targets 가 옵션에 자동 반영). 0 = 해당 지표 비활성.
        dli_t = float(self.dli_target or 0.0) or None
        gdd_t = float(self.gdd_target_daily or 0.0) or None

        # internal['light'] 는 시스템 관례상 W/m²(전천일사). light_unit 이 명시되면 사용.
        rolled = accumulate_cycle(
            acc=self._daily_acc,
            light_value=internal.get('light'),
            light_unit=internal.get('light_unit'),
            T_mean=internal.get('T', 20.0),
            VPD=internal.get('VPD', 0.5),
            CO2=internal.get('CO2', 400.0),
            cycle_sec=cycle_sec,
            T_base=T_base,
            tz=tz,
        )

        # Day rollover handling
        if rolled:
            suggestions = generate_suggestions(
                debt_dli  = (dli_t - self._daily_acc.dli) if dli_t else 0.0,
                debt_gdd  = (gdd_t - self._daily_acc.gdd) if gdd_t else 0.0,
                authority = authority,
                dli_target=dli_t,
                gdd_target=gdd_t,
            )
            save_daily_state(
                function_id=self.unique_id,
                acc=self._daily_acc,
                dli_target=dli_t,
                gdd_target=gdd_t,
                suggestions=suggestions,
            )
            for s in suggestions:
                self.logger.warning('CumulativeTracker: %s', s.message)

            # Initialize for the new day (로컬 날짜 기준)
            self._daily_acc = DailyAccumulator(day_local=local_today(tz))

        # Periodic interim save (every hour)
        elif (int(time.time()) % 3600) < int(cycle_sec):
            save_daily_state(
                function_id=self.unique_id,
                acc=self._daily_acc,
                dli_target=dli_t,
                gdd_target=gdd_t,
                suggestions=[],
            )

    def _apply_end_behaviors(self):
        """Send end-of-window commands to each actuator based on its end_behavior setting."""
        actions = db_retrieve_table_daemon(Actions).filter(
            Actions.function_id == self.unique_id,
            Actions.action_type == 'env_actuator',
        ).all()

        for action in actions:
            try:
                opts = json.loads(action.custom_options or '{}')
            except Exception:
                continue

            output_val = opts.get('output', '')
            if not output_val:
                continue
            parts      = str(output_val).split(',')
            device_id  = parts[0].strip()
            channel_id = parts[1].strip() if len(parts) > 1 else None
            ch_obj = 0
            if channel_id:
                try:
                    ch_obj = self.get_output_channel_from_channel_id(channel_id)
                except Exception:
                    pass

            behavior = opts.get('end_behavior', 'nothing')
            if behavior == 'off':
                self.control.output_off(device_id, output_channel=ch_obj)
            elif behavior == 'on':
                self.control.output_on(device_id, output_channel=ch_obj)
            elif behavior == 'open_pct':
                pct = float(opts.get('end_open_pct', 0.0) or 0.0)
                self.control.output_on(device_id, output_type='value',
                                       amount=pct, output_channel=ch_obj)

    def _collect_internal(self, max_age: float, outdoor_data: dict = None) -> dict:
        """실내 센서 데이터 수집.

        Args:
            max_age:      센서 최대 허용 경과시간 (초)
            outdoor_data: _run_cycle 에서 이미 읽은 read_outdoor_sensors() 결과.
                          전달 시 outdoor 재조회를 생략한다 (InfluxDB 중복 쿼리 방지).
        """
        result = {}

        # geo/facility single source: sensors_resolved (indoor) -> T, RH, CO2, VPD, light
        _sr = getattr(self, '_sensors_resolved', [])
        if _sr:
            try:
                from aot.aot_flask.geo.facility_sensors import compute_spatial_internal
                spatial = compute_spatial_internal(_sr, max_age=int(max_age))
                for _k in ('T', 'RH', 'CO2', 'VPD', 'light'):
                    if spatial.get(_k) is not None:
                        result[_k] = spatial[_k]
                # Spatial extremes — safety_gates judge heatwave/cold using max/min, not the average
                for _k in ('T_min', 'T_max', 'RH_min', 'RH_max'):
                    if spatial.get(_k) is not None:
                        result[_k] = spatial[_k]
                if spatial.get('hotspot_T'):
                    result['_spatial_hotspot_T'] = True
                if spatial.get('hotspot_RH'):
                    result['_spatial_hotspot_RH'] = True
                # Spatial outlier (faulty sensor) count — if greater than 0, a commissioning branch is possible
                if spatial.get('rejected_count'):
                    result['_spatial_rejected_count'] = spatial['rejected_count']
            except Exception as _se:
                self.logger.debug('facility spatial collect failed: %s', _se)

        # P0 fallback: when the spatial path returns none of T/RH/CO2
        # (all sensors expired, full MAD rejection, etc.) -> substitute a role-based weighted average.
        if not any(k in result for k in ('T', 'RH', 'CO2')) and _sr:
            try:
                from aot.aot_flask.geo.facility_sensors import read_facility_sensors
                role_data = read_facility_sensors(_sr, max_age=int(max_age))
                indoor = role_data.get('indoor') or {}
                if indoor.get('temp_c') is not None and 'T' not in result:
                    result['T'] = indoor['temp_c']
                if indoor.get('humidity_pct') is not None and 'RH' not in result:
                    result['RH'] = indoor['humidity_pct']
                if indoor.get('co2_ppm') is not None and 'CO2' not in result:
                    result['CO2'] = indoor['co2_ppm']
                if result:
                    self.logger.debug(
                        '_collect_internal: spatial failed -> using role-based fallback')
            except Exception as _fe:
                self.logger.debug(
                    '_collect_internal: role-based fallback failed: %s', _fe)

        # geo/facility single source: sensors_outdoor (outdoor) -> wind, wind_dir, solar
        # outdoor_data 가 전달된 경우 _run_cycle 에서 이미 읽은 결과를 재사용한다.
        _sr_out = getattr(self, '_sensors_resolved_outdoor', [])
        if _sr_out:
            od = outdoor_data
            if od is None:
                try:
                    from aot.aot_flask.geo.facility_sensors import read_outdoor_sensors
                    od = read_outdoor_sensors(_sr_out, max_age=int(max_age))
                except Exception as _se:
                    self.logger.debug('facility outdoor collect (wind/solar) failed: %s', _se)
                    od = {}
            if od:
                if od.get('wind_ms') is not None:
                    result['wind'] = od['wind_ms']
                if od.get('wind_deg') is not None:
                    result['wind_dir'] = od['wind_deg']
                # When there is no indoor light sensor, supplement with outdoor solar irradiance
                if od.get('solar_wm2') is not None and 'light' not in result:
                    result['light'] = od['solar_wm2']
                    # 이 값은 차광막 '바깥' 값이라 차광막 개도를 반영하지 못한다.
                    # 실내 광량 추정(estimate_indoor_light)을 적용해도 되는지
                    # 판별하는 플래그 — 실제 실내 센서가 있으면 이미 차광이
                    # 반영돼 있으므로 추정을 덧씌우면 이중 계산이 된다.
                    result['_light_is_outdoor'] = True

        return result

    def _build_gate_env(self, internal: dict, external: dict) -> dict:
        wind_val     = internal.get('wind',     external.get('wind',     0.0))
        wind_dir_val = internal.get('wind_dir', external.get('wind_dir', None))
        # Heatwave/cold judgment uses spatial extremes, not the average — if one corner is
        # at a dangerous level, emergency must fire even when the average is still normal.
        T_for_heat = internal.get('T_max', internal.get('T', 25.0))
        T_for_cold = internal.get('T_min', internal.get('T', 25.0))
        return {
            'internal': {
                'T':      internal.get('T',  25.0),
                'T_max':  T_for_heat,
                'T_min':  T_for_cold,
                'RH':     internal.get('RH', 60.0),
                'RH_max': internal.get('RH_max', internal.get('RH', 60.0)),
                'RH_min': internal.get('RH_min', internal.get('RH', 60.0)),
            },
            'external': {
                'T':        external.get('T_ext', 20.0),
                'RH':       external.get('RH_ext', 60.0),
                'wind':     wind_val,
                'wind_dir': wind_dir_val,
                'rain':     external.get('rain', 0.0),
            },
            'now_ts':      time.time(),
            'last_ext_ts': external.get('last_ext_ts', time.time()),
            'last_int_ts': time.time(),
        }

    # ── Dispatch lifetime-protection constants ────────────────────────────────────────────────
    _DISPATCH_DEADBAND_PCT = 1.0    # if |new - prev| < this value, skip sending (%)
    _DISPATCH_WATCHDOG_SEC = 600.0  # even for the same value, force a re-confirm send every this period (s)
    _DISPATCH_STAGGER_SEC  = 1.0    # sequential send interval between devices (s) — spreads simultaneous batch-send load

    # ── Motor-driven actuator (side/roof vent) lifetime protection: motion gate ──────────────────
    # Even in steady state, the PI controller produces a target value that wobbles 1~3% every
    # cycle due to the integral term and sensor noise. With only the default deadband (1%), these
    # micro-fluctuations drive the motor every cycle, accelerating gearbox and limit-switch wear.
    # opening kinds reduce move frequency with the following triple gate:
    #   1) Quantize (step grid): snap the command to the move_step_pct grid -> absorb micro-fluctuations.
    #   2) Hysteresis: must diverge at least one step (move_step_pct) from the last sent value to move.
    #   3) Minimum move interval: suppress moves within the effective actuation period (see
    #      _actuation_params()) of the last ACTUAL move. During an emergency cycle
    #      (see CycleMixin._classify_emergency), this gate is bypassed down to
    #      emergency_period_sec so sudden weather changes / safety gates still move vents promptly.
    # step (=cmd_constraints.move_step_pct) is a per-actuator user option.
    # Default 5%, 0 = gate disabled -> micro-vibration is passed straight to the motor (legacy behavior).
    _MOTOR_KINDS = frozenset({'opening'})
    _MOTOR_MIN_MOVE_SEC = 180.0     # fallback when no profile/actuation_profile is resolvable (s)

    # ── Actuation-rate profiles (normal-cycle minimum move interval, seconds) ────────────────────
    # 'standard' matches the legacy _MOTOR_MIN_MOVE_SEC so existing installs are unaffected until
    # the user explicitly picks a different profile.
    _ACTUATION_PROFILE_SEC = {
        'responsive': 60.0,
        'standard':   180.0,
        'gentle':     600.0,
    }

    def _actuation_params(self) -> tuple:
        """Resolve (normal_min_dwell_sec, emergency_min_dwell_sec) from custom_options.

        normal_min_dwell_sec: minimum interval between vent moves in a normal (non-emergency)
                              cycle. Profile default, or actuation_period_sec when profile='custom'.
        emergency_min_dwell_sec: minimum interval enforced even during an emergency cycle
                              (prevents rapid back-to-back moves; does not delay the FIRST
                              emergency move once the interval has elapsed).
        """
        profile = getattr(self, 'actuation_profile', 'standard') or 'standard'
        if profile == 'custom':
            custom_sec = float(getattr(self, 'actuation_period_sec', 0.0) or 0.0)
            normal_sec = custom_sec if custom_sec > 0.0 else self._ACTUATION_PROFILE_SEC['standard']
        else:
            normal_sec = self._ACTUATION_PROFILE_SEC.get(profile, self._MOTOR_MIN_MOVE_SEC)
        emergency_sec = float(getattr(self, 'emergency_period_sec', 60.0) or 60.0)
        return normal_sec, emergency_sec

    def _motor_motion_gate(self, target, last_sent, age, min_dwell, step):
        """Decide whether a motor-driven actuator should move and what value to send.

        Returns (send_val, should_move):
          - should_move=False -> skip sending this cycle (keep last_sent).
          - should_move=True  -> move to the quantized send_val.

        last_sent is always a value on the grid, so comparing against the quantized target gives hysteresis.
        If step <= 0, the caller skips the gate, so this is never reached.

        min_dwell is supplied by the caller — a normal cycle passes the actuation_profile
        period, an emergency cycle passes the (much shorter) emergency_period_sec. There is
        no magnitude-based bypass here: an urgent, large command is expressed by the caller
        choosing a small min_dwell (emergency=True), not by this function inferring urgency
        from the size of the move.
        """
        q = round(target / step) * step
        q = max(0.0, min(100.0, q))
        if last_sent is None:
            return q, True
        move = abs(q - last_sent)
        if move < step - 1e-6:
            return last_sent, False          # quantized result is the same step -> no move needed
        if age < min_dwell:
            return last_sent, False          # minimum move interval not met
        return q, True

    def _resolve_adapter(self, actuator_id: str):
        """Dynamically select the DispatchAdapter for a single actuator (daemon-safe).

        Used to backfill on the fly when not present in _adapter_by_id. Selects an
        on_off / pwm / value (actuator_paired) / vol adapter based on the device's
        module type and output_types.
        Uses db_retrieve_table_daemon instead of the Flask Output.query.
        """
        try:
            from aot.functions.utils.env_control.dispatch_adapters import select_adapter
            from aot.utils.outputs import parse_output_information
            from aot.databases.models import Output
            from aot.utils.database import db_retrieve_table_daemon

            row = db_retrieve_table_daemon(Output, unique_id=actuator_id)
            module_name = row.output_type if row is not None else ''
            try:
                output_info = parse_output_information()
            except Exception:
                output_info = {}
            types_list = (output_info.get(module_name, {}) or {}).get('output_types') or []
            profile = getattr(self, '_by_id', {}).get(actuator_id)
            cap_meta = getattr(profile, 'capacity_meta', None) or {}
            return select_adapter(module_name, types_list, cap_meta)
        except Exception as exc:
            self.logger.warning(
                'EnvCoordinator: _resolve_adapter failed actuator=%s err=%s',
                actuator_id, exc)
            return None

    def _sync_prev_from_devices(self):
        """슬루 기준(prev_commands)을 actuator_paired 장치의 실제 위치로 동기화한다.

        코디네이터의 위치 기억(prev_commands, runtime_state)과 장치의 실측 위치
        (last_position_pct, output_channel)는 별도 저장되어 재시작·수동조작 시
        어긋날 수 있다. 어긋나면 slew 기준이 틀려 '닫기' 명령이 '열기' 동작으로
        실행되는 등 반대로 움직인다(현장 aot-005 차광막 사건). 장치를 위치의 single
        source of truth 로 보고 매 사이클 prev_commands 를 장치 위치로 맞춘다.

        last_position_pct(모터 위치)는 map_aperture_to_motor 의 역변환으로
        코디네이터 개도(aperture)로 환산한다.
        """
        state = getattr(self, '_coord_state', None)
        if state is None:
            return
        try:
            from aot.databases.models import OutputChannel
            from aot.databases.utils import session_scope
            from aot.config import AOT_DB_PATH
            opts_by_id = {}
            with session_scope(AOT_DB_PATH) as sess:
                for ch in sess.query(OutputChannel).filter(
                        OutputChannel.channel == 0).all():
                    opts_by_id[ch.output_id] = ch.custom_options
                sess.expunge_all()
        except Exception:
            self.logger.debug('prev_commands resync: DB read failed', exc_info=True)
            return

        for p in getattr(self, '_profiles', []):
            raw = opts_by_id.get(p.actuator_id)
            if not raw:
                continue
            try:
                opts = json.loads(raw or '{}')
            except Exception:
                continue
            if 'last_position_pct' not in opts:
                continue   # actuator_paired 만 보유 (팬·릴레이 제외)
            try:
                motor = float(opts.get('last_position_pct') or 0.0)
            except (TypeError, ValueError):
                continue
            s = p.cmd_constraints.effective_start_pct
            e = p.cmd_constraints.effective_end_pct
            aperture = ((motor - s) / (e - s) * 100.0) if e > s else motor
            aperture = max(0.0, min(100.0, aperture))
            prev = state.prev_commands.get(p.actuator_id)
            if prev is None or abs(prev - aperture) > 0.5:
                state.prev_commands[p.actuator_id] = aperture
                self.logger.debug(
                    'prev_commands resync %s: %s → %.1f (device motor=%.1f%%)',
                    p.actuator_id[:8],
                    f'{prev:.1f}' if prev is not None else 'none', aperture, motor)

    def _dispatch(self, commands: dict, cycle_sec: float = 60.0, emergency: bool = False) -> set:
        """Dispatch commands. Returns set of actuator_ids that FAILED.

        Lifetime protection (2026-05-18):
        - Deadband: if |new - prev_sent| < _DISPATCH_DEADBAND_PCT, skip sending.
        - No-change skip: if the value is the same and within _DISPATCH_WATCHDOG_SEC, skip.
        - Watchdog re-confirm: force a send once every _DISPATCH_WATCHDOG_SEC (state sync).

        Actuation rate (opening kinds only): the minimum interval between actual
        vent MOVES (not sends) is the actuation_profile period in a normal cycle,
        or emergency_period_sec when emergency=True (safety gate / large deviation /
        fast rate-of-change / just-changed setpoint — see CycleMixin._classify_emergency).
        The interval is measured from the last ACTUAL move (_dispatch_moved), not from
        the last send, so a same-value watchdog re-confirm never resets the dwell clock.

        P0 (2026-05-16): return the failure set, WARNING log, record CH_DISPATCH_FAIL.
        P0 (adapter): auto-convert to the appropriate output_type based on the device output_types.
          - on_off  relay   -> TimeProportionalAdapter (sec proportional)
          - pwm output      -> PwmAdapter
          - actuator_paired -> PairedAdapter (delegates internal conversion)
          - vol pump        -> VolumetricAdapter (mL conversion)
          - default (value) -> ValueAdapter (0-100% direct)
        """
        if not hasattr(self, '_dispatch_sent'):
            # {actuator_id: (sent_value, sent_ts)} — every actual transmission (moved or not)
            self._dispatch_sent: dict = {}
        if not hasattr(self, '_dispatch_moved'):
            # {actuator_id: moved_ts} — only transmissions where the value actually changed
            self._dispatch_moved: dict = {}

        # Adapter map — built in _reload_profiles(); empty dict if absent (uses default ValueAdapter)
        _adapters = getattr(self, '_adapter_by_id', {})

        now = time.time()
        failed: set = set()
        skipped = 0
        sent = 0  # number of devices actually sent — used to apply the 1-second sequential interval between devices

        for actuator_id, cmd in commands.items():
            val = (cmd.get('value', 0.0) if isinstance(cmd, dict)
                   else getattr(cmd, 'value', 0.0))
            ch = self._channel_map.get(actuator_id, 0)

            # ── Lifetime protection: compare against the previous sent value ────────────────────────────────
            # Prefer the per-actuator min_dwell_sec (= min_repeat_sec) setting,
            # otherwise use the system default watchdog period.
            profile = getattr(self, '_by_id', {}).get(actuator_id)
            watchdog_sec = (
                profile.cmd_constraints.min_dwell_sec
                if (profile and profile.cmd_constraints.min_dwell_sec > 30.0)
                else self._DISPATCH_WATCHDOG_SEC
            )
            prev_sent = self._dispatch_sent.get(actuator_id)
            will_move = True   # whether THIS send represents an actual position change

            # ── Motor-driven actuator (side/roof vent): motion gate ──────────────────
            # Suppress per-cycle micro-moves via quantize, hysteresis, and minimum move interval.
            # When the gate permits a move, replace val with the grid-snapped value.
            # The motor gate is active only for opening kinds + move_step_pct > 0. If step=0,
            # skip the gate and take the normal deadband path below, sending micro-vibration as-is.
            step = (profile.cmd_constraints.move_step_pct
                    if (profile and profile.kind in self._MOTOR_KINDS) else 0.0)
            gate_active = step > 0.0
            if gate_active:
                normal_sec, emergency_sec = self._actuation_params()
                period_eff = emergency_sec if emergency else normal_sec
                min_dwell = max(period_eff, profile.cmd_constraints.min_dwell_sec)
                # Watchdog cadence must not be shorter than the actuation period, or a
                # 'gentle' (600s) setting would be silently overridden by a faster
                # default re-confirm cycle.
                gate_watchdog_sec = max(self._DISPATCH_WATCHDOG_SEC, min_dwell)

                if prev_sent is None:
                    # First send: snap to the grid to ensure consistency of later comparisons.
                    val = max(0.0, min(100.0, round(val / step) * step))
                else:
                    prev_val, prev_ts = prev_sent
                    send_age = now - prev_ts
                    moved_ts = self._dispatch_moved.get(actuator_id, prev_ts)
                    move_age = now - moved_ts
                    if send_age < gate_watchdog_sec:
                        send_q, should_move = self._motor_motion_gate(
                            val, prev_val, move_age, min_dwell, step)
                        if not should_move:
                            skipped += 1
                            continue
                        val = send_q
                        will_move = True   # should_move True => val diverges >= step from prev_val
                    else:
                        # Watchdog period reached -> force a re-confirm with the grid value for state sync.
                        # This may or may not be an actual move — check against prev_val below.
                        val = max(0.0, min(100.0, round(val / step) * step))
                        will_move = abs(val - prev_val) >= (step - 1e-6)

            if (not gate_active) and prev_sent is not None:
                prev_val, prev_ts = prev_sent
                age = now - prev_ts
                delta = abs(val - prev_val)
                if delta < self._DISPATCH_DEADBAND_PCT and age < watchdog_sec:
                    skipped += 1
                    continue  # no send needed

            try:
                # Sequential send: from the second device on, space _DISPATCH_STAGGER_SEC from the previous send.
                # (Prevents momentary load / communication collisions on simultaneous batch sends.)
                if sent > 0 and self._DISPATCH_STAGGER_SEC > 0:
                    time.sleep(self._DISPATCH_STAGGER_SEC)

                # curtain/shade: 부분 전개 시 스크린이 불균일 → 0/100 으로 스냅
                # (완전 닫힘 또는 완전 열림만 사용). 반전은 하지 않는다 — effect 모델·
                # 장치(actuator_paired, invert_direction=False) 모두 개도 규약
                # (100=열림, 0=닫힘)으로 일치하므로 코디네이터 개도를 그대로 보낸다.
                # 과거 'send_val=100-snapped' 반전은 옛 "0=최대효과" 규약 잔재였고,
                # effect 모델 규약수정 후엔 이중반전(닫기→열기)을 유발했다.
                send_val = val
                if profile and profile.kind in ('curtain', 'shade'):
                    send_val = 100.0 if val >= 50.0 else 0.0

                # Convert output_type + amount via the per-device-type adapter.
                # The adapter is dynamically selected based on the registered device type (on_off/pwm/value/vol).
                adapter = _adapters.get(actuator_id)
                if adapter is None:
                    # If unregistered, select dynamically on the fly (no hardcoded on/off fallback).
                    # In particular, controlling an actuator_paired with output_off turns both relays
                    # off to Stop, so the 0% (closed) command is ignored.
                    adapter = self._resolve_adapter(actuator_id)
                    if adapter is not None:
                        _adapters[actuator_id] = adapter
                if adapter is not None:
                    adapter.send(self.control, actuator_id, send_val, ch, cycle_sec)
                else:
                    # Last-resort fallback: value-based passthrough. Send even 0% as
                    # output_on(amount=0) so the driver handles it as a closed target (no output_off).
                    self.control.output_on(
                        actuator_id,
                        output_type='value',
                        amount=send_val,
                        output_channel=ch,
                    )
                self._dispatch_sent[actuator_id] = (val, now)
                if gate_active and will_move:
                    self._dispatch_moved[actuator_id] = now
                sent += 1
            except Exception as exc:
                failed.add(actuator_id)
                self.logger.warning(
                    'EnvCoordinator: dispatch failed actuator=%s val=%s ch=%s err=%s',
                    actuator_id, val, ch, exc)

        if skipped and getattr(self, 'debug_logging', False):
            self.logger.debug(
                'EnvCoordinator: dispatch deadband skip %d/%d actuators',
                skipped, len(commands))
        if failed:
            try:
                write_decision_log(
                    self.unique_id, 'dispatch_fail_count',
                    CH_DISPATCH_FAIL, float(len(failed)))
            except Exception:
                pass
        return failed

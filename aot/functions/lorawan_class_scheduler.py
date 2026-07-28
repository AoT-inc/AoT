# coding=utf-8
#
#  lorawan_class_scheduler.py - Per-site environment-driven LoRaWAN class scheduler.
#
#  Replaces the per-device lorawan_mode_manager. A SINGLE instance per site is the
#  only writer of class state for its devices. It decides Class C (ACTIVE - wireless
#  control on, immediate downlinks) vs Class A (REST - low power, downlink waits for
#  next uplink) from environmental data (solar radiation / soil moisture / rain), and:
#    - toggles the shared ChirpStack device profile(s) supports_class_c, and
#    - broadcasts the matching firmware CFG mode (HB period) to each device,
#  in the correct order so a transition never drops a downlink.
#  It also stores per-device telemetry (RSSI/SNR/battery) sequentially and exposes
#  the current state + a manual override to users.
#
#  Class B is intentionally NOT used (ping-slot latency is bad for valve control).
#
#  === Changes in 26.07 ===
#   [SC-1] Per-device reconcile pass every loop: compares each device's reported
#          actual class / HB period (from the firmware's ext-HB feedback) to the
#          current site target and re-enqueues CFG only for drifted devices. Fixes
#          a rebooted device (boots Class C / short HB) being stranded between
#          transitions and forever defeating the power policy. Closes the loop on
#          the actual_cls feedback the firmware sends.
#   [SC-2] Valve-open safety interlock: never sit in REST while any managed device
#          reports a non-idle valve (held open), else a STOP/CLOSE downlink waits a
#          whole HB period for an RX window. Reads the ext-HB valve bitfield.
#   [SC-3] (in _lorawan_common) fetch_device_state now also returns node_class_actual
#          and valves, consumed by SC-1 / SC-2.
#   [SC-4] ACTIVE->REST CFG enqueued confirmed=True to reduce the profile-toggle race.
#   [SC-5] Precedence changed to override > winter so emergency manual control is
#          possible even in winter (valve safety). Flip OVERRIDE_BEATS_WINTER to
#          restore winter-hard-lock if a site needs it.
#   [SC-6] Battery gate: battery_type option (lead_acid / lifepo4) sets per-type
#          thresholds. When any managed device's battery_V falls below 'low' the
#          scheduler forces REST (override still passes). Below 'critical' it forces
#          REST regardless of override. The valve-open interlock (SC-2) still beats
#          battery_critical so a held-open valve can always be closed.
#          Extended HB period (bat_low_hb_min) applied when battery is low/critical.
#   Per-tick device-state cache avoids double-fetching ChirpStack metrics across the
#   interlock / reconcile / telemetry passes.
#
# Copyright (c) 2026, AoT Project Authors. All rights reserved.

import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from flask_babel import lazy_gettext

from aot.databases.models import CustomController, Misc
from aot.functions.base_function import AbstractFunction
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb

from aot.functions._lorawan_common import (
    ChirpStackClient, MODE_A, MODE_C)

# Channels are created/removed DYNAMICALLY per managed device when devices are
# assigned on Settings -> ChirpStack (see _lorawan_common.sync_scheduler_channels):
# (3 per device: RSSI/SNR/Vbat at base = slot*3) plus a final site-state channel at
# (managed_count * 3). measurements_dict stays empty + measurements_variable_amount so
# the framework does not pre-allocate a fixed channel count. MAX_DEVICES is only a
# safety cap on how many devices one scheduler instance will manage.
MAX_DEVICES = 64

# [SC-5] When True, an active manual override forces ACTIVE (Class C) even in winter,
# so a held-open valve can always be controlled. Set False to make winter a hard
# REST lock that even override cannot break.
OVERRIDE_BEATS_WINTER = True

# [SC-2] Valve-state bits inside the ext-HB 'valves' byte. The firmware packs three
# 2-bit valve states into bits 0-5 and then reuses bit6/bit7 for GPS present/power
# (see rak3172-C-S valves encoding), and the codec forwards the byte RAW. Comparing
# the whole byte against 0 would read "GPS fitted" as "valve open" and pin the site
# to Class C forever -- the exact battery trap this scheduler exists to avoid.
VALVE_STATE_MASK = 0x3F

# [SC-6] Battery voltage thresholds per battery type.
# 'low': ACTIVE is blocked (REST forced) unless override is active.
# 'critical': REST is forced unconditionally (override cannot bypass).
BAT_THRESHOLDS = {
    'lead_acid': {'low': 11.7, 'critical': 11.4},
    'lifepo4':   {'low': 12.8, 'critical': 12.0},
}

measurements_dict = {}
channels_dict = {}


def _state_channel(managed_count: int) -> int:
    return managed_count * 3


# Environmental signal definitions (fallback scoring when no coordinator is set).
# Polarity/weight/thresholds are DECIDED by signal type and baked in — the user
# only maps each signal to a measurement.
# (option_id, label, hint, polarity, weight, enter, exit)
SIGNAL_DEFS = [
    ('meas_radiation', lazy_gettext('Solar radiation (W/m2)'),
     lazy_gettext('Light drives photosynthesis. Pick the radiation measurement (leave empty to skip).'),
     'high_active', 1.5, 150.0, 80.0),
    ('meas_soil', lazy_gettext('Soil moisture (%)'),
     lazy_gettext('Wet soil = irrigation not needed.'), 'high_rest', 1.0, 45.0, 30.0),
    ('meas_rain', lazy_gettext('Rainfall now (mm/h)'),
     lazy_gettext('Currently raining.'), 'high_rest', 1.0, 0.2, 0.05),
    ('meas_rain_accum', lazy_gettext('Rainfall accumulated (mm)'),
     lazy_gettext('Recent accumulated rain -> soil saturated.'), 'high_rest', 1.0, 10.0, 3.0),
]


def _signal_pickers():
    return [{'id': oid, 'type': 'select_measurement', 'default_value': '',
             'options_select': ['Input', 'Function'], 'name': label, 'phrase': hint}
            for oid, label, hint, _p, _w, _e, _x in SIGNAL_DEFS]


FUNCTION_INFORMATION = {
    'function_name_unique': 'lorawan_class_scheduler',
    'function_name': lazy_gettext('LoRaWAN Class Scheduler (per-site)'),
    'function_name_short': 'LoRa Class Scheduler',

    'message': lazy_gettext(
        'Single per-site authority for LoRaWAN class. Decides Class C (active/wireless '
        'control) vs Class A (rest/low-power) from environmental data, toggles the shared '
        'ChirpStack device profile(s) and broadcasts the firmware HB mode to each device, '
        'stores per-device RSSI/SNR/battery, and offers a manual override. Replaces the '
        'per-device LoRaWAN Mode Manager.'),

    # No measurement-config UI: telemetry channels are created automatically when
    # devices are assigned on Settings -> ChirpStack (sync_scheduler_channels).
    # (matches EnvCoordinator, which disables measurements_select/configure.)
    'options_enabled': ['custom_options', 'function_status'],
    'options_disabled': ['measurements_select', 'measurements_configure'],

    'custom_commands': [
        {'type': 'message',
         'default_value': '<b>{}</b>'.format(lazy_gettext('Manual override'))},
        {'id': 'force_active_value', 'type': 'integer', 'default_value': 0,
         'name': lazy_gettext('Force-Active minutes (0 = until expire time)')},
        {'id': 'force_active_now', 'type': 'button', 'wait_for_return': True,
         'name': lazy_gettext('Force Active (Class C) now')},
        {'id': 'clear_override', 'type': 'button', 'wait_for_return': True,
         'name': lazy_gettext('Clear override')},
    ],

    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,

    'custom_options': [
        # These two render under the framework "Advanced Settings" (with Log Level Debug).
        {'id': 'update_period', 'type': 'text', 'class': 'aot-time-input',
         'default_value': 600, 'required': True,
         'constraints_pass': constraints_pass_positive_value,
         'name': "{} ({})".format(lazy_gettext('Evaluation period'), lazy_gettext('Seconds'))},
        {'id': 'measurement_max_age', 'type': 'text', 'class': 'aot-time-input',
         'default_value': 4000, 'name': lazy_gettext('Input max age (s)')},

        {'type': 'header', 'name': lazy_gettext('ChirpStack')},
        {'id': 'cs_rest_port', 'type': 'integer', 'default_value': 8090, 'required': True,
         'name': lazy_gettext('REST Port'),
         'phrase': lazy_gettext('Server/token from Settings -> ChirpStack; devices assigned there ("Managed by").')},

        {'type': 'header', 'name': lazy_gettext('Control Mode')},
        {'id': 'control_mode', 'type': 'select', 'default_value': 'AUTO',
         'options_select': [('AUTO', lazy_gettext('AUTO - environment scoring')),
                            ('MANUAL', lazy_gettext('MANUAL - fixed daily C window'))],
         'name': lazy_gettext('Control mode')},
        {'id': 'manual_c_start', 'type': 'text', 'default_value': '05:00',
         'name': lazy_gettext('Manual C start (HH:MM)')},
        {'id': 'manual_c_expire', 'type': 'text', 'default_value': '17:00',
         'name': lazy_gettext('Manual C expire (HH:MM)')},

        {'type': 'header', 'name': lazy_gettext('Environmental Inputs (AUTO fallback)')},
        # Only the measurement is user-chosen; polarity/weight/thresholds are decided.
        *_signal_pickers(),

        {'type': 'header', 'name': lazy_gettext('Decision')},
        {'id': 'score_enter_active', 'type': 'float', 'default_value': 0.55,
         'name': lazy_gettext('Score >= -> ACTIVE')},
        {'id': 'score_exit_active', 'type': 'float', 'default_value': 0.40,
         'name': lazy_gettext('Score < -> REST')},
        {'id': 'min_dwell_min', 'type': 'integer', 'default_value': 15,
         'name': lazy_gettext('Minimum dwell (min)')},

        {'type': 'header', 'name': lazy_gettext('Class / HB Periods')},
        {'id': 'active_c_period_min', 'type': 'integer', 'default_value': 10,
         'name': lazy_gettext('ACTIVE Class C HB (min)')},
        {'id': 'rest_a_period_min', 'type': 'integer', 'default_value': 30,
         'name': lazy_gettext('REST Class A HB (min)')},
        {'id': 'winter_a_period_min', 'type': 'integer', 'default_value': 60,
         'name': lazy_gettext('Winter Class A HB (min)')},

        {'type': 'header', 'name': lazy_gettext('Winter (forced REST)')},
        {'id': 'winter_start', 'type': 'text', 'default_value': '12-01',
         'name': lazy_gettext('Winter start (MM-DD)')},
        {'id': 'winter_end', 'type': 'text', 'default_value': '02-28',
         'name': lazy_gettext('Winter end (MM-DD)')},

        # [SC-6] Battery gate
        {'type': 'header', 'name': lazy_gettext('Battery Management')},
        {'id': 'battery_type',
         'type': 'select',
         'default_value': 'none',
         'options_select': [
             ('none',      lazy_gettext('Not configured (no battery gate)')),
             ('lead_acid', lazy_gettext('Lead-acid  (low < 11.7 V / critical < 11.4 V)')),
             ('lifepo4',   lazy_gettext('LiFePO4    (low < 12.8 V / critical < 12.0 V)')),
         ],
         'name': lazy_gettext('Battery Type'),
         'phrase': lazy_gettext(
             'Reads battery_V from ChirpStack metrics (requires INA219 wired). '
             'Low: forces REST unless manual override is active. '
             'Critical: forces REST unconditionally; valve-open interlock still applies.'
         )},
        {'id': 'bat_low_hb_min', 'type': 'integer', 'default_value': 60,
         'name': lazy_gettext('Low-battery HB (min)'),
         'phrase': lazy_gettext(
             'Heartbeat period (minutes) applied when battery is low or critical. '
             'Should be >= REST HB to maximise sleep time.'
         )},
    ],
}


class CustomModule(AbstractFunction):
    """Per-site LoRaWAN class scheduler."""

    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)

        self.timer_loop = 0.0
        self._last_seen = {}  # dev_eui -> last stored lastSeenAt (telemetry dedup)
        self._state_cache = {}  # per-loop dev_eui -> fetch_device_state result (avoids double fetch)

        # custom option attributes (populated by setup_custom_options)
        self.update_period = None
        self.cs_rest_port = None
        self.measurement_max_age = None
        self.control_mode = None
        self.manual_c_start = None
        self.manual_c_expire = None
        self.score_enter_active = None
        self.score_exit_active = None
        self.min_dwell_min = None
        self.active_c_period_min = None
        self.rest_a_period_min = None
        self.winter_a_period_min = None
        self.winter_start = None
        self.winter_end = None
        self.battery_type = None
        self.bat_low_hb_min = None

        if not testing:
            custom_function = db_retrieve_table_daemon(
                CustomController, unique_id=self.unique_id)
            self.setup_custom_options(
                FUNCTION_INFORMATION['custom_options'], custom_function)
            self.try_initialize()

    def initialize(self):
        self.logger.info("LoRaWAN class scheduler started")

    # ------------------------------------------------------------------ client
    def _conn(self):
        """Read ChirpStack server/token from the global Settings (Misc), daemon-safe."""
        m = db_retrieve_table_daemon(Misc, entry='first')
        server = (getattr(m, 'chirpstack_grpc_server', '') or '') if m else ''
        token = (getattr(m, 'chirpstack_api_token', '') or '') if m else ''
        return server, token

    def _client(self) -> ChirpStackClient:
        server, token = self._conn()
        return ChirpStackClient(server, token,
                                rest_port=self._int('cs_rest_port', 8090),
                                logger=self.logger)

    # -------------------------------------------------------------- device set
    def _persisted_devices(self) -> List[Tuple[str, int, Optional[str]]]:
        """Load [(dev_eui, slot, profile_id)] persisted by the Fetch button."""
        raw = self.get_custom_option('device_slot_map', None)
        if not raw:
            return []
        try:
            m = json.loads(raw)
            return [(eui, int(v[0]), v[1]) for eui, v in m.items()]
        except Exception:
            return []

    def _compute_owned_profiles(self, devices):
        """A profile may be class-toggled only if EVERY device on it (across the
        whole server) is managed by this scheduler. Computed each loop from the
        live device list so it stays correct as assignments change."""
        managed = {d[0] for d in devices}
        managed_pids = {d[2] for d in devices if d[2]}
        if not managed_pids:
            return []
        server, token = self._conn()
        try:
            from aot.aot_flask.utils.utils_chirpstack import list_chirpstack_devices
            full, err = list_chirpstack_devices(server, token, limit=500)
        except Exception:
            full, err = None, 'unavailable'
        if err or not full:
            return []  # cannot verify ownership -> do not toggle any profile
        client = self._client()
        prof_all = {}
        for d in full:
            eui = normalize(d.get('dev_eui'))
            if not eui:
                continue
            pid = client.get_profile_id(eui)
            if pid in managed_pids:
                prof_all.setdefault(pid, set()).add(eui)
        return [pid for pid in managed_pids
                if prof_all.get(pid, set()).issubset(managed)]

    # --------------------------------------------------------------- override
    def force_active_now(self, args_dict):
        minutes = 0
        try:
            minutes = int(args_dict.get('force_active_value', 0) or 0)
        except Exception:
            minutes = 0
        if minutes > 0:
            until = time.time() + minutes * 60
        else:
            until = self._today_time_epoch(getattr(self, 'manual_c_expire', '17:00'))
        self.set_custom_option('override_until', str(until))
        return "Override active (Class C) until {}".format(
            datetime.fromtimestamp(until).strftime('%Y-%m-%d %H:%M'))

    def clear_override(self, args_dict):
        self.set_custom_option('override_until', '0')
        return "Override cleared."

    # ------------------------------------------------------------- time utils
    @staticmethod
    def _parse_hhmm(s, default_h, default_m):
        try:
            hh, mm = str(s).strip().split(':')
            return int(hh), int(mm)
        except Exception:
            return default_h, default_m

    def _today_time_epoch(self, hhmm):
        h, m = self._parse_hhmm(hhmm, 17, 0)
        now = datetime.now()
        return now.replace(hour=h, minute=m, second=0, microsecond=0).timestamp()

    def _in_manual_window(self, now: datetime) -> bool:
        sh, sm = self._parse_hhmm(getattr(self, 'manual_c_start', '05:00'), 5, 0)
        eh, em = self._parse_hhmm(getattr(self, 'manual_c_expire', '17:00'), 17, 0)
        cur = now.hour * 60 + now.minute
        return (sh * 60 + sm) <= cur < (eh * 60 + em)

    def _is_winter(self, now: datetime) -> bool:
        def md(s, dM, dD):
            try:
                mm, dd = str(s).strip().split('-')
                return int(mm), int(dd)
            except Exception:
                return dM, dD
        sm, sd = md(getattr(self, 'winter_start', '12-01'), 12, 1)
        em, ed = md(getattr(self, 'winter_end', '02-28'), 2, 28)
        cur = (now.month, now.day)
        start, end = (sm, sd), (em, ed)
        if start <= end:
            return start <= cur <= end
        return cur >= start or cur <= end  # wrap across new year

    # --------------------------------------------------------------- scoring
    def _read_env_slots(self):
        """Read configured signals; polarity/weight/thresholds come from SIGNAL_DEFS
        (decided), only the measurement mapping is user-supplied."""
        slots = []
        max_age = self._int('measurement_max_age', 4000)
        for oid, label, _hint, pol, w, enter, exit_ in SIGNAL_DEFS:
            dev_id = getattr(self, oid + '_device_id', None)
            meas_id = getattr(self, oid + '_measurement_id', None)
            if not dev_id or not meas_id:
                continue
            try:
                last = self.get_last_measurement(dev_id, meas_id, max_age=max_age)
            except Exception:
                last = None
            if not last or last[1] is None:
                continue
            slots.append({'value': float(last[1]), 'enter': enter, 'exit': exit_,
                          'polarity': pol, 'weight': w, 'idx': oid.replace('meas_', '')})
        return slots

    @staticmethod
    def _slot_vote(slot) -> float:
        """Per-slot vote for ACTIVE in [0,1], hysteresis-aware via enter/exit."""
        v, enter, exit_ = slot['value'], slot['enter'], slot['exit']
        lo, hi = min(enter, exit_), max(enter, exit_)
        if hi == lo:
            base = 1.0 if v >= hi else 0.0
        else:
            base = (v - lo) / (hi - lo)
            base = max(0.0, min(1.0, base))
        # base = "how high is the value" in [0,1]; for high_active high->active,
        # for high_rest high->rest (invert).
        if slot['polarity'] == 'high_rest':
            return 1.0 - base
        return base

    def _compute_decision(self, slots, current_state):
        """Return (desired_state, score, judged_str)."""
        if not slots:
            return None, None, "no env inputs"
        num = sum(s['weight'] * self._slot_vote(s) for s in slots)
        den = sum(s['weight'] for s in slots) or 1.0
        score = num / den
        enter = self._float('score_enter_active', 0.55)
        exit_ = self._float('score_exit_active', 0.40)
        if current_state == 'ACTIVE':
            desired = 'ACTIVE' if score >= exit_ else 'REST'
        else:
            desired = 'ACTIVE' if score >= enter else 'REST'
        judged = " ".join("{}={:.1f}".format(s['idx'], s['value']) for s in slots)
        return desired, score, judged

    # ----------------------------------------------------------------- helpers
    def _int(self, attr, default):
        try:
            return int(getattr(self, attr, default) or default)
        except Exception:
            return default

    def _float(self, attr, default):
        try:
            return float(getattr(self, attr, default))
        except Exception:
            return default

    # -------------------------------------------------------------------- loop
    def loop(self):
        now_ts = time.time()
        period = float(self._int('update_period', 600))
        if now_ts < self.timer_loop:
            return
        self.timer_loop = now_ts + period

        devices = self._persisted_devices()
        if not devices:
            self.logger.warning(
                "No devices assigned - assign devices on Settings -> ChirpStack.")
            return
        now = datetime.now()
        self._state_cache = {}  # fresh per-tick cache (interlock/reconcile/telemetry share it)

        # --- decide target state (precedence: override > winter > MANUAL > AUTO) ---
        # [SC-5] override now beats winter so emergency manual control is possible in
        # winter; set OVERRIDE_BEATS_WINTER=False to restore a winter hard-lock.
        prev_state = self.get_custom_option('sched_state', 'REST')
        winter = self._is_winter(now)
        try:
            override_until = float(self.get_custom_option('override_until', '0') or 0)
        except Exception:
            override_until = 0.0
        override = override_until > now_ts

        score = None
        bypass_dwell = False
        if override and (OVERRIDE_BEATS_WINTER or not winter):
            desired, reason = 'ACTIVE', 'manual_override'
            bypass_dwell = True
        elif winter:
            desired, reason = 'REST', 'winter'
            bypass_dwell = True
        elif str(self.control_mode) == 'MANUAL':
            desired = 'ACTIVE' if self._in_manual_window(now) else 'REST'
            reason = 'manual_window'
        else:
            slots = self._read_env_slots()
            d, score, judged = self._compute_decision(slots, prev_state)
            if d is None:  # no inputs -> fall back to manual window
                desired = 'ACTIVE' if self._in_manual_window(now) else 'REST'
                reason = 'auto_no_inputs_fallback'
            else:
                desired = d
                reason = 'auto:{}'.format(judged)

        # [SC-6] Battery gate (applied before valve interlock).
        # critical: force REST unconditionally (override cannot bypass).
        # low:      force REST unless a manual override is active.
        # Valve-open interlock below still beats battery_critical for safety.
        bat_status, bat_v = self._battery_status(devices)
        bat_low_hb = self._int('bat_low_hb_min', 60)
        if bat_status == 'critical':
            desired = 'REST'
            reason = reason + '+bat_critical({:.2f}V)'.format(bat_v)
            bypass_dwell = True
        elif bat_status == 'low' and desired == 'ACTIVE' and not override:
            desired = 'REST'
            reason = reason + '+bat_low({:.2f}V)'.format(bat_v)
        self.set_custom_option('last_bat_status', bat_status)
        self.set_custom_option('last_bat_v', '-' if bat_v is None else '{:.2f}'.format(bat_v))

        # [SC-2] Valve-open safety interlock: never sit in REST while any managed
        # valve is non-idle (held open), otherwise a STOP/CLOSE downlink waits a full
        # HB period for an RX window. This also overrides winter for safety.
        if desired == 'REST' and self._any_valve_open(devices):
            desired = 'ACTIVE'
            reason = reason + '+valve_open_hold'
            bypass_dwell = True

        # --- HB period per state ---
        if desired == 'ACTIVE':
            mode, hb = MODE_C, self._int('active_c_period_min', 10)
        elif winter:
            mode, hb = MODE_A, self._int('winter_a_period_min', 60)
        else:
            mode, hb = MODE_A, self._int('rest_a_period_min', 30)
        # [SC-6] Extend HB when battery is low or critical
        if bat_status in ('low', 'critical'):
            hb = max(hb, bat_low_hb)

        # --- apply transition if state changed and dwell satisfied ---
        try:
            last_tr = float(self.get_custom_option('sched_last_transition_ts', '0') or 0)
        except Exception:
            last_tr = 0.0
        dwell_ok = (now_ts - last_tr) >= self._int('min_dwell_min', 15) * 60
        if desired != prev_state and (bypass_dwell or dwell_ok):
            owned = self._compute_owned_profiles(devices)  # only when transitioning
            self._apply_transition(desired, mode, hb, devices, owned)
            self.set_custom_option('sched_state', desired)
            self.set_custom_option('sched_last_transition_ts', str(now_ts))
            self.logger.info("class transition {} -> {} (mode={} hb={} reason={})".format(
                prev_state, desired, mode, hb, reason))
            cur_state = desired
        else:
            cur_state = prev_state

        # [SC-1] Per-device reconcile to the current site target (self-heals reboots,
        # closes the loop on the firmware's actual-class feedback). Runs every loop,
        # independent of transitions; rate-limited per device.
        self._reconcile_devices(devices, mode, hb)

        # --- sequential per-device telemetry ---
        self._store_all_telemetry(devices)

        # --- site state channel + status fields ---
        self._write_state_channel(cur_state == 'ACTIVE', _state_channel(len(devices)))
        self.set_custom_option('last_reason', reason)
        self.set_custom_option('last_score', '-' if score is None else "{:.2f}".format(score))
        self.set_custom_option('winter_active', '1' if winter else '0')

    # -------------------------------------------------------------- transition
    def _apply_transition(self, desired, mode, hb, devices, owned):
        client = self._client()
        euis = [d[0] for d in devices]
        if desired == 'ACTIVE':
            # profile C ON first, then tell each device to go C
            for pid in owned:
                client.set_profile_supports_class_c(pid, True)
            for eui in euis:
                client.enqueue_cfg(eui, mode, hb)
        else:
            # tell each device to go A first (still C, they receive it), then C OFF.
            # [SC-4] confirmed=True so ChirpStack retries until the device acks,
            # narrowing the window where the profile loses Class C before the device
            # has actually adopted Class A.
            for eui in euis:
                client.enqueue_cfg(eui, mode, hb, confirmed=True)
            for pid in owned:
                client.set_profile_supports_class_c(pid, False)

    # -------------------------------------------------------- state cache / reads
    def _dev_state(self, client, eui, max_age):
        """fetch_device_state with a per-loop cache so the interlock, reconcile and
        telemetry passes share a single set of ChirpStack reads per device."""
        st = self._state_cache.get(eui)
        if st is None:
            st = client.fetch_device_state(eui, max_age=max_age)
            self._state_cache[eui] = st
        return st

    def _any_valve_open(self, devices):
        """[SC-2] True if any managed device reports a non-idle valve (ext-HB valve
        bitfield != 0). Short-circuits on the first open valve.

        A device with no valve reading cannot be judged, so it is skipped rather
        than counted as open: treating a telemetry gap as "valve open" would pin the
        site to Class C indefinitely and drain the battery. That fail-open choice is
        only defensible while the gap is visible, so a pass where NO managed device
        yielded a reading is logged as a warning -- it means the interlock is
        inoperative, not that every valve is idle. (This is exactly how SC-2 sat
        silently dead: fetch_device_state() did not return 'valves' at all.)
        """
        client = self._client()
        max_age = self._int('measurement_max_age', 4000)
        saw_reading = False
        for eui, _slot, _pid in devices:
            try:
                st = self._dev_state(client, eui, max_age)
            except Exception:
                continue
            valves = st.get('valves')
            if valves is None:
                continue
            saw_reading = True
            open_bits = int(valves) & VALVE_STATE_MASK
            if open_bits != 0:
                self.logger.debug("valve-open hold: {} valves=0x{:02X}".format(
                    eui, int(valves)))
                return True
        if saw_reading:
            self._sc2_blind_warned = False
        elif devices and not getattr(self, '_sc2_blind_warned', False):
            self.logger.warning(
                "[SC-2] valve interlock inoperative: no managed device reported a "
                "'valves' measurement. Verify the ext-HB codec field is declared as "
                "a device-profile measurement in ChirpStack. REST transitions are "
                "NOT protected against a held-open valve until this is resolved.")
            self._sc2_blind_warned = True
        return False

    def _battery_status(self, devices):
        """[SC-6] Return (status, min_v) across all managed devices.
        status: 'ok' | 'low' | 'critical' | 'unknown' | 'disabled'
        Uses the per-loop state cache. Invalid sentinel values (INA219 absent) are skipped.
        """
        bat_type = str(getattr(self, 'battery_type', 'none') or 'none')
        if bat_type == 'none':
            return 'disabled', None
        thresholds = BAT_THRESHOLDS.get(bat_type)
        if not thresholds:
            return 'disabled', None

        client = self._client()
        max_age = self._int('measurement_max_age', 4000)
        min_v = None
        for eui, _slot, _pid in devices:
            try:
                st = self._dev_state(client, eui, max_age)
            except Exception:
                continue
            v = st.get('battery_V')
            if v is None or not (0.5 <= v <= 60.0):
                continue
            if min_v is None or v < min_v:
                min_v = v

        if min_v is None:
            return 'unknown', None
        if min_v < thresholds['critical']:
            return 'critical', min_v
        if min_v < thresholds['low']:
            return 'low', min_v
        return 'ok', min_v

    def _reconcile_devices(self, devices, mode, hb):
        """[SC-1] Per-device self-heal. If a device's reported actual class / HB period
        does not match the current site target, re-enqueue its CFG. Fixes a rebooted
        device (firmware boots Class C / short HB) that would otherwise never be
        corrected between transitions. Uses the firmware's actual-class feedback;
        rate-limited per device to one resend per dwell window."""
        client = self._client()
        max_age = self._int('measurement_max_age', 4000)
        want_class = 3 if mode == MODE_C else 1  # 1=A, 3=C
        dwell_s = self._int('min_dwell_min', 15) * 60
        now_ts = time.time()
        for eui, _slot, _pid in devices:
            try:
                st = self._dev_state(client, eui, max_age)
            except Exception:
                continue
            actual = st.get('node_class_actual')
            if actual is None:
                actual = st.get('node_class')
            cur_hb = st.get('node_hb_min')
            if actual is None:
                continue  # no fresh ext-HB reading yet -> nothing to compare
            if actual == want_class and (cur_hb is None or cur_hb == hb):
                continue  # already in sync
            key = 'reconc_' + eui
            try:
                last = float(self.get_custom_option(key, '0') or 0)
            except Exception:
                last = 0.0
            if now_ts - last < dwell_s:
                continue  # rate-limit: at most one resend per dwell window
            if client.enqueue_cfg(eui, mode, hb):
                self.set_custom_option(key, str(now_ts))
                self.logger.info(
                    "reconcile {}: actual={}/{}min -> resend mode={} hb={}".format(
                        eui, actual, cur_hb, mode, hb))

    # --------------------------------------------------------------- telemetry
    def _store_all_telemetry(self, devices):
        client = self._client()
        max_age = self._int('measurement_max_age', 4000)
        for eui, slot, _pid in devices:  # strictly sequential
            try:
                st = self._dev_state(client, eui, max_age)
            except Exception as e:
                self.logger.debug("fetch_device_state {} failed: {}".format(eui, e))
                continue
            last_seen = st.get('last_seen_at')
            if last_seen is not None and self._last_seen.get(eui) == last_seen:
                continue  # no new uplink -> skip (dedup)
            ts_utc = None
            if last_seen:
                try:
                    ts_utc = datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
                except Exception:
                    ts_utc = None
            base = slot * 3
            meas = {}
            if st.get('rssi') is not None:
                meas[base + 0] = {'measurement': 'rssi', 'unit': 'dBm',
                                  'value': float(st['rssi'])}
            if st.get('snr') is not None:
                meas[base + 1] = {'measurement': 'snr', 'unit': 'dB',
                                  'value': float(st['snr'])}
            if st.get('battery_V') is not None:
                meas[base + 2] = {'measurement': 'electrical_potential', 'unit': 'mV',
                                  'value': float(st['battery_V']) * 1000.0}
            if not meas:
                continue
            if ts_utc is not None:
                for m in meas.values():
                    m['timestamp_utc'] = ts_utc
            try:
                add_measurements_influxdb(self.unique_id, meas,
                                          use_same_timestamp=(ts_utc is None))
                self._last_seen[eui] = last_seen
            except Exception as e:
                self.logger.debug("store telemetry {} failed: {}".format(eui, e))

    def _write_state_channel(self, active: bool, state_ch: int):
        try:
            add_measurements_influxdb(self.unique_id, {
                state_ch: {'measurement': 'unitless', 'unit': 'none',
                           'value': 1.0 if active else 0.0}},
                use_same_timestamp=True)
        except Exception as e:
            self.logger.debug("state channel write failed: {}".format(e))

    # ----------------------------------------------------------------- status
    def function_status(self):
        g = self.get_custom_option
        state = g('sched_state', 'REST')
        wireless_on = (state == 'ACTIVE')
        winter = g('winter_active', '0') == '1'
        try:
            override = float(g('override_until', '0') or 0) > time.time()
        except Exception:
            override = False
        if wireless_on:
            cls = 'Class C (active / 일반)'
        elif winter:
            cls = 'Class A (winter / 초절전)'
        else:
            cls = 'Class A (rest / 절전)'
        devs = self._persisted_devices()
        flags = ''
        if override:
            flags += ' [OVERRIDE]'
        if winter:
            flags += ' [WINTER]'
        last_tr = g('sched_last_transition_ts', '0')
        try:
            last_tr_s = datetime.fromtimestamp(float(last_tr)).strftime('%Y-%m-%d %H:%M') \
                if float(last_tr) else '-'
        except Exception:
            last_tr_s = '-'
        bat_status = g('last_bat_status', 'disabled')
        bat_v = g('last_bat_v', '-')
        bat_type = str(getattr(self, 'battery_type', 'none') or 'none')
        if bat_type == 'none':
            bat_line = "Battery: not configured"
        else:
            thr = BAT_THRESHOLDS.get(bat_type, {})
            bat_line = "Battery: {} {} V  [type={} low<{}V crit<{}V]".format(
                bat_status.upper(), bat_v, bat_type,
                thr.get('low', '-'), thr.get('critical', '-'))
        lines = [
            "Wireless control: {}".format('ON' if wireless_on else 'OFF'),
            "Current class: {}".format(cls),
            "Control mode: {}{}".format(self.control_mode, flags),
            "Decision reason: {}".format(g('last_reason', '-')),
            "Score: {} (enter>={} / exit<{})".format(
                g('last_score', '-'),
                getattr(self, 'score_enter_active', '-'),
                getattr(self, 'score_exit_active', '-')),
            bat_line,
            "Managed devices: {}".format(len(devs)),
            "Last transition: {}".format(last_tr_s),
        ]
        return {'string_status': "\n".join(lines), 'error': []}


def normalize(e):
    return ''.join(ch for ch in (e or '') if ch.isalnum()).lower()

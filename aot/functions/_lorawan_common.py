# coding=utf-8
#
#  _lorawan_common.py — shared, device-EUI-parameterized ChirpStack helpers.
#
#  Extracted/refactored from lorawan_mode_manager.py so a single per-site
#  scheduler (lorawan_class_scheduler.py) can manage MANY devices. Unlike the
#  original single-device methods (bound to self.dev_eui), every call here takes
#  an explicit dev_eui / profile_id.
#
#  REST-only: all operations use the ChirpStack v4 REST API (default port 8090),
#  which avoids the optional grpcio/chirpstack-api dependency. The endpoints used
#  here were verified against the live server during development:
#    GET  /api/devices?limit&applicationId
#    GET  /api/devices/{eui}
#    GET  /api/devices/{eui}/metrics
#    GET  /api/devices/{eui}/link-metrics
#    GET  /api/device-profiles/{id}
#    PUT  /api/device-profiles/{id}
#    POST /api/devices/{eui}/queue
#
# Copyright (c) 2026, AoT Project Authors. All rights reserved.

import base64
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests

# ----- Policy mode codes (firmware CFG byte) -----
MODE_A = 1  # Ultra/low-power policy state  (LoRa Class A)
MODE_B = 2  # Power-saving policy state      (LoRa Class B — unused by scheduler)
MODE_C = 3  # Performance policy state       (LoRa Class C)

FPORT_CFG = 14  # mode/period config downlink port: [0xD0, mode, hb_min]

_NULL_LOGGER = logging.getLogger("aot.functions._lorawan_common")


def normalize_server(srv: str) -> str:
    """Strip scheme/path, return bare host[:port]."""
    srv = (srv or '').strip()
    if '://' in srv:
        srv = srv.split('://', 1)[1]
    return srv.split('/', 1)[0]


def normalize_token(tok: str) -> str:
    tok = (tok or '').strip()
    if tok.lower().startswith('bearer '):
        tok = tok[7:].strip()
    return tok


def normalize_deveui(dev: str) -> str:
    dev = (dev or '').strip()
    return ''.join(ch for ch in dev if ch.isalnum()).lower()


def build_mode_downlink(mode: int, period_min: int) -> Tuple[int, bytes, str]:
    """Serialize policy mode into a firmware CFG frame.

    FPort 14 format: [0xD0, mode(1=A,2=B,3=C), hb_min]. The firmware sets its own
    LoRa class from the mode byte; ChirpStack profile supports_class_c gates the
    downlink delivery timing independently (handled by the scheduler).
    """
    try:
        hb = int(period_min)
    except Exception:
        hb = 30
    if hb <= 0:
        hb = 30
    hb = max(1, min(255, hb))
    payload = bytes([0xD0, mode & 0xFF, hb & 0xFF])
    return FPORT_CFG, payload, f"mode={mode}, hb={hb}"


SCHEDULER_DEVICE = 'lorawan_class_scheduler'  # CustomController.device value


# --- scheduler device-assignment + channel sync (shared by Flask UI + daemon) ---
def load_slot_map(scheduler_uid):
    """Return {dev_eui: [slot, profile_id]} for a scheduler instance."""
    import json
    from aot.utils.database import db_retrieve_table_daemon
    from aot.databases.models import CustomController
    cc = db_retrieve_table_daemon(CustomController, unique_id=scheduler_uid)
    if not cc:
        return {}
    try:
        raw = json.loads(cc.custom_options or '{}').get('device_slot_map')
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _save_slot_map(scheduler_uid, slot_map):
    import json
    from aot.config import AOT_DB_PATH
    from aot.databases.utils import session_scope
    from aot.databases.models import CustomController
    with session_scope(AOT_DB_PATH) as s:
        cc = s.query(CustomController).filter(
            CustomController.unique_id == scheduler_uid).first()
        if not cc:
            return
        try:
            opts = json.loads(cc.custom_options or '{}')
        except Exception:
            opts = {}
        opts['device_slot_map'] = json.dumps(slot_map)
        cc.custom_options = json.dumps(opts)
        s.commit()


def sync_scheduler_channels(scheduler_uid, slot_map):
    """Create/update/remove the scheduler's measurement channels to match its
    managed devices exactly: 3 per device (RSSI/SNR/Vbat at base=slot*3) + 1 site
    state channel. Channels follow the device count dynamically."""
    from aot.config import AOT_DB_PATH
    from aot.databases.utils import session_scope
    from aot.databases.models import DeviceMeasurements
    needed = {}
    for eui, v in slot_map.items():
        b = int(v[0]) * 3
        sfx = eui[-4:]
        needed[b + 0] = ('rssi', 'dBm', sfx + ' RSSI')
        needed[b + 1] = ('snr', 'dB', sfx + ' SNR')
        needed[b + 2] = ('electrical_potential', 'mV', sfx + ' Vbat')
    needed[len(slot_map) * 3] = ('unitless', 'none', 'wireless_on')
    with session_scope(AOT_DB_PATH) as s:
        rows = s.query(DeviceMeasurements).filter(
            DeviceMeasurements.device_id == scheduler_uid).all()
        by_ch = {r.channel: r for r in rows}
        for ch, (meas, unit, name) in needed.items():
            r = by_ch.get(ch)
            if r is None:
                r = DeviceMeasurements()
                r.device_id = scheduler_uid
                r.channel = ch
                s.add(r)
            r.measurement = meas
            r.unit = unit
            r.name = name
            r.is_enabled = True
        for ch, r in by_ch.items():
            if ch not in needed:
                s.delete(r)
        s.commit()
    return len(needed)


def assign_device_to_scheduler(scheduler_uid, dev_eui, profile_id=None, assign=True):
    """Add/remove a device to/from a scheduler, recompact slots 0..n-1, and
    re-sync the scheduler's channels. Returns the new slot_map."""
    eui = normalize_deveui(dev_eui)
    sm = load_slot_map(scheduler_uid)
    if assign:
        if eui not in sm:
            sm[eui] = [9999, profile_id]  # temp high slot -> sorted last on recompact
        elif profile_id:
            sm[eui][1] = profile_id
    else:
        sm.pop(eui, None)
    ordered = sorted(sm.items(),
                     key=lambda kv: (kv[1][0] if isinstance(kv[1], list) else 0, kv[0]))
    sm = {e: [i, (v[1] if isinstance(v, list) else None)]
          for i, (e, v) in enumerate(ordered)}
    _save_slot_map(scheduler_uid, sm)
    sync_scheduler_channels(scheduler_uid, sm)
    return sm


def list_schedulers():
    """Return [(unique_id, name)] of all lorawan_class_scheduler instances."""
    import json
    from aot.config import AOT_DB_PATH
    from aot.databases.utils import session_scope
    from aot.databases.models import CustomController
    out = []
    with session_scope(AOT_DB_PATH) as s:
        for cc in s.query(CustomController).filter(
                CustomController.device == SCHEDULER_DEVICE).all():
            out.append((cc.unique_id, cc.name))
    return out


def scheduler_of_device(dev_eui):
    """Return the scheduler unique_id currently managing dev_eui, or None."""
    eui = normalize_deveui(dev_eui)
    for uid, _name in list_schedulers():
        if eui in load_slot_map(uid):
            return uid
    return None


class ChirpStackClient:
    """REST client for ChirpStack v4, parameterized per device/profile.

    One instance per scheduler. Methods take explicit dev_eui / profile_id so a
    single owner can manage an arbitrary set of devices spanning >1 profile.
    """

    def __init__(self, server: str, token: str, rest_port: int = 8090,
                 logger: Optional[logging.Logger] = None):
        self.host = normalize_server(server).split(':')[0]
        self.token = normalize_token(token)
        try:
            self.rest_port = int(rest_port or 8090)
        except Exception:
            self.rest_port = 8090
        self.logger = logger or _NULL_LOGGER

    # --- low level ---------------------------------------------------------
    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.rest_port}"

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def ok(self) -> bool:
        return bool(self.host and self.token)

    def _get(self, path: str, params: Optional[dict] = None, timeout: int = 5):
        return requests.get(f"{self.base_url}{path}", headers=self._headers,
                            params=params, timeout=timeout)

    # --- device listing (for user selection / discovery) -------------------
    def list_devices(self, application_id: str = '', limit: int = 100) -> List[Dict]:
        """Return [{dev_eui, name, device_profile_id, ...}] for an application.

        Resolves each device's deviceProfileId via a per-device GET (the list
        endpoint omits it), so the scheduler can group devices by profile.
        """
        out: List[Dict] = []
        try:
            params = {'limit': limit}
            if application_id:
                params['applicationId'] = application_id
            r = self._get("/api/devices", params=params)
            if r.status_code != 200:
                self.logger.warning(f"list_devices HTTP {r.status_code}")
                return out
            for d in (r.json().get('result') or []):
                eui = (d.get('devEui') or '').lower()
                if not eui:
                    continue
                out.append({
                    'dev_eui': eui,
                    'name': d.get('name') or eui,
                    'device_profile_id': self.get_profile_id(eui),
                })
        except Exception as e:
            self.logger.warning(f"list_devices failed: {e}")
        return out

    def get_profile_id(self, dev_eui: str) -> Optional[str]:
        try:
            r = self._get(f"/api/devices/{normalize_deveui(dev_eui)}")
            if r.status_code == 200:
                return r.json().get('device', {}).get('deviceProfileId')
        except Exception as e:
            self.logger.debug(f"get_profile_id({dev_eui}) failed: {e}")
        return None

    def list_profile_device_euis(self, application_id: str, profile_id: str,
                                 limit: int = 200) -> List[str]:
        """All dev_euis in the application that use profile_id (for ownership guard)."""
        euis: List[str] = []
        try:
            r = self._get("/api/devices",
                          params={'limit': limit, 'applicationId': application_id})
            if r.status_code == 200:
                for d in (r.json().get('result') or []):
                    eui = (d.get('devEui') or '').lower()
                    if eui and self.get_profile_id(eui) == profile_id:
                        euis.append(eui)
        except Exception as e:
            self.logger.debug(f"list_profile_device_euis failed: {e}")
        return euis

    # --- device profile class flag ----------------------------------------
    def get_profile_supports_class_c(self, profile_id: str) -> Optional[bool]:
        try:
            r = self._get(f"/api/device-profiles/{profile_id}")
            if r.status_code == 200:
                return bool(r.json().get('deviceProfile', {}).get('supportsClassC'))
        except Exception as e:
            self.logger.debug(f"get supportsClassC failed: {e}")
        return None

    def set_profile_supports_class_c(self, profile_id: str, want_c: bool) -> bool:
        """Set supports_class_c on a profile. Returns True if changed/ok."""
        try:
            r = self._get(f"/api/device-profiles/{profile_id}")
            if r.status_code != 200:
                self.logger.warning(f"profile get HTTP {r.status_code}")
                return False
            body = r.json()
            dp = body.get('deviceProfile', {})
            if bool(dp.get('supportsClassC')) == bool(want_c):
                return True  # already at target
            dp['supportsClassC'] = bool(want_c)
            pr = requests.put(f"{self.base_url}/api/device-profiles/{profile_id}",
                              headers={**self._headers, 'Content-Type': 'application/json'},
                              json=body, timeout=10)
            if pr.status_code == 200:
                self.logger.info(
                    f"profile {profile_id} supportsClassC -> {want_c}")
                return True
            self.logger.warning(f"profile PUT HTTP {pr.status_code}")
        except Exception as e:
            self.logger.warning(f"set supportsClassC failed: {e}")
        return False

    # --- CFG (mode/period) downlink enqueue --------------------------------
    def enqueue_cfg(self, dev_eui: str, mode: int, hb_min: int,
                    confirmed: bool = False) -> bool:
        _, payload, desc = build_mode_downlink(mode, hb_min)
        data_b64 = base64.b64encode(payload).decode()
        # Site-wide pacing: a class transition enqueues CFG to EVERY device at
        # once; on a single half-duplex gateway that floods the air. Share the
        # one global limiter (with the on/off output) so CFG + control downlinks
        # are spaced together and device ACK uplinks keep airtime.
        try:
            from aot.utils.lorawan_pacing import claim_send_slot
            from time import sleep
            w = claim_send_slot()
            if w > 0:
                sleep(w)
        except Exception:
            pass
        try:
            pr = requests.post(
                f"{self.base_url}/api/devices/{normalize_deveui(dev_eui)}/queue",
                headers={**self._headers, 'Content-Type': 'application/json'},
                json={'queueItem': {'fPort': FPORT_CFG, 'data': data_b64,
                                    'confirmed': bool(confirmed)}},
                timeout=10)
            if pr.status_code == 200:
                self.logger.debug(f"enqueue_cfg {dev_eui} {desc}")
                return True
            self.logger.warning(f"enqueue_cfg {dev_eui} HTTP {pr.status_code}")
        except Exception as e:
            self.logger.warning(f"enqueue_cfg {dev_eui} failed: {e}")
        return False

    # --- device state (battery / class / rssi / snr / last-seen) -----------
    @staticmethod
    def _latest_metric_val(metric: dict, skip_zero: bool = True) -> Optional[float]:
        datasets = metric.get('datasets', [])
        timestamps = metric.get('timestamps', [])
        if not datasets or not timestamps:
            return None
        for i in range(len(timestamps) - 1, -1, -1):
            for ds in datasets:
                data = ds.get('data', [])
                if i < len(data) and data[i] is not None:
                    try:
                        v = float(data[i])
                        if skip_zero and v == 0.0:
                            continue
                        return v
                    except Exception:
                        pass
        return None

    def fetch_device_state(self, dev_eui: str, max_age: int = 4000) -> dict:
        """Return {battery_V, rssi, snr, node_class, node_hb_min, last_seen_at}."""
        result = {'battery_V': None, 'rssi': None, 'snr': None,
                  'node_class': None, 'node_hb_min': None, 'last_seen_at': None}
        eui = normalize_deveui(dev_eui)
        if not self.ok() or not eui:
            return result
        now = datetime.utcnow()
        start = (now - timedelta(seconds=max_age)).strftime('%Y-%m-%dT%H:%M:%SZ')
        end = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        # ChirpStack stores HOUR/DAY/MONTH (not MINUTE); use HOUR for any real window.
        agg = 'HOUR' if max_age >= 3600 else 'MINUTE'
        params = {'start': start, 'end': end, 'aggregation': agg}

        try:
            r = self._get(f"/api/devices/{eui}/metrics", params=params)
            if r.status_code == 200:
                m = r.json().get('metrics', {})
                if 'battery_V' in m:
                    result['battery_V'] = self._latest_metric_val(m['battery_V'])
                if 'node_class' in m:
                    v = self._latest_metric_val(m['node_class'])
                    result['node_class'] = int(v) if v is not None else None
                if 'node_hb_min' in m:
                    v = self._latest_metric_val(m['node_hb_min'])
                    result['node_hb_min'] = int(v) if v is not None else None
        except Exception as e:
            self.logger.debug(f"metrics fetch failed {eui}: {e}")

        try:
            r = self._get(f"/api/devices/{eui}/link-metrics", params=params)
            if r.status_code == 200:
                d = r.json()
                if 'gwRssi' in d:
                    result['rssi'] = self._latest_metric_val(d['gwRssi'])
                if 'gwSnr' in d:
                    result['snr'] = self._latest_metric_val(d['gwSnr'])
        except Exception as e:
            self.logger.debug(f"link-metrics fetch failed {eui}: {e}")

        try:
            r = self._get(f"/api/devices/{eui}")
            if r.status_code == 200:
                result['last_seen_at'] = r.json().get('lastSeenAt')
        except Exception as e:
            self.logger.debug(f"device get failed {eui}: {e}")
        return result

# coding=utf-8
"""
AoT Input: Matter node sensors

One Input per Matter node; one channel per sensor attribute (temperature,
humidity, illuminance, boolean state, battery). Channels are created from the
node's own description when the device is shared to AoT (Settings > Matter);
see docs/design/matter-controller.md §4 and §5-2.

Values come from the Matter server's subscription to the node, through the
shared client (aot/devices/matter_client.py). Two write paths:

  - on change: the server pushes attribute_updated; the value is written at
    once (a door contact that flips between samples is not lost);
  - on a sample interval: the values are read live from the device and
    written. Matter devices report only on change (plus empty keep-alives),
    so a steady temperature would otherwise look stale to AoT's freshness
    checks. The read is live, not from the cache, because the server can keep
    a node "available" for minutes after it stopped answering AoT (another
    ecosystem removed AoT's fabric); a failed read writes nothing.

Nothing is written while the server connection is down or the node is
unavailable: the subscription no longer vouches for the cached value, and
re-writing it as new would hide the outage from freshness checks
(sensor-freshness-and-control-cadence.md).
"""
import datetime
import queue
import threading
import time

from flask_babel import lazy_gettext

from aot.config_translations import TRANSLATIONS
from aot.databases.models import Conversion
from aot.databases.models import InputChannel
from aot.databases.models import Trigger
from aot.inputs.base_input import AbstractInput
from aot.utils.actions import run_input_actions
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.inputs import parse_measurement
from aot.utils.timekit import FARM, naive_utc, to_tz, utc_now

measurements_dict = {}

# A sample's live read; it runs on the Input's own listener thread.
LIVE_READ_TIMEOUT_S = 10.0
ICD_MANAGEMENT = 0x0046

channels_dict = {
    0: {}
}

INPUT_INFORMATION = {
    'input_name_unique': 'MATTER_NODE',
    'input_manufacturer': 'Matter',
    'input_name': 'Matter Node (Sensors)',
    'input_name_short': 'Matter',
    'input_library': 'websockets',
    'measurements_name': 'Variable measurements',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,

    'measurements_variable_amount': True,
    'channel_quantity_same_as_measurements': True,
    'measurements_use_same_timestamp': False,

    'message': lazy_gettext(
        'Sensor values from a Matter device on the AoT Matter fabric. Created automatically '
        'when a device is shared to AoT from Settings > Matter; each channel is one sensor '
        'the device reported. Values are written when they change and again every sample '
        'interval while the device is reachable. Nothing is written while it is unreachable.'
    ),

    # Values arrive on the listener thread (see listener()); there is no
    # periodic get_measurement(), so only the freshness override is exposed.
    'listener': True,
    'options_enabled': [
        'measurements_select',
        'max_age_only'
    ],
    'options_disabled': ['interface'],

    'dependencies_module': [
        ('pip-pypi', 'websockets', 'websockets==16.0')
    ],

    'interfaces': ['IP'],

    'custom_options': [
        {
            'id': 'node_id',
            'type': 'integer',
            'default_value': 0,
            'required': True,
            'name': lazy_gettext('Node ID'),
            'phrase': lazy_gettext(
                'Node ID on the AoT Matter fabric. Inherited from the Matter device')
        },
        {
            'id': 'sample_interval_s',
            'type': 'integer',
            'default_value': 60,
            'constraints_pass': lambda mod_input, value: (
                (True, None, mod_input) if value >= 5
                else (False, ['Sample interval must be at least 5 seconds'], mod_input)),
            'required': True,
            'name': lazy_gettext('Sample Interval (seconds)'),
            'phrase': lazy_gettext(
                'How often the current value is written while the device is reachable, '
                'in addition to every change it reports')
        },
    ],

    'custom_channel_options': [
        {
            'id': 'name',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': TRANSLATIONS['name']['title'],
            'phrase': TRANSLATIONS['name']['phrase']
        },
        {
            'id': 'endpoint',
            'type': 'integer',
            'default_value': 1,
            'required': True,
            'name': lazy_gettext('Endpoint'),
            'phrase': lazy_gettext('Matter endpoint number on the device')
        },
        {
            'id': 'cluster_id',
            'type': 'integer',
            'default_value': 0,
            'required': True,
            'name': lazy_gettext('Cluster ID'),
            'phrase': lazy_gettext('Matter cluster id (decimal)')
        },
        {
            'id': 'attribute_id',
            'type': 'integer',
            'default_value': 0,
            'required': True,
            'name': lazy_gettext('Attribute ID'),
            'phrase': lazy_gettext('Matter attribute id (decimal)')
        },
        {
            'id': 'matter_kind',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('Sensor Kind'),
            'phrase': lazy_gettext(
                'How the raw value is scaled: temperature, humidity, illuminance, '
                'boolean_state or battery')
        },
    ]
}


def execute_at_creation(error, new_input, dict_inputs=None):
    """Only Settings > Matter creates this (bound to a node); refuse elsewhere."""
    from aot.devices.matter_onboarding import refuse_outside_settings
    return refuse_outside_settings(error, new_input, dict_inputs)


INPUT_INFORMATION['execute_at_creation'] = execute_at_creation


class InputModule(AbstractInput):
    """Writes Matter sensor attributes from the shared Matter server client.

    @phase experimental
    @stability experimental
    @dependency AbstractInput, matter_client
    """

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.node_id = None
        self.sample_interval_s = None
        self.options_channels = None
        self.client = None
        self._paths = {}            # "ep/cluster/attr" -> [channel, ...]
        self._sub_handle = None
        self._lock = threading.Lock()
        self._last_write_ts = None
        self._wake = threading.Event()
        self._was_available = False
        self._changes = queue.SimpleQueue()     # (kind, path, payload, received)
        self._last_bool = {}                    # channel -> last written 0/1
        self._snapshot_due = False
        self._probe_failed = False              # last live read of a sample failed

        if not testing:
            self.setup_custom_options(
                INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        """Build the channel map only. Never connects (daemon boot, C2)."""
        from aot.devices import matter_clusters
        from aot.devices.matter_client import get_client

        input_channels = db_retrieve_table_daemon(
            InputChannel).filter(InputChannel.input_id == self.input_dev.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            INPUT_INFORMATION['custom_channel_options'], input_channels)

        paths = {}
        for channel in self.channels_measurement:
            try:
                path = matter_clusters.attribute_path(
                    self.options_channels['endpoint'][channel],
                    self.options_channels['cluster_id'][channel],
                    self.options_channels['attribute_id'][channel])
            except (KeyError, TypeError, ValueError):
                self.logger.error(f"Channel {channel} has no Matter attribute configured")
                continue
            paths.setdefault(path, []).append(channel)
        self._paths = paths
        self.client = get_client()

    # ------------------------------------------------------------------ #

    def listener(self):
        """Writes happen here, never on the client's reader thread: writing
        runs Input Actions (DB queries, daemon RPC), and while the reader is
        busy every Matter reply and event in this process waits — including
        the reply an Action's own Matter command would be waiting for."""
        if not self.node_id:
            self.logger.error("Node ID is not set; nothing to listen to")
            return
        self.client.ensure_started()
        self._sub_handle = self.client.subscribe(self._on_event, node_id=self.node_id)
        if not self.running:
            # stop_input() ran before we subscribed; don't leak a subscription.
            self.client.unsubscribe(self._sub_handle)
            self._sub_handle = None
            return
        self._was_available = self._node_available()
        # Values already in the cache when we start are current if the node is
        # available (the subscription keeps them so) — write them once now
        # rather than waiting a full interval.
        self._write_snapshot('startup')
        interval = max(5, int(self.sample_interval_s or 60))
        next_sample = time.monotonic() + interval
        while self.running:
            self._wake.wait(max(0.1, next_sample - time.monotonic()))
            self._wake.clear()
            if not self.running:
                break
            self._drain_changes()
            now = time.monotonic()
            if self._snapshot_due or now >= next_sample:
                self._snapshot_due = False
                self._write_snapshot('sample')
                next_sample = now + interval

    def _on_event(self, event, data):
        """Runs on the client's reader thread: queue and return."""
        if event == 'attribute_updated':
            try:
                path, value = data[1], data[2]
            except (TypeError, IndexError):
                return
            if path in self._paths:
                # Stamp on receipt: a contact that opens and closes within
                # one wake keeps both transitions at their own times.
                self._changes.put(('attr', path, value, naive_utc(utc_now())))
                self._wake.set()
        elif event == 'node_event':
            # A button gesture. Only Switch events are used; the button's
            # channel is keyed by its CurrentPosition path.
            from aot.devices import matter_clusters
            if not isinstance(data, dict) or data.get('cluster_id') != matter_clusters.SWITCH:
                return
            path = matter_clusters.attribute_path(data.get('endpoint_id', 0),
                                                  matter_clusters.SWITCH, 1)
            if path in self._paths:
                self._changes.put(('button', path, (data.get('event_id'), data.get('data')),
                                   naive_utc(utc_now())))
                self._wake.set()
        elif event == 'connected':
            # Back after a server outage: fresh snapshot.
            self._snapshot_due = True
            self._wake.set()
        elif event in ('node_updated', 'node_added'):
            # node_updated also fires for interview refreshes; only a node
            # coming back online is worth an immediate snapshot.
            available = bool(isinstance(data, dict) and data.get('available'))
            if available and not self._was_available:
                self._snapshot_due = True
                self._wake.set()
            self._was_available = available

    def _drain_changes(self):
        items = []
        while True:
            try:
                items.append(self._changes.get_nowait())
            except queue.Empty:
                break
        if not items:
            return
        # Everything queued here was *reported* by the node over its live
        # subscription — proof of life in itself. An availability flag that
        # has not caught up yet (it lags after an outage) must not drop it:
        # a dropped contact change would also lose its edge for good, since
        # the next snapshot records the new state without firing one.
        for kind, path, payload, received in items:
            channels = self._paths.get(path, ())
            if kind == 'button':
                self._button(channels, path, payload, received)
                continue
            channels = [ch for ch in channels if not self._event_only(ch)]
            if channels:
                self._write({ch: payload for ch in channels}, received, edges=True)

    def _event_only(self, channel):
        from aot.devices import matter_clusters
        spec = matter_clusters.sensor_spec(self.options_channels['matter_kind'].get(channel))
        return bool(spec and spec.get('event_only'))

    def _button(self, channels, path, payload, received):
        from aot.devices import matter_clusters
        event_id, data = payload
        endpoint = int(path.split('/')[0])
        fmap = self.client.get_attribute(self.node_id, matter_clusters.attribute_path(
            endpoint, matter_clusters.SWITCH, matter_clusters.FEATURE_MAP_ATTR))
        multi = isinstance(fmap, int) and bool(fmap & matter_clusters.SWITCH_FEATURE_MULTI_PRESS)
        # Unknown FeatureMap: assume the common release-capable button.
        release = not isinstance(fmap, int) or bool(fmap & matter_clusters.SWITCH_FEATURE_RELEASE)
        value = matter_clusters.button_value(event_id, data, multi, release)
        if value is None:
            return
        self._write({ch: value for ch in channels}, received)
        if value == matter_clusters.BUTTON_LONG_PRESS_VALUE:
            label = 'long press'
        else:
            label = f'{int(value)} press' + ('es' if value > 1 else '')
        self._fire_edge('rising', f'button {label} on endpoint {endpoint}')

    def _node_available(self):
        if not self.client.is_connected():
            return False
        node = self.client.get_node(self.node_id)
        return bool(node and node.get('available'))

    def _write_snapshot(self, source):
        """A sample: read the values live from the device and write them.

        Not from the cache. The server's `available` flag can stay true for
        minutes after the device stopped answering AoT — e.g. another
        ecosystem removed AoT's fabric from it (observed: >3 min, while every
        command timed out). Re-writing cached values in that state would
        present stale numbers as fresh. A live read either proves the device
        still answers AoT or fails, and then nothing is written and the link
        shows as faulted until a read succeeds again.
        """
        from aot.devices.matter_client import MatterError
        if not self._node_available():
            self.logger.debug(f"Node {self.node_id} unavailable; {source} skipped")
            return
        paths = [path for path, channels in self._paths.items()
                 # A button has no state to sample: re-writing its last value
                 # would look like a new press to Input Actions.
                 if any(not self._event_only(ch) for ch in channels)]
        if not paths:
            return
        if self._sleepy():
            # A battery (ICD) device answers only when it wakes, so a live
            # read would time out and turn every sample into a fault while
            # draining its battery. Its live subscription is the proof here.
            self._write({ch: self.client.get_attribute(self.node_id, path)
                         for path in paths for ch in self._paths[path]
                         if not self._event_only(ch)})
            return
        # Stamped when the read is sent: a change the device reports while
        # the read is in flight is newer and must stay the latest point.
        sent_at = naive_utc(utc_now())
        try:
            values = self.client.send_command('read_attribute', {
                'node_id': int(self.node_id), 'attribute_path': paths},
                timeout=LIVE_READ_TIMEOUT_S) or {}
        except MatterError as err:
            if not self._probe_failed:
                self.logger.warning(
                    f"Node {self.node_id} did not answer a live read ({err}); "
                    f"not writing until it does")
            self._probe_failed = True
            return
        if not isinstance(values, dict):
            values = {}
        if self._probe_failed:
            self.logger.info(f"Node {self.node_id} answers again")
        self._probe_failed = False
        raw = {}
        for path in paths:
            value = values.get(path, self.client.get_attribute(self.node_id, path))
            for ch in self._paths[path]:
                if not self._event_only(ch):
                    raw[ch] = value
        self._write(raw, sent_at)
        # Changes queued during the read carry later receipt times; write them
        # now so they follow the sample instead of waiting a wake-up.
        self._drain_changes()

    def _sleepy(self):
        """Intermittently connected (ICD) device: ICD Management cluster on
        the root endpoint."""
        from aot.devices import matter_clusters
        node = self.client.get_node(self.node_id) or {}
        clusters = matter_clusters.endpoint_clusters(node.get('attributes') or {}).get(0, set())
        return ICD_MANAGEMENT in clusters

    def _write(self, raw_by_channel, timestamp=None, edges=False):
        """Write converted values. With edges=True (a reported change, not a
        sample), a boolean channel that flipped also fires edge Triggers."""
        from aot.devices import matter_clusters

        now = timestamp or naive_utc(utc_now())
        measurement = {}
        flipped = []
        for channel, raw in raw_by_channel.items():
            if channel not in self.channels_measurement:
                continue
            kind = self.options_channels['matter_kind'].get(channel)
            value = matter_clusters.convert(kind, raw)
            if value is None:
                continue
            if self.channels_measurement[channel].unit == 'bool':
                prev = self._last_bool.get(channel)
                self._last_bool[channel] = value
                if edges and prev is not None and prev != value:
                    flipped.append((channel, value))
            measurement[channel] = {
                'measurement': self.channels_measurement[channel].measurement,
                'unit': self.channels_measurement[channel].unit,
                'value': value,
                'timestamp_utc': now,
            }
            measurement = self.check_conversion(channel, measurement)
        if not measurement:
            return
        with self._lock:
            self._last_write_ts = time.time()
        _message, measurement = run_input_actions(
            self.unique_id, "", measurement, self.input_dev.log_level_debug)
        add_measurements_influxdb(
            self.unique_id,
            measurement,
            use_same_timestamp=INPUT_INFORMATION['measurements_use_same_timestamp'])
        for channel, value in flipped:
            name = self.channels_measurement[channel].name if hasattr(
                self.channels_measurement[channel], 'name') else f'channel {channel}'
            self._fire_edge('rising' if value else 'falling',
                            f'{name or "channel " + str(channel)} '
                            f'{"on" if value else "off"}')

    def _fire_edge(self, direction, what):
        """Run the actions of active edge Triggers on this Input (the same
        mechanism GPIO edge inputs use, aot/inputs/rpi_edge.py). An edge
        Trigger binds to the Input, not a channel: every channel's edge
        reaches it, with the channel named in the message."""
        try:
            triggers = db_retrieve_table_daemon(Trigger).filter(
                Trigger.trigger_type == 'trigger_edge').filter(
                Trigger.measurement == self.unique_id).filter(
                Trigger.is_activated.is_(True)).all()
        except Exception:
            self.logger.exception("Looking up edge triggers failed")
            return
        if triggers and getattr(self, 'control', None) is None:
            from aot.aot_client import DaemonControl
            self.control = DaemonControl()
        for trigger in triggers:
            if trigger.edge_detected not in ('both', direction):
                continue
            stamp = to_tz(utc_now(), FARM).strftime('%Y-%m-%d %H-%M-%S')
            message = (f"{stamp}\n[Trigger {trigger.id} ({trigger.name})] "
                       f"Input {self.unique_id} ({self.input_dev.name}) "
                       f"{direction} edge: {what}")
            try:
                self.control.trigger_all_actions(trigger.unique_id, message=message)
            except Exception:
                self.logger.exception("Running trigger %s failed", trigger.unique_id)

    def check_conversion(self, channel, measurement):
        """Same as mqtt_paho_json: the push path skips create_measurements_dict()."""
        try:
            if self.channels_conversion[channel]:
                conversion = db_retrieve_table_daemon(
                    Conversion,
                    unique_id=self.channels_measurement[channel].conversion_id)
                if conversion:
                    meas = parse_measurement(
                        self.channels_conversion[channel],
                        self.channels_measurement[channel],
                        measurement,
                        channel,
                        measurement[channel],
                        timestamp=measurement[channel]['timestamp_utc'])
                    measurement[channel]['measurement'] = meas[channel]['measurement']
                    measurement[channel]['unit'] = meas[channel]['unit']
                    measurement[channel]['value'] = meas[channel]['value']
        except Exception:
            self.logger.exception("Checking conversion")
        return measurement

    # ------------------------------------------------------------------ #
    # Communication status (AbstractBaseController.comm_*): the link is the
    # server connection plus the node's own availability as the server sees
    # it. A quiet sensor on a live subscription is not a fault.
    # ------------------------------------------------------------------ #
    def comm_capable(self):
        return True

    def comm_last_success(self):
        return self._last_write_ts

    def comm_is_fault(self, channel=None):
        return self.client is None or self._probe_failed or not self._node_available()

    def comm_is_pending(self, channel=None):
        return False

    def stop_input(self):
        """Called when Input is deactivated."""
        self.running = False
        self._wake.set()
        if self.client is not None and self._sub_handle is not None:
            self.client.unsubscribe(self._sub_handle)
            self._sub_handle = None

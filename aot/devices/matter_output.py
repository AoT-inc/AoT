# coding=utf-8
"""Shared plumbing for Matter Output modules whose state is a number
(MATTER_LEVEL dimmer, MATTER_COVERING curtain).

What it owns: the node link (server connection + node availability, the
`_shared_link` contract ConfirmableOutputMixin.comm_is_fault() reads), the
subscription to the node's events, registering the runtime channels, and
the re-seed rule learned in P1 — re-read state from the cache only on
reconnect or when the node comes back online, never on an interview
refresh (whose cache may predate a command's report).

The modules keep their state as numbers in `output_states` and do not use
ConfirmableOutputMixin's boolean confirm/pending machinery: it would
overwrite a level or position with True/False. The device's own attribute
reports are the source of truth; a command's success is the device's invoke
response.

The on/off module (aot/outputs/on_off_matter.py) predates this and keeps its
own copy of the same rules, because it does use the boolean confirmation.

@phase experimental
@stability experimental
"""
import threading

from aot.devices import matter_clusters


class NodeLink:
    """`_shared_link` for ConfirmableOutputMixin.comm_is_fault()."""

    def __init__(self, client, node_id):
        self.client = client
        self.node_id = node_id

    def is_healthy(self):
        if not self.client.is_connected():
            return False
        node = self.client.get_node(self.node_id)
        return bool(node and node.get('available'))


class MatterOutputMixin:
    """Mix into an AbstractOutput subclass, before it in the bases.

    The module provides:
      - state_paths(endpoint) -> list of attribute paths that carry its state;
      - _state_from_cache(channel, endpoint) -> number or None;
      - optionally _on_state_report(channel, endpoint, path, value).
    """

    def _matter_init(self):
        self.node_id = None
        self.client = None
        self._sub_handle = None
        self._channel_by_path = {}
        self._was_available = False
        self._matter_lock = threading.Lock()

    def _matter_setup(self, output_information):
        """Call from initialize() after setup_custom_options(). Never blocks."""
        from aot.devices.matter_client import get_client

        for ch in self.options_channels.get('endpoint', {}):
            if ch not in self.output_states:
                self.output_states[ch] = None
                self.output_off_triggered[ch] = False
                self.output_time_turned_on[ch] = None
                self.output_on_duration[ch] = False
                self.output_last_duration[ch] = 0
                self.output_off_until[ch] = 0
                self._started_at_written[ch] = False

        self._channel_by_path = {}
        for ch, endpoint in self.options_channels.get('endpoint', {}).items():
            for path in self.state_paths(int(endpoint)):
                self._channel_by_path.setdefault(path, []).append(ch)

        self.client = get_client()
        self._shared_link = NodeLink(self.client, self.node_id)
        if self._sub_handle is None:
            self._sub_handle = self.client.subscribe(self._matter_event, node_id=self.node_id)
        self.client.ensure_started()
        self.output_setup = True

        node = self.client.get_node(self.node_id) if self.client.is_connected() else None
        self._was_available = bool(node and node.get('available'))
        if self._was_available:
            self._reseed('initialize')

    def _matter_teardown(self):
        if self.client is not None and self._sub_handle is not None:
            self.client.unsubscribe(self._sub_handle)
            self._sub_handle = None

    def _endpoint(self, channel):
        endpoint = self.options_channels.get('endpoint', {}).get(channel)
        return None if endpoint is None else int(endpoint)

    # ------------------------------------------------------------------ #

    def _matter_event(self, event, data):
        """Runs on the client's reader thread: cache reads and state only."""
        if event == 'attribute_updated':
            try:
                path, value = data[1], data[2]
            except (TypeError, IndexError):
                return
            for ch in self._channel_by_path.get(path, ()):
                self.note_device_alive(ch)
                self._on_state_report(ch, self._endpoint(ch), path, value)
        elif event == 'connected':
            self._reseed(event)
        elif event in ('node_updated', 'node_added'):
            available = bool(isinstance(data, dict) and data.get('available'))
            if available and not self._was_available:
                self._reseed(event)
            self._was_available = available

    def _reseed(self, source):
        node = self.client.get_node(self.node_id)
        if not node or not node.get('available'):
            return
        for ch in self.options_channels.get('endpoint', {}):
            value = self._state_from_cache(ch, self._endpoint(ch))
            if value is not None:
                self._set_state(ch, value, source)

    def _on_state_report(self, channel, endpoint, path, value):
        state = self._state_from_cache(channel, endpoint)
        if state is not None:
            self._set_state(channel, state, 'report')

    def _set_state(self, channel, value, source):
        with self._matter_lock:
            self.output_states[channel] = value

    def _attr(self, endpoint, cluster_id, attribute_id):
        return self.client.get_attribute(
            self.node_id, matter_clusters.attribute_path(endpoint, cluster_id, attribute_id))

    def _send(self, endpoint, cluster_id, command, payload, timeout):
        """device_command; raises MatterError on failure."""
        return self.client.send_command('device_command', {
            'node_id': int(self.node_id),
            'endpoint_id': int(endpoint),
            'cluster_id': int(cluster_id),
            'command_name': command,
            'payload': payload or {},
        }, timeout=timeout)

    def is_setup(self):
        return self.output_setup

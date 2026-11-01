# coding=utf-8
"""Shared WebSocket client for the Matter controller sidecar (matterjs-server).

AoT does not embed a Matter stack. The `matter_server` container
(docker/docker-compose.prod.yml, profile "matter") owns the AoT fabric, does
commissioning, CASE sessions and subscriptions, and exposes the
python-matter-server compatible WebSocket API. This module is the AoT side of
that API: one long-lived connection per process, a node/attribute cache fed by
the server's event stream, and a blocking command call for drivers.
Design: docs/design/matter-controller.md §5-1.

Why one connection per process (same reasoning as aot/devices/modbus_client.py):
every Matter Input/Output on every node shares it. `start_listening` returns a
full snapshot of all nodes and then streams `attribute_updated` events, so a
second connection would only duplicate that stream.

Runtime contract with drivers (plc-modbus-integration.md §3, C1~C5):
  - Nothing here connects at import or construction. get_client() returns an
    unstarted client; the first ensure_started() spawns the reader thread and
    returns immediately. Driver __init__/initialize() must never wait on it (C2).
  - Cache reads (nodes(), get_attribute(), is_connected()) never touch the
    network, so Output.is_on() can call them on every page poll (C4).
  - send_command() blocks for at most `timeout` seconds; callers in
    output_switch() must keep that well under the 8s Pyro budget (C3).

Transport: unix socket by default (the server's WebSocket API has no
authentication, so it is not exposed on TCP — design §3-2). AOT_MATTER_URL
switches to TCP: a native (systemd) install sets ws://127.0.0.1:5580/ws, the
server's loopback port on the same host (install/aot-matter.conf, design §14);
development can point it at a server on another host.

Run `python -m aot.devices.matter_client` inside a container to check that it
reaches the server (P0 exit check).

@phase experimental
@stability experimental
@dependency websockets
"""
import itertools
import json
import logging
import os
import random
import threading
import time

logger = logging.getLogger(__name__)

# The server runs as uid 1000 and can only create its socket somewhere it owns,
# i.e. inside its /data volume. AoT containers mount that volume read-only at
# /app/matter_data (connect() on a socket works on a read-only mount).
DEFAULT_SOCKET_PATH = '/app/matter_data/matter-server.sock'
# Host header / request path used over the unix socket. The server only looks
# at the path.
SOCKET_URI = 'ws://localhost/ws'

CONNECT_TIMEOUT_S = 5.0
# Under the 8s Pyro budget output_switch() runs in (C3): a driver that just
# takes the default must time out here first, not in the RPC layer.
DEFAULT_COMMAND_TIMEOUT_S = 5.0
# start_listening returns every node with every attribute. A few dozen nodes
# fit in a couple of MB; the websockets default of 1 MiB does not.
MAX_MESSAGE_BYTES = 32 * 1024 * 1024

# The snapshot answer can be slow on a server that is still resuming CASE
# sessions to every node right after its own restart.
LISTEN_TIMEOUT_S = 30.0

# Keepalive. A dead server must show up fast in the daemon: while the
# connection looks alive, Inputs keep writing subscribed values as current.
# The web process's commissioning connection overrides this (see
# utils_matter): the server stops answering pings while a failed
# commissioning attempt runs (~227s observed), and 20s would cut it off.
PING_INTERVAL_S = 20.0
PING_TIMEOUT_S = 20.0

RECONNECT_MIN_S = 1.0
RECONNECT_MAX_S = 60.0

# Server schema this client was written against: matterjs-server 1.4.0
# (SCHEMA_VERSION 13, MIN_SUPPORTED_SCHEMA_VERSION 11). A newer server is fine
# as long as its min_supported_schema_version still covers us; see
# _check_schema().
CLIENT_SCHEMA_VERSION = 13


# The websockets library logs a keepalive timeout as an ERROR with a full
# traceback. A lost connection is handled here (one WARNING, reconnect with
# backoff), so its own logging is only noise.
_WS_LOGGER = logging.getLogger(__name__ + '.websockets')
_WS_LOGGER.setLevel(logging.CRITICAL)


class MatterError(Exception):
    """Base class for errors raised to callers of this module."""


class MatterNotConnected(MatterError):
    """No live connection to the Matter server (or not listening yet)."""


class MatterCommandTimeout(MatterError):
    """The server did not answer a command within the timeout."""


class MatterCommandError(MatterError):
    """The server answered a command with an error message."""

    def __init__(self, command, error_code, details):
        self.command = command
        self.error_code = error_code
        self.details = details
        super().__init__(f"{command} failed (error_code={error_code}): {details}")


class _SessionFatal(MatterError):
    """Raised inside the reader to end the session (and reconnect)."""


class _Pending:
    __slots__ = ('command', 'event', 'result', 'error')

    def __init__(self, command):
        self.command = command
        self.event = threading.Event()
        self.result = None
        self.error = None


class MatterServerClient:
    """One connection to the Matter server plus a cache of its nodes.

    Thread model: a single reader thread owns connect/recv/reconnect. Any
    thread may call send_command(); websockets' sync connection allows send()
    concurrently with the reader's recv(). Subscriber callbacks run on the
    reader thread and must return quickly.
    """

    def __init__(self, socket_path=None, url=None,
                 connect_timeout=CONNECT_TIMEOUT_S,
                 reconnect_min=RECONNECT_MIN_S, reconnect_max=RECONNECT_MAX_S,
                 ping_interval=PING_INTERVAL_S, ping_timeout=PING_TIMEOUT_S,
                 quiet=False):
        self.socket_path = socket_path
        # Short-lived per-request clients (web) log connection life at debug.
        self.quiet = quiet
        self.url = url
        self.connect_timeout = connect_timeout
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.reconnect_min = reconnect_min
        self.reconnect_max = reconnect_max

        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self._ready = threading.Event()   # connected AND start_listening answered
        self._ws = None
        self._listen_id = None
        self._session_ready = False   # this session got its snapshot

        self._ids = itertools.count(1)
        self._pending = {}

        self._server_info = None
        self._nodes = {}
        self._subscribers = {}
        self._sub_ids = itertools.count(1)

        self._last_error = None
        self._connects = 0
        self._connected_since = None

    # ------------------------------------------------------------------ setup

    @property
    def endpoint(self):
        return self.url or f"unix:{self.socket_path or DEFAULT_SOCKET_PATH}"

    def ensure_started(self):
        """Start the reader thread if it is not running. Never blocks.

        If a stop() is still winding the thread down (it can sit in connect()
        for up to connect_timeout), clearing the stop flag makes that same
        thread carry on instead of exiting. The thread only gives up its slot
        under _lock (end of _run), so there is no window in which it has
        decided to exit but still looks alive here.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._stop.clear()
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name='matter-client', daemon=True)
            self._thread.start()

    def stop(self, timeout=5.0):
        """Stop the reader thread and close the connection."""
        with self._lock:
            self._stop.set()
            ws = self._ws
            thread = self._thread
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def wait_ready(self, timeout):
        """Block until the snapshot has arrived. For CLIs and tests only —
        drivers must not call this from __init__/initialize() (C2)."""
        return self._ready.wait(timeout)

    # ------------------------------------------------------------ cache reads

    def is_connected(self):
        return self._ready.is_set()

    def server_info(self):
        return dict(self._server_info) if self._server_info else None

    def nodes(self):
        """Snapshot of {node_id: node dict}. Never touches the network."""
        with self._lock:
            return dict(self._nodes)

    def get_node(self, node_id):
        with self._lock:
            return self._nodes.get(int(node_id))

    def get_attribute(self, node_id, attribute_path, default=None):
        """Cached value for 'endpoint/cluster/attribute' (decimal ids)."""
        with self._lock:
            node = self._nodes.get(int(node_id))
            if not node:
                return default
            return node.get('attributes', {}).get(attribute_path, default)

    def status(self):
        """Diagnostics for the settings page and the CLI."""
        info = self._server_info or {}
        with self._lock:
            node_count = len(self._nodes)
            available = sum(1 for n in self._nodes.values() if n.get('available'))
        return {
            'endpoint': self.endpoint,
            'connected': self._ready.is_set(),
            'connected_since': self._connected_since,
            'connects': self._connects,
            'last_error': self._last_error,
            'schema_version': info.get('schema_version'),
            'sdk_version': info.get('sdk_version'),
            'fabric_id': info.get('fabric_id'),
            'fabric_index': info.get('fabric_index'),
            'bluetooth_enabled': bool(info.get('bluetooth_enabled')),
            'node_count': node_count,
            'nodes_available': available,
        }

    # ----------------------------------------------------------- subscribers

    def subscribe(self, callback, node_id=None):
        """Register callback(event_name, data) for server events.

        node_id narrows delivery to events about that node. Events are the
        server's own names (attribute_updated, node_added, node_updated,
        node_removed, node_event) plus two of ours: 'connected' (snapshot
        refreshed, data=None) and 'disconnected' (data=error text).
        Returns a handle for unsubscribe().
        """
        handle = next(self._sub_ids)
        with self._lock:
            self._subscribers[handle] = (callback,
                                         None if node_id is None else int(node_id))
        return handle

    def unsubscribe(self, handle):
        with self._lock:
            self._subscribers.pop(handle, None)

    # -------------------------------------------------------------- commands

    def send_command(self, command, args=None, timeout=DEFAULT_COMMAND_TIMEOUT_S):
        """Send a command and wait for its result.

        Raises MatterNotConnected, MatterCommandTimeout or MatterCommandError.
        Must not be called from a subscriber callback: those run on the
        reader thread, which is the only thread that can deliver the answer.
        """
        self.ensure_started()
        if not self._ready.is_set():
            raise MatterNotConnected(self._last_error or 'not connected to Matter server')
        return self._request(command, args, timeout)

    def _request(self, command, args, timeout):
        if threading.current_thread() is self._thread:
            raise MatterError(
                f'{command}: send_command() called from a subscriber callback '
                '(reader thread) would wait on itself; hand the work to another thread')
        ws = self._ws
        if ws is None:
            raise MatterNotConnected(self._last_error or 'not connected to Matter server')
        message_id = str(next(self._ids))
        pending = _Pending(command)
        with self._lock:
            self._pending[message_id] = pending
        try:
            payload = {'message_id': message_id, 'command': command}
            if args is not None:
                payload['args'] = args
            try:
                ws.send(json.dumps(payload))
            except Exception as err:
                raise MatterNotConnected(f'send failed: {err}') from err
            if not pending.event.wait(timeout):
                raise MatterCommandTimeout(f'{command}: no answer in {timeout:g}s')
            if pending.error is not None:
                raise pending.error
            return pending.result
        finally:
            with self._lock:
                self._pending.pop(message_id, None)

    # ------------------------------------------------------------ reader loop

    def _connect(self):
        from websockets.sync.client import connect, unix_connect
        common = dict(open_timeout=self.connect_timeout, max_size=MAX_MESSAGE_BYTES,
                      ping_interval=self.ping_interval, ping_timeout=self.ping_timeout,
                      logger=_WS_LOGGER)
        if self.url:
            return connect(self.url, proxy=None, **common)
        return unix_connect(self.socket_path or DEFAULT_SOCKET_PATH, uri=SOCKET_URI,
                            **common)

    def _run(self):
        try:
            from websockets.exceptions import ConnectionClosedOK
        except ImportError as err:
            # An image built before websockets was added to requirements.txt.
            # Nothing to retry; say so in status() instead of dying silently.
            self._last_error = f'websockets is not installed: {err}'
            logger.error("Matter client cannot start: %s", self._last_error)
            with self._lock:
                self._thread = None
            return
        delay = self.reconnect_min
        while True:
            while not self._stop.is_set():
                self._session_ready = False
                try:
                    self._session()
                except ConnectionClosedOK as err:
                    # Orderly close: server restart/shutdown, or our stop().
                    self._last_error = f'connection closed: {err}'
                    if not self._stop.is_set():
                        logger.info("Matter server closed the connection (%s)",
                                    self.endpoint)
                except Exception as err:
                    self._last_error = f'{type(err).__name__}: {err}'
                    if not self._stop.is_set():
                        logger.warning("Matter server connection lost (%s): %s",
                                       self.endpoint, self._last_error)
                finally:
                    self._on_disconnect()
                if self._stop.is_set():
                    break
                # A session that got as far as its snapshot was healthy: the
                # next failure starts the backoff over. Only back-to-back
                # failures (server down, socket missing) grow it.
                if self._session_ready:
                    delay = self.reconnect_min
                # Jitter so several processes (daemon, web workers) don't
                # reconnect in lockstep after a server restart.
                self._stop.wait(delay * (0.8 + 0.4 * random.random()))
                delay = min(delay * 2, self.reconnect_max)
            # Give up the slot under the lock, unless ensure_started() cleared
            # the stop flag meanwhile -- then carry on as the live thread.
            with self._lock:
                if self._stop.is_set():
                    self._thread = None
                    return
            delay = self.reconnect_min

    def _session(self):
        ws = self._connect()
        self._ws = ws
        try:
            # The server speaks first: one ServerInfo message.
            first = json.loads(ws.recv(timeout=self.connect_timeout))
            if 'fabric_id' not in first and 'schema_version' not in first:
                raise MatterError(f'unexpected first message: {str(first)[:200]}')
            self._server_info = first
            self._check_schema(first)

            # Ask for the snapshot + event stream. Its answer is applied on
            # this (reader) thread in _handle_message(), in stream order, so
            # no attribute_updated that follows it can be overwritten by it.
            self._listen_id = str(next(self._ids))
            ws.send(json.dumps({'message_id': self._listen_id,
                                'command': 'start_listening'}))
            deadline = time.monotonic() + LISTEN_TIMEOUT_S
            while not self._stop.is_set() and not self._ready.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MatterCommandTimeout(
                        f'start_listening: no answer in {LISTEN_TIMEOUT_S:g}s')
                try:
                    raw = ws.recv(timeout=remaining)
                except TimeoutError:
                    continue
                self._dispatch(raw)

            # Steady state. Dead peers are caught by websockets' keepalive
            # pings (ping_interval/ping_timeout), which close the connection
            # and make recv() raise.
            while not self._stop.is_set():
                self._dispatch(ws.recv())
        finally:
            self._ws = None
            self._listen_id = None
            try:
                ws.close()
            except Exception:
                pass

    def _dispatch(self, raw):
        """Handle one frame. A malformed frame is logged and dropped -- only
        transport errors and a failed snapshot end the session; otherwise
        one bad event would fail every in-flight command and refetch the
        whole snapshot."""
        try:
            self._handle_message(json.loads(raw))
        except _SessionFatal:
            raise
        except Exception:
            logger.exception("Matter: dropping malformed message: %.300s", raw)

    def _apply_snapshot(self, msg):
        if 'error_code' in msg:
            raise _SessionFatal(str(MatterCommandError(
                'start_listening', msg.get('error_code'), msg.get('details'))))
        try:
            nodes = {int(n['node_id']): n for n in (msg.get('result') or [])}
        except (TypeError, KeyError, ValueError) as err:
            raise _SessionFatal(f'start_listening: malformed snapshot: {err!r}') from err
        with self._lock:
            self._nodes = nodes
            count = len(nodes)
        self._session_ready = True
        self._connects += 1
        self._connected_since = time.time()
        self._last_error = None
        self._ready.set()
        (logger.debug if self.quiet else logger.info)(
            "Matter server ready (%s): %d node(s)", self.endpoint, count)
        self._emit('connected', None, None)

    def _check_schema(self, info):
        server_min = info.get('min_supported_schema_version')
        server_ver = info.get('schema_version')
        if isinstance(server_min, int) and server_min > CLIENT_SCHEMA_VERSION:
            # Not fatal: most commands we use have been stable across schema
            # bumps. Loud, because a mismatch is the first suspect on errors.
            logger.error("Matter server requires schema >= %s; this client speaks %s",
                         server_min, CLIENT_SCHEMA_VERSION)
        elif isinstance(server_ver, int) and server_ver < CLIENT_SCHEMA_VERSION:
            logger.warning("Matter server schema %s is older than client schema %s",
                           server_ver, CLIENT_SCHEMA_VERSION)

    def _handle_message(self, msg):
        if 'event' in msg:
            self._handle_event(msg['event'], msg.get('data'))
            return
        message_id = msg.get('message_id')
        if message_id is None:
            logger.debug("Matter: ignoring message without id: %.200s", msg)
            return
        if self._listen_id is not None and str(message_id) == self._listen_id:
            self._apply_snapshot(msg)
            return
        with self._lock:
            pending = self._pending.get(str(message_id))
        if pending is None:
            return  # caller already timed out
        if 'error_code' in msg:
            pending.error = MatterCommandError(
                pending.command, msg.get('error_code'), msg.get('details'))
        else:
            pending.result = msg.get('result')
        pending.event.set()

    def _handle_event(self, event, data):
        node_id = None
        if event == 'attribute_updated':
            # data = [node_id, "endpoint/cluster/attribute", value]
            node_id, path, value = int(data[0]), data[1], data[2]
            with self._lock:
                node = self._nodes.get(node_id)
                if node is not None:
                    node.setdefault('attributes', {})[path] = value
        elif event in ('node_added', 'node_updated'):
            node_id = int(data['node_id'])
            with self._lock:
                self._nodes[node_id] = data
        elif event == 'node_removed':
            node_id = int(data)
            with self._lock:
                self._nodes.pop(node_id, None)
        elif event in ('node_event', 'endpoint_added', 'endpoint_removed'):
            if isinstance(data, dict) and data.get('node_id') is not None:
                node_id = int(data['node_id'])
        elif event == 'server_info_updated':
            self._server_info = data
        elif event == 'server_shutdown':
            logger.info("Matter server announced shutdown")
            ws = self._ws
            if ws is not None:
                ws.close()
            return
        self._emit(event, data, node_id)

    def _on_disconnect(self):
        was_ready = self._ready.is_set()
        self._ready.clear()
        self._connected_since = None
        err = MatterNotConnected(self._last_error or 'connection closed')
        with self._lock:
            pending = list(self._pending.values())
        for p in pending:
            # A reply that already landed stays the answer: the command did
            # reach the device even if the socket dropped right after.
            if not p.event.is_set():
                p.error = err
                p.event.set()
        if was_ready:
            self._emit('disconnected', self._last_error, None)

    def _emit(self, event, data, node_id):
        with self._lock:
            subscribers = list(self._subscribers.values())
        for callback, only_node in subscribers:
            if only_node is not None and node_id is not None and only_node != node_id:
                continue
            if only_node is not None and node_id is None and event not in (
                    'connected', 'disconnected'):
                continue
            try:
                callback(event, data)
            except Exception:
                logger.exception("Matter subscriber failed on %s", event)


_client = None
_client_lock = threading.Lock()


def get_client():
    """Process-wide client, configured from the environment. Not started —
    call ensure_started() (cheap, non-blocking) before relying on it."""
    global _client
    with _client_lock:
        if _client is None:
            _client = MatterServerClient(
                socket_path=os.environ.get('AOT_MATTER_SOCKET') or DEFAULT_SOCKET_PATH,
                url=os.environ.get('AOT_MATTER_URL') or None)
        return _client


def _main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        description='Check the connection to the Matter server sidecar.')
    parser.add_argument('--wait', type=float, default=10.0,
                        help='seconds to wait for the node snapshot')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    client = get_client()
    client.ensure_started()
    ok = client.wait_ready(args.wait)
    print(json.dumps(client.status(), indent=2, ensure_ascii=False))
    client.stop()
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(_main())

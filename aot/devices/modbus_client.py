# coding=utf-8
"""Shared Modbus TCP client registry, keyed by (host, port).

One PLC normally backs several AoT Inputs and Outputs at once. Each driver
instance opening its own TCP connection would break in two ways:

  1. Connection exhaustion — many PLCs/gateways cap concurrent TCP connections
     at 1~8.
  2. Transaction interleaving — pymodbus clients are not thread safe, and every
     Input controller runs in its own thread (aot/controllers/controller_input.py).
     Sharing one connection without a lock scrambles transaction IDs.

So connections are shared process-wide and every request/response pair is
wrapped in that connection's lock. Threading locks (not /var/lock files) are
correct here because Modbus devices are only touched by the daemon process —
unlike I2C, which the Flask process also reaches for GIS layers. If Modbus is
ever exposed to Flask, this must be promoted to a file lock.

The link-health accessors (is_healthy/mark_link_ok/mark_link_fail) implement the
contract that ConfirmableOutputMixin.comm_is_fault() expects from a driver's
self._shared_link (aot/outputs/confirmable_output.py) — one PLC going down marks
every channel on it as faulted, with no command in flight.

Timeout/retry defaults come from measurement, not guesswork (Phase 0 PoC):
a request costs at most timeout x (retries + 1), and connect() costs at most
timeout with no retry multiplier. With the defaults below a write+readback pair
tops out near 3s, well under the 8s Pyro budget the daemon gives output_switch()
(aot/aot_client.py).

@phase active
@stability experimental
@dependency pymodbus
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

# Measured worst case = TIMEOUT x (RETRIES + 1) per request. See module docstring.
DEFAULT_TIMEOUT_S = 1.0
DEFAULT_RETRIES = 1

# A link is declared down after this many consecutive failures. 1 would make a
# single dropped frame paint the whole PLC as offline; RS-485/TCP hiccups are
# common enough that one retry-after is worth the extra second of latency.
FAILURES_BEFORE_UNHEALTHY = 2

_registry = {}
_registry_lock = threading.Lock()

# data_type option value -> (pymodbus DATATYPE name, registers consumed).
# 'bool' is not a register type at all — it comes from coils/discrete inputs.
DATA_TYPES = {
    'bool': (None, 1),
    'int16': ('INT16', 1),
    'uint16': ('UINT16', 1),
    'int32': ('INT32', 2),
    'uint32': ('UINT32', 2),
    'float32': ('FLOAT32', 2),
}


def register_count(data_type):
    """How many 16-bit registers one value of this type occupies."""
    return DATA_TYPES.get(data_type, (None, 1))[1]


def _datatype(data_type):
    """Resolve the pymodbus DATATYPE enum member, importing lazily."""
    name = DATA_TYPES.get(data_type, (None, 1))[0]
    if name is None:
        raise ValueError(f"'{data_type}' is not a register data type")
    from pymodbus.client import ModbusTcpClient
    return getattr(ModbusTcpClient.DATATYPE, name)


def decode_registers(registers, data_type, word_order='big'):
    """Decode raw registers into a Python number.

    word_order matters only for multi-register types and is vendor-specific, so
    it is a per-channel option rather than a fixed convention. pymodbus 3.x
    replaced BinaryPayloadDecoder with convert_from_registers().
    """
    from pymodbus.client import ModbusTcpClient
    return ModbusTcpClient.convert_from_registers(
        list(registers), _datatype(data_type), word_order=word_order)


def encode_value(value, data_type, word_order='big'):
    """Encode a Python number into raw registers (Phase 2 value writes)."""
    from pymodbus.client import ModbusTcpClient
    return ModbusTcpClient.convert_to_registers(
        value, _datatype(data_type), word_order=word_order)


class ModbusTCPLink:
    """One shared TCP connection to a single PLC, plus its link health.

    Never connects in __init__ — the daemon activates Inputs sequentially at
    boot and waits on an untimed Event (aot/aot_daemon.py), so a blocking
    connect here would stall the entire daemon startup. Connection happens
    lazily inside the first request.

    @phase active
    @stability experimental
    @dependency pymodbus
    """

    def __init__(self, host, port=502, timeout_s=DEFAULT_TIMEOUT_S, retries=DEFAULT_RETRIES):
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self.retries = retries

        self.lock = threading.RLock()
        self.logger = logging.getLogger(f"{__name__}_{host}_{port}")

        self._client = None
        self.connected = False
        self.last_ok_ts = None
        self.consecutive_failures = 0
        self.last_error = None

    # ------------------------------------------------------------------ #
    # Link health — the self._shared_link contract (confirmable_output.py)
    # ------------------------------------------------------------------ #
    def is_healthy(self):
        """Is this PLC currently reachable.

        Optimistic before the first attempt: a link nothing has talked to yet is
        not known to be down, and reporting fault at that point would paint every
        channel red for the whole window between daemon start and first poll.
        """
        if self.last_ok_ts is None and self.consecutive_failures == 0:
            return True
        return self.consecutive_failures < FAILURES_BEFORE_UNHEALTHY

    def mark_link_ok(self):
        self.last_ok_ts = time.time()
        self.consecutive_failures = 0
        self.last_error = None

    def mark_link_fail(self, err):
        self.consecutive_failures += 1
        self.last_error = str(err)
        if self.consecutive_failures == FAILURES_BEFORE_UNHEALTHY:
            self.logger.error(
                f"Modbus link {self.host}:{self.port} down after "
                f"{self.consecutive_failures} consecutive failures: {err}")

    def status(self):
        """Diagnostic snapshot (daemon status RPC / driver logging)."""
        return {
            'host': self.host,
            'port': self.port,
            'connected': self.connected,
            'healthy': self.is_healthy(),
            'last_ok_ts': self.last_ok_ts,
            'consecutive_failures': self.consecutive_failures,
            'last_error': self.last_error,
        }

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #
    def _ensure_client(self):
        """Build the pymodbus client (no I/O) and connect if needed.

        Caller must hold self.lock. pymodbus reconnects on its own on the next
        request after a drop, so this only has to cover the very first connect
        and the case where connect() previously failed outright.
        """
        if self._client is None:
            from pymodbus.client import ModbusTcpClient
            self._client = ModbusTcpClient(
                self.host,
                port=self.port,
                timeout=self.timeout_s,
                retries=self.retries)

        if not self._client.connected:
            self.connected = bool(self._client.connect())
        else:
            self.connected = True
        return self.connected

    def close(self):
        with self.lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
            self.connected = False

    # ------------------------------------------------------------------ #
    # Requests — every one holds the lock for the full request/response pair
    # ------------------------------------------------------------------ #
    def _execute(self, description, fn):
        """Run one pymodbus call under the lock, updating link health.

        :param fn: callable taking the pymodbus client, returning its response
        :return: the pymodbus response
        :raise ModbusLinkError: connection down, transport error, or Modbus
            exception response. Callers translate this into (1, msg) for
            output_switch() or None for get_measurement().
        """
        with self.lock:
            if not self._ensure_client():
                err = f"connect failed ({self.host}:{self.port})"
                self.mark_link_fail(err)
                raise ModbusLinkError(err)
            try:
                result = fn(self._client)
            except Exception as e:
                self.connected = False
                self.mark_link_fail(e)
                raise ModbusLinkError(f"{description}: {e}") from e
            if result is None or result.isError():
                self.mark_link_fail(result)
                raise ModbusLinkError(f"{description}: {result}")
            self.mark_link_ok()
            return result

    def read_coils(self, address, count=1, device_id=1):
        rr = self._execute(
            f"read_coils({address}, {count})",
            lambda c: c.read_coils(address, count=count, device_id=device_id))
        return list(rr.bits)[:count]

    def read_discrete_inputs(self, address, count=1, device_id=1):
        rr = self._execute(
            f"read_discrete_inputs({address}, {count})",
            lambda c: c.read_discrete_inputs(address, count=count, device_id=device_id))
        return list(rr.bits)[:count]

    def read_holding_registers(self, address, count=1, device_id=1):
        rr = self._execute(
            f"read_holding_registers({address}, {count})",
            lambda c: c.read_holding_registers(address, count=count, device_id=device_id))
        return list(rr.registers)

    def read_input_registers(self, address, count=1, device_id=1):
        rr = self._execute(
            f"read_input_registers({address}, {count})",
            lambda c: c.read_input_registers(address, count=count, device_id=device_id))
        return list(rr.registers)

    def write_coil(self, address, value, device_id=1):
        self._execute(
            f"write_coil({address}, {value})",
            lambda c: c.write_coil(address, bool(value), device_id=device_id))

    def write_register(self, address, value, device_id=1):
        self._execute(
            f"write_register({address}, {value})",
            lambda c: c.write_register(address, int(value), device_id=device_id))

    def write_registers(self, address, values, device_id=1):
        self._execute(
            f"write_registers({address}, {values})",
            lambda c: c.write_registers(address, list(values), device_id=device_id))

    def write_coil_and_read_back(self, address, value, device_id=1):
        """Write a coil and re-read it inside the same lock hold.

        This is the whole point of the shared lock: another thread must not slip
        a write in between the command and its confirmation. Returns the coil
        value actually read back, which the Output driver hands to
        confirm_command().
        """
        with self.lock:
            self.write_coil(address, value, device_id=device_id)
            return self.read_coils(address, count=1, device_id=device_id)[0]


class ModbusLinkError(Exception):
    """Any failure to complete a Modbus request — transport or protocol."""


def get_link(host, port=502, timeout_s=DEFAULT_TIMEOUT_S, retries=DEFAULT_RETRIES):
    """Return the process-wide shared link for this PLC, creating it if needed.

    Timeout/retry arguments only apply when the link is first created; later
    callers for the same (host, port) get the existing one. That is deliberate —
    the connection is shared, so its transport settings cannot be per-driver.
    """
    key = (host, int(port))
    with _registry_lock:
        link = _registry.get(key)
        if link is None:
            link = ModbusTCPLink(host, port=int(port), timeout_s=timeout_s, retries=retries)
            _registry[key] = link
            logger.debug(f"Created shared Modbus link for {host}:{port}")
        return link


def all_links():
    """Every shared link currently registered (diagnostics)."""
    with _registry_lock:
        return list(_registry.values())

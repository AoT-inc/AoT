# PLC (Modbus TCP)

AoT talks to PLCs, relay boards, gateways, and meters over Modbus TCP. Reading is done
with the **Modbus TCP (PLC)** Input, switching with the **On/Off: Modbus TCP Coil (PLC)**
Output. Both are built in — no plugin to install.

!!! warning "Modbus has no authentication or encryption"
    Anyone who can reach the device on the network can read and write every register.
    Keep the PLC on an isolated network (VLAN or firewall allow-list) and never expose
    it to the internet.

## Before you start

Get the register map from the vendor documentation. You need, for each value you care
about:

- Which table it lives in — coil, discrete input, holding register, or input register
- Its address
- For numbers wider than 16 bits: the data type and the word order

Two things bite almost everyone on a first connection:

- **Address base.** Vendor documents often use one-based addresses (`40001` meaning
  holding register `0`, `00001` meaning coil `0`). AoT uses the zero-based address that
  goes on the wire.
- **Word order.** For 32-bit values, some vendors put the high word first and some the
  low word first. If the address is right but the value is nonsense, this is almost
  always why — switch the Word Order option and read again.

## Reading values

Add an Input of type **Modbus TCP (PLC)**, then set:

| Option | Notes |
|---|---|
| Host / Port | Address of the device. Port 502 is standard |
| Unit ID | Usually 1 when addressing a device directly, or the slave address behind a serial gateway |
| Timeout / Retries | Leave at 1.0 s and 1 unless the device is slow. See [Timing](#timing) |
| Period | How often to poll, in seconds. Start at 1–5 s and watch the PLC's load |

Set the number of measurements to the number of registers you want to read, then
configure each channel:

| Channel option | Notes |
|---|---|
| Register Type | Coil and Discrete Input are bits; Holding and Input Register are 16-bit words |
| Register Address | Zero-based address within that table |
| Data Type | `Bit` for coils and discrete inputs; `int16`/`uint16`/`int32`/`uint32`/`float32` for registers |
| Word Order | 32-bit types only. Try the other one if the value looks wrong |
| Scale Factor | Multiplied into the raw value. Use `0.1` for a device reporting tenths |

Bits are stored as `1.0` and `0.0` so they can be graphed and used by Functions like any
other measurement.

When a read fails, AoT stores nothing for that channel rather than storing a placeholder.
That silence is what marks the device as offline — a filler value would hide the outage.
A failure on one channel does not stop the others from being read.

## Switching coils

Add an Output of type **On/Off: Modbus TCP Coil (PLC)**. The host, port, unit ID, timeout,
and retries mean the same as for the Input. Set **Number of Channels** to the number of
coils you want to control and save — one row appears per coil, and each needs only its
**Coil Address**.

After every command, AoT writes the coil and immediately reads it back. That readback is
the confirmation:

- If the readback matches the command, the channel state is confirmed from the device
  rather than assumed.
- If it does not match, the command is reported as failed. Usually this means the PLC
  program is driving that coil itself, or the address is wrong.
- If the device cannot be reached, the command fails and the channel keeps its previous
  state — it never shows a state the PLC never accepted.

!!! note "A readback confirms the register, not the relay"
    Reading the coil back proves the PLC accepted the value. It does not prove the relay
    moved or that the wiring is intact. If you need that, wire a feedback contact and read
    it as a separate Input, then compare.

**Startup State** and **Shutdown State** work as they do for other outputs. Leaving
Startup State at "Do Nothing" is usually right for a PLC: AoT then reads the coil and
adopts whatever state the PLC already has, instead of overriding it.

Right after the daemon starts, channels briefly show as unknown while AoT reads their
actual state in the background. This is deliberate — an unread coil is reported as
unknown rather than assumed off.

## Sharing one connection

Inputs and Outputs pointing at the same host and port automatically share a single TCP
connection, and requests on it are serialized. You do not have to configure anything for
this, and it is why one PLC can back many Inputs and Outputs without exhausting the
connection limit that most devices impose.

The consequence worth knowing: **timeout and retries are per connection, not per device
entry.** The first Input or Output to be activated establishes them for everything sharing
that host and port.

## Communication status

A PLC that stops responding is reported without any extra configuration.

- **Outputs** show every channel on that PLC as faulted as soon as the link is down, even
  with no command in flight. A single dropped frame is not enough — the link is declared
  down after two consecutive failures.
- **Inputs** are judged by measurement staleness: no new measurement for several polling
  periods marks the Input as not communicating.

The daemon also sends an administrator email when a device transitions into or out of a
communication fault. See [Alerts](Alerts.md).

## Timing {: #timing }

One request takes at most `timeout × (retries + 1)`, and connecting takes at most
`timeout`. With the defaults (1.0 s, 1 retry) a command that cannot reach the PLC gives up
in about three seconds.

Raising retries multiplies how long an unreachable device blocks. Since a control command
runs synchronously, keeping the product well under the daemon's command budget matters
more than squeezing out one more retry — raise the timeout for a genuinely slow device
rather than the retry count.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Value is wildly wrong but stable | Word order, or the wrong data type for that register |
| Value is off by a factor of 10 or 100 | Scale Factor not set |
| Reads work, writes report a mismatch | The PLC program is driving that coil, or the coil address is wrong |
| Everything times out, nothing connects | Wrong host/port, or a firewall dropping the connection |
| Connects but every request fails | Wrong Unit ID |
| Off-by-one addresses everywhere | Vendor documentation is one-based; subtract 1 |

Enable the Input or Output's debug logging to see each request and its result in the log.

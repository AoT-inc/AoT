# coding=utf-8
"""Verify the 0xC0 relay-status parsing added to on_off_chirpstack.ingest_uplink()
for RAK3172-C-E (board/relay controller, e.g. the pump output) uplinks, and that
the pre-existing 0xB0 valve-status parsing is unaffected.

No DB access: OutputModule is built via object.__new__() and wired with just the
attributes ingest_uplink()/_my_board_ch() actually touch.
"""
import pytest

from aot.outputs.on_off_chirpstack import OutputModule


class _FakeLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass


def make_output(on_payload, off_payload, payload_format='hex'):
    inst = object.__new__(OutputModule)
    inst.options = {
        'payload_format': payload_format,
        'on_payload': on_payload,
        'off_payload': off_payload,
        'confirmed': False,
    }
    inst.output = None
    inst.logger = _FakeLogger()
    inst.debug_logging = False
    inst.output_states = {0: False}
    inst.output_time_turned_on = {0: None}
    inst._confirm_init()
    return inst


# ---- _my_board_ch() ----

def test_my_board_ch_parses_pump_payload():
    # pump on_payload = 00 03 01 00 -> board=0, ch=3, cmd=ON, dur=0
    inst = make_output('00030100', '00030000')
    assert inst._my_board_ch() == (0, 3)


def test_my_board_ch_none_for_3byte_valve_payload():
    inst = make_output('010108', '010208')
    assert inst._my_board_ch() == (None, None)


# ---- ingest_uplink() : 0xC0 relay-status branch ----

def test_relay_status_confirms_on_when_ack_and_state_bit_set():
    inst = make_output('00030100', '00030000')
    # board=0, state bit3 set (ch3 ON)=0x0008, ack bit3 set=0x0008
    payload = bytes([0xC0, 0x00, 0x00, 0x08, 0x00, 0x08])
    inst.ingest_uplink(12, payload)
    confirmed = inst._cmd_confirmed.get(0)
    assert confirmed is not None
    assert confirmed['state'] is True
    assert confirmed['source'] == 'relay_status'


def test_relay_status_confirms_off_when_ack_set_but_state_bit_clear():
    inst = make_output('00030100', '00030000')
    payload = bytes([0xC0, 0x00, 0x00, 0x00, 0x00, 0x08])  # state bit3=0, ack bit3=1
    inst.ingest_uplink(12, payload)
    confirmed = inst._cmd_confirmed.get(0)
    assert confirmed is not None
    assert confirmed['state'] is False


def test_relay_status_ignored_for_different_board():
    inst = make_output('00030100', '00030000')  # my board=0
    payload = bytes([0xC0, 0x01, 0x00, 0x08, 0x00, 0x08])  # frame board=1
    inst.ingest_uplink(12, payload)
    assert inst._cmd_confirmed.get(0) is None


def test_relay_status_ignored_when_my_channel_not_in_ack_mask():
    inst = make_output('00030100', '00030000')  # my ch=3
    # board matches, but ack bitmask only has bit2 set, not bit3 (mine)
    payload = bytes([0xC0, 0x00, 0x00, 0x08, 0x00, 0x04])
    inst.ingest_uplink(12, payload)
    assert inst._cmd_confirmed.get(0) is None


def test_relay_status_multi_board_multi_channel_isolation():
    # board 1, channel 5: on_payload = 01 05 01 00
    inst = make_output('01050100', '01050000')
    assert inst._my_board_ch() == (1, 5)
    # frame: board=1, state bit5 set (0x0020), ack bit5 set (0x0020)
    payload = bytes([0xC0, 0x01, 0x00, 0x20, 0x00, 0x20])
    inst.ingest_uplink(12, payload)
    confirmed = inst._cmd_confirmed.get(0)
    assert confirmed is not None
    assert confirmed['state'] is True


# ---- regression: existing 0xB0 valve-status path still works ----

def test_valve_0xb0_status_still_confirms_open():
    inst = make_output('010108', '010208')  # vid=1
    payload = bytes([0xB0, 0x01, 0x01])  # vid=1, open_done
    inst.ingest_uplink(12, payload)
    confirmed = inst._cmd_confirmed.get(0)
    assert confirmed is not None
    assert confirmed['state'] is True
    assert confirmed['source'] == 'status'


def test_valve_0xb0_status_still_confirms_close():
    inst = make_output('010108', '010208')
    payload = bytes([0xB0, 0x01, 0x02])  # vid=1, close_done
    inst.ingest_uplink(12, payload)
    confirmed = inst._cmd_confirmed.get(0)
    assert confirmed is not None
    assert confirmed['state'] is False


def test_valve_0xb0_ignored_for_sibling_vid():
    inst = make_output('010108', '010208')  # vid=1
    payload = bytes([0xB0, 0x02, 0x01])  # vid=2 (sibling on same DevEUI)
    inst.ingest_uplink(12, payload)
    assert inst._cmd_confirmed.get(0) is None

# coding=utf-8
"""Bus scheduling and interlock behaviour for actuator_paired_bus.

The interesting logic is the bus worker: it must never energize the Open and
Close relays at the same moment, must never make or break a selector contact
while the bus is live, and must merge end-stop targets into a single run so an
emergency close of every window finishes in one pass.

These tests drive the real ``_Bus._run_batch`` with real ``OutputModule``
instances (constructed in testing mode, options injected, relay calls recorded)
rather than a re-implementation, so a regression in the scheduler is caught.
"""
from types import SimpleNamespace

import pytest

from aot.outputs.actuator_paired_bus import (
    OUTPUT_INFORMATION,
    OutputModule,
    _Bus,
)
from aot.outputs.paired_actuator_common import (
    PAIRED_ACTUATOR_OUTPUT_TYPES,
    is_paired_actuator,
)

# travel_time() clamps to a 1 s minimum, so the tests keep full-stroke times
# realistic and instead command SHORT strokes: a 20% move at 1 s/stroke runs for
# 0.2 s. Run times, not travel times, are what the stage planner works on.
TRAVEL_SEC = 1.0


@pytest.fixture(autouse=True)
def _isolate_from_services(monkeypatch):
    """Keep the unit under test off the database and the measurement store."""
    monkeypatch.setattr(
        'aot.outputs.actuator_paired_bus.add_measurements_influxdb',
        lambda *args, **kwargs: None)

    def _plain_logger(self, testing=False, name=None, output_dev=None):
        import logging
        self.logger = logging.getLogger('test.{}'.format(name or 'paired_bus'))

    # The real one reads the log level out of the AoT database.
    monkeypatch.setattr(
        'aot.outputs.base_output.AbstractOutput.setup_logger', _plain_logger)


def make_member(unique_id, selector, open_ref, close_ref, log,
                position=0.0, travel_open=TRAVEL_SEC, travel_close=TRAVEL_SEC,
                end_stop=True, invert=False):
    """A real OutputModule with its options injected and its relays recorded."""
    output = SimpleNamespace(
        unique_id=unique_id, name=unique_id, output_type='actuator_paired_bus',
        latitude=None, longitude=None, location_source='manual',
        log_level_debug=False)

    member = OutputModule(output, testing=True)
    member.unique_id = unique_id
    member.output = output
    member.output_states = {0: False}
    member._position_pct = position
    member.options_channels = {
        'selector_output_id': {0: selector},
        'output_open_id': {0: open_ref},
        'output_close_id': {0: close_ref},
        'travel_time_open_sec': {0: travel_open},
        'travel_time_close_sec': {0: travel_close},
        'end_stop_overrun': {0: end_stop},
        'invert_direction': {0: invert},
        'allow_parallel_same_direction': {0: True},
        # Zeroed so the tests exercise ordering, not wall-clock dwells.
        'selector_settle_sec': {0: 0.0},
        'reverse_pause_sec': {0: 0.0},
        'batch_window_sec': {0: 0.0},
        'min_command_interval_sec': {0: 0.0},
        'confirm_timeout_sec': {0: 1.0},
        'startup_force_off': {0: False},
    }

    member.set_custom_channel_option = lambda *args, **kwargs: None
    member.relay_on = lambda ref, duration=0.0: log.append(('on', ref))
    member.relay_off = lambda ref: log.append(('off', ref))
    member.wait_confirm = lambda refs, want_on: True
    member.relay_reports_on = lambda ref: False
    return member


def run_batch(members, targets):
    """Seed a bus with targets and run one batch synchronously."""
    bus = _Bus('test-bus')
    for member in members:
        bus._members[member.unique_id] = member
    bus._requests = {member.unique_id: targets[member.unique_id]
                     for member in members if member.unique_id in targets}
    bus._run_batch()
    return bus


def bus_runs(log, ref):
    """Number of complete on/off cycles recorded for a relay."""
    return sum(1 for entry in log if entry == ('on', ref))


def assert_never_both_on(log, ref_a, ref_b):
    """The two bus relays must never be energized at the same moment."""
    live = set()
    for action, ref in log:
        if ref not in (ref_a, ref_b):
            continue
        if action == 'on':
            live.add(ref)
            assert live != {ref_a, ref_b}, (
                "Open and Close were energized simultaneously: {}".format(log))
        else:
            live.discard(ref)


# ── module metadata ──────────────────────────────────────────────────────────
def test_output_name_unique():
    assert OUTPUT_INFORMATION['output_name_unique'] == 'actuator_paired_bus'


def test_output_types_value():
    assert OUTPUT_INFORMATION['output_types'] == ['value']


def test_single_value_channel():
    # One Output per actuator: the env coordinator keys a control profile by
    # Output id, so a multi-channel module would leave all but one uncontrolled.
    assert list(OUTPUT_INFORMATION['channels_dict']) == [0]
    assert 'value' in OUTPUT_INFORMATION['channels_dict'][0]['types']


def test_required_options_present():
    ids = {option['id'] for option in OUTPUT_INFORMATION['custom_channel_options']}
    must = {
        'actuator_kind', 'selector_output_id',
        'output_open_id', 'output_close_id',
        'travel_time_open_sec', 'travel_time_close_sec',
        'end_stop_overrun', 'allow_parallel_same_direction',
        'move_step_pct', 'last_position_pct', 'calib_direction',
    }
    assert must.issubset(ids), "missing: {}".format(must - ids)


def test_bus_registry_is_shared_across_separately_loaded_copies():
    """AoT loads an output module afresh per Output; the bus must still be shared.

    load_module_from_file() builds a new module object on every call and never
    registers it in sys.modules, so a registry declared inside
    actuator_paired_bus.py is private to each Output rather than process-wide.
    Four windows on one relay pair each ended up with their own _Bus and drove the
    shared relay on their own schedule — four overlapping ON commands, and the
    first window to finish switched the bus off underneath the other three
    (observed on the local stack). The registry therefore lives in
    paired_actuator_bus_scheduler, which is reached by normal import.
    """
    import aot.outputs.actuator_paired_bus as reference
    from aot.utils.modules import load_module_from_file

    copy_a, status_a = load_module_from_file(reference.__file__, 'outputs')
    copy_b, status_b = load_module_from_file(reference.__file__, 'outputs')
    assert status_a == 'success' and status_b == 'success'
    assert copy_a is not copy_b, "expected two independent module objects"

    key = 'test-shared-bus-key'
    assert copy_a.get_bus(key) is copy_b.get_bus(key)
    assert copy_a.get_bus(key) is reference.get_bus(key)


def test_registered_as_paired_actuator():
    # Consumers dispatch on this set; forgetting to register would silently drop
    # the module out of env-control, the geo 3-way popup and the output form.
    assert 'actuator_paired_bus' in PAIRED_ACTUATOR_OUTPUT_TYPES
    assert 'actuator_paired' in PAIRED_ACTUATOR_OUTPUT_TYPES
    assert is_paired_actuator('actuator_paired_bus')
    assert not is_paired_actuator('on_off_gpio')


# ── switching discipline ─────────────────────────────────────────────────────
def test_selector_engages_before_bus_and_releases_after():
    log = []
    member = make_member('w1', 'sel1', 'busOpen', 'busClose', log, position=80.0)
    run_batch([member], {'w1': 100.0})

    assert log == [
        ('on', 'sel1'),
        ('on', 'busOpen'),
        ('off', 'busOpen'),
        ('off', 'sel1'),
    ], log


def test_bus_not_energized_when_selector_does_not_confirm():
    log = []
    member = make_member('w1', 'sel1', 'busOpen', 'busClose', log, position=80.0)
    # Selector never reports on; the bus must stay dead.
    member.wait_confirm = lambda refs, want_on: 'sel1' not in refs

    run_batch([member], {'w1': 100.0})

    assert ('on', 'busOpen') not in log
    assert ('off', 'sel1') in log


def test_opposite_relay_found_on_is_cleared_before_driving():
    log = []
    member = make_member('w1', 'sel1', 'busOpen', 'busClose', log, position=80.0)
    # Something outside this module (manual toggle, Trigger, power-cut default)
    # left the close relay live.
    stale = {'busClose': True}
    member.relay_reports_on = lambda ref: stale.get(ref, False)

    def _off(ref):
        stale[ref] = False
        log.append(('off', ref))
    member.relay_off = _off

    run_batch([member], {'w1': 100.0})

    assert ('off', 'busClose') in log, log
    assert log.index(('off', 'busClose')) < log.index(('on', 'busOpen')), log


# ── interlock across actuators ───────────────────────────────────────────────
def test_open_and_close_actuators_never_overlap():
    log = []
    opener = make_member('w1', 'sel1', 'busOpen', 'busClose', log, position=80.0)
    closer = make_member('w2', 'sel2', 'busOpen', 'busClose', log, position=20.0)

    run_batch([opener, closer], {'w1': 100.0, 'w2': 0.0})

    assert_never_both_on(log, 'busOpen', 'busClose')
    # Closing is the safety-relevant direction and runs first.
    assert log.index(('on', 'busClose')) < log.index(('on', 'busOpen')), log


def test_inverted_actuator_does_not_share_a_stage():
    log = []
    normal = make_member('w1', 'sel1', 'busOpen', 'busClose', log, position=80.0)
    # Same logical direction, opposite physical relay — must not run together.
    inverted = make_member('w2', 'sel2', 'busOpen', 'busClose', log,
                           position=80.0, invert=True)

    run_batch([normal, inverted], {'w1': 100.0, 'w2': 100.0})

    assert_never_both_on(log, 'busOpen', 'busClose')
    assert bus_runs(log, 'busOpen') >= 1
    assert bus_runs(log, 'busClose') >= 1


# ── staging ──────────────────────────────────────────────────────────────────
def test_end_stop_targets_merge_into_one_bus_run():
    log = []
    near = make_member('w1', 'sel1', 'busOpen', 'busClose', log, position=20.0)
    far = make_member('w2', 'sel2', 'busOpen', 'busClose', log, position=50.0)

    run_batch([near, far], {'w1': 0.0, 'w2': 0.0})

    # Both are heading for the limit switch, so one bus run closes everything —
    # this is what makes an emergency close-all finish in a single pass.
    assert bus_runs(log, 'busClose') == 1, log
    assert ('on', 'sel1') in log and ('on', 'sel2') in log


def test_end_stop_merge_disabled_without_limit_switch():
    log = []
    near = make_member('w1', 'sel1', 'busOpen', 'busClose', log,
                       position=20.0, end_stop=False)
    far = make_member('w2', 'sel2', 'busOpen', 'busClose', log,
                      position=50.0, end_stop=False)

    run_batch([near, far], {'w1': 0.0, 'w2': 0.0})

    # Without a limit switch the nearer actuator must stop on time, so the bus is
    # cut and restarted instead of overrunning it into a stall.
    assert bus_runs(log, 'busClose') == 2, log


def test_partial_targets_stage_with_bus_off_between():
    log = []
    short = make_member('w1', 'sel1', 'busOpen', 'busClose', log)
    long = make_member('w2', 'sel2', 'busOpen', 'busClose', log)

    run_batch([short, long], {'w1': 20.0, 'w2': 50.0})

    assert bus_runs(log, 'busOpen') == 2, log
    # The short actuator's selector is released while the bus is de-energized,
    # between the two runs — never under load.
    first_off = log.index(('off', 'busOpen'))
    second_on = log.index(('on', 'busOpen'), first_off)
    release = log.index(('off', 'sel1'))
    assert first_off < release < second_on, log


def test_position_recorded_after_move():
    log = []
    member = make_member('w1', 'sel1', 'busOpen', 'busClose', log, position=80.0)

    run_batch([member], {'w1': 100.0})

    assert member._position_pct == pytest.approx(100.0)
    assert member.output_states[0] == pytest.approx(100.0)


def test_calibrated_travel_time_takes_effect_without_a_reload():
    """A freshly calibrated travel time must be visible to the running module.

    set_custom_channel_option() only writes the database, while options_channels is
    built once at construction. Before save_option() existed, calibrating produced
    a stored travel time the module could not see: travel_time() fell back to its
    60 s default and the next move drove the motor for the wrong duration (observed
    on the local stack — a 100%→50% move ran the bus 30 s instead of 5.3 s).
    """
    log = []
    member = make_member('w1', 'sel1', 'busOpen', 'busClose', log,
                         travel_open=0.0, travel_close=0.0)
    saved = {}
    member.set_custom_channel_option = lambda ch, key, value: saved.__setitem__(key, value)

    assert member.travel_time('open') == 60.0  # uncalibrated fallback

    member.save_option('travel_time_open_sec', 12.0)  # what calib_stop does

    assert saved['travel_time_open_sec'] == 12.0  # persisted
    assert member.travel_time('open') == 12.0     # and visible in-memory


def test_already_at_target_does_not_touch_the_bus():
    log = []
    member = make_member('w1', 'sel1', 'busOpen', 'busClose', log, position=50.0)

    run_batch([member], {'w1': 50.0})

    assert log == [], log

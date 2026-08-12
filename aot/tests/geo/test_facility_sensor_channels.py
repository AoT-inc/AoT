# coding=utf-8
"""A sensor fitting can read several channels of one device.

A temperature/humidity probe is one box reporting two numbers, and the model has
always carried ``channel_measurements`` as an array for it. The picker did not
survive a refactor: on 2026-08-01 (``70d72d1``) wiring moved out of the fitting
inspector into the component table, the inspector's rows were pinned shut with
``#facility-3d-inspector .fi-dup {display:none !important}``, and the single
``<select>`` that replaced them in the table could only ever hold one channel.
The array stayed in the data and in the backend, so nothing broke loudly — the
capability just became unreachable, and a sensor that already had two channels
could not be edited at all: the table refused it and sent the user to the
inspector row that CSS forbids from ever showing.

These pin the parts of that story that are cheap to check statically.
"""
import os
import re


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS = os.path.join(ROOT, 'aot_flask', 'static', 'js')
SENSOR_UI = os.path.join(JS, 'geo', 'facility', 'sensor-ui.js')
DESIGN_JS = os.path.join(JS, 'geo', 'aot-facility-design.js')
CSS       = os.path.join(ROOT, 'aot_flask', 'static', 'css', 'pages', 'geo-facility.css')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


class TestTheTableOffersEveryChannel:
    def test_channel_cell_is_a_multi_picker_not_a_single_select(self):
        src = _read(SENSOR_UI)
        assert 'data-channel-btn' in src, \
            'the channel cell must open the multi-channel picker'
        assert not re.search(r'<select[^>]*data-channel\b', src), \
            'a single <select> for channels can only ever hold one — that is the bug'

    def test_no_dead_end_pointing_at_the_hidden_inspector(self):
        # The old cell gave up on multi-channel sensors and sent the user to a
        # panel that CSS hides for good.
        assert 'edit in the inspector' not in _read(SENSOR_UI)

    def test_picker_groups_by_device(self):
        # A fitting reads one device, so the ticks have to say which box they
        # belong to and switching device has to move the fitting wholesale.
        src = _read(SENSOR_UI)
        assert 'FAC_INPUT_DEVICES' in src, 'the picker needs the device-grouped list'
        assert 'ch-group' in src, 'channels must be grouped under their device'
        body = src[src.index('function _openChannelPicker('):]
        body = body[:body.index('\n  }\n')]
        assert 'f.input_id' in body, \
            'ticking a channel on another device must move the fitting, not mix two'


class TestClearingChannelsLeavesNothingBehind:
    def test_patch_does_not_fabricate_a_row_when_given_the_array(self):
        # patchFitting keeps channel_measurements[0] in step with the top-level
        # fields. Clearing arrives as {channel_measurements: [], measurement_id:
        # null}; without this guard the sync pushed an empty row back in and the
        # sensor ended up with one channel whose id was null.
        src = _read(DESIGN_JS)
        i = src.index('patchFitting: function')
        body = src[i:src.index('\n    }', i)]
        assert "!('channel_measurements' in props)" in body, \
            'a caller that passes the array itself must not be second-guessed'


class TestThePickerIsActuallyVisible:
    def test_floating_panels_sit_above_the_drawer(self):
        # These panels are appended to <body> to escape the drawer's scrolling.
        # At the dropdown level they render behind it — in the DOM, measurable,
        # and invisible, which is exactly how this went unnoticed.
        css = _read(CSS)
        i = css.index('.fac-dropdown-panel {')
        rule = css[i:css.index('}', i)]
        assert 'var(--aot-z-popover)' in rule, \
            'a picker opened from inside the drawer must outrank the modal layer'

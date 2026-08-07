# coding=utf-8
"""The shared Output-state classifier must not turn 'no data' into 'off'.

From the 2026-08-07 audit. aot-output-state.js opens by declaring that fault
is "NOT a fake off" -- and then folded undefined into 'off' anyway. That is
what an unreachable daemon looked like on screen: /outputstate answered {},
every lookup missed, and every channel rendered a confident "Inactive". The
operator saw a farm that was calmly switched off rather than a server it could
not reach.

'unknown' is deliberately distinct from 'fault' as well. 'fault' means the
DEVICE did not answer -- a real, confirmed problem with that valve. 'unknown'
means WE could not ask, so the device may be perfectly fine; alarming on it
would cry wolf every time the daemon restarts.

Runs the real file under node rather than reimplementing it in Python -- a
reimplementation would drift from the shipped behaviour, which is the class of
bug this file exists to prevent.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = (Path(__file__).resolve().parents[1] /
      'aot_flask' / 'static' / 'js' / 'common' / 'aot-output-state.js')

pytestmark = pytest.mark.skipif(
    shutil.which('node') is None, reason='node is required to run the classifier')


def classify_many(raws_js):
    """Load the real module in node and classify each raw value."""
    script = f"""
      const root = {{}};
      {JS.read_text().replace("typeof window !== 'undefined' ? window : this", "root")}
      const out = ({raws_js}).map(function (r) {{
        const c = root.AoTOutputState.classify(r);
        return {{kind: c.kind, isOn: c.isOn, isFault: c.isFault,
                cssClass: c.cssClass, label: root.AoTOutputState.label(r)}};
      }});
      console.log(JSON.stringify(out));
    """
    proc = subprocess.run(['node', '-e', script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_missing_data_is_unknown_not_off():
    """The regression: undefined (key absent) and null (RPC returned None)."""
    results = classify_many('[undefined, null]')

    for got in results:
        assert got['kind'] == 'unknown', \
            f"missing data classified as {got['kind']!r} -- a fake off"
        assert got['isOn'] is False
        assert got['isFault'] is False, \
            "'we could not ask' must not be reported as a device fault"
        assert got['cssClass'] == 'unknown-background'


def test_unknown_reads_as_unknown_not_inactive():
    assert classify_many('[undefined]')[0]['label'] == 'Unknown'


def test_a_real_off_is_still_off():
    """The fix must not make genuine off-states ambiguous."""
    for got in classify_many("['off', false]"):
        assert got['kind'] == 'off'
        assert got['label'] == 'Inactive'
        assert got['cssClass'] == 'inactive-background'


def test_the_other_states_are_untouched():
    on, pending, fault, duty = classify_many("['on', 'pending', 'fault', 42]")

    assert on['kind'] == 'on' and on['isOn'] is True
    assert pending['kind'] == 'pending'
    assert fault['kind'] == 'fault' and fault['isFault'] is True
    assert duty['kind'] == 'on' and duty['isOn'] is True


def test_an_all_empty_aggregate_is_unknown():
    """Card-level version of the same lie: an empty /outputstate response
    painted every card a confident 'inactive'."""
    script = f"""
      const root = {{}};
      {JS.read_text().replace("typeof window !== 'undefined' ? window : this", "root")}
      const empty = root.AoTOutputState.aggregate([]);
      const allNull = root.AoTOutputState.aggregate([null, undefined]);
      const withOn = root.AoTOutputState.aggregate([null, 'on']);
      console.log(JSON.stringify({{empty: empty.kind, allNull: allNull.kind,
                                   withOn: withOn.kind, emptyFault: empty.isFault}}));
    """
    proc = subprocess.run(['node', '-e', script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)

    assert got['empty'] == 'unknown'
    assert got['allNull'] == 'unknown'
    assert got['emptyFault'] is False, "no data is not a device fault"
    assert got['withOn'] == 'on', "real data must still win over the gaps"


def test_every_consumer_clears_the_new_class():
    """A cssClass that no consumer removes stays painted on forever.

    aot-output-state.js carries this warning in its own header, from when
    'fault-background' was added and stuck to rows that had recovered.
    """
    root = Path(__file__).resolve().parents[1] / 'aot_flask'
    consumers = [
        root / 'templates' / 'pages' / 'output.html',
        root / 'templates' / 'pages' / 'function.html',
        root / 'static' / 'js' / 'widgets' / 'AoT_map' / 'aot-map-widget-vector.js',
    ]

    for path in consumers:
        text = path.read_text()
        # Only the sites that clear the sibling state classes need it.
        if 'inactive-background' not in text or 'classList.remove' not in text:
            continue
        assert 'unknown-background' in text, (
            f"{path.name} clears the other state classes but not "
            f"'unknown-background', so it will stick once applied")


def test_every_page_requests_the_same_classifier_version():
    """All ?v= cache-busters for this file must agree.

    Found the hard way on 2026-08-07: the classifier was fixed but the ?v=
    stayed at 8, so the browser kept serving the cached old file and the fix
    was invisible in the UI while every unit test passed. A partial bump is
    worse still -- some pages would classify 'unknown' and others 'off' in the
    same session.
    """
    import re

    root = Path(__file__).resolve().parents[1]
    versions = {}
    for path in list(root.rglob('*.html')) + list(root.rglob('*.py')):
        if 'aot-output-state.js?v=' not in path.read_text(errors='ignore'):
            continue
        for v in re.findall(r'aot-output-state\.js\?v=([\w.]+)',
                            path.read_text(errors='ignore')):
            versions.setdefault(v, []).append(path.name)

    assert versions, "no versioned reference to the classifier was found"
    assert len(versions) == 1, (
        f"the classifier is requested at several versions at once: "
        f"{ {v: sorted(set(f)) for v, f in versions.items()} }")


def test_the_new_class_is_defined_in_css():
    css = (Path(__file__).resolve().parents[1] / 'aot_flask' / 'static' /
           'css' / 'aot-base.css').read_text()
    assert '.unknown-background' in css, \
        "classify() hands out a class with no stylesheet rule behind it"

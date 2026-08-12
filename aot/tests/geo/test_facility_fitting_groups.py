# coding=utf-8
"""Linked groups of envelope-generated fittings ("연결됨").

Components the envelope generates in mirrored pairs — a side window on each
wall, a roof vent on each slope, a reinforcement panel on each side — are one
component repeated, so an edit to any of them has to reach the rest. Two ways
that has broken, both silent:

  * the mirror side was part of the group key, so the two halves of a pair were
    never in the same group. On a single-unit house each half was a group of
    one, which also hid the "Linked" row entirely — the option looked broken
    because it was never offered.
  * a size edit reached the group's members but the detachment from automatic
    geometry did not, leaving them hand-sized yet still auto-tracked. The next
    envelope regeneration overwrote exactly those members, which reads as
    "I resized one roof vent and the others snapped back".

Both live in JavaScript, so these read the sources. They pin the two rules that
regressed, not the whole mechanism.
"""
import os
import re


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRIDGE = os.path.join(ROOT, 'aot_flask', 'static', 'js', 'geo', 'facility',
                      'facility-3d-bridge.js')
FITTINGS = os.path.join(ROOT, 'aot_flask', 'static', 'js', 'geo',
                        'aot-facility-design.js')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


class TestMirroredPairsShareAGroup:
    # Variables holding "which side of the mirror is this" at the point the
    # group key is built. A key that interpolates one of these splits a pair.
    SIDE_VARS = ('w.id', 'p.sideId', 'sd', 'w.side', 'side')

    def test_no_link_group_is_keyed_by_mirror_side(self):
        keys = re.findall(r'link_group:\s*(.+)', _read(BRIDGE))
        assert keys, 'no link_group assignments found — did the file move?'
        offenders = []
        for expr in keys:
            expr = expr.rstrip(',').strip()
            for var in self.SIDE_VARS:
                # match the variable as a whole operand, not as a substring of
                # another name (st.id must not trip on 'sd')
                if re.search(r'(^|[^\w.])' + re.escape(var) + r'($|[^\w])', expr):
                    offenders.append((expr, var))
        assert not offenders, (
            'mirrored components must share one link_group; these keys still '
            'split by side: %r' % offenders)

    def test_reinforcement_groups_by_axis_not_by_side(self):
        # The two side walls are a pair and the two gable ends are a pair, but a
        # side wall and a gable end are not — their sizes come from different
        # dimensions (L×eaveH vs unitWidth×apexH). One group per axis, never one
        # group for all four, and never one group per side.
        src = _read(BRIDGE)
        decl = re.search(r"var axisGroup\s*=\s*(.+?);", src, re.S)
        assert decl, 'reinforcement must build its group key as axisGroup'
        expr = decl.group(1)
        assert "'x'" in expr and "'y'" in expr, (
            'axisGroup must resolve to an x pair or a y pair, got: %r' % expr)
        # all three reinforcement branches (x_neg, x_pos, gable) use it
        assert src.count('link_group: axisGroup') == 3, (
            'every reinforcement branch must use the axis key, found %d'
            % src.count('link_group: axisGroup'))


class TestEditsCarryDetachment:
    def test_sync_group_propagates_auto_geom(self):
        src = _read(FITTINGS)
        body = src[src.index('function _syncGroup('):]
        body = body[:body.index('\n  }')]
        assert '_auto_geom' in body, (
            '_syncGroup writes a hand-set size onto its group members; without '
            'carrying the source\'s _auto_geom=false they stay auto-tracked and '
            'the next envelope regeneration reverts them')

    def test_position_propagation_carries_auto_geom(self):
        src = _read(FITTINGS)
        body = src[src.index('function _onTransform('):]
        body = body[:body.index('\n    function ')]
        assert re.search(r'moved\s*&&\s*f\._auto_geom\s*===\s*false', body), (
            'members that receive a hand-set position must leave automatic '
            'geometry with the source — and only those that actually moved')

    def test_auto_restore_returns_the_whole_group(self):
        src = _read(FITTINGS)
        body = src[src.index('setAutoGeom: function'):]
        body = body[:body.index('\n    },')]
        assert 'link_group' in body, (
            'the group leaves automatic geometry together, so "back to '
            'automatic" has to bring it back together')

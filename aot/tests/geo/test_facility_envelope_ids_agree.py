# coding=utf-8
"""The two envelope-fitting generators must name the same component the same.

A facility's envelope components are generated in two places:

  * ``facility-3d-bridge.js`` — the design page. Its ids are the ones that get
    persisted, because a component the user edits by hand is saved under its id
    (see FittingsUI.read).
  * ``aot-facility-3d.js`` — every view built from saved data: the map overlay
    on the design page and the dashboard map widget.

When those disagree nothing can tell that a saved row and a generated item are
the same vent, so both get drawn — the component in its edited size next to the
same component in its default size. That is what the map widget showed. The two
lists are merged by id (``_mergeFittings``), which only works while the naming
agrees, and a rename on either side is invisible at runtime: no error, just a
second copy of the greenhouse's windows.

Every id the render-side generator emits must therefore also come out of the
editor's. The reverse is not required — the editor generates a few families the
render side does not model yet.
"""
import os
import re


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EDITOR = os.path.join(ROOT, 'aot_flask', 'static', 'js', 'geo', 'facility',
                      'facility-3d-bridge.js')
RENDER = os.path.join(ROOT, 'aot_flask', 'static', 'js', 'widgets',
                      'AoT_facility', 'aot-facility-3d.js')

# leading literal of each generated envelope id, e.g. "env_roof_vent_outer_b"
_ID_LITERAL = re.compile(r"id:\s*'(env_[^']*)'")


def _prefixes(path):
    with open(path, encoding='utf-8') as fh:
        return set(_ID_LITERAL.findall(fh.read()))


class TestEnvelopeIdsAgree:
    def test_render_side_ids_are_a_subset_of_the_editor_ids(self):
        editor, render = _prefixes(EDITOR), _prefixes(RENDER)
        assert editor, 'no envelope ids found in the editor generator'
        assert render, 'no envelope ids found in the render generator'
        stray = sorted(render - editor)
        assert not stray, (
            'these ids exist only on the render side, so a saved edit can never '
            'be matched to them and the component gets drawn twice: %s' % stray)

    def test_the_families_that_exist_on_both_sides_still_do(self):
        # A shrinking render side is not an error (a family may be dropped), but
        # the shared core is what the merge depends on — losing it silently would
        # bring the duplicates back for those components.
        render = _prefixes(RENDER)
        for core in ('env_roof_vent_outer_b', 'env_side_vent_outer_u',
                     'env_curtain_shade_b', 'env_reinforcement_'):
            assert core in render, '%s no longer generated render-side' % core


class TestSavedRowsWinOverGenerated:
    def test_merge_keeps_one_row_per_id(self):
        with open(RENDER, encoding='utf-8') as fh:
            src = fh.read()
        body = src[src.index('function _mergeFittings('):]
        body = body[:body.index('\n  }')]
        assert 'seen' in body and 'return' in body, \
            '_mergeFittings must drop generated items whose id is already saved'
        # and it must be what feeds both the openings and the fitting meshes
        assert src.count('_mergeFittings(facility.fittings, envFittings)') == 1
        assert 'P.buildFacilityMeshGroup(facility, MAT, allFittings)' in src, \
            'the cover openings must be punched from the merged list too'

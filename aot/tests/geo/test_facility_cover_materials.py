# coding=utf-8
"""A cover material has to exist in three places at once.

Picking one in the envelope form sets a key that travels to:

  * ``facility_calc.MATERIALS`` — the U-value and light transmittance the
    capacity figures are computed from;
  * ``core/materials.js`` (and its inline mirror in ``aot-facility-3d.js``) —
    the colour and density the model is drawn with;
  * the picker lists in ``aot-facility-design.js`` — where the user chooses it.

A key missing from any of them fails silently: an absent material falls back to
vinyl_double, so the facility is drawn as clear vinyl and costed as clear vinyl
while the form says concrete. Nothing errors, and the heating figure is simply
wrong. These tests hold the three lists to each other.
"""
import os
import re


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS = os.path.join(ROOT, 'aot_flask', 'static', 'js')
MATERIALS_JS = os.path.join(JS, 'widgets', 'AoT_facility', 'core', 'materials.js')
VIEWER_JS    = os.path.join(JS, 'widgets', 'AoT_facility', 'aot-facility-3d.js')
DESIGN_JS    = os.path.join(JS, 'geo', 'aot-facility-design.js')
TEMPLATE     = os.path.join(ROOT, 'aot_flask', 'templates', 'pages', 'geo',
                            'geo_facility.html')

# Added 2026-08-12 on request: opaque covers, where previously every material
# was a glazing. They are the ones most likely to be half-added.
OPAQUE = ('film_white_opaque', 'film_black', 'film_grey',
          'sandwich_panel', 'concrete', 'brick')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _js_keys(path, table_start):
    """Keys of an object literal that begins at `table_start`."""
    src = _read(path)
    i = src.index(table_start)
    j = src.index('};', i)
    return set(re.findall(r'^\s*([a-z_0-9]+)\s*:', src[i:j], re.M))


def _picker_keys(list_name):
    src = _read(DESIGN_JS)
    i = src.index('var %s = [' % list_name)
    j = src.index('];', i)
    return set(re.findall(r"v:\s*'([^']+)'", src[i:j]))


def _python_materials():
    from aot.aot_flask.geo.facility_calc import MATERIALS
    return MATERIALS


class TestEveryOfferedMaterialIsBacked:
    def test_pickers_only_offer_materials_the_calculator_knows(self):
        known = set(_python_materials())
        for lst in ('COVERS_OUTER', 'COVERS_INNER'):
            missing = sorted(_picker_keys(lst) - known)
            assert not missing, (
                '%s offers %s, which facility_calc.MATERIALS has no U-value '
                'for — they would be costed as vinyl_double' % (lst, missing))

    def test_pickers_only_offer_materials_the_renderer_knows(self):
        drawn = _js_keys(MATERIALS_JS, 'const _COVER_OPTS = {')
        for lst in ('COVERS_OUTER', 'COVERS_INNER'):
            missing = sorted(_picker_keys(lst) - drawn)
            assert not missing, (
                '%s offers %s, which core/materials.js has no colour for — '
                'they would be drawn as clear vinyl' % (lst, missing))

    def test_the_inline_mirror_matches_the_shared_table(self):
        # aot-facility-3d.js carries a fallback copy for when core/materials.js
        # is not loaded (the dashboard widgets). A copy that drifts is a copy
        # that draws a different building.
        assert _js_keys(MATERIALS_JS, 'const _COVER_OPTS = {') == \
               _js_keys(VIEWER_JS, 'const _CO = {')

    def test_every_picker_label_is_translatable(self):
        # Raw keys used to be shown as labels; new ones must not reintroduce that.
        src = _read(DESIGN_JS)
        i = src.index('var COVERS_OUTER = [')
        j = src.index('];', src.index('var COVERS_INNER = ['))
        for label in re.findall(r"l:\s*([^,\n]+)", src[i:j]):
            assert label.strip().startswith('_T('), \
                'cover label %s is not wrapped for translation' % label.strip()


class TestOpaqueMaterials:
    def test_all_present_everywhere(self):
        known  = set(_python_materials())
        drawn  = _js_keys(MATERIALS_JS, 'const _COVER_OPTS = {')
        outer  = _picker_keys('COVERS_OUTER')
        for m in OPAQUE:
            assert m in known, '%s missing from facility_calc.MATERIALS' % m
            assert m in drawn, '%s missing from core/materials.js' % m
            assert m in outer, '%s is not offered on the outer cover' % m

    def test_opaque_means_zero_transmittance(self):
        mats = _python_materials()
        for m in OPAQUE:
            assert mats[m]['transmittance'] == 0.0, (
                '%s is an opaque material — letting light through it would '
                'feed a solar gain that is not there' % m)

    def test_colour_is_ordered_by_absorptance(self):
        # The only term that separates the three films. If they ever collapse to
        # one value the picker is offering three names for the same facility.
        mats = _python_materials()
        white = mats['film_white_opaque']['absorptance']
        grey  = mats['film_grey']['absorptance']
        black = mats['film_black']['absorptance']
        assert white < grey < black, \
            'white %s / grey %s / black %s must absorb in that order' % (white, grey, black)

    def test_insulated_panel_beats_every_glazing(self):
        mats = _python_materials()
        glazing = [v['u'] for k, v in mats.items() if v['transmittance'] > 0]
        assert mats['sandwich_panel']['u'] < min(glazing), \
            'an insulated panel that does not insulate better than glass is wrong'

    def test_labels_are_in_the_i18n_dict(self):
        html = _read(TEMPLATE)
        for m in OPAQUE:
            assert 'mat_%s:' % m in html, \
                'mat_%s has no entry in the page i18n dict' % m

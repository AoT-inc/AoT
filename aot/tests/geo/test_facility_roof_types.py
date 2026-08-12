# coding=utf-8
"""A roof type has to be taught to every place that draws or measures a roof.

The cross-section is rebuilt in four separate JavaScript functions — two shape
builders (the parametric module and the inline fallback in the 3D viewer) and
two surface samplers (apex height, height-at-t, normal-at-t, once per file).
A type missing from one of them does not fail: the branch falls through to the
arch default, so the model is drawn as an arch, or the roof vents float above a
surface computed for a shape that is not there.

'gable2' — one bay carrying two gables — is the type these pin. Adding another
means extending ROOF_TYPES here and following the failures.
"""
import os
import re


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS = os.path.join(ROOT, 'aot_flask', 'static', 'js')

PARAMETRIC = os.path.join(JS, 'widgets', 'AoT_facility', 'core', 'parametric.js')
VIEWER     = os.path.join(JS, 'widgets', 'AoT_facility', 'aot-facility-3d.js')
BRIDGE     = os.path.join(JS, 'geo', 'facility', 'facility-3d-bridge.js')
TEMPLATE   = os.path.join(ROOT, 'aot_flask', 'templates', 'pages', 'geo',
                          'geo_facility.html')

# roof types that must be handled everywhere, beyond the 'arch' fallback
ROOF_TYPES = ('gable2',)

# (file, function) pairs that branch on the roof type
SHAPE_SITES = [
    (PARAMETRIC, 'buildMultiSpanShape'),
    (PARAMETRIC, '_roofProfilePoints'),
    (VIEWER,     '_buildMultiSpanShape'),
]
SURFACE_SITES = [
    (VIEWER, '_roofYatT'),
    (VIEWER, '_roofNormalAtT'),
    (BRIDGE, '_roofYatT'),
    (BRIDGE, '_roofNormalAtT'),
]


def _code(path):
    """File contents with // comments stripped.

    Every one of these branches is explained in a comment that names the roof
    type, so checking the raw text would pass on the prose alone.
    """
    with open(path, encoding='utf-8') as fh:
        return re.sub(r'//[^\n]*', '', fh.read())


def _fn_body(path, name):
    src = _code(path)
    m = re.search(r'function\s+' + re.escape(name) + r'\s*\(', src)
    assert m, '%s not found in %s' % (name, os.path.basename(path))
    i = src.index('{', m.end() - 1)
    depth, j = 0, i
    while j < len(src):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                break
        j += 1
    return src[i:j + 1]


class TestEveryRoofSiteKnowsTheType:
    def test_shape_builders(self):
        for path, fn in SHAPE_SITES:
            body = _fn_body(path, fn)
            for rt in ROOF_TYPES:
                assert rt in body, (
                    "%s() in %s does not build '%s' — it would silently fall "
                    "through to the arch default"
                    % (fn, os.path.basename(path), rt))

    def test_surface_samplers(self):
        for path, fn in SURFACE_SITES:
            body = _fn_body(path, fn)
            for rt in ROOF_TYPES:
                assert rt in body, (
                    "%s() in %s does not sample '%s' — roof vents would be "
                    "placed against a surface the model does not have"
                    % (fn, os.path.basename(path), rt))

    def test_apex_height_covers_the_type(self):
        # roofApexY is not a function: one file assigns it in an expression, the
        # other through an if/else. Read everything between its first mention
        # and the sampler that follows it in both files.
        for path in (VIEWER, BRIDGE):
            src = _code(path)
            i = src.index('roofApexY')
            stmt = src[i:src.index('function _gableT', i)]
            for rt in ROOF_TYPES:
                assert rt in stmt, (
                    "roofApexY in %s does not cover '%s' — ridge-mounted vents "
                    "would float or sink" % (os.path.basename(path), rt))


class TestTheTypeIsOfferedInTheForm:
    def test_option_exists(self):
        with open(TEMPLATE, encoding='utf-8') as fh:
            html = fh.read()
        for rt in ROOF_TYPES:
            assert 'value="%s"' % rt in html, \
                "'%s' is implemented but not offered in the roof-type picker" % rt

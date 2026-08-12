# coding=utf-8
"""GeoMap.viewport() — where a map's saved camera actually lives.

The latitude/longitude columns look like the answer and are not: no write path
fills them, so they are NULL on every real map while the live camera sits in
``state_json`` ('center' as {lat, lng}). A reader that trusts the columns sends
every map to the same default coordinates, and switching maps in the facility
page's picker then looks like it did nothing at all. These pin the resolution
order and the "unknown means unknown" contract the callers rely on.
"""
import ast
import json
import os


class _FakeMap(object):
    """GeoMap.viewport() only touches state_json and the two columns."""

    from aot.databases.models.geo import GeoMap
    viewport = GeoMap.viewport
    state_dict = GeoMap.state_dict

    def __init__(self, state=None, latitude=None, longitude=None, zoom=None):
        self.state_json = json.dumps(state) if state is not None else None
        self.latitude = latitude
        self.longitude = longitude
        self.zoom = zoom


class TestViewportResolution:
    def test_state_json_center_dict_wins(self):
        m = _FakeMap(state={'center': {'lat': 35.85, 'lng': 126.86}, 'zoom': 16.85},
                     latitude=None, longitude=None, zoom=12)
        assert m.viewport() == (35.85, 126.86, 16.85)

    def test_state_json_center_list_is_lat_lng(self):
        # api_geo_designs_list has always read index 0 as latitude — keep it.
        m = _FakeMap(state={'center': [35.85, 126.86], 'zoom': 15})
        assert m.viewport() == (35.85, 126.86, 15)

    def test_columns_used_when_state_has_no_center(self):
        m = _FakeMap(state={'zoom': 14}, latitude=37.5, longitude=127.0, zoom=12)
        assert m.viewport() == (37.5, 127.0, 14)

    def test_column_zoom_used_when_state_has_no_zoom(self):
        m = _FakeMap(state={'center': {'lat': 1.0, 'lng': 2.0}}, zoom=11)
        assert m.viewport() == (1.0, 2.0, 11)

    def test_unknown_centre_stays_none(self):
        # Not a default coordinate: the caller decides (leave the camera alone,
        # fit to the map's shapes). Substituting Seoul here is the original bug.
        lat, lng, zoom = _FakeMap(state={}, zoom=12).viewport()
        assert lat is None and lng is None
        assert zoom == 12

    def test_broken_state_json_does_not_raise(self):
        m = _FakeMap()
        m.state_json = '{not json'
        assert m.viewport() == (None, None, None)


class TestReadersUseViewport:
    """The columns must not creep back into the readers."""

    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))

    def test_facility_template_reads_viewport(self):
        path = os.path.join(self.ROOT, 'aot_flask', 'templates', 'pages',
                            'geo', 'geo_facility.html')
        with open(path, encoding='utf-8') as fh:
            html = fh.read()
        assert 'm.viewport()' in html, 'map picker must resolve via viewport()'
        for dead in ('m.latitude', 'm.longitude'):
            assert dead not in html, (
                '%s is NULL on every map — use viewport()' % dead)

    def test_designs_list_endpoint_reads_viewport(self):
        path = os.path.join(self.ROOT, 'aot_flask', 'routes_geo.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == 'api_geo_designs_list')
        body = ast.dump(fn)
        assert "attr='viewport'" in body, \
            'api_geo_designs_list must resolve the camera via GeoMap.viewport()'

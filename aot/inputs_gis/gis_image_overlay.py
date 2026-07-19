# coding=utf-8
"""
gis_image_overlay.py
User-uploaded aerial/drone photo overlay provider.

Unlike the tile providers (OSM, RainViewer, ...) this layer renders a single
static, georeferenced image as a MapLibre ``image`` source defined by four
ground-corner coordinates. The image and its corner coordinates are stored in the
GeoLayer ``options`` JSON (set by the upload route, refined by the corner-drag UI).

The provider itself is intentionally thin: the heavy lifting (EXIF/XMP extraction,
footprint computation) lives in ``aot.utils.geo_photo_georef`` and runs in the
upload route. Here we just surface the stored ``image_url`` / ``coordinates`` /
``opacity`` to the frontend in the shape the map loader expects.

@phase active
@stability experimental
@dependency AbstractGisInput
"""
import json

from flask_babel import lazy_gettext as lg

from aot.inputs_gis.base_input_gis import AbstractGisInput

INPUT_INFORMATION = {
    'input_name_unique': 'gis_image_overlay',
    'input_manufacturer': lg('AoT'),
    'message': lg(
        'Overlay a user-uploaded aerial or drone photo on the map. On upload, '
        'GPS and camera pose embedded in the photo (EXIF/XMP) are used to place '
        'it automatically; the four corners can then be dragged to fine-tune the '
        'fit against map features.'),
    'country': ['GL'],
    'input_name': 'Aerial Photo Overlay',
    'input_library': 'gis_image_overlay',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': '',
    'attribution': '',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'overlay',
    'layer_type': 'image',
    'dependencies_module': [],
    'time_enabled': False,
    # Rendered by a dedicated panel (file upload + corner-drag map), not the
    # generic option form. Declared here so values persist through geo_layer_mod.
    'custom_options': [
        {
            'id': 'image_url',
            'type': 'hidden',
            'default': '',
            'name': 'Image URL',
        },
        {
            'id': 'coordinates',
            'type': 'hidden',
            'default': '',
            'name': 'Corner coordinates (JSON)',
        },
        {
            'id': 'opacity',
            'type': 'hidden',
            'default': '0.85',
            'name': 'Opacity',
        },
        {
            'id': 'meta',
            'type': 'hidden',
            'default': '',
            'name': 'Extracted metadata (JSON)',
        },
    ],
}


class InputModule(AbstractGisInput):
    """
    Static georeferenced image overlay (drone/aerial photo).

    @phase active
    @stability experimental
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'image'
        self.layer_category = 'overlay'
        self.default_url = ''
        self.attribution = ''

    def get_url(self):
        """The 'url' of an image overlay is the served path of the uploaded image."""
        return self.get_custom_option('image_url', '') or ''

    def _parse_coordinates(self):
        """Return the stored 4-corner coordinate list, or None if unset/invalid."""
        raw = self.get_custom_option('coordinates', '')
        if not raw:
            return None
        if isinstance(raw, (list, tuple)):
            coords = raw
        else:
            try:
                coords = json.loads(raw)
            except (TypeError, ValueError):
                return None
        # Expect 4 [lng, lat] pairs.
        if (isinstance(coords, list) and len(coords) == 4
                and all(isinstance(p, (list, tuple)) and len(p) == 2 for p in coords)):
            return [[float(p[0]), float(p[1])] for p in coords]
        return None

    def _parse_opacity(self):
        try:
            val = float(self.get_custom_option('opacity', 0.85))
        except (TypeError, ValueError):
            val = 0.85
        return max(0.0, min(1.0, val))

    def get_leaflet_options(self):
        """
        Carry image-overlay specifics to the frontend via the layer's ``options``
        dict, which the map loader reads.

        Two render modes:
          - 'image' (small images): a single georeferenced ``image`` source. The
            ``image_url`` is the downscaled preview when one exists, else the
            original — keeping a large original off the GPU while still allowing
            a quick view before/without tiling.
          - 'tiled' (large images): an XYZ tile pyramid (``tile_url`` +
            min/maxzoom). The frontend renders it as a raster tile source.
        """
        options = super(InputModule, self).get_leaflet_options()
        coords = self._parse_coordinates()
        if coords:
            options['coordinates'] = coords
        options['opacity'] = self._parse_opacity()

        render_mode = self.get_custom_option('render_mode', 'image') or 'image'
        tile_status = self.get_custom_option('tile_status', 'none') or 'none'
        options['render_mode'] = render_mode
        options['tile_status'] = tile_status

        if render_mode == 'tiled' and self.get_custom_option('tile_url', ''):
            options['tile_url'] = self.get_custom_option('tile_url', '')
            for k in ('minzoom', 'maxzoom'):
                v = self.get_custom_option(k, None)
                if v is not None and v != '':
                    try:
                        options[k] = int(v)
                    except (TypeError, ValueError):
                        pass
        else:
            # Image mode: prefer the downscaled preview as the rendered texture.
            preview = self.get_custom_option('preview_url', '') or ''
            if preview:
                options['image_url'] = preview
        return options

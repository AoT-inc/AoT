# coding=utf-8
"""
Lightweight timezone lookup API.

Returns the IANA timezone name for a device by its unique_id, with a
resolution chain matching aot.utils.device_tz.get_device_tz():

  device.timezone  →  resolve_tz_from_coords(lat, lon)  →  Misc.timezone  →  UTC
"""
import logging

import flask_login
from flask import jsonify
from flask_restx import Resource

from aot.aot_flask.api import api
from aot.aot_flask.api import default_responses
from aot.utils.device_tz import device_tz_name, resolve_tz_from_coords
from aot.utils.time_utils import get_timezone_name

logger = logging.getLogger(__name__)

ns_tz = api.namespace('timezone', description='Timezone resolution')


def _lookup_device(unique_id):
    """Search Input/Output/Controller/Function/Conditional/Trigger by unique_id."""
    from aot.databases.models import Input, Output
    from aot.databases.models.controller import CustomController
    from aot.databases.models.function import Function, Conditional, Trigger

    for model in (Input, Output, CustomController, Function, Conditional, Trigger):
        try:
            row = model.query.filter_by(unique_id=unique_id).first()
            if row is not None:
                return row
        except Exception:
            continue
    return None


@ns_tz.route('/device/<string:unique_id>')
@ns_tz.doc(security='apikey', responses=default_responses)
class DeviceTimezone(Resource):
    """Resolve the IANA timezone for a device."""

    @flask_login.login_required
    def get(self, unique_id):
        device = _lookup_device(unique_id)
        if device is None:
            return {'error': 'device not found'}, 404
        tz = device_tz_name(device)
        return {
            'unique_id': unique_id,
            'timezone': tz,
            'source': ('explicit' if getattr(device, 'timezone', None)
                       else ('coords' if getattr(device, 'latitude', None) is not None
                             else 'fallback'))
        }


@ns_tz.route('/coords')
@ns_tz.doc(security='apikey', responses=default_responses)
class CoordsTimezone(Resource):
    """Resolve IANA timezone from arbitrary lat/lon query string."""

    @flask_login.login_required
    def get(self):
        from flask import request
        try:
            lat = float(request.args.get('lat'))
            lon = float(request.args.get('lon'))
        except (TypeError, ValueError):
            return {'error': 'lat and lon required'}, 400
        tz = resolve_tz_from_coords(lat, lon) or get_timezone_name() or 'UTC'
        return {'lat': lat, 'lon': lon, 'timezone': tz}


@ns_tz.route('/fallback')
@ns_tz.doc(security='apikey', responses=default_responses)
class FallbackTimezone(Resource):
    """Return the system fallback timezone (Misc.timezone or UTC)."""

    def get(self):
        return {'timezone': get_timezone_name() or 'UTC'}

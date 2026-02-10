# coding=utf-8
import json
import traceback
from datetime import datetime

from flask import request, current_app
from flask_restx import Resource, abort, fields
from flask_login import login_required
from sqlalchemy import or_

from aot.databases.models import GeoMap, GeoShape, GeoSetting, Input, Output
from aot.aot_flask.api import api, default_responses
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_general

ns_geo = api.namespace('geo', description='Geo Information Services')

# --- Models ---
geo_overlay_model = api.model('GeoOverlay', {
    'type': fields.String(description='FeatureCollection'),
    'features': fields.List(fields.Raw, description='GeoJSON Features'),
    'level_id': fields.Integer(description='Hierarchy Level (1=Site, 2=Zone, 3=Device)'),
    'channel_id': fields.String(description='Logical Channel ID'),
    'map_uuid': fields.String(required=True, description='Target Map UUID'),
})

geo_design_model = api.model('GeoDesign', {
    'map_uuid': fields.String(description='Map UUID (Optional for create)'),
    'name': fields.String(required=True, description='Map Name'),
})

# --- Resources ---

# Conflicting endpoints removed.
# Logic has been moved to aot/aot_flask/routes_geo.py to support new Hybrid Data Strategy and updated GeoShape model.

# @ns_geo.route('/designs')
# class GeoDesigns(Resource):
#     ...

# @ns_geo.route('/overlays')
# class GeoOverlays(Resource):
#     ...


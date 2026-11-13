# coding=utf-8
import flask_login
from flask import request
from flask_restx import Resource, fields, abort

from aot.aot_flask.api import api, default_responses
from aot.aot_flask.design_engine.irrigation_processor import IrrigationProcessor
from aot.aot_flask.utils import utils_general

ns_design = api.namespace('design', description='Irrigation Design Tools')

@ns_design.route('/rows')
@ns_design.doc(security='apikey', responses=default_responses)
class DesignRows(Resource):
    """Generate Irrigation Rows."""

    @flask_login.login_required
    def post(self):
        """
        Generate rows based on polygon boundary, spacing, and angle.
        Payload:
        {
            "boundary": { ... GeoJSON Geometry ... },
            "spacing": 1.2,
            "angle": 0
        }
        """
        # MVP Permissions: View Settings allows trying it out? Or Edit?
        # Let's say Edit settings for now.
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
            
        try:
            payload = request.get_json(force=True)
            boundary = payload.get('boundary')
            baseline = payload.get('baseline') # Parse baseline
            spacing = payload.get('spacing', 1.2)
            angle = payload.get('angle', 0)
            offset = payload.get('offset', 0)
            
            try:
                spacing = float(spacing)
                angle = float(angle)
                offset = float(offset)
            except ValueError:
                 return {'message': 'Invalid numbers'}, 400
            
            if not boundary:
                abort(400, "Boundary polygon required")
                
            # Call Engine
            result_fc = IrrigationProcessor.generate_rows(boundary, spacing, angle, offset, baseline)
            
            if "error" in result_fc:
                abort(500, result_fc["error"])
                
            # Calculate BOM immediately for MVP convenience
            bom = IrrigationProcessor.calculate_bom_lite(result_fc)
            
            return {
                "rows": result_fc,
                "bom": bom
            }, 200
            
        except Exception as e:
            abort(400, str(e))

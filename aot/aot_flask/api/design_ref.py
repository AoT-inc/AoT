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


@ns_design.route('/list')
@ns_design.doc(security='apikey', responses=default_responses)
class DesignList(Resource):
    """List saved designs."""
    @flask_login.login_required
    def get(self):
        try:
            from aot.databases.models.irrigation import IrrigationDesign
            designs = IrrigationDesign.query.order_by(IrrigationDesign.updated_at.desc()).all()
            return {
                "designs": [{
                    "id": d.unique_id,
                    "name": d.name,
                    "created_at": d.created_at.isoformat() if d.created_at else "",
                    "updated_at": d.updated_at.isoformat() if d.updated_at else ""
                } for d in designs]
            }, 200
        except Exception as e:
            return {"error": str(e)}, 500


@ns_design.route('/save')
@ns_design.doc(security='apikey', responses=default_responses)
class DesignSave(Resource):
    """Save current design."""
    @flask_login.login_required
    def post(self):
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
            
        try:
            payload = request.get_json(force=True)
            name = payload.get('name', 'New Design')
            
            # Extract JSON strings or objects
            import json
            def ensure_string(val):
                if isinstance(val, (dict, list)):
                    return json.dumps(val)
                return val or '{}'

            from aot.databases.models.irrigation import IrrigationDesign
            
            design = IrrigationDesign(
                name=name,
                boundary_json=ensure_string(payload.get('boundary')),
                rows_json=ensure_string(payload.get('rows')),
                sprinklers_json=ensure_string(payload.get('sprinklers')),
                config_json=ensure_string(payload.get('config'))
            )
            design.save()
            
            return {"message": "Saved successfully", "id": design.unique_id}, 200
            
        except Exception as e:
            abort(400, str(e))


@ns_design.route('/<string:design_id>')
@ns_design.doc(security='apikey', responses=default_responses)
class DesignItem(Resource):
    """Load or Delete a design."""
    @flask_login.login_required
    def get(self, design_id):
        from aot.databases.models.irrigation import IrrigationDesign
        design = IrrigationDesign.query.filter_by(unique_id=design_id).first()
        if not design:
            abort(404, "Design not found")
            
        return {
            "id": design.unique_id,
            "name": design.name,
            "boundary": design.boundary_json,
            "rows": design.rows_json,
            "sprinklers": design.sprinklers_json,
            "config": design.config_json
        }, 200

    @flask_login.login_required
    def delete(self, design_id):
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
            
        from aot.databases.models.irrigation import IrrigationDesign
        design = IrrigationDesign.query.filter_by(unique_id=design_id).first()
        if design:
            design.delete()
            return {"message": "Deleted"}, 200
        abort(404, "Design not found")

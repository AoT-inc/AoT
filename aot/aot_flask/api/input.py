# coding=utf-8
import logging
import traceback

import flask_login
from flask_accept import accept
from flask_restx import Resource
from flask_restx import abort
from flask_restx import fields

from aot.databases.models import DeviceMeasurements
from aot.databases.models import Input
from aot.databases.models import InputChannel
from aot.databases.models.input import InputChannelSchema
from aot.databases.models.input import InputSchema
from aot.databases.models.measurement import DeviceMeasurementsSchema
from aot.aot_client import DaemonControl
from aot.aot_flask.api import api
from aot.aot_flask.api import default_responses
from aot.aot_flask.api.sql_schema_fields import device_measurement_fields
from aot.aot_flask.api.sql_schema_fields import input_channel_fields
from aot.aot_flask.api.sql_schema_fields import input_fields
from aot.aot_flask.api.utils import get_from_db
from aot.aot_flask.api.utils import return_list_of_dictionaries
from aot.aot_flask.utils import utils_general

logger = logging.getLogger(__name__)

ns_input = api.namespace('inputs', description='Input operations')

input_single_fields = api.model('Input Status Fields', {
    'input settings': fields.Nested(input_fields),
    'input channels': fields.List(fields.Nested(input_channel_fields)),
    'device measurements': fields.List(
        fields.Nested(device_measurement_fields)),
})

input_list_fields = api.model('Input Fields List', {
    'input settings': fields.List(fields.Nested(input_fields)),
    'input channels': fields.List(fields.Nested(input_channel_fields))
})


@ns_input.route('/')
@ns_input.doc(security='apikey', responses=default_responses)
class Inputs(Resource):
    """Input information."""

    @accept('application/vnd.aot.v1+json')
    @ns_input.marshal_with(input_list_fields)
    @flask_login.login_required
    def get(self):
        """Show all input settings."""
        if not utils_general.user_has_permission('view_settings'):
            abort(403)
        try:
            list_data = get_from_db(InputSchema, Input)
            list_channels = get_from_db(InputChannelSchema, InputChannel)
            if list_data:
                return {
                    'input settings': list_data,
                    'input channels': list_channels
                }, 200
        except Exception:
            abort(500,
                  message='An exception occurred',
                  error=traceback.format_exc())


@ns_input.route('/<string:unique_id>')
@ns_input.doc(
    security='apikey',
    responses=default_responses,
    params={'unique_id': 'The unique ID of the input'}
)
class SettingsInputsUniqueID(Resource):
    """Interacts with input settings in the SQL database"""

    @accept('application/vnd.aot.v1+json')
    @ns_input.marshal_with(input_single_fields)
    @flask_login.login_required
    def get(self, unique_id):
        """Show the settings for an input."""
        if not utils_general.user_has_permission('view_settings'):
            abort(403)
        try:
            # 1. Fetch Input Settings
            list_data = get_from_db(InputSchema, Input, unique_id=unique_id)
            if not list_data:
                abort(404, message=f"Input {unique_id} not found")

            # 2. Fetch Channels (Safe Mode)
            list_channels = []
            try:
                measure_schema = InputChannelSchema()
                list_channels = return_list_of_dictionaries(
                    measure_schema.dump(
                        InputChannel.query.filter_by(
                            input_id=unique_id).all(), many=True))
            except Exception as e:
                logger.error(f"Error fetching channels for input {unique_id}: {e}")
                list_channels = []

            # 3. Fetch Measurements (Safe Mode)
            list_measurements = []
            try:
                measure_schema = DeviceMeasurementsSchema()
                list_measurements = return_list_of_dictionaries(
                    measure_schema.dump(
                        DeviceMeasurements.query.filter_by(
                            device_id=unique_id).all(), many=True))
            except Exception as e:
                logger.error(f"Error fetching measurements for input {unique_id}: {e}")
                list_measurements = []

            return {
                'input settings': list_data,
                'input channels': list_channels,
                'device measurements': list_measurements
            }, 200
        except Exception as e:
            # Check if it was a manual abort (404/403)
            if hasattr(e, 'code') and e.code in [403, 404]:
                raise e
                
            logger.error(f"Unexpected error in /api/inputs/{unique_id}: {traceback.format_exc()}")
            abort(500,
                  message='An exception occurred',
                  error=str(e))


@ns_input.route('/<string:unique_id>/force-measurement')
@ns_input.doc(
    security='apikey',
    responses=default_responses,
    params={'unique_id': 'The unique ID of the input.'}
)
class InputsUniqueID(Resource):
    """Input with Unique ID."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def post(self, unique_id):
        """Force an input to acquire measurements."""
        if not utils_general.user_has_permission('edit_controllers'):
            abort(403)

        try:
            control = DaemonControl()
            return_ = control.input_force_measurements(unique_id)
            if return_[0]:
                return {'message': return_[1]}, 460
            else:
                return {'message': return_[1]}, 200
        except Exception:
            abort(500,
                  message='An exception occurred',
                  error=traceback.format_exc())

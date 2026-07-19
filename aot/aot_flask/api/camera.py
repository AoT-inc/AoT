# coding=utf-8
import logging
import os
import traceback

import flask_login
from flask import send_file
from flask_accept import accept
from flask_restx import Resource, abort

from aot.config import PATH_CAMERAS
from aot.databases.models import Camera
from aot.devices.camera import camera_record
from aot.aot_flask.api import api, default_responses
from aot.aot_flask.utils import utils_general
from aot.utils.system_pi import assure_path_exists

logger = logging.getLogger(__name__)

ns_camera = api.namespace(
    'cameras', description='Camera operations')


@ns_camera.route('/capture_image/<string:unique_id>')
@ns_camera.doc(
    security='apikey',
    responses=default_responses,
    params={
        'unique_id': 'The unique ID of the camera'
    }
)
class CameraGetLastImage(Resource):
    """Returns the last image acquired by a camera"""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self, unique_id):
        """get last camera image."""
        if not utils_general.user_has_permission('view_camera'):
            abort(403)

        camera = Camera.query.filter(Camera.unique_id == unique_id).first()

        if not camera:
            abort(422, custom='No camera with ID found')

        tmp_filename = f'{camera.unique_id}_tmp.jpg'

        path, filename = camera_record('photo', camera.unique_id, tmp_filename=tmp_filename)
        if not path and not filename:
            abort(422, custom="Could not acquire image.")
        else:
            try:
                image_path = os.path.join(path, filename)
                return send_file(image_path, mimetype='image/jpeg')
            except Exception:
                abort(500,
                      message='An exception occurred',
                      error=traceback.format_exc())


@ns_camera.route('/last_image/<string:unique_id>/<string:img_type>')
@ns_camera.doc(
    security='apikey',
    responses=default_responses,
    params={
        'unique_id': 'The unique ID of the camera',
        'img_type': 'The type of image to return, either "still" or "timelapse"'
    }
)
class CameraGetLastImage(Resource):
    """Returns the last image acquired by a camera"""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self, unique_id, img_type):
        """get last camera image."""
        if not utils_general.user_has_permission('view_camera'):
            abort(403)

        camera = Camera.query.filter(Camera.unique_id == unique_id).first()

        if not camera:
            abort(422, custom='No camera with ID found')
        if img_type not in ["still", "timelapse"]:
            abort(422, custom='Type not "still" or "timelapse"')

        (latest_img_still_ts,
         latest_img_still_size,
         latest_img_still,
         latest_img_tl_ts,
         latest_img_tl_size,
         latest_img_tl,
         time_lapse_imgs) = utils_general.get_camera_image_info()

        camera_path = assure_path_exists(
            os.path.join(PATH_CAMERAS, unique_id))

        path = ""
        filename = ""
        if img_type == 'still':
            filename = latest_img_still[unique_id]
            if camera.path_still:
                path = camera.path_still
            else:
                path = os.path.join(camera_path, img_type)
        elif img_type == 'timelapse':
            filename = latest_img_tl[unique_id]
            if camera.path_timelapse:
                path = camera.path_timelapse
            else:
                path = os.path.join(camera_path, img_type)
        else:
            abort(422, custom=f'Unknown image type: {img_type}')

        if path and os.path.isdir(path):
            files = (files for files in os.listdir(path)
                     if os.path.isfile(os.path.join(path, files)))
        else:
            files = []

        try:
            if filename and filename in files:
                path_file = os.path.join(path, filename)
                if os.path.abspath(path_file).startswith(path):
                    return send_file(path_file, mimetype='image/jpeg')

            return abort(500)
        except Exception:
            abort(500,
                  message='An exception occurred',
                  error=traceback.format_exc())


@ns_camera.route('/info/<string:unique_id>')
@ns_camera.doc(
    security='apikey',
    responses=default_responses,
    params={
        'unique_id': 'The unique ID of the camera'
    }
)
class CameraGetInfo(Resource):
    """Returns information about a specific camera"""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self, unique_id):
        """get camera information."""
        if not utils_general.user_has_permission('view_camera'):
            abort(403)

        camera = Camera.query.filter(Camera.unique_id == unique_id).first()

        if not camera:
            abort(422, custom='No camera with ID found')

        return {
            'unique_id': camera.unique_id,
            'name': camera.name,
            'url_stream': camera.url_stream,
            'url_still': camera.url_still,
            'auth_username': camera.auth_username,
            'auth_password': camera.auth_password,
            'width': camera.width,
            'height': camera.height,
            'library': camera.library
        }

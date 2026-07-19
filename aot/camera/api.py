"""
Camera API Blueprint — Flask routes for the modernized camera system.
Connects CameraService, StreamHandler, TimelapseService, ConfigManager,
SecurityManager, and Diagnostics to HTTP endpoints.
"""
import logging
from flask import Blueprint, jsonify, request, Response
from typing import Optional

logger = logging.getLogger(__name__)

camera_api = Blueprint('camera_api', __name__, url_prefix='/api/camera')

# -- Service references (wired at app init) ----------------------------------
_camera_service = None
_stream_handler = None
_timelapse_service = None
_config_manager = None
_security_manager = None
_image_processor = None


def init_camera_api(
    camera_service,
    stream_handler,
    timelapse_service,
    config_manager,
    security_manager,
    image_processor
):
    """Wire service instances into the camera API blueprint at app startup.

    @phase active
    @stability stable
    @dependency CameraService, StreamHandler, TimelapseService, ConfigManager, SecurityManager, ImageProcessor
    """
    global _camera_service, _stream_handler, _timelapse_service
    global _config_manager, _security_manager, _image_processor
    _camera_service = camera_service
    _stream_handler = stream_handler
    _timelapse_service = timelapse_service
    _config_manager = config_manager
    _security_manager = security_manager
    _image_processor = image_processor


# ─── Camera CRUD ────────────────────────────────────────────────────

@camera_api.route('/list', methods=['GET'])
def list_cameras():
    """Return list of active camera IDs."""
    ids = _camera_service.list_cameras()
    return jsonify({'cameras': ids})


@camera_api.route('/status/<camera_id>', methods=['GET'])
def camera_status(camera_id: str):
    """Return status for a single camera."""
    backend = _camera_service.get_camera(camera_id)
    if not backend:
        return jsonify({'error': 'Camera not found'}), 404
    return jsonify({
        'camera_id': camera_id,
        'initialized': backend.is_initialized,
        'streaming': _stream_handler.is_streaming(camera_id),
        'timelapse_active': _timelapse_service.is_capturing(camera_id),
    })


# ─── Streaming ──────────────────────────────────────────────────────

@camera_api.route('/stream/<camera_id>', methods=['GET'])
def mjpeg_stream(camera_id: str):
    """Serve MJPEG stream for a camera."""
    backend = _camera_service.get_camera(camera_id)
    if not backend:
        return jsonify({'error': 'Camera not found'}), 404

    return Response(
        _stream_handler.get_mjpeg_stream(backend, camera_id),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@camera_api.route('/stream/<camera_id>/stop', methods=['POST'])
def stop_stream(camera_id: str):
    """Stop an active MJPEG stream."""
    _stream_handler.stop_stream(camera_id)
    return jsonify({'status': 'stopped', 'camera_id': camera_id})


# ─── Timelapse ──────────────────────────────────────────────────────

@camera_api.route('/timelapse/<camera_id>/start', methods=['POST'])
def start_timelapse(camera_id: str):
    """Start timelapse capture for a camera."""
    backend = _camera_service.get_camera(camera_id)
    if not backend:
        return jsonify({'error': 'Camera not found'}), 404

    interval = request.json.get('interval', 60) if request.json else 60
    ok = _timelapse_service.start_capture(camera_id, backend, interval)
    return jsonify({'started': ok, 'camera_id': camera_id})


@camera_api.route('/timelapse/<camera_id>/stop', methods=['POST'])
def stop_timelapse(camera_id: str):
    """Stop timelapse capture."""
    _timelapse_service.stop_capture(camera_id)
    return jsonify({'status': 'stopped', 'camera_id': camera_id})


@camera_api.route('/timelapse/<camera_id>/video', methods=['POST'])
def generate_timelapse_video(camera_id: str):
    """Generate timelapse video from captured frames."""
    fps = request.json.get('fps', 24) if request.json else 24
    path = _timelapse_service.create_video(camera_id, fps=fps)
    if path:
        return jsonify({'video_path': path})
    return jsonify({'error': 'No frames available'}), 404


# ─── Configuration ──────────────────────────────────────────────────

@camera_api.route('/config/<camera_id>', methods=['GET'])
def get_config(camera_id: str):
    """Get camera configuration."""
    config = _config_manager.get_config(camera_id)
    if not config:
        return jsonify({'error': 'Config not found'}), 404
    return jsonify({'camera_id': camera_id, 'config': vars(config)})


@camera_api.route('/config/presets', methods=['GET'])
def list_presets():
    """List available configuration presets."""
    presets = {k: v for k, v in _config_manager._presets.items()}
    return jsonify({'presets': presets})


# ─── Diagnostics ────────────────────────────────────────────────────

@camera_api.route('/diagnostics', methods=['GET'])
def diagnostics():
    """Get system diagnostics."""
    from .diagnostics import Diagnostics
    report = Diagnostics.get_camera_status_report(_camera_service)
    return jsonify(report)

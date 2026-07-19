# coding=utf-8
from typing import List, Dict
from flask_babel import lazy_gettext as lg

# === Modern unified backends ===
CAMERA_TYPES = {
    # Raspberry Pi
    'rpi_csi': {
        'type': 'rpi_csi',
        'display_name': 'Raspberry Pi CSI Camera Module',
        'description': lg('Raspberry Pi Camera Module v2/v3 (CSI interface)'),
        'category': 'modern',
        'platform': 'raspberry_pi',
        'backend': 'libcamera',
        'library': 'picamera2',
        'requirements': [
            ('pip-pypi', 'picamera2', 'picamera2'),
            ('pip-pypi', 'opencv-python', 'opencv-python>=4.8.0')
        ],
        'device_detection': 'libcamera-hello --list-cameras',
        'supported_features': ['high_fps', 'hardware_acceleration', 'hdr']
    },

    # General-purpose USB webcam
    'usb_webcam': {
        'type': 'usb_webcam',
        'display_name': lg('USB Webcam'),
        'description': lg('USB-connected webcam (general purpose)'),
        'category': 'modern',
        'platform': 'all',
        'backend': 'opencv',
        'library': 'opencv-python',
        'requirements': [
            ('pip-pypi', 'opencv-python', 'opencv-python>=4.8.0')
        ],
        'device_detection': 'v4l2-ctl --list-devices',
        'supported_features': ['auto_focus', 'auto_exposure']
    },

    # PC built-in webcam
    'builtin_webcam': {
        'type': 'builtin_webcam',
        'display_name': lg('Built-in Webcam'),
        'description': lg('Laptop/PC built-in webcam'),
        'category': 'modern',
        'platform': 'debian_pc',
        'backend': 'opencv',
        'library': 'opencv-python',
        'requirements': [
            ('pip-pypi', 'opencv-python', 'opencv-python>=4.8.0')
        ],
        'device_detection': 'v4l2-ctl --list-devices',
        'supported_features': ['auto_focus', 'auto_exposure']
    },

    # Virtual camera
    'virtual_camera': {
        'type': 'virtual_camera',
        'display_name': lg('Virtual Camera (v4l2loopback)'),
        'description': lg('v4l2loopback virtual camera device'),
        'category': 'modern',
        'platform': 'debian_pc',
        'backend': 'opencv',
        'library': 'opencv-python',
        'requirements': [
            ('pip-pypi', 'opencv-python', 'opencv-python>=4.8.0'),
            ('apt', 'v4l2loopback-dkms', 'v4l2loopback-dkms')
        ],
        'device_detection': 'v4l2-ctl --list-devices | grep v4l2loopback',
        'supported_features': ['custom_resolution', 'custom_fps']
    },

    # IP camera
    'ip_camera': {
        'type': 'ip_camera',
        'display_name': lg('IP Camera (ONVIF/RTSP)'),
        'description': lg('IP camera with ONVIF protocol support'),
        'category': 'modern',
        'platform': 'all',
        'backend': 'onvif',
        'library': 'python-onvif-zeep',
        'requirements': [
            ('pip-pypi', 'opencv-python', 'opencv-python>=4.8.0'),
            ('pip-pypi', 'python-onvif-zeep', 'python-onvif-zeep>=0.2.12')
        ],
        'device_detection': 'onvif_discovery',
        'supported_features': ['ptz', 'remote_access', 'high_resolution']
    },

    # Streaming URL
    'stream_url': {
        'type': 'stream_url',
        'display_name': lg('Streaming URL (RTSP/HTTP)'),
        'description': lg('RTSP/HTTP streaming URL'),
        'category': 'modern',
        'platform': 'all',
        'backend': 'opencv',
        'library': 'opencv-python',
        'requirements': [
            ('pip-pypi', 'opencv-python', 'opencv-python>=4.8.0')
        ],
        'device_detection': 'manual',
        'supported_features': ['remote_access', 'low_latency']
    },

    # Docker USB passthrough
    'usb_passthrough': {
        'type': 'usb_passthrough',
        'display_name': lg('Host USB Camera (Docker)'),
        'description': lg('USB camera on the Docker host (device passthrough)'),
        'category': 'modern',
        'platform': 'docker',
        'backend': 'opencv',
        'library': 'opencv-python',
        'requirements': [
            ('pip-pypi', 'opencv-python', 'opencv-python>=4.8.0')
        ],
        'device_detection': 'v4l2-ctl --list-devices',
        'docker_config': {
            'devices': ['/dev/video0:/dev/video0'],
            'privileged': False
        },
        'supported_features': ['auto_focus', 'auto_exposure']
    },

    # === Legacy backends (kept for compatibility) ===
    'fswebcam': {
        'type': 'fswebcam',
        'display_name': 'USB Webcam (fswebcam) [Legacy]',
        'description': lg('USB webcam capture via fswebcam CLI'),
        'category': 'legacy',
        'platform': 'all',
        'backend': 'fswebcam',
        'library': 'fswebcam',
        'requirements': [
            ('apt', 'fswebcam', 'fswebcam')
        ],
        'deprecated': True,
        'recommended_alternative': 'usb_webcam',
        'deprecation_message': lg('fswebcam is no longer recommended. Use the OpenCV-based USB webcam instead.')
    },

    'raspistill': {
        'type': 'raspistill',
        'display_name': 'Raspberry Pi Camera (raspistill) [Legacy]',
        'description': lg('CSI camera capture via raspistill CLI'),
        'category': 'legacy',
        'platform': 'raspberry_pi',
        'backend': 'raspistill',
        'library': 'raspistill',
        'requirements': [
            ('apt', 'libraspberrypi-bin', 'libraspberrypi-bin')
        ],
        'deprecated': True,
        'recommended_alternative': 'rpi_csi',
        'deprecation_message': lg('raspistill is no longer recommended. Use the libcamera-based CSI camera instead.')
    },

    'picamera': {
        'type': 'picamera',
        'display_name': 'Raspberry Pi Camera (picamera v1) [Legacy]',
        'description': lg('CSI camera via the picamera v1 library'),
        'category': 'legacy',
        'platform': 'raspberry_pi',
        'backend': 'picamera',
        'library': 'picamera',
        'requirements': [
            ('pip-pypi', 'picamera', 'picamera')
        ],
        'deprecated': True,
        'recommended_alternative': 'rpi_csi',
        'deprecation_message': lg('picamera v1 is no longer recommended. Use picamera2 instead.')
    },

    'url_urllib': {
        'type': 'url_urllib',
        'display_name': 'URL Stream (urllib) [Legacy]',
        'description': lg('URL image/stream capture via urllib'),
        'category': 'legacy',
        'platform': 'all',
        'backend': 'urllib',
        'library': 'urllib',
        'requirements': [],  # Built-in library
        'deprecated': True,
        'recommended_alternative': 'stream_url',
        'deprecation_message': lg('urllib-based streaming is no longer recommended. Use the OpenCV-based stream instead.')
    },

    'url_requests': {
        'type': 'url_requests',
        'display_name': 'URL Stream (requests) [Legacy]',
        'description': lg('URL image/stream capture via the requests library'),
        'category': 'legacy',
        'platform': 'all',
        'backend': 'requests',
        'library': 'requests',
        'requirements': [
            ('pip-pypi', 'requests', 'requests')
        ],
        'deprecated': True,
        'recommended_alternative': 'stream_url',
        'deprecation_message': lg('requests-based streaming is no longer recommended. Use the OpenCV-based stream instead.')
    }
}

CAPTURE_MODES = {
    'snapshot': {
        'name': 'Photo (Snapshot)',
        'description': 'Single image capture',
        'settings': ['resolution', 'quality', 'format']
    },
    'timelapse': {
        'name': 'Timelapse',
        'description': 'Interval image capture',
        'settings': ['resolution', 'interval', 'duration', 'format']
    },
    'video': {
        'name': 'Video',
        'description': 'Continuous video recording',
        'settings': ['resolution', 'fps', 'duration', 'codec']
    },
    'stream': {
        'name': 'Live Stream',
        'description': 'Real-time live streaming',
        'settings': ['resolution', 'fps', 'bitrate', 'protocol']
    }
}

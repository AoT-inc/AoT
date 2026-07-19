# coding=utf-8
"""
Camera-type specific dependencies for automatic installation.
Follows the AoT_ai widget dependency pattern.
"""

# (type, name, pip_install_string)
CAMERA_DEPENDENCIES = {
    'usb': [
        ('pip-pypi', 'opencv-python', 'opencv-python>=4.8.0')
    ],
    'csi': [
        ('pip-pypi', 'opencv-python', 'opencv-python>=4.8.0'),
        ('pip-pypi', 'picamera2', 'picamera2')
    ],
    'ip': [
        ('pip-pypi', 'opencv-python', 'opencv-python>=4.8.0'),
        ('pip-pypi', 'python-onvif-zeep', 'python-onvif-zeep>=0.2.12')
    ],
    'plant': [
        ('pip-pypi', 'plantcv', 'plantcv')
    ]
}

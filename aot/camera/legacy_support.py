# coding=utf-8

LEGACY_CAMERA_MAPPING = {
    'fswebcam':      {'new_type': 'usb_webcam',  'backend': 'opencv',    'legacy_backend': 'fswebcam'},
    'libcam':        {'new_type': 'rpi_csi',     'backend': 'libcamera', 'legacy_backend': None},
    'opencv':        {'new_type': 'usb_webcam',  'backend': 'opencv',    'legacy_backend': None},
    'picam':         {'new_type': 'rpi_csi',     'backend': 'libcamera', 'legacy_backend': 'picamera'},
    'raspistill':    {'new_type': 'rpi_csi',     'backend': 'libcamera', 'legacy_backend': 'raspistill'},
    'url_urllib':    {'new_type': 'stream_url',  'backend': 'opencv',    'legacy_backend': 'urllib'},
    'url_requests':  {'new_type': 'stream_url',  'backend': 'opencv',    'legacy_backend': 'requests'},
    'direct_stream': {'new_type': 'ip_camera',   'backend': 'onvif',     'legacy_backend': None}
}

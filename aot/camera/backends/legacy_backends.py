# coding=utf-8
import subprocess
import urllib.request
import logging
import numpy as np
import cv2
from aot.camera.backends.base import CameraBackend, CameraConfig, CameraError

logger = logging.getLogger(__name__)

class FswebcamBackend(CameraBackend):
    """Legacy backend using fswebcam CLI for USB webcam capture.

    @phase deprecated
    @stability frozen
    @see OpenCVBackend
    """

    def __init__(self):
        self.device = '/dev/video0'
        self.width = 1280
        self.height = 720
        self.temp_file = '/tmp/fswebcam_capture.jpg'

    def initialize(self, config: CameraConfig) -> bool:
        self.device = f'/dev/video{config.device_id}'
        self.width = config.width
        self.height = config.height
        return True

    def capture_image(self) -> np.ndarray:
        cmd = [
            'fswebcam', '-d', self.device,
            '-r', f'{self.width}x{self.height}',
            '--no-banner', self.temp_file
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise CameraError(f"fswebcam failed: {result.stderr.decode()}")
        return cv2.imread(self.temp_file)

class RaspistillBackend(CameraBackend):
    """Legacy backend using raspistill CLI for CSI camera capture.

    @phase deprecated
    @stability frozen
    @see LibcameraBackend
    """

    def __init__(self):
        self.width = 1920
        self.height = 1080
        self.temp_file = '/tmp/raspistill_capture.jpg'

    def initialize(self, config: CameraConfig) -> bool:
        self.width = config.width
        self.height = config.height
        return True

    def capture_image(self) -> np.ndarray:
        cmd = [
            'raspistill',
            '-w', str(self.width), '-h', str(self.height),
            '-o', self.temp_file, '-t', '1', '-n'
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise CameraError(f"raspistill failed: {result.stderr.decode()}")
        return cv2.imread(self.temp_file)

class PicameraBackend(CameraBackend):
    """Legacy backend using picamera v1 library for CSI camera capture.

    @phase deprecated
    @stability frozen
    @see LibcameraBackend
    """

    def __init__(self):
        self.camera = None

    def initialize(self, config: CameraConfig) -> bool:
        try:
            import picamera
            self.camera = picamera.PiCamera()
            self.camera.resolution = (config.width, config.height)
            self.camera.framerate = config.fps
            import time
            time.sleep(2)  # 카메라 워밍업
            return True
        except Exception as e:
            logger.error(f"picamera initialization failed: {e}")
            return False

    def capture_image(self) -> np.ndarray:
        import picamera.array
        with picamera.array.PiRGBArray(self.camera) as output:
            self.camera.capture(output, 'rgb')
            return cv2.cvtColor(output.array, cv2.COLOR_RGB2BGR)

    def release(self) -> None:
        if self.camera:
            self.camera.close()

class UrllibStreamBackend(CameraBackend):
    """Legacy backend using urllib for HTTP image stream capture.

    @phase deprecated
    @stability frozen
    @see OpenCVBackend
    """

    def __init__(self):
        self.url = None

    def initialize(self, config: CameraConfig) -> bool:
        self.url = config.stream_url
        return True

    def capture_image(self) -> np.ndarray:
        try:
            with urllib.request.urlopen(self.url, timeout=5) as response:
                image_data = response.read()
            nparr = np.frombuffer(image_data, np.uint8)
            return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except Exception as e:
            raise CameraError(f"Failed to fetch image from URL: {e}")

class RequestsStreamBackend(CameraBackend):
    """Legacy backend using requests library for HTTP image stream capture.

    @phase deprecated
    @stability frozen
    @see OpenCVBackend
    """

    def __init__(self):
        self.url = None
        self.session = None

    def initialize(self, config: CameraConfig) -> bool:
        import requests
        self.url = config.stream_url
        self.session = requests.Session()
        return True

    def capture_image(self) -> np.ndarray:
        try:
            response = self.session.get(self.url, timeout=5)
            response.raise_for_status()
            nparr = np.frombuffer(response.content, np.uint8)
            return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except Exception as e:
            raise CameraError(f"Failed to fetch image from URL: {e}")

    def release(self) -> None:
        if self.session:
            self.session.close()

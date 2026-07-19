import cv2
import time
import logging
from typing import Generator, Dict
from .backend import CameraBackend

logger = logging.getLogger(__name__)

class StreamHandler:
    """Manage active MJPEG video streams from camera backends for web consumption.

    @phase active
    @stability stable
    @dependency CameraBackend
    """
    
    def __init__(self):
        self._active_streams: Dict[str, bool] = {}

    def get_mjpeg_stream(self, backend: CameraBackend, camera_id: str, quality: int = 70) -> Generator[bytes, None, None]:
        """
        Produce an MJPEG stream as a generator.
        """
        self._active_streams[camera_id] = True
        logger.info(f"Starting MJPEG stream for {camera_id}")
        
        try:
            while self._active_streams.get(camera_id, False):
                frame = backend.capture_image()
                if frame is None:
                    continue

                # Encode to JPEG
                ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                if not ret:
                    continue

                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                
                # Small sleep to regulate FPS if needed
                # Real FPS control should ideally be in the backend
                time.sleep(0.01)
                
        except Exception as e:
            logger.error(f"Stream error for {camera_id}: {e}")
        finally:
            self.stop_stream(camera_id)
            logger.info(f"Stream stopped for {camera_id}")

    def stop_stream(self, camera_id: str) -> None:
        """Signal a stream to stop."""
        self._active_streams[camera_id] = False

    def is_streaming(self, camera_id: str) -> bool:
        """Check if a camera is currently being streamed."""
        return self._active_streams.get(camera_id, False)

    @property
    def active_stream_count(self) -> int:
        """Return number of currently active streams."""
        return sum(1 for v in self._active_streams.values() if v)

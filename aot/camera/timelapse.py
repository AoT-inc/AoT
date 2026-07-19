import cv2
import os
import time
import logging
import threading
from typing import Optional, Dict
from datetime import datetime
from .backend import CameraBackend

logger = logging.getLogger(__name__)

class TimelapseService:
    """Handle periodic image capture and compile captured frames into video files.

    @phase active
    @stability stable
    @dependency CameraBackend
    """
    
    def __init__(self, storage_root: str = "storage/timelapse"):
        self.storage_root = storage_root
        self._active_captures: Dict[str, threading.Event] = {}
        self._active_threads: Dict[str, threading.Thread] = {}
        
        if not os.path.exists(self.storage_root):
            os.makedirs(self.storage_root)

    def start_capture(self, camera_id: str, backend: CameraBackend, interval_seconds: int) -> bool:
        """Start a timelapse capture thread."""
        if camera_id in self._active_captures:
            logger.warning(f"Timelapse for {camera_id} already running.")
            return False

        stop_event = threading.Event()
        self._active_captures[camera_id] = stop_event
        
        thread = threading.Thread(
            target=self._capture_loop,
            args=(camera_id, backend, interval_seconds, stop_event),
            daemon=True
        )
        self._active_threads[camera_id] = thread
        thread.start()
        
        logger.info(f"Started timelapse for {camera_id} at {interval_seconds}s interval")
        return True

    def stop_capture(self, camera_id: str) -> None:
        """Stop a timelapse capture thread."""
        stop_event = self._active_captures.pop(camera_id, None)
        if stop_event:
            stop_event.set()
        
        thread = self._active_threads.pop(camera_id, None)
        if thread:
            thread.join(timeout=2.0)
        
        logger.info(f"Stopped timelapse for {camera_id}")

    def is_capturing(self, camera_id: str) -> bool:
        """Check if a timelapse capture is active for the given camera."""
        return camera_id in self._active_captures

    def create_video(self, camera_id: str, fps: int = 24) -> Optional[str]:
        """
        Compile captured images into a video file.
        """
        session_dir = os.path.join(self.storage_root, camera_id)
        if not os.path.exists(session_dir):
            logger.error(f"No captured images found for {camera_id}")
            return None

        images = sorted([img for img in os.listdir(session_dir) if img.endswith(".jpg")])
        if not images:
            return None

        output_path = os.path.join(self.storage_root, f"{camera_id}_{int(time.time())}.mp4")
        
        first_img = cv2.imread(os.path.join(session_dir, images[0]))
        height, width, _ = first_img.shape
        
        # Define codec and create VideoWriter
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

        try:
            for img_name in images:
                img_path = os.path.join(session_dir, img_name)
                frame = cv2.imread(img_path)
                out.write(frame)
        finally:
            out.release()
            
        logger.info(f"Timelapse video created: {output_path}")
        return output_path

    def _capture_loop(self, camera_id: str, backend: CameraBackend, interval: int, stop_event: threading.Event):
        """Loop for capturing images at intervals."""
        session_dir = os.path.join(self.storage_root, camera_id)
        if not os.path.exists(session_dir):
            os.makedirs(session_dir)
            
        while not stop_event.is_set():
            try:
                frame = backend.capture_image()
                if frame is not None:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"capture_{timestamp}.jpg"
                    img_path = os.path.join(session_dir, filename)
                    cv2.imwrite(img_path, frame)
                    logger.debug(f"Saved timelapse frame: {img_path}")
            except Exception as e:
                logger.error(f"Timelapse capture error for {camera_id}: {e}")
            
            # Wait for interval or stop signal
            stop_event.wait(timeout=interval)

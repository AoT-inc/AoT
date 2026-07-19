# coding=utf-8
import logging
import threading
import time
import os
from datetime import datetime
import cv2

logger = logging.getLogger(__name__)
CAMERA_STORAGE_PATH = os.getenv('AOT_CAMERA_STORAGE_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../storage/camera'))

class TimelapseThread(threading.Thread):
    """Background thread for periodic timelapse frame capture with optional video generation.

    @phase active
    @stability stable
    @dependency CameraService
    """

    def __init__(self, camera_id, camera_service, interval, duration, auto_video, settings):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self.camera_service = camera_service
        self.interval = interval
        self.duration = duration
        self.auto_video = auto_video
        self.settings = settings
        self.running = True
        self.captured_files = []

    def run(self):
        backend = self.camera_service.active_cameras.get(self.camera_id)
        if not backend:
            logger.error(f"Camera {self.camera_id} not found in active cameras")
            return

        start_time = time.time()
        capture_count = 0

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        timelapse_dir = os.path.join(CAMERA_STORAGE_PATH, f'timelapse_{self.camera_id}_{timestamp}')
        os.makedirs(timelapse_dir, exist_ok=True)

        while self.running:
            try:
                image = backend.capture_image()
                filename = f'frame_{capture_count:06d}.jpg'
                filepath = os.path.join(timelapse_dir, filename)
                cv2.imwrite(filepath, image, [cv2.IMWRITE_JPEG_QUALITY, 95])

                self.captured_files.append(filepath)
                capture_count += 1

                if self.duration > 0 and (time.time() - start_time) >= self.duration:
                    break

                # Sleep in small increments to allow responsive stopping
                sleep_end = time.time() + self.interval
                while self.running and time.time() < sleep_end:
                    time.sleep(0.5)
            except Exception as e:
                logger.exception(f"Timelapse capture error: {e}")
                time.sleep(min(self.interval, 5))

        logger.info(f"Timelapse completed: {capture_count} frames")

        if self.auto_video and self.captured_files:
            self._generate_video(timelapse_dir)

    def _generate_video(self, timelapse_dir):
        """Compile captured JPEG frames into an MP4 video."""
        try:
            output_file = os.path.join(timelapse_dir, 'timelapse_video.mp4')
            if not self.captured_files: return
            
            first_image = cv2.imread(self.captured_files[0])
            height, width = first_image.shape[:2]

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_file, fourcc, 30, (width, height))

            for filepath in self.captured_files:
                img = cv2.imread(filepath)
                if img is not None:
                    out.write(img)

            out.release()
            logger.info(f"Timelapse video created: {output_file}")
        except Exception as e:
            logger.exception(f"Video generation failed: {e}")

    def stop(self):
        """Signal the timelapse thread to stop."""
        self.running = False


class VideoRecordThread(threading.Thread):
    """Background thread for continuous video recording from a camera backend.

    @phase active
    @stability stable
    @dependency CameraService
    """

    def __init__(self, camera_id, camera_service, fps, duration, codec, settings):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self.camera_service = camera_service
        self.fps = fps
        self.duration = duration
        self.codec = codec
        self.settings = settings
        self.running = True

    def run(self):
        """Execute the video recording loop until stopped or duration expires."""
        backend = self.camera_service.active_cameras.get(self.camera_id)
        if not backend:
            logger.error(f"Camera {self.camera_id} not found in active cameras")
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(CAMERA_STORAGE_PATH, f'video_{self.camera_id}_{timestamp}.mp4')

        width = self.settings.get('width', 1920)
        height = self.settings.get('height', 1080)

        codec_map = {'h264': 'mp4v', 'h265': 'hev1', 'mjpeg': 'MJPG'}
        fourcc = cv2.VideoWriter_fourcc(*codec_map.get(self.codec, 'mp4v'))
        out = cv2.VideoWriter(filepath, fourcc, self.fps, (width, height))

        start_time = time.time()
        frame_count = 0
        frame_interval = 1.0 / self.fps

        while self.running:
            try:
                frame_start = time.time()
                frame = backend.capture_image()
                if frame is not None:
                    out.write(cv2.resize(frame, (width, height)))
                    frame_count += 1

                if self.duration > 0 and (time.time() - start_time) >= self.duration:
                    break

                # FPS control
                elapsed = time.time() - frame_start
                if elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)
            except Exception as e:
                logger.exception(f"Video recording error: {e}")
                time.sleep(0.1)

        out.release()
        logger.info(f"Video completed: {filepath}, {frame_count} frames")

    def stop(self):
        """Signal the video recording thread to stop."""
        self.running = False

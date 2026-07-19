import cv2
import numpy as np
import logging
import time
from typing import Optional, Dict, Any
from .models import PerformanceProfile, ProcessedImage

logger = logging.getLogger(__name__)

class ImageProcessor:
    """Process raw camera frames with enhancement, format conversion, and plant health analysis.

    @phase active
    @stability stable
    @dependency PerformanceProfile, PlantCV
    """
    
    def __init__(self, profile: PerformanceProfile):
        self.profile = profile
        self._plantcv_available = self._check_plantcv()
        
    def process_frame(self, frame: np.ndarray, config: Any) -> ProcessedImage:
        """
        Main pipeline to process a raw frame from a camera backend.
        Applies enhancements, calculates metrics, and packages into ProcessedImage.
        """
        processed_frame = frame.copy()
        
        # 1. Basic Enhancements (Always allowed or profile-dependent)
        if config.flip_h:
            processed_frame = cv2.flip(processed_frame, 1)
        if config.flip_v:
            processed_frame = cv2.flip(processed_frame, 0)
        if config.rotation != 0:
            if config.rotation == 90:
                processed_frame = cv2.rotate(processed_frame, cv2.ROTATE_90_CLOCKWISE)
            elif config.rotation == 180:
                processed_frame = cv2.rotate(processed_frame, cv2.ROTATE_180)
            elif config.rotation == 270:
                processed_frame = cv2.rotate(processed_frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        # 2. Advanced Enhancements (Profile dependent)
        if self.profile.enable_noise_reduction:
            processed_frame = cv2.fastNlMeansDenoisingColored(processed_frame, None, 10, 10, 7, 21)
            
        # 3. Plant Health Analysis (PlantCV)
        plant_metrics = None
        if self.profile.enable_plantcv and self._plantcv_available:
            plant_metrics = self.analyze_plant_health(processed_frame)

        # 4. Convert to bytes for ProcessedImage
        _, buffer = cv2.imencode('.jpg', processed_frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.profile.stream_quality])
        raw_data = buffer.tobytes()

        return ProcessedImage(
            raw_data=raw_data,
            format='jpeg',
            timestamp=time.time(),
            metadata={
                'width': processed_frame.shape[1],
                'height': processed_frame.shape[0],
                'channels': processed_frame.shape[2] if len(processed_frame.shape) > 2 else 1,
                'profile': self.profile.name
            },
            plant_metrics=plant_metrics
        )

    def analyze_plant_health(self, image: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Analyze plant health using PlantCV.
        """
        if not self._plantcv_available:
            return None
            
        try:
            from plantcv import plantcv as pcv
            # Simple PlantCV pipeline example: 
            # 1. Convert to HSV
            # 2. Threshold for green
            # 3. Calculate green area / total area
            
            # Note: This is an illustrative pipeline. In a real app, this would be more complex.
            device = 0 # PlantCV device counter
            
            # Convert to gray for basic analysis
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # Mocking some metrics for the demonstration
            # In a real implementation, we would use pcv.threshold.binary, pcv.analyze_object, etc.
            green_pixels = np.sum((image[:,:,1] > image[:,:,0]) & (image[:,:,1] > image[:,:,2]))
            total_pixels = image.shape[0] * image.shape[1]
            green_ratio = float(green_pixels) / total_pixels
            
            metrics = {
                'green_ratio': green_ratio,
                'health_index': green_ratio * 100, # Dummy index
                'status': 'healthy' if green_ratio > 0.1 else 'warning'
            }
            
            return metrics
        except Exception as e:
            logger.error(f"PlantCV analysis failed: {e}")
            return None

    def _check_plantcv(self) -> bool:
        """Check if PlantCV is installed."""
        try:
            import plantcv
            return True
        except ImportError:
            logger.debug("PlantCV not found.")
            return False

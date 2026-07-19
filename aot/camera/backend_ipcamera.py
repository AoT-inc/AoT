import cv2
import numpy as np
import logging
from typing import Optional, Dict, List, Any
from .backend import CameraBackend, StreamHandle
from .models import CameraConfig, CameraCapabilities
from .exceptions import CameraError, InitializationError, CaptureError

logger = logging.getLogger(__name__)

class IPCameraBackend(CameraBackend):
    """IP camera backend supporting ONVIF discovery, PTZ control, and RTSP streaming.

    @phase active
    @stability stable
    @dependency CameraBackend, ONVIFCamera
    """
    
    def __init__(self):
        super().__init__()
        self.rtsp_url: Optional[str] = None
        self.onvif_client: Any = None
        self.cap: Optional[cv2.VideoCapture] = None
        self.ptz_service = None
        self.profile_token: Optional[str] = None
        
    def initialize(self, config: CameraConfig) -> bool:
        """Initialize IP camera via ONVIF discovery and RTSP stream connection.

        Establishes connection to an IP camera using ONVIF protocol for
        device discovery and RTSP for video streaming. Falls back to direct
        RTSP URL if ONVIF fails.
        """
        # In CameraConfig, device_path is used for the IP address/host
        host = config.device_path or config.url
        if not host:
            logger.error("Host (IP address or URL) required for IPCameraBackend")
            return False
            
        try:
            from onvif import ONVIFCamera
        except ImportError:
            logger.error("onvif-zeep not installed. IP camera support unavailable.")
            return False
            
        try:
            # 1. Connect via ONVIF if host looks like an IP/hostname (not a full URL)
            is_ip = not (host.startswith('rtsp://') or host.startswith('http://'))
            
            if is_ip:
                try:
                    self.onvif_client = ONVIFCamera(
                        host,
                        config.custom_options.get('onvif_port', 80),
                        config.username or "",
                        config.password or ""
                    )
                    
                    media_service = self.onvif_client.create_media_service()
                    profiles = media_service.GetProfiles()
                    if profiles:
                        self.profile_token = profiles[0].token
                        # Try to get RTSP URL from ONVIF
                        stream_setup = media_service.create_type('GetStreamUri')
                        stream_setup.ProfileToken = self.profile_token
                        stream_setup.StreamSetup = {
                            'Stream': 'RTP-Unicast', 
                            'Transport': {'Protocol': 'RTSP'}
                        }
                        uri_response = media_service.GetStreamUri(stream_setup)
                        self.rtsp_url = uri_response.Uri
                except Exception as e:
                    logger.warning(f"ONVIF initialization failed for {host}: {e}. Falling back to direct RTSP if available.")
            
            # 2. Initialize PTZ if available
            if self.onvif_client:
                try:
                    self.ptz_service = self.onvif_client.create_ptz_service()
                except Exception:
                    self.ptz_service = None
                
            # 3. Open RTSP stream with OpenCV
            # Priority: config.url > discovered rtsp_url > config.device_path (if it's a URL)
            rtsp_target = config.url or self.rtsp_url
            if not rtsp_target and host.startswith('rtsp://'):
                rtsp_target = host
                
            if not rtsp_target:
                logger.error("Could not determine RTSP URL for IP camera")
                return False
                
            self.cap = cv2.VideoCapture(rtsp_target)
            if not self.cap.isOpened():
                logger.error(f"Failed to open RTSP stream: {rtsp_target}")
                return False
                
            self._is_initialized = True
            logger.info(f"IP Camera initialized: {rtsp_target}")
            return True
            
        except Exception as e:
            logger.error(f"Error during IP camera initialization: {e}")
            return False
            
    def capture_image(self) -> np.ndarray:
        """Capture a single frame from the RTSP stream."""
        if not self._is_initialized or self.cap is None:
            raise CameraError("IP Camera not initialized")
            
        try:
            ret, frame = self.cap.read()
            if not ret or frame is None:
                raise CaptureError("Failed to receive frame from IP camera RTSP stream")
            return frame
        except Exception as e:
            if not isinstance(e, (CameraError, CaptureError)):
                logger.error(f"Unexpected error during IP camera capture: {e}")
                raise CaptureError(f"IP camera capture failed: {e}") from e
            raise

    def start_stream(self) -> StreamHandle:
        """Start the RTSP video stream and return a handle."""
        if not self._is_initialized:
            raise CameraError("IP Camera not initialized")
        return StreamHandle(id=f"rtsp_stream_{hex(id(self))}")

    def stop_stream(self, handle: StreamHandle) -> None:
        """Stop the RTSP video stream."""

    def get_capabilities(self) -> CameraCapabilities:
        """Query camera capabilities including PTZ support and RTSP URL."""
        return CameraCapabilities(
            resolutions=[],
            max_fps=0,
            supports_ptz=(self.ptz_service is not None),
            supports_hdr=False,
            supports_manual_exposure=False,
            backend_specific={"rtsp_url": self.rtsp_url}
        )

    def control_ptz(self, pan: float, tilt: float, zoom: float) -> bool:
        """Execute continuous PTZ move with pan, tilt, zoom values (-1.0 to 1.0)."""
        if not self.ptz_service or not self.profile_token:
            return False
            
        try:
            request = self.ptz_service.create_type('ContinuousMove')
            request.ProfileToken = self.profile_token
            request.Velocity = {
                'PanTilt': {'x': pan, 'y': tilt},
                'Zoom': {'x': zoom}
            }
            self.ptz_service.ContinuousMove(request)
            return True
        except Exception as e:
            logger.error(f"PTZ move failed: {e}")
            return False

    def release(self) -> None:
        if self.cap:
            self.cap.release()
            self.cap = None
        self.onvif_client = None
        self.ptz_service = None
        self._is_initialized = False

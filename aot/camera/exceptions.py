class CameraError(Exception):
    """Base exception for all camera-related errors."""
    pass

class InitializationError(CameraError):
    """Raised when camera initialization fails."""
    pass

class CaptureError(CameraError):
    """Raised when image capture fails."""
    pass

class ConfigurationError(CameraError):
    """Raised when an invalid camera configuration is provided."""
    pass

class ResourceError(CameraError):
    """Raised when camera resources cannot be allocated or released."""
    pass

class BackendNotFoundError(CameraError):
    """Raised when a requested camera backend is not available on the current system."""
    pass

class ConnectionError(CameraError):
    """Raised when connection to an IP camera fails."""
    pass

class ONVIFConnectionError(ConnectionError):
    """Raised when ONVIF service connection fails."""
    pass

class RTSPStreamError(ConnectionError):
    """Raised when RTSP stream cannot be established."""
    pass

class StreamError(CameraError):
    """Raised when a streaming operation fails."""
    pass

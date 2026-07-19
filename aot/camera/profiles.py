from .models import PerformanceProfile

# Predefined Performance Profiles as specified in design.md

LOW = PerformanceProfile(
    name="Low",
    max_resolution=(640, 480),
    max_fps=5,
    enable_plantcv=False,
    enable_hdr=False,
    enable_noise_reduction=False,
    max_ip_cameras=1,
    stream_quality=50
)

MEDIUM = PerformanceProfile(
    name="Medium",
    max_resolution=(1280, 720),
    max_fps=15,
    enable_plantcv=True,
    enable_hdr=False,
    enable_noise_reduction=True,
    max_ip_cameras=3,
    stream_quality=75
)

HIGH = PerformanceProfile(
    name="High",
    max_resolution=(1920, 1080),
    max_fps=30,
    enable_plantcv=True,
    enable_hdr=True,
    enable_noise_reduction=True,
    max_ip_cameras=10,
    stream_quality=90
)

PROFILES = {
    "low": LOW,
    "medium": MEDIUM,
    "high": HIGH
}

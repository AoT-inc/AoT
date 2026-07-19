# coding=utf-8
import os
import subprocess
from typing import List, Dict

class PlatformDetector:
    """Detect hardware platform and manage available camera type listings.

    @phase active
    @stability stable
    """

    @staticmethod
    def detect_platform() -> str:
        """Detect the current hardware platform type."""
        if os.path.exists('/.dockerenv'):
            return 'docker'

        try:
            if os.path.exists('/proc/cpuinfo'):
                with open('/proc/cpuinfo', 'r') as f:
                    cpuinfo = f.read()
                    if 'Raspberry Pi' in cpuinfo or 'BCM' in cpuinfo:
                        return 'raspberry_pi'
        except Exception:
            pass

        if os.path.exists('/etc/debian_version'):
            return 'debian_pc'

        return 'unknown'

    @staticmethod
    def get_camera_types_for_platform(platform_type: str,
                                      include_legacy: bool = True) -> List[Dict]:
        """Return available camera types for the given platform."""
        from aot.camera.types import CAMERA_TYPES

        available_types = []
        for camera_type, config in CAMERA_TYPES.items():
            if not include_legacy and config.get('category') == 'legacy':
                continue

            if config['platform'] == 'all' or config['platform'] == platform_type:
                type_info = {
                    'type': camera_type,
                    'display_name': config['display_name'],
                    'description': config.get('description', ''),
                    'platform': config['platform'],
                    'category': config.get('category', 'modern'),
                    'deprecated': config.get('deprecated', False)
                }
                if config.get('deprecated'):
                    type_info['recommended_alternative'] = config.get('recommended_alternative')
                    type_info['deprecation_message'] = config.get('deprecation_message')
                
                available_types.append(type_info)

        return available_types

    @staticmethod
    def detect_available_cameras() -> List[Dict]:
        """Detect physically available cameras on the system."""
        available = []

        # USB/내장 웹캠 감지 (v4l2)
        try:
            result = subprocess.run(
                ['v4l2-ctl', '--list-devices'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                # v4l2-ctl output parser
                lines = result.stdout.split('\n')
                current_device_name = ""
                for line in lines:
                    if line and not line.startswith('\t'):
                        current_device_name = line.strip()
                    elif '/dev/video' in line:
                        device_path = line.strip()
                        available.append({
                            'type': 'usb_webcam',
                            'device': device_path,
                            'name': f'{current_device_name} ({device_path})'
                        })
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Raspberry Pi CSI 카메라 감지
        try:
            result = subprocess.run(
                ['libcamera-hello', '--list-cameras'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and 'Available cameras' in result.stdout:
                available.append({
                    'type': 'rpi_csi',
                    'device': 'csi',
                    'name': 'Raspberry Pi CSI Camera'
                })
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return available

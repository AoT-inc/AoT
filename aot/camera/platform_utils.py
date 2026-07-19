import os
import platform
import multiprocessing
from typing import Dict, Any
from .profiles import LOW, MEDIUM, HIGH, PerformanceProfile

def detect_platform() -> str:
    """Detect the hardware platform."""
    sys_platform = platform.system().lower()
    if sys_platform == "linux":
        try:
            with open("/proc/cpuinfo", "r") as f:
                content = f.read()
                if "raspberry pi" in content.lower() or "bcm2" in content.lower():
                    # Further distinguish Pi models if possible
                    if "revision" in content.lower():
                        return "raspberry_pi"
        except FileNotFoundError:
            pass
    return sys_platform

def get_system_resources() -> Dict[str, Any]:
    """Get CPU count and physical memory if possible."""
    resources = {
        "cpu_count": multiprocessing.cpu_count(),
        "memory_gb": 0.0,
        "platform": detect_platform()
    }
    
    # Try to get memory
    try:
        if resources["platform"] == "darwin":
            # Mac
            import subprocess
            mem_bytes = subprocess.check_output(['sysctl', '-n', 'hw.memsize']).strip()
            resources["memory_gb"] = int(mem_bytes) / (1024**3)
        elif resources["platform"] == "linux" or resources["platform"] == "raspberry_pi":
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if "MemTotal" in line:
                        mem_kb = int(line.split()[1])
                        resources["memory_gb"] = mem_kb / (1024**2)
                        break
    except Exception:
        pass
        
    return resources

def recommend_profile() -> PerformanceProfile:
    """Recommend a performance profile based on detected hardware capabilities.

    @phase active
    @stability stable
    @dependency PerformanceProfile
    """
    resources = get_system_resources()
    cpu = resources["cpu_count"]
    ram = resources["memory_gb"]
    
    if resources["platform"] == "raspberry_pi":
        if cpu >= 4 and ram >= 4:
            return MEDIUM
        return LOW
        
    if cpu >= 8 and ram >= 8:
        return HIGH
    if cpu >= 4:
        return MEDIUM
    return LOW

import logging
import re
from typing import List, Dict, Any, Optional
from .exceptions import CameraError

logger = logging.getLogger(__name__)

class IPCameraDiscovery:
    """Discover ONVIF-compliant IP cameras on the local network via WS-Discovery.

    @phase active
    @stability experimental
    """
    
    @staticmethod
    def discover_cameras(timeout: int = 5) -> List[Dict[str, str]]:
        """
        Discover ONVIF cameras using WS-Discovery.
        Returns a list of dictionaries containing camera info.
        """
        try:
            # Note: WSDiscovery might require 'wsdiscovery' or 'onvif-zeep' integrated tools
            # Often onvif-zeep installs its own discovery or we use 'zeep'
            from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery
        except ImportError:
            try:
                # Alternative import from some onvif-zeep distributions
                from onvif.discovery import WSDiscovery
            except ImportError:
                logger.error("WS-Discovery library not found. Discovery unavailable.")
                return []
                
        try:
            wsd = WSDiscovery()
            wsd.start()
            
            # Search for services
            services = wsd.searchServices(timeout=timeout)
            cameras = []
            
            for service in services:
                # Check if service is an ONVIF camera by checking its types
                service_types = str(service.getTypes()).lower()
                if 'onvif' in service_types or 'device' in service_types:
                    xaddrs = service.getXAddrs()
                    if xaddrs:
                        # Extract IP address from XAddr (e.g., http://192.168.1.10:80/onvif/device_service)
                        match = re.search(r'http[s]?://([^:/]+)', xaddrs[0])
                        if match:
                            ip_address = match.group(1)
                            cameras.append({
                                'ip_address': ip_address,
                                'xaddr': xaddrs[0],
                                'name': f"IP Camera ({ip_address})",
                                'scopes': [str(s) for s in service.getScopes()]
                            })
            
            wsd.stop()
            # Deduplicate by IP
            unique_cameras = {c['ip_address']: c for c in cameras}.values()
            return list(unique_cameras)
            
        except Exception as e:
            logger.error(f"Error during IP camera discovery: {e}")
            return []

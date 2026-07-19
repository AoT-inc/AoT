# coding=utf-8
import logging
from datetime import datetime, timedelta
from aot.utils.influx import read_influxdb_list

logger = logging.getLogger(__name__)

def get_device_icon(device_type):
    """장치 타입별 아이콘 반환"""
    icons = {
        'valve': '💧',
        'pump': '⚙️',
        'heater': '🌡️',
        'light': '💡',
        'fan': '🌬️',
        'sensor': '📡',
        'motor': '🔧',
        'relay': '🔌'
    }
    return icons.get(device_type.lower(), '📟')

def get_device_runtime(device_id, hours=24):
    """
    InfluxDB에서 장치의 실제 작동 기록 조회
    
    Returns:
        list: [{start, end, duration, timestamp}, ...]
    """
    try:
        # duration_time 측정값 조회
        data = read_influxdb_list(
            unique_id=device_id,
            unit='s',
            channel=0,
            measure='duration_time',
            duration_sec=hours * 3600
        )
        
        if not data:
            return []
        
        # 연속된 작동을 그룹화
        runtime_records = []
        for ts_epoch, duration_val in data:
            try:
                if duration_val and float(duration_val) > 0:
                    start_time = datetime.fromtimestamp(float(ts_epoch))
                    end_time = start_time + timedelta(seconds=float(duration_val))
                    
                    runtime_records.append({
                        'start': start_time.isoformat(),
                        'end': end_time.isoformat(),
                        'duration': float(duration_val),
                        'timestamp': float(ts_epoch)
                    })
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid data point for {device_id}: {e}")
                continue
        
        return runtime_records
        
    except Exception as e:
        logger.error(f"Failed to get runtime for {device_id}: {e}")
        return []

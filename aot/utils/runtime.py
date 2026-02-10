# coding=utf-8
import datetime
import logging
import time
from pytz import timezone

# AoT Imports
from aot.databases.models import Output, OutputChannel, Misc
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import read_influxdb_list, query_string, read_influxdb_single
from aot.aot_client import DaemonControl

logger = logging.getLogger("aot.runtime")

def get_started_at(device_unique_id, channel_id=0, lookback_days=30):
    """
    장치가 마지막으로 ON 된 시각(Epoch)을 반환합니다.
    InfluxDB의 'output_started_at' 측정을 기반으로 하며, 
    값(value)과 포인트 시각(point_ts) 중 더 적절한 것을 선택합니다.
    """
    try:
        # ID 정제: 'uuid::channel' 형태가 들어오면 순수 UUID만 추출
        if isinstance(device_unique_id, str) and '::' in device_unique_id:
            # 채널 정보가 ID에 포함되어 있고 channel_id가 기본값(0)이면 ID에서 추출 시도
            parts = device_unique_id.split('::')
            device_unique_id = parts[0]
            if channel_id == 0 and len(parts) > 1:
                channel_id = parts[1]

        # 채널 인덱스 확인
        ch_index = _resolve_channel_index(device_unique_id, channel_id)
        if ch_index is None:
            ch_index = 0
            
        lookback_sec = lookback_days * 24 * 3600
        
        # InfluxDB에서 'output_started_at' 조회
        data = read_influxdb_list(
            unique_id=device_unique_id,
            unit='s',
            channel=ch_index,
            measure='output_started_at',
            duration_sec=lookback_sec
        )
        
        if not data:
            # [Runtime Service] Fallback: InfluxDB에 데이터가 없는 경우 데몬에 직접 문의
            try:
                from aot.aot_client import DaemonControl
                control = DaemonControl()
                # 장치 상태가 'on'인지 확인
                state = control.output_state(device_unique_id, output_channel=ch_index)
                if state == 'on':
                    elapsed = control.output_sec_currently_on(device_unique_id, output_channel=ch_index)
                    if elapsed and elapsed > 0:
                        logger.debug(f"[AoT Runtime] InfluxDB Miss: Using Daemon Fallback for {device_unique_id}")
                        return int(time.time() - elapsed)
            except Exception:
                pass
            return None

        # 가장 최근 포인트 선택
        point_ts, last_val = data[-1]
        point_ts = int(point_ts)

        # 값(last_val)이 유효한 Epoch인지 확인
        value_epoch = None
        try:
            v = int(float(last_val))
            if v > 1e10:         # ms -> sec
                value_epoch = int(v / 1000)
            elif v >= 1e9:       # sec
                value_epoch = v
        except Exception:
            pass

        selected = point_ts
        
        # 값이 유효하고 시각 차이가 너무 크지 않으면(KST/UTC 오차 제외) 값 우선 사용
        if value_epoch:
            diff = abs(value_epoch - point_ts)
            # 6~12시간 차이가 나면 타임존 설정 문제로 보고 point_ts 사용
            if 6*3600 - 900 <= diff <= 12*3600 + 900:
                selected = point_ts
            else:
                selected = value_epoch

        return int(selected)
    except Exception as e:
        logger.error(f"get_started_at error for {device_unique_id}: {e}")
        return None

def get_elapsed_seconds(device_unique_id, channel_id=0):
    """
    장치가 현재 작동 중인 경우, 작동 시작 후 현재까지의 경과 초(seconds)를 반환합니다.
    작동 중이 아니거나 정보를 알 수 없는 경우 0을 반환합니다.
    """
    try:
        # 현재 장치 상태 확인 (DaemonControl 활용)
        control = DaemonControl()
        state = control.output_state(device_unique_id, output_channel=channel_id)
        
        if state != 'on':
            return 0
            
        started_at = get_started_at(device_unique_id, channel_id)
        if not started_at:
            return 0
            
        now = int(time.time())
        elapsed = now - started_at
        return max(0, elapsed)
    except Exception as e:
        logger.error(f"get_elapsed_seconds error for {device_unique_id}: {e}")
        return 0

def get_operational_seconds(device_unique_id, past_seconds, channel_id=0):
    """
    특정 과거 기간(past_seconds) 동안 장치가 작동한 총 누적 시간(초)을 반환합니다.
    조회 기간 및 현재 실시간 가동 여부를 합산하여 계산합니다.
    """
    try:
        # 1. InfluxDB에 기록된 누적 시간(duration_time SUM) 조회
        data = query_string(
            's', device_unique_id,
            measure='duration_time',
            channel=channel_id,
            value='SUM',
            past_sec=past_seconds
        )
        
        sec_recorded = 0
        if data:
            settings = db_retrieve_table_daemon(Misc, entry='first')
            # InfluxDB 결과를 합산 (버전에 따른 처리)
            for table in data:
                for row in table.records:
                    if settings.measurement_db_version == '1':
                        sec_recorded += row.values['_value']
                    else:
                        sec_recorded = row.values['_value']
                        
        # 2. 현재 작동 중인 경우, 지금 이 순간까지의 실시간 가동 시간 추가
        sec_currently_on = 0
        try:
            control = DaemonControl()
            if control.output_state(device_unique_id, output_channel=channel_id) == 'on':
                currently_on_total = control.output_sec_currently_on(device_unique_id, output_channel=channel_id)
                sec_currently_on = min(currently_on_total, past_seconds)
        except Exception:
            pass

        return int(sec_recorded + sec_currently_on)
    except Exception as e:
        logger.error(f"get_operational_seconds error for {device_unique_id}: {e}")
        return 0

def _resolve_channel_index(device_unique_id, channel_id):
    """
    채널 ID(숫자 또는 UUID)를 채널 인덱스(int)로 변환합니다.
    """
    try:
        if isinstance(channel_id, int): return channel_id
        if str(channel_id).isdigit(): return int(channel_id)
        
        # UUID로 조회
        oc = db_retrieve_table_daemon(OutputChannel).filter(OutputChannel.unique_id == channel_id).first()
        if oc and hasattr(oc, 'channel'):
            return int(oc.channel)
    except Exception:
        pass
    return None

def get_last_duration(device_unique_id, channel_id=0, lookback_days=30):
    """
    장치가 마지막으로 작동했던 지속 시간(초)을 반환합니다.
    InfluxDB의 'output_duration' 또는 'output_duration_sec' 측정을 기반으로 합니다.
    """
    try:
        # 채널 인덱스 확인
        ch_index = _resolve_channel_index(device_unique_id, channel_id)
        if ch_index is None:
            ch_index = 0
            
        lookback_sec = lookback_days * 24 * 3600
        
        # Try to resolve the specific measurement channel that has unit 's'
        # Strategy: Query DeviceMeasurements directly (most reliable source of truth)
        target_channel = ch_index
        target_measure_name = 'duration_time'
        
        try:
            from aot.databases.models import DeviceMeasurements
            from sqlalchemy import and_
            
            # Find all measurements for this device with unit 's' (seconds)
            dms = db_retrieve_table_daemon(DeviceMeasurements).filter(
                and_(DeviceMeasurements.device_id == device_unique_id, 
                     DeviceMeasurements.unit == 's')
            ).all()
            
            if dms:
                # If we found candidates, verify which one implies duration
                for dm in dms:
                    # Check if measurement name looks like duration
                    m_name = dm.measurement.lower()
                    if 'duration' in m_name or 'time' in m_name:
                         target_channel = dm.channel
                         target_measure_name = dm.measurement
                         # logger.debug(f"[get_last_duration] Found DM: ch={target_channel}, meas={target_measure_name}")
                         break
            else:
                # Fallback to Config Parsing if DB lookup failed (e.g. not yet synced)
                from aot.utils.outputs import parse_output_information
                from aot.databases.models import Output
                
                output_dev = db_retrieve_table_daemon(Output).filter(Output.unique_id == device_unique_id).first()
                if output_dev:
                    dict_outputs = parse_output_information()
                    if output_dev.output_type in dict_outputs:
                        out_info = dict_outputs[output_dev.output_type]
                        if 'channels_dict' in out_info and ch_index in out_info['channels_dict']:
                            ch_info = out_info['channels_dict'][ch_index]
                            if 'measurements' in ch_info:
                                for m_id in ch_info['measurements']:
                                    if 'measurements_dict' in out_info and m_id in out_info['measurements_dict']:
                                        if out_info['measurements_dict'][m_id].get('unit') == 's':
                                            target_channel = m_id
                                            break
        except Exception as e:
            pass

        # 측정 항목 후보: prioritized resolved name first
        measures = [target_measure_name, 'duration_time', 'output_duration_sec', 'output_duration']
        # Remove duplicates
        measures = list(dict.fromkeys(measures))
        
        last = None
        
        for m in measures:
            try:
                # 1. Use resolved target_channel if checking the resolved measure name, otherwise use target_channel (best guess) or ch_index
                # If we scanned DB and found a specific channel for 'duration_time', target_channel is set to that.
                query_ch = target_channel
                
                data = read_influxdb_list(
                    unique_id=device_unique_id,
                    unit='s',
                    channel=query_ch,
                    measure=m,
                    duration_sec=lookback_sec
                )
                
                # 2. If no data and measure is 'duration_time', try with channel=None (missing metadata case)
                if not data and m == 'duration_time':
                     data = read_influxdb_list(
                        unique_id=device_unique_id,
                        unit='s',
                        channel=None,
                        measure=m,
                        duration_sec=lookback_sec
                    )

                if data:
                     data = read_influxdb_list(
                        unique_id=device_unique_id,
                        unit='s',
                        channel=None,
                        measure=m,
                        duration_sec=lookback_sec
                    )

                if data:
                    # 가장 최근 값 선택 (timestamp 기준)
                    last_ts, last_val = data[-1]
                    try:
                        v = int(float(last_val))
                    except Exception:
                        v = None
                        
                    if v is not None and v >= 0:
                        # 후보 중 더 최신 것이면 교체
                        if last is None or int(last_ts) > int(last[0]):
                            last = (last_ts, v)
            except Exception:
                continue
                
        if last is None:
            # logger.debug(f"[get_last_duration] No data found for {device_unique_id} ch={ch_index}")
            return None
            
        # 값(초) 반환
        # logger.debug(f"[get_last_duration] Found for {device_unique_id}: {int(last[1])}")
        return int(last[1])
    except Exception as e:
        logger.error(f"[get_last_duration] Error fetching data for {device_unique_id}: {e}")
        return None

# -------------------------------------------------------------------------
# New Shared Helpers for Routes/Timer (Migrated from AoT_timer.py)
# -------------------------------------------------------------------------
from aot.utils.database import db_retrieve_table_daemon
from aot.databases.models import OutputChannel
from aot.utils.influx import read_influxdb_list
import threading
import queue
import time

def resolve_channel_index(device_unique_id, channel_id):
    """
    Returns an integer channel index if resolvable, else None.
    Accepts either plain integer strings (e.g., '0') or OutputChannel.unique_id (UUID).
    """
    try:
        return int(channel_id)
    except Exception:
        pass
    try:
        oc = db_retrieve_table_daemon(OutputChannel).filter(OutputChannel.unique_id == channel_id).first()
        if oc is not None and getattr(oc, 'channel', None) is not None:
            return int(getattr(oc, 'channel'))
    except Exception as e:
        pass
    return None

def read_latest_started_at(device_unique_id, primary_ch_index, lookback_sec):
    try:
        tried = set()
        candidates = [] 
        def _read_one(ch):
            data = read_influxdb_list(
                unique_id=device_unique_id,
                unit='s',
                channel=ch,
                measure='output_started_at',
                duration_sec=lookback_sec
            )
            if data:
                last_ts, last_val = data[-1]
                candidates.append((int(last_ts), last_val))

        if primary_ch_index is not None:
            tried.add(primary_ch_index)
            try:
                _read_one(primary_ch_index)
            except Exception:
                pass
        else:
            # Only scan other channels if no primary output channel is specified
            for ch in (0, 1, 2, 3):
                if ch in tried: continue
                try:
                    _read_one(ch)
                except Exception:
                    pass

        if not candidates:
            return None

        point_ts, last_val = max(candidates, key=lambda p: p[0])
        value_epoch = None
        try:
            v = int(float(last_val))
            if v > 1e10: value_epoch = int(v / 1000)
            elif v >= 1e9: value_epoch = v
        except Exception:
            value_epoch = None

        selected = point_ts
        source = 'point_ts'
        if isinstance(value_epoch, int):
            # [Fix] Remove aggressive timezone Check (9h offset)
            # This check was resetting StartTime to PointTime (Now) when diff was ~9h,
            # causing 00:00:00 glitch in KST environments.
            # We entrust the value written by the daemon.
            # diff = abs(value_epoch - point_ts)
            # if 6*3600 - 900 <= diff <= 12*3600 + 900:
            #     selected = point_ts
            #     source = 'point_ts_sanitized'
            # else:
            selected = value_epoch
            source = 'value'
            
        # [Debug] Log final selection
        # logger.debug(f"[StartedAt] ID={device_unique_id} PointTS={point_ts} Value={value_epoch} Source={source} Selected={selected}")
        if (point_ts - selected) < 5: 
             # Only log suspicious resets (Start ~ Now)
             logger.info(f"[StartedAt-DEBUG] SUSPICIOUS RESET? ID={device_unique_id} PointTS={point_ts} Value={value_epoch} Selected={selected} (Diff={point_ts-selected})")

        return {
            "selected_epoch": int(selected),
            "point_ts_epoch": int(point_ts),
            "value_epoch": int(value_epoch) if isinstance(value_epoch, int) else None,
            "source": source
        }
    except Exception as e:
        logger.error(f"[StartedAt-DEBUG] Error: {e}")
        return None

def read_latest_started_at_safe(device_unique_id, primary_ch_index, lookback_sec, timeout_sec=2.0):
    q = queue.Queue(maxsize=1)
    def _worker():
        try:
            res = read_latest_started_at(device_unique_id, primary_ch_index, lookback_sec)
            try:
                q.put_nowait(res)
            except Exception: pass
        except Exception:
            try: q.put_nowait(None)
            except Exception: pass
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    try:
        return q.get(timeout=timeout_sec)
    except Exception:
        return None

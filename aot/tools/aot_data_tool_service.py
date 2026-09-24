import logging
import re
from aot.utils.time_utils import serialize_ts
from datetime import datetime


logger = logging.getLogger(__name__)


_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)


def _with_translated_alias(fn):
    """번역된 이름으로 불러도 원문 엔티티를 찾게 한다.

    사용자 지정 이름 번역이 켜져 있으면 화면에는 "1号ハウス" 가 보이는데 DB 에는
    "1번 하우스" 로 저장되어 있다. 사용자는 자기가 보는 이름으로 말하므로, 원문
    매칭이 실패했을 때 번역 사전을 역방향으로 읽어 한 번 더 시도한다.

    원문 매칭을 **먼저** 한다. 저장된 이름으로 부른 것을 번역명으로 오인해
    엉뚱한 엔티티로 보내면 안 되기 때문이다.

    docs/design/user-string-live-translation.md
    """
    import functools

    @functools.wraps(fn)
    def wrapper(target_name):
        result = fn(target_name)
        if result and (result[0] or result[1] == 'ambiguous'):
            return result
        try:
            from aot.tools import providers
            source = providers.get('reverse_lookup')(target_name)
        except Exception:
            source = None
        if source and source != target_name:
            return fn(source)
        return result

    return wrapper


def _looks_like_uuid(value):
    """uuid 꼴인가 — 이름 기반 폴백을 건너뛸지 판정한다.

    이름 부분일치는 사람이 말한 이름('1포장')을 위한 것인데, uuid 를 그 자리에
    넣으면 우연한 문자열 포함으로 엉뚱한 도형이 걸린다. uuid 로 물어 못 찾았다면
    "없다" 가 정답이다.
    """
    return bool(_UUID_RE.match(str(value).strip()))


# ---------------------------------------------------------------------------
# @ANCHOR: WEATHER_DEVICE_KINDS
# Input.device values of the drivers that actually observe the weather.
#
# get_weather used to hand the zone uuid straight to get_sensor_detail, which
# takes the FIRST Input that happens to sit inside the polygon. On a real farm
# that is a soil probe: koat's '1포장' answered "No data for device
# '토양온습도_2'" (a soil sensor with no recent rows) and '3포장' answered with a
# plain air-temp/humidity node's readings — LoRaWAN rssi/snr included, and not
# one rain/wind field — while a dedicated KMA input and a SenseCAP weather
# station sat on both plots unused.
#
# A name list is deliberate: "is this a weather station" is a property of the
# DRIVER, not of the readings. Deriving it from measurements alone would let any
# node reporting temperature+humidity pass, which is exactly the wrong answer
# here. _WEATHER_MEASUREMENTS below is only a secondary net for drivers not
# listed here (a generic MQTT/Modbus feed wired to a real weather mast), and it
# asks for a measurement that only a weather station has — wind or rain.
#
# Add new weather drivers here when they are written.
_WEATHER_INPUT_DEVICES = frozenset({
    'KMA_weather_500',
    'KMA_weather_stn',
    'sensecap_weather',
    'ecowitt_weather',
    'OPENWEATHERMAP_CALL_WEATHER',
    'OPENWEATHERMAP_CALL_ONECALL',
})

# Measurements no ordinary sensor node carries. Used only for devices whose
# driver is not in _WEATHER_INPUT_DEVICES. 'temperature'/'humidity'/'pressure'
# are NOT here on purpose — every second sensor in the system has them.
# A bare 'speed' is deliberately NOT here — it is generic enough to match
# non-weather hardware, and every driver that reports wind speed also reports
# wind direction.
_WEATHER_MEASUREMENTS = frozenset({
    'direction',      # wind direction (unit 'bearing')
    'precipitation',
    'rain',
    'snowfall',
})


# get_sensor_detail(sensor_type='weather') 가 남길 측정 이름의 부분문자열.
# 'precipitation'/'snow'/'visibility' 가 명시적으로 들어 있는 이유: 'rain' 은
# 'precipitation' 의 부분문자열이 **아니라서**, 날씨를 묻는 바로 그 질의가 KMA
# 입력의 강수 채널을 통째로 걸러내고 있었다.
_WEATHER_METRIC_KEYWORDS = (
    'temperature', 'humidity', 'pressure', 'wind', 'rain', 'precipitation',
    'snow', 'visibility', 'solar', 'radiation', 'uv', 'dewpoint',
    'speed', 'direction',
)


def _devices_on_map_p2(map_uuid):
    """[P2] 지도에 배치된 장치 uuid 집합. map_config_id 조회의 대체.

    지도 소속의 정본은 배치(마커)다 — device_membership 이 정본이며,
    map_config_id 는 사망 컬럼이다.
    """
    try:
        from aot.aot_flask.geo.device_membership import devices_on_map
        return devices_on_map(map_uuid)
    except Exception:
        return set()


def _map_for_device_p2(device_uuid, prefer=None):
    """[P2] 장치가 배치된 대표 지도 uuid. map_config_id 읽기의 대체."""
    try:
        from aot.aot_flask.geo.device_membership import map_for_device
        return map_for_device(device_uuid, prefer=prefer)
    except Exception:
        return None



def _control_targets_for(controller):
    """이 코디네이터가 따르는 목표 → AI 가 읽는 dict.

    함수 옵션이 아니라 **제어와 같은 계산**을 거친다. 옛 키를 읽으면 AI 는 늘
    "목표 없음" 으로 보고 조언한다.
    """
    try:
        from aot.aot_flask.geo import coordinator_plot
        t = coordinator_plot.control_targets(controller)
        return {'vpd_kpa': (t.get('vpd') or {}).get('value'),
                'vpd_curve': bool((t.get('vpd') or {}).get('method_id')),
                'co2_ppm': (t.get('co2') or {}).get('value'),
                'co2_curve': bool((t.get('co2') or {}).get('method_id')),
                'dli': t.get('dli'), 'gdd_daily': t.get('gdd_daily'),
                'plot': t.get('plot_name'),
                'stage': (t.get('stage') or {}).get('name'),
                'reason': t.get('reason')}
    except Exception:                                       # noqa: BLE001
        return {'reason': 'error'}


def _plot_started_on(controller):
    """이 코디네이터가 따르는 구획의 시작일 → ISO 문자열|None.

    예전에는 함수 옵션(`schedule_start_time`)에 같은 날짜를 또 적게 했다. 그
    칸이 없어진 뒤로 옛 키를 읽으면 AI 는 늘 "작기 시작일 없음" 으로 본다.
    """
    try:
        from aot.aot_flask.geo import coordinator_plot
        d = coordinator_plot.control_targets(controller).get('started_on')
        return d.isoformat() if d else None
    except Exception:                                       # noqa: BLE001
        return None


def _plot_ended_on(controller):
    """이 코디네이터가 따르는 구획의 종료 신호 → (ISO 문자열|None, 확정 여부).

    2026-09-01 부로 코디네이터에는 별도 종료일 옵션(`schedule_end_time`)이
    없다 — 구획을 새로 심어도 그 날짜를 사람이 다시 고치기 전까지 계속 멈춰
    있던 것이 실제 사고였다. `ended_on`(사람이 확정한 실제 종료일)이 있으면
    그것을, 없으면 `expected_end_on`(진행 중인 구획의 예상치)을 낸다 — AI 가
    이 값을 예상이 아니라 확정으로 오인하지 않도록 두 번째 항목으로 구분한다.
    """
    try:
        from aot.aot_flask.geo import coordinator_plot
        t = coordinator_plot.control_targets(controller)
        ended = t.get('ended_on')
        if ended:
            return ended.isoformat(), True
        expected = t.get('expected_end_on')
        return (expected.isoformat() if expected else None), False
    except Exception:                                       # noqa: BLE001
        return None, False


def _local_iso(value):
    """UTC ISO 문자열 → 농장 현지시각 ISO 문자열. 못 읽으면 원래 값 그대로.

    `serialize_ts` 는 datetime 을 받는데, 여기 오는 값은 이미 다른 층에서
    문자열로 굳은 뒤다(요약 스냅샷의 timestamp 처럼). 그 층은 UTC 로 저장하는
    것이 맞으므로 저장을 건드리지 않고 **내보낼 때만** 현지시각으로 돌린다.
    """
    if not value:
        return value
    try:
        return serialize_ts(datetime.fromisoformat(str(value)))
    except Exception:                                       # noqa: BLE001
        return value



from aot.tools.data_tools.definition import DefinitionToolsMixin
from aot.tools.data_tools.function import FunctionToolsMixin
from aot.tools.data_tools.device import DeviceToolsMixin
from aot.tools.data_tools.measurement import MeasurementToolsMixin
from aot.tools.data_tools.schedule import ScheduleToolsMixin
from aot.tools.data_tools.record import RecordToolsMixin
from aot.tools.data_tools.space import SpaceToolsMixin
from aot.tools.data_tools.system import SystemToolsMixin
from aot.tools.data_tools._common import CommonToolsMixin


class AoTDataToolService(DefinitionToolsMixin, FunctionToolsMixin, DeviceToolsMixin, MeasurementToolsMixin, ScheduleToolsMixin, RecordToolsMixin, SpaceToolsMixin, SystemToolsMixin, CommonToolsMixin):
    """
    AoT 내부 데이터를 AI 도구 규격에 맞게 제공하는 서비스 레이어.
    가상 MCP 워커(mcp_aot)가 이를 호출합니다.

    @phase active
    @stability stable
    """

    # All tool methods now live in aot/tools/data_tools/*.py
    # drawer mixins (see class bases above). Nothing left to add here.
    pass

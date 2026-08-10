# coding=utf-8
"""장치 교체를 관통하는 시계열 접합 — `geo_binding.history()` 가 근거다.

InfluxDB 는 값을 장치 uuid 로 태깅한다. 장치를 갈면 uuid 가 바뀌므로 그래프는
교체 시점에서 끊긴다. 사람이 보고 싶은 것은 "이 센서의 값"이 아니라
**"이 자리의 값"** 이다 — 3-1 하우스의 온도는 온도계를 갈아도 3-1 하우스의
온도다.

과거 데이터를 새 uuid 로 다시 쓰는 방법은 쓰지 않는다. 그건 되돌릴 수 없고,
"그때 실제로 측정한 기계"라는 사실을 지운다. 대신 **조회 시점에 이어 붙인다**:
슬롯의 바인딩 이력이 [언제부터 언제까지 어느 장치가 이 자리를 맡았나]를
정확히 알고 있으므로, 구간마다 그 구간의 장치에게 물어보면 된다.

## 접합하지 않는 경우가 정상이다

- 접속정보만 갈아끼운 교체(같은 모델, DevEUI 만 교체)는 장치 uuid 가 그대로라
  **애초에 끊기지 않는다.** 접합할 구간이 생기지 않는 것이 정상이고, 그
  교체의 흔적은 `category='maintenance'` 노트에 남는다.
- 바인딩 이력이 하나뿐이면 접합은 단일 장치 조회와 같다. 그때는 빈 목록을
  돌려주고 호출자가 기존 경로를 그대로 타게 한다 — 같은 결과를 두 코드
  경로로 만들지 않는다.

## 대응 측정값을 못 찾으면 조용히 빼지 않는다

교체 전 장치에 같은 측정이 없으면 그 구간은 값이 없다. 그 구간을 말없이
건너뛰면 그래프는 "그 기간에는 아무 일도 없었다"고 거짓말한다. `gaps` 로
분리해 돌려주고 화면이 그렇게 말하게 한다.

@phase active
@stability experimental
@dependency GeoBinding, DeviceMeasurements, influx
"""
import logging

logger = logging.getLogger(__name__)

# 한 슬롯을 두 role 이 동시에 맡고 있을 때의 우선순위.
# 'area'(담당 구역)가 'marker'(위치 점)보다 앞이다 — 자리의 연속성을 말하는
# 것은 "무엇을 담당했나"이지 "어디에 점이 찍혔나"가 아니다.
_ROLE_PRIORITY = ('area', 'marker', 'actuator', 'sensor')


def _measurement_info(measurement_id):
    """(measurement, unit, channel). 없으면 None."""
    from aot.databases.models import Conversion, DeviceMeasurements
    from aot.utils.influx import return_measurement_info

    meas = DeviceMeasurements.query.filter(
        DeviceMeasurements.unique_id == measurement_id).first()
    if meas is None:
        return None
    conversion = Conversion.query.filter(
        Conversion.unique_id == meas.conversion_id).first()
    channel, unit, measurement = return_measurement_info(meas, conversion)
    return {'device_id': meas.device_id, 'channel': channel,
            'unit': unit, 'measurement': measurement}


def _slot_of(device_id):
    """이 장치가 맡고 있는 자리 하나 — (spatial_kind, spatial_id, role).

    한 장치가 여러 자리를 맡는 것은 정상이다(위치 마커 + 담당 구역). 시계열의
    연속성을 말하는 자리는 하나여야 하므로 `_ROLE_PRIORITY` 로 고른다.
    임의로 첫 행을 집으면 같은 장치가 실행마다 다른 자리를 기준으로 접합될 수
    있다 — 정렬 순서에 기대는 결과는 재현되지 않는다.
    """
    from aot.aot_flask.geo import device_binding

    rows = device_binding.bindings_for_device(device_id)
    if not rows:
        return None

    def rank(b):
        try:
            return _ROLE_PRIORITY.index(b.role)
        except ValueError:
            return len(_ROLE_PRIORITY)

    best = sorted(rows, key=lambda b: (rank(b), b.spatial_id))[0]
    return best.spatial_kind, best.spatial_id, best.role


def _match_measurement(device_id, want):
    """다른 장치에서 같은 뜻의 측정값을 찾는다. 없으면 None.

    기준은 (측정 종류, 단위) 다. 같은 자리를 맡은 온습도계 둘은 모델이 달라도
    온도는 온도다. 후보가 여럿이면 **채널이 같은 것**을 고른다 — 채널 번호는
    최초 배정 후 재배정하지 않는 불변값이라(프로젝트 규칙) 다채널 장치에서
    어느 구멍이었나를 말해주는 유일한 단서다.
    """
    from aot.databases.models import Conversion, DeviceMeasurements
    from aot.utils.influx import return_measurement_info

    rows = DeviceMeasurements.query.filter(
        DeviceMeasurements.device_id == device_id).all()
    hits = []
    for m in rows:
        conversion = Conversion.query.filter(
            Conversion.unique_id == m.conversion_id).first()
        channel, unit, measurement = return_measurement_info(m, conversion)
        if measurement == want['measurement'] and unit == want['unit']:
            hits.append((channel, m.unique_id))
    if not hits:
        return None
    for channel, uid in hits:
        if channel == want['channel']:
            return uid
    return hits[0][1]


def slot_segments(device_id, measurement_id):
    """이 측정값이 놓인 자리의 장치 교체 구간 — 시간순.

    반환: [{'device_id','device_name','measurement_id','valid_from','valid_to',
            'has_data'}]
    구간이 하나 이하이면 **빈 목록**을 돌려준다(접합할 것이 없다는 뜻).
    """
    from aot.aot_flask.geo import device_binding

    want = _measurement_info(measurement_id)
    if want is None:
        return []

    slot = _slot_of(device_id)
    if slot is None:
        return []

    rows = device_binding.history(*slot)
    if len(rows) < 2:
        return []

    names = device_binding._device_names([b.device_id for b in rows])
    out = []
    for b in rows:
        if b.device_id == device_id:
            mid = measurement_id
        elif b.measurement_id:
            # 바인딩이 측정값을 직접 지목했다면 그것이 정본이다.
            mid = b.measurement_id
        else:
            mid = _match_measurement(b.device_id, want)
        out.append({
            'device_id': b.device_id,
            'device_name': names.get(b.device_id) or b.device_id[:8],
            'measurement_id': mid,
            'valid_from': b.valid_from,
            'valid_to': b.valid_to,
            'has_data': mid is not None,
        })
    return out


def _segment_series(segment, start, end, group_sec):
    """한 구간의 값 목록 [(epoch, value)]. 구간 밖은 잘라낸다."""
    from aot.utils.influx import influx_to_list, query_string

    want = _measurement_info(segment['measurement_id'])
    if want is None:
        return []

    seg_start = max(start, segment['valid_from']) if segment['valid_from'] else start
    seg_end = min(end, segment['valid_to']) if segment['valid_to'] else end
    if seg_start >= seg_end:
        return []

    fmt = '%Y-%m-%dT%H:%M:%S.%fZ'
    try:
        data = query_string(
            want['unit'], segment['device_id'],
            measure=want['measurement'],
            channel=want['channel'],
            start_str=seg_start.strftime(fmt),
            end_str=seg_end.strftime(fmt),
            group_sec=group_sec or None)
    except Exception as err:
        logger.error('[SeriesStitch] 구간 조회 실패 (%s): %s',
                     segment['device_id'], err)
        return []
    if not data:
        return []
    return influx_to_list(data)


def stitched_series(device_id, measurement_id, start, end, max_points=700):
    """장치 교체를 관통해 이어 붙인 값 목록.

    그룹핑 간격은 **구간별이 아니라 전체 범위 기준**으로 계산한다. 구간마다
    따로 계산하면 짧은 구간이 촘촘해지고 긴 구간이 성글어져, 같은 그래프 안에서
    점 밀도가 교체 시점마다 튄다 — 사람은 그 계단을 데이터의 변화로 읽는다.

    반환: (points, segments) — points 는 [(epoch, value)] 시간순,
    segments 는 `slot_segments()` 결과에 'points' 를 더한 것.
    접합할 이력이 없으면 (None, []) — 호출자는 기존 단일 장치 경로를 탄다.
    """
    segments = slot_segments(device_id, measurement_id)
    if not segments:
        return None, []

    span = (end - start).total_seconds()
    group_sec = int(span / max_points) if span > 0 else 0

    points = []
    for seg in segments:
        if not seg['has_data']:
            seg['points'] = 0
            continue
        got = _segment_series(seg, start, end, group_sec)
        seg['points'] = len(got)
        points.extend(got)

    points.sort(key=lambda p: p[0])
    return points, segments


def hardware_events(device_id, measurement_id):
    """이 측정값이 놓인 자리의 **하드웨어 변경 시점** — 그래프 마커용.

    두 종류를 합쳐야 한다. 하나만 보면 절반을 놓친다:

    - **다른 장치로 옮긴 교체**는 바인딩 구간 경계에만 남는다(uuid 가 바뀐다).
    - **같은 모델로 갈아끼운 교체**는 바인딩에 아무 흔적이 없다 — uuid 가
      그대로라 슬롯의 연결이 변한 것이 없기 때문이다. 그쪽의 유일한 기록이
      `category='maintenance'` 노트다.

    값이 어느 시점에 한 단 뛰었을 때 그것이 환경의 변화인지 기계가 바뀐
    탓인지는 사람이 판단해야 하고, 판단하려면 이 시점들이 보여야 한다.

    반환: [{'time': epoch, 'kind': 'rebind'|'swap', 'title', 'text'}] 시간순.
    """
    from aot.databases.models import Notes

    events = []
    segments = slot_segments(device_id, measurement_id)

    for i, seg in enumerate(segments):
        if i == 0 or not seg['valid_from']:
            continue          # 첫 구간의 시작은 교체가 아니라 설치다
        events.append({
            'time': seg['valid_from'].timestamp(),
            'kind': 'rebind',
            # label 은 깃발 위에 찍히는 짧은 글자다. 아이콘을 쓰지 않으므로
            # (프로젝트 규칙) 이름 자체가 라벨이고, 자세한 내용은 툴팁이 맡는다.
            'label': seg['device_name'],
            'title': seg['device_name'],
            'text': '',
        })

    # 노트는 이 자리를 거쳐간 장치 전부에서 모은다 — 교체 전 장치에 남은
    # 접속정보 갱신도 이 그래프가 설명해야 할 사건이다.
    device_ids = {s['device_id'] for s in segments} or {device_id}
    rows = Notes.query.filter(
        Notes.category == 'maintenance',
        Notes.target_id.in_(device_ids)).order_by(Notes.date_time).all()
    names = {}
    for s in segments:
        names[s['device_id']] = s['device_name']
    for n in rows:
        if not n.date_time:
            continue
        events.append({
            'time': n.date_time.timestamp(),
            'kind': 'swap',
            'label': names.get(n.target_id) or (n.name or ''),
            'title': n.name or '',
            'text': n.note or '',
        })

    events.sort(key=lambda e: e['time'])
    return events


def segments_payload(segments):
    """화면에 넘길 형태로 구간을 직렬화한다(경계선·범례용)."""
    out = []
    for s in segments:
        out.append({
            'device_id': s['device_id'],
            'device_name': s['device_name'],
            'from': s['valid_from'].timestamp() if s['valid_from'] else None,
            'to': s['valid_to'].timestamp() if s['valid_to'] else None,
            'points': s.get('points', 0),
            'has_data': s['has_data'],
        })
    return out

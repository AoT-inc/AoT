# coding=utf-8
"""기상 입력의 과거 기압 값을 옛 꼬리표 → 'kPa'(값 ÷ 10) 로 옮긴다.

- OpenWeatherMap 두 드라이버: API 의 hPa 값을 'Pa' 로 선언해 저장했다(1022 hPa 가
  "1022 Pa"). 장치 단위 행은 마이그레이션 p6_81 이 'kPa' 로 옮긴다.
- 기상청(KMA_weather_500): 'hPa' 로 저장했다. 같은 측정을 드라이버마다 다른
  단위로 두지 않도록 kPa 로 맞춘다(p6_82, 2026-10-09 사용자 결정).

드라이버는 이제 모두 kPa(hPa ÷ 10)로 저장한다. 두 경우 모두 저장된 숫자는 hPa
값이라 ÷10 이 맞다. 그런데 InfluxDB 의 과거 값은 꼬리표가 'Pa' 로 남아
있어, 단위를 kPa 로 묻는 그래프·조회가 **과거 기압을 찾지 못한다.** 이 스크립트가
그 값을 같은 시각에 'kPa' 꼬리표로 다시 쓴다(값 ÷ 10).

- **옛 'Pa' 값은 지우지 않는다.** 되돌릴 수 있게 남기고(InfluxDB 1.x 는 삭제를
  지원하지 않을 수도 있다), 더는 아무도 그 꼬리표로 묻지 않는다.
- 같은 시각·같은 꼬리표에 다시 쓰면 덮어쓴다 — 두 번 돌려도 값이 늘지 않는다.
- p6_81 이 아직 안 돌았으면(장치 행이 여전히 'Pa') 대상으로 잡지 않는다 — 옮긴
  값을 아무도 읽지 않게 되기 때문이다.

    python3 -m aot.scripts.migrate_pressure_kpa            # 미리보기
    python3 -m aot.scripts.migrate_pressure_kpa --apply    # 실제 반영

종료 0=옮길 것 없음/성공, 1=옮길 것 있음(미리보기), 2=실패.
"""

import argparse
import sys

#: 드라이버 → 옛 꼬리표. 저장된 숫자는 둘 다 hPa 값이다.
OLD_UNITS = {
    'OPENWEATHERMAP_CALL_WEATHER': 'Pa',
    'OPENWEATHERMAP_CALL_ONECALL': 'Pa',
    'KMA_weather_500': 'hPa',
}
DRIVERS = tuple(OLD_UNITS)
NEW_UNIT, FACTOR = 'kPa', 0.1


def _client_and_bucket():
    """앱 설정으로 InfluxDB 클라이언트와 버킷 — write_influxdb_value 와 같은 규칙."""
    from influxdb_client import InfluxDBClient

    from aot.config import INFLUXDB_PORT, resolve_measurement_db_host
    from aot.databases.models import Misc

    s = Misc.query.first()
    url = 'http://%s:%s' % (resolve_measurement_db_host(s.measurement_db_host),
                            INFLUXDB_PORT or s.measurement_db_port)
    if s.measurement_db_version == '1':
        client = InfluxDBClient(
            url=url, org='aot', timeout=60000,
            token='%s:%s' % (s.measurement_db_user, s.measurement_db_password))
        bucket = '%s/%s' % (s.measurement_db_dbname, s.measurement_db_retention_policy)
    else:
        client = InfluxDBClient(url=url, token=s.measurement_db_password,
                                org='aot', timeout=60000)
        bucket = s.measurement_db_dbname
    return client, bucket


def targets():
    """[(input unique_id, 이름, 채널, 지금 단위, 옛 꼬리표)] — 기압 채널."""
    from aot.databases.models import DeviceMeasurements, Input

    out = []
    for inp in Input.query.filter(Input.device.in_(DRIVERS)).all():
        for dm in DeviceMeasurements.query.filter_by(
                device_id=inp.unique_id, measurement='pressure').all():
            out.append((inp.unique_id, inp.name, dm.channel, dm.unit,
                        OLD_UNITS[inp.device]))
    return out


def _old_points(query_api, bucket, device_id, old_unit):
    flux = ('from(bucket: "%s") |> range(start: 1970-01-01T00:00:00Z) '
            '|> filter(fn: (r) => r._measurement == "%s" and r.device_id == "%s" '
            'and r._field == "value")' % (bucket, old_unit, device_id))
    for table in query_api.query(flux):
        for rec in table.records:
            yield rec


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true', help='실제로 반영한다')
    args = ap.parse_args()

    from aot.start_flask_ui import app

    with app.app_context():
        try:
            rows = targets()
            client, bucket = _client_and_bucket()
        except Exception as exc:                             # noqa: BLE001
            print('ERROR: 준비 실패 — %s' % exc, file=sys.stderr)
            return 2

        todo = []
        with client:
            query_api = client.query_api()
            for uid, name, channel, unit, old_unit in rows:
                if unit != NEW_UNIT:
                    print('  건너뜀  %s ch%s: 장치 단위가 %r — 마이그레이션 p6_81·p6_82 '
                          '가 먼저 돌아야 한다' % (name, channel, unit))
                    continue
                try:
                    pts = [r for r in _old_points(query_api, bucket, uid, old_unit)
                           if str(r.values.get('channel')) == str(channel)]
                except Exception as exc:                     # noqa: BLE001
                    print('ERROR: %s 조회 실패 — %s' % (name, exc), file=sys.stderr)
                    return 2
                print('  대상    %s ch%s: 과거 %d건 (%s → kPa, ÷10)'
                      % (name, channel, len(pts), old_unit))
                if pts:
                    todo.append((name, pts))

            if not todo:
                print('옮길 것이 없습니다.')
                return 0
            if not args.apply:
                print('\n미리보기입니다. %d건을 옮기려면 --apply 를 붙이세요. 옛 값은 '
                      '지우지 않습니다.' % sum(len(p) for _n, p in todo))
                return 1

            from influxdb_client import Point
            from influxdb_client.client.write_api import SYNCHRONOUS
            write_api = client.write_api(write_options=SYNCHRONOUS)
            done = 0
            try:
                for name, pts in todo:
                    batch = []
                    for r in pts:
                        p = Point(NEW_UNIT).tag('device_id', r.values.get('device_id'))
                        for tag in ('measure', 'channel'):
                            if r.values.get(tag) is not None:
                                p = p.tag(tag, r.values.get(tag))
                        batch.append(p.field('value', float(r.get_value()) * FACTOR)
                                     .time(r.get_time()))
                        if len(batch) >= 5000:
                            write_api.write(bucket=bucket, record=batch)
                            done += len(batch)
                            batch = []
                    if batch:
                        write_api.write(bucket=bucket, record=batch)
                        done += len(batch)
            except Exception as exc:                         # noqa: BLE001
                print('ERROR: 쓰기 실패(%d건까지 반영) — %s' % (done, exc), file=sys.stderr)
                return 2

    print('\n%d건 옮겼습니다.' % done)
    return 0


if __name__ == '__main__':
    sys.exit(main())

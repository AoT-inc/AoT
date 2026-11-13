"""S8 — 기상청 원천 시각은 한 곳(kma_clock)에서만 KST 로 읽고, 장소 시계는 장소 시간대를 따른다."""
import datetime as dt

from aot.utils import kma_clock
from aot.utils.timekit import utc_now


def test_kma_wall_is_seoul_wall_regardless_of_host():
    t = dt.datetime(2026, 11, 1, 15, 0, tzinfo=dt.timezone.utc)      # 11-02 00:00 KST
    assert kma_clock.kma_wall(t) == dt.datetime(2026, 11, 2, 0, 0)
    assert kma_clock.kma_wall(t.timestamp()) == dt.datetime(2026, 11, 2, 0, 0)
    assert kma_clock.kma_wall(utc_now()).tzinfo is None


def test_kma_wall_to_utc_roundtrip():
    wall = dt.datetime(2026, 11, 2, 9, 5)
    assert kma_clock.kma_wall_to_utc(wall) == dt.datetime(2026, 11, 2, 0, 5, tzinfo=dt.timezone.utc)
    assert kma_clock.kma_wall(kma_clock.kma_wall_to_utc(wall)) == wall


def test_gis_kma_observation_time_uses_kma_clock():
    from aot.inputs_gis import gis_kma
    assert gis_kma.kma_wall is kma_clock.kma_wall
    assert gis_kma.kma_wall_to_utc is kma_clock.kma_wall_to_utc


def test_forecast_file_without_tz_is_kma_clock():
    from aot.functions.utils.env_control.forecast_feedforward import forecast_epoch
    e = forecast_epoch('202611020900', None)
    assert e == dt.datetime(2026, 11, 2, 0, 0, tzinfo=dt.timezone.utc).timestamp()
    # 시간대 키가 있는 파일(Open-Meteo 시설 파일)은 그 시간대 — 뉴욕은 서머타임 끝난 11-02 에 EST(-5)
    ny = forecast_epoch('202611020900', 'America/New_York')
    assert ny == dt.datetime(2026, 11, 2, 14, 0, tzinfo=dt.timezone.utc).timestamp()
    ny_dst = forecast_epoch('202607010900', 'America/New_York')
    assert ny_dst == dt.datetime(2026, 7, 1, 13, 0, tzinfo=dt.timezone.utc).timestamp()

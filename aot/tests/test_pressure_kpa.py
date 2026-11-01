# coding=utf-8
"""기상 입력의 기압은 kPa 로 저장한다(2026-10-09) — OpenWeatherMap·기상청.

두 드라이버가 API 의 hPa 값을 'Pa' 로 선언해 1022 hPa 가 "1022 Pa" 로 보였다.
드라이버(값 ÷10, 단위 kPa) · 마이그레이션 p6_81(장치 단위 행) · 과거 값 스크립트
셋이 함께 움직여야 한다 — 단위 꼬리표는 드라이버 정의가 아니라 장치 행에서 오므로,
행만 남겨 두면 새 값이 'Pa' 로 쌓이고, 과거 값을 안 옮기면 그래프가 과거를 못 찾는다.
"""
import importlib.util
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REV = 'p6_81_owm_pressure_kpa_20261009'


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_drivers_declare_kpa_and_divide():
    for rel, ch in (('inputs/openweathermap_weather.py', 2),
                    ('inputs/openweathermap_onecall.py', 4)):
        src = open(os.path.join(_ROOT, rel), encoding='utf-8').read()
        assert "'measurement': 'pressure',\n        'unit': 'kPa'" in src, rel
        assert "self.value_set(%d, pressure / 10.0" % ch in src, rel


def _run(mod, fn, engine):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(mod, fn)()


def test_migration_moves_only_owm_pressure_rows_in_pa(tmp_path):
    import sqlalchemy as sa
    engine = sa.create_engine("sqlite:///%s" % (tmp_path / 'm.db'))
    with engine.begin() as c:
        c.execute(sa.text("CREATE TABLE input (unique_id TEXT, device TEXT)"))
        c.execute(sa.text("CREATE TABLE device_measurements (unique_id TEXT, "
                          "device_id TEXT, measurement TEXT, unit TEXT, conversion_id TEXT)"))
        c.execute(sa.text("INSERT INTO input VALUES ('owm', 'OPENWEATHERMAP_CALL_WEATHER'),"
                          " ('one', 'OPENWEATHERMAP_CALL_ONECALL'), ('kma', 'KMA_weather_500')"))
        c.execute(sa.text(
            "INSERT INTO device_measurements VALUES "
            "('a', 'owm', 'pressure', 'Pa', ''),"        # 옮긴다
            "('b', 'one', 'pressure', 'Pa', NULL),"      # 옮긴다
            "('c', 'kma', 'pressure', 'hPa', ''),"       # 다른 드라이버 — 그대로
            "('d', 'owm', 'temperature', 'C', ''),"      # 기압 아님 — 그대로
            "('e', 'one', 'pressure', 'Pa', 'conv-1')"   # 사람이 변환을 걸었다 — 그대로
            ))
    mod = _load(os.path.join(_ROOT, '..', 'alembic_db', 'alembic', 'versions', _REV + '.py'), _REV)
    assert mod.down_revision == 'p6_80_api_key_tool_modules_20260929'

    def units():
        with engine.connect() as c:
            return dict(c.execute(sa.text(
                "SELECT unique_id, unit FROM device_measurements")).all())

    for _ in range(2):
        _run(mod, 'upgrade', engine)
    assert units() == {'a': 'kPa', 'b': 'kPa', 'c': 'hPa', 'd': 'C', 'e': 'Pa'}
    _run(mod, 'downgrade', engine)
    assert units() == {'a': 'Pa', 'b': 'Pa', 'c': 'hPa', 'd': 'C', 'e': 'Pa'}


def test_history_script_skips_devices_the_migration_has_not_moved():
    """행이 아직 'Pa' 면 옮긴 값을 아무도 읽지 않는다 — 대상으로 잡지 않는다."""
    src = open(os.path.join(_ROOT, 'scripts', 'migrate_pressure_kpa.py'),
               encoding='utf-8').read()
    assert "if unit != NEW_UNIT:" in src
    assert 'delete_api' not in src, '옛 값은 지우지 않는다(되돌릴 수 있게)'


def test_kma_driver_stores_kpa():
    src = open(os.path.join(_ROOT, 'inputs', 'kma_weather_500.py'), encoding='utf-8').read()
    assert "2: {'measurement': 'pressure', 'unit': 'kPa'" in src
    assert "'unit': 'kPa', 'value': row['pa'] / 10.0" in src      # 백필
    assert "self.value_set(2, pressure / 10.0" in src             # 실시간
    assert "(2, 'kPa', 'pressure')" in src                        # 이력 확인


def test_p6_82_moves_only_kma_pressure_rows_in_hpa(tmp_path):
    import sqlalchemy as sa
    rev = 'p6_82_kma_pressure_kpa_20261009'
    engine = sa.create_engine("sqlite:///%s" % (tmp_path / 'k.db'))
    with engine.begin() as c:
        c.execute(sa.text("CREATE TABLE input (unique_id TEXT, device TEXT)"))
        c.execute(sa.text("CREATE TABLE device_measurements (unique_id TEXT, "
                          "device_id TEXT, measurement TEXT, unit TEXT, conversion_id TEXT)"))
        c.execute(sa.text("INSERT INTO input VALUES ('kma', 'KMA_weather_500'),"
                          " ('owm', 'OPENWEATHERMAP_CALL_WEATHER')"))
        c.execute(sa.text(
            "INSERT INTO device_measurements VALUES "
            "('a', 'kma', 'pressure', 'hPa', ''),"
            "('b', 'kma', 'pressure', 'hPa', 'conv-1'),"
            "('c', 'owm', 'pressure', 'Pa', '')"))
    mod = _load(os.path.join(_ROOT, '..', 'alembic_db', 'alembic', 'versions', rev + '.py'), rev)
    assert mod.down_revision == _REV

    def units():
        with engine.connect() as c:
            return dict(c.execute(sa.text(
                "SELECT unique_id, unit FROM device_measurements")).all())

    for _ in range(2):
        _run(mod, 'upgrade', engine)
    assert units() == {'a': 'kPa', 'b': 'hPa', 'c': 'Pa'}
    _run(mod, 'downgrade', engine)
    assert units() == {'a': 'hPa', 'b': 'hPa', 'c': 'Pa'}


def test_history_script_knows_each_drivers_old_tag():
    src = open(os.path.join(_ROOT, 'scripts', 'migrate_pressure_kpa.py'),
               encoding='utf-8').read()
    assert "'KMA_weather_500': 'hPa'" in src
    assert "'OPENWEATHERMAP_CALL_WEATHER': 'Pa'" in src


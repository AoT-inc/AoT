# coding=utf-8
"""내장 통로가 같은 엔진·같은 쓰기 층을 쓴다는 것, 그리고 노드 import 가 서버 모듈을 끌어오지 않는다는 것."""
import subprocess
import sys
import time
import types

import pytest

from aot.twin import consumer
from aot.twin.node import TwinNode
from aot.twin.settings import NodeSettings, ServerSettings
from aot.twin.types import Status, TargetKind

from .helpers import facility_spec


@pytest.fixture
def fake_influx(monkeypatch):
    """`aot.utils.influx` 를 메모리 구현으로 바꿔 끼운다 (진짜 Influx·flask 없이)."""
    import datetime
    store = {}

    def read_influxdb_list(uid, unit, ch, measure=None, duration_sec=None, **k):
        now = time.time()
        return [(t, v) for t, v in sorted(store.get((uid, unit, ch), {}).items())
                if now - (duration_sec or 0) <= t <= now + 1] or None

    def write_influxdb_value(uid, unit, value, measure=None, channel=None, timestamp=None, extra_tags=None):
        ts = timestamp.replace(tzinfo=datetime.timezone.utc).timestamp() if timestamp else time.time()
        store.setdefault((uid, unit, channel), {})[ts] = value
        return 0

    mod = types.ModuleType("aot.utils.influx")
    mod.read_influxdb_list, mod.write_influxdb_value = read_influxdb_list, write_influxdb_value
    pkg = sys.modules.get("aot.utils") or types.ModuleType("aot.utils")
    monkeypatch.setitem(sys.modules, "aot.utils", pkg)
    monkeypatch.setitem(sys.modules, "aot.utils.influx", mod)
    monkeypatch.setattr(pkg, "influx", mod, raising=False)
    return store


def test_embedded_roundtrip(fake_influx):
    now = time.time()
    for i in range(6):
        t = now - (5 - i) * 60 - 5
        fake_influx.setdefault(("sens-in", "C", 0), {})[t] = 22.0
        fake_influx.setdefault(("sens-in", "percent", 1), {})[t] = 70.0
    srv = ServerSettings("local", "embedded", targets=[facility_spec("local")])
    node = TwinNode(NodeSettings(enabled=True, servers=[srv]))
    node.startup_bench()
    rep = node.run_once()[0]
    assert rep.error is None and rep.rejected == 0 and rep.status == Status.DEGRADED  # 외기 결측 → degraded
    assert {k[1] for k in fake_influx if k[1].startswith("env_twin")} >= {"env_twin", "env_twin_meta"}
    m = consumer.read_latest_meta(node.channels["local"][0], TargetKind.FACILITY, "coord-1", time.time())
    assert m is not None and m.status == Status.DEGRADED


def test_embedded_sink_refuses_non_twin_measurements(fake_influx):
    from aot.twin.sources.embedded import EmbeddedSink
    from aot.twin.types import Point
    r = EmbeddedSink("x").write([Point("temperature", "d", 0, 1.0, 1.0)])
    assert r.rejected == 1 and r.written == 0 and not fake_influx


def test_import_does_not_pull_server_modules():
    """원격 노드는 AoT 서버 없이 돈다: flask·DB·Influx 클라이언트를 import 하지 않는다."""
    code = ("import sys, aot.twin.node, aot.twin.settings, aot.twin.models, aot.twin.service, aot.twin.gate, aot.twin.discovery\n"
            "bad=[m for m in sys.modules if m.split('.')[0] in ('flask','influxdb_client','sqlalchemy','flask_sqlalchemy')"
            " or m.startswith(('aot.databases','aot.aot_flask','aot.utils.influx'))]\n"
            "print(bad)\nsys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_embedded_sink_uses_batch_write_when_available(fake_influx):
    from aot.twin.sources.embedded import EmbeddedSink
    from aot.twin.types import Point
    import aot.utils.influx as inf
    got = []
    inf.write_influxdb_points = lambda pts: got.extend(pts) or len(pts)
    try:
        r = EmbeddedSink("x").write([Point("env_twin_field_meta", "p", 0, 1.0, 0.0), Point("temperature", "d", 0, 1.0, 1.0)])
    finally:
        del inf.write_influxdb_points
    assert r.written == 1 and r.rejected == 1 and [p.measurement for p in got] == ["env_twin_field_meta"]


def test_embedded_sink_batch_failure_is_reported_not_raised(fake_influx):
    from aot.twin.sources.embedded import EmbeddedSink
    from aot.twin.types import Point
    import aot.utils.influx as inf

    def boom(pts):
        raise ConnectionError("influx down")
    inf.write_influxdb_points = boom
    try:
        r = EmbeddedSink("x").write([Point("env_twin_field", "p", 0, 1.0, 0.0)])
    finally:
        del inf.write_influxdb_points
    assert r.written == 0 and "influx down" in r.error

# coding=utf-8
"""더미 왕복: 가짜 AoT 서버(진짜 HTTP) ← 원격 통로 → 노드 → 더미 모델 → env_twin* 쓰기 → 소비자가 읽기.

원격 쓰기는 제품에서 비활성이다(AoT 서버 수신 API 폐기, 계획서 §9.19). 계약을 받는 가짜 서버로 직렬화·왕복을
시험할 때만 `remote_write=True` / `write_enabled=True` 로 켠다(설정에는 칸이 없다).
"""
import time

import pytest

from aot.twin import consumer, settings as S
from aot.twin.node import TwinNode
from aot.twin.sources.remote import REMOTE_WRITE_DISABLED, RemoteSink, RemoteSource, RestClient, RestError
from aot.twin.types import Provenance, SeriesRef, Status, TargetKind

from .fakes import FakeAoT
from .helpers import facility_spec, field_spec, seed_facility


def _settings(fake, targets, **kw):
    srv = S.ServerSettings("dev8084", "remote", fake.url, "TWIN_KEY", targets=targets)
    return S.NodeSettings(enabled=True, servers=[srv], **kw)


def _node(fake, targets, **kw):
    return TwinNode(_settings(fake, targets, **kw), env={"TWIN_KEY": fake.api_key}, remote_write=True)


def test_facility_roundtrip_over_http():
    with FakeAoT() as fake:
        seed_facility(fake)
        node = _node(fake, [facility_spec()])
        cap = node.startup_bench()
        assert cap.tier in ("full", "deterministic", "light")
        reps = node.run_once()
        assert len(reps) == 1
        r = reps[0]
        assert r.error is None and r.rejected == 0 and r.status == Status.OK
        assert r.written == r.points > 0
        # 서버 저장소에 env_twin* 이 생겼다 (왕복의 '되돌려 쓰기')
        meas = {k[1] for k in fake.store}
        assert {"env_twin", "env_twin_lead", "env_twin_meta"} <= meas
        assert fake.max_ingest_batch <= 2000
        # 소비자 규칙: 머리말 먼저, 유효할 때만
        src = node.channels["dev8084"][0]
        now = time.time()
        m = consumer.usable_meta(src, TargetKind.FACILITY, "coord-1", now)
        assert m is not None and m.status == Status.OK and m.valid_until > now
        # 만료 후엔 같은 자료가 '없음'이 된다 (원칙 1)
        assert consumer.usable_meta(src, TargetKind.FACILITY, "coord-1", m.valid_until + 1) is None
        # 곡선 값이 센서 근처에서 출발한다
        t0 = m.t0
        first = fake.store[("coord-1", "env_twin", 1)][t0]
        assert abs(first - 22.0) < 0.5


def test_second_run_overwrites_not_duplicates():
    with FakeAoT() as fake:
        seed_facility(fake)
        node = _node(fake, [facility_spec()])
        node.startup_bench()
        node.run_once()
        n1 = {k: len(v) for k, v in fake.store.items() if k[1].startswith("env_twin")}
        node.run_once()
        n2 = {k: len(v) for k, v in fake.store.items() if k[1].startswith("env_twin")}
        assert n1 == n2                                              # 같은 t0 → 같은 점을 덮어쓴다


def test_provenance_label_does_not_hide_the_twin():
    with FakeAoT() as fake:
        seed_facility(fake)
        node = _node(fake, [facility_spec(provenance=Provenance.UNKNOWN)])
        node.startup_bench()
        rep = node.run_once()[0]
        assert rep.status != Status.NOT_TWINNABLE and rep.error is None      # 출처 표시는 판정에 쓰지 않는다


def test_field_roundtrip_mixed_site_one_node():
    with FakeAoT() as fake:
        seed_facility(fake)
        fake.seed_recent("soil-3", "percent", 2, 35.0, n=3, step=600)
        node = _node(fake, [facility_spec(), field_spec()])
        node.startup_bench()
        reps = node.run_once()
        assert {r.target_key[1] for r in reps} == {"facility", "field"}
        assert all(r.error is None and r.rejected == 0 for r in reps)
        assert any(k[1] == "env_twin_field" for k in fake.store)
        assert any(k[1] == "env_twin_field_meta" for k in fake.store)
        src = node.channels["dev8084"][0]
        m = consumer.usable_meta(src, TargetKind.FIELD, "plot-53bdbec9", time.time())
        assert m is not None and m.valid_until - m.t0 == 36 * 3600


def test_server_down_is_skipped_not_fatal():
    fake = FakeAoT()
    with fake:
        url = fake.url
    s = S.ServerSettings("dead", "remote", url, "TWIN_KEY", timeout_s=0.5, targets=[facility_spec("dead")])
    node = TwinNode(S.NodeSettings(enabled=True, servers=[s]), env={"TWIN_KEY": "x"})
    node.startup_bench()
    assert node.run_once() == []                                     # 닿지 않는 서버는 이번 주기 건너뜀


def test_two_servers_one_node_independent():
    with FakeAoT() as a, FakeAoT() as b:
        seed_facility(a)
        seed_facility(b, t_in=18.0)
        sa = S.ServerSettings("A", "remote", a.url, "KA", targets=[facility_spec("A")])
        sb = S.ServerSettings("B", "remote", b.url, "KB", targets=[facility_spec("B")])
        node = TwinNode(S.NodeSettings(enabled=True, servers=[sa, sb]), env={"KA": a.api_key, "KB": b.api_key},
                        remote_write=True)
        node.startup_bench()
        reps = node.run_once()
        assert {r.server_id for r in reps} == {"A", "B"} and all(r.error is None for r in reps)
        ta = a.store[("coord-1", "env_twin", 1)]
        tb = b.store[("coord-1", "env_twin", 1)]
        assert abs(ta[min(ta)] - 22.0) < 0.5 and abs(tb[min(tb)] - 18.0) < 0.5   # 서버별로 자기 자료만 쓴다


def test_remote_write_is_disabled_by_default_and_sends_nothing():
    """제품 기본: 원격 모드로 돌려도 읽고 계산은 하지만 아무것도 보내지 않고 이유를 오류로 적는다."""
    with FakeAoT() as fake:
        seed_facility(fake)
        node = TwinNode(_settings(fake, [facility_spec()]), env={"TWIN_KEY": fake.api_key})
        node.startup_bench()
        rep = node.run_once()[0]
        assert rep.error == REMOTE_WRITE_DISABLED and rep.written == 0 and rep.points > 0
        assert fake.max_ingest_batch == 0                                   # POST 가 한 번도 없었다
        assert not any(k[1].startswith("env_twin") for k in fake.store)
        r = RemoteSink("x", RestClient(fake.url, fake.api_key)).write([])
        assert r.error == REMOTE_WRITE_DISABLED and not r.ok


def test_server_without_ingest_api_reports_error_not_crash():
    with FakeAoT(accept_ingest=False) as fake:
        seed_facility(fake)
        node = _node(fake, [facility_spec()])
        node.startup_bench()
        rep = node.run_once()[0]
        assert rep.error and "404" in rep.error and rep.written == 0


def test_wrong_key_rejected_and_not_retried():
    with FakeAoT() as fake:
        c = RestClient(fake.url, "wrong", retries=3, backoff_s=0.01)
        with pytest.raises(RestError) as e:
            c.get_json("/api/settings/measurements")
        assert e.value.status == 403
        assert len(fake.requests) == 1                               # 4xx 는 재시도하지 않는다
        assert "wrong" not in repr(c)


def test_transient_5xx_is_retried():
    with FakeAoT() as fake:
        fake.fail_next = 2
        c = RestClient(fake.url, fake.api_key, retries=2, backoff_s=0.01)
        assert c.get_json("/api/settings/measurements") == {"measurements": []}


def _meta(dev, t0, status=0, valid_s=7200.0):
    from aot.twin.types import Point
    return [Point("env_twin_meta", dev, 0, t0, float(status)),
            Point("env_twin_meta", dev, 1, t0, t0 + (valid_s if status < 2 else 0.0))]


def test_sink_rejects_non_twin_measurement():
    with FakeAoT() as fake:
        sink = RemoteSink("x", RestClient(fake.url, fake.api_key), write_enabled=True)
        from aot.twin.types import Point
        t0 = float(int(time.time()) // 60 * 60)
        r = sink.write([Point("temperature", "d", 0, t0, 1.0), Point("env_twin", "d", 1, t0 + 600, 2.0)]
                       + _meta("d", t0))
        assert (r.written, r.rejected) == (3, 1) and not r.ok
        assert fake.reasons == {"measurement": 1}


def test_batches_split():
    """조각마다 머리말 요약(pubs)이 실려 서버가 머리말 없는 조각의 곡선도 받는다."""
    with FakeAoT() as fake:
        from aot.twin.types import Point
        t0 = float(int(time.time()) // 60 * 60)
        sink = RemoteSink("x", RestClient(fake.url, fake.api_key), max_batch=100, write_enabled=True)
        r = sink.write([Point("env_twin", "d", 1, t0 + 600.0 * (i % 289), 1.0) for i in range(250)]
                       + _meta("d", t0))
        assert r.written == 252 and r.rejected == 0 and fake.max_ingest_batch == 100


def test_late_publication_is_refused_by_server():
    """유효기한이 이미 지난 발행은 서버가 통째로 거부한다 — 새 곡선을 덮어쓰지 않게(원칙 1)."""
    with FakeAoT() as fake:
        from aot.twin.types import Point
        t0 = float(int(time.time()) // 60 * 60) - 3 * 3600
        sink = RemoteSink("x", RestClient(fake.url, fake.api_key), write_enabled=True)
        r = sink.write([Point("env_twin", "d", 1, t0 + 600, 1.0)] + _meta("d", t0, valid_s=7200.0))
        assert r.written == 0 and r.rejected == 3 and fake.reasons == {"expired": 3}

# coding=utf-8
import json

import pytest

from aot.twin import settings as S

CFG = {"enabled": True, "period_s": 3600, "servers": [{
    "server_id": "dev8084", "mode": "remote", "url": "http://host.docker.internal:8084",
    "api_key_env": "K", "targets": [{
        "kind": "facility", "target_id": "coord-1", "facility": "a3d725da",
        "inputs": {"T_int": {"unique_id": "u", "unit": "C", "channel": 0, "provenance": "measured"}}}]}]}


def test_from_dict_roundtrip(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(CFG))
    ns = S.load(str(p))
    t = ns.servers[0].targets[0]
    assert ns.enabled and t.inputs["T_int"].provenance.value == "measured" and t.server_id == "dev8084"


def test_default_is_off_and_provenance_unknown():
    ns = S.from_dict({"servers": [{"server_id": "a", "targets": [
        {"kind": "field", "target_id": "p", "inputs": {"theta": {"unique_id": "u", "unit": "percent", "channel": 2}}}]}]})
    assert not ns.enabled and ns.servers[0].mode == "off"
    assert ns.servers[0].targets[0].inputs["theta"].provenance.value == "unknown"


@pytest.mark.parametrize("bad", [
    {"servers": [{"server_id": "a", "mode": "remote", "url": "ftp://x", "api_key_env": "K"}]},
    {"servers": [{"server_id": "a", "mode": "remote", "url": "http://x"}]},
    {"servers": [{"server_id": "a", "mode": "weird"}]},
    {"servers": [{"server_id": "a"}, {"server_id": "a"}]},
    {"period_s": 5},
])
def test_validation_rejects(bad):
    with pytest.raises(S.SettingsError):
        S.from_dict(bad)


def test_api_key_comes_from_env_only():
    ns = S.from_dict(CFG)
    s = ns.servers[0]
    assert s.api_key({"K": "secret"}) == "secret"
    with pytest.raises(S.SettingsError):
        s.api_key({})
    assert "secret" not in json.dumps(CFG)


def test_from_misc_semantics():
    class Absent:          # 열이 아직 없는 서버
        pass

    assert not S.from_misc(Absent()).enabled

    class Embedded:
        twin_mode = "embedded"

    ns = S.from_misc(Embedded())
    assert ns.enabled and ns.servers[0].mode == "embedded"

    class Elsewhere:       # 노드는 다른 서버에 있다 → 이 서버 안에서는 아무것도 띄우지 않는다
        twin_mode = "remote"
        twin_node_url = "http://nas:9000"

    assert not S.from_misc(Elsewhere()).enabled


def test_url_env_expansion(monkeypatch):
    monkeypatch.setenv("AOT_TWIN_DEV_URL", "http://10.0.0.5:8084")
    ns = S.from_dict({"servers": [{"server_id": "a", "mode": "remote", "url": "${AOT_TWIN_DEV_URL}", "api_key_env": "K"}]})
    assert ns.servers[0].url == "http://10.0.0.5:8084"
    monkeypatch.delenv("AOT_TWIN_DEV_URL")
    with pytest.raises(S.SettingsError):                               # 치환 안 된 채로는 통과하지 못한다
        S.from_dict({"servers": [{"server_id": "a", "mode": "remote", "url": "${AOT_TWIN_DEV_URL}", "api_key_env": "K"}]})


def test_remote_mode_is_accepted_but_says_remote_write_is_disabled(caplog):
    """원격 방식은 거부하지 않되(배포 제안 §2 '다른 서버 지정' 유지) 결과를 되돌려 쓰지 못한다고 분명히 알린다."""
    import logging
    from aot.twin.sources.remote import REMOTE_WRITE_DISABLED
    with caplog.at_level(logging.WARNING, logger="aot.twin.settings"):
        ns = S.from_dict({"servers": [{"server_id": "a", "mode": "remote", "url": "http://x", "api_key_env": "K"},
                                      {"server_id": "b", "mode": "embedded"}]})
    assert ns.notices() == ["[a] mode 'remote': " + REMOTE_WRITE_DISABLED]
    assert "서버 수신 API 없음 — 원격 쓰기는 비활성" in REMOTE_WRITE_DISABLED
    assert any(REMOTE_WRITE_DISABLED in r.getMessage() for r in caplog.records)
    assert S.from_dict({"servers": [{"server_id": "b", "mode": "embedded"}]}).notices() == []


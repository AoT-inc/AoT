# coding=utf-8
"""Docker 업데이트 가용성 판정 회귀 가드.

배경:
    Docker 배포는 이미지를 pull 해서 올라가는데, 업데이트 가용 여부는 GitHub
    릴리스 태그로 판정하고 있었다. 태그는 push 즉시 생기고 멀티아치 이미지는
    수 분 뒤에 발행되므로, 그 사이 "업데이트 있음"이 뜨지만 pull 은 404 다.
    그래서 Docker 에서는 레지스트리(GHCR) 태그 목록이 정본이다.

    이 테스트가 고정하는 것:
      1. 릴리스 태그만 릴리스로 인정한다 — 'latest'/'26.08'/'sha-*' 같은
         움직이는 태그를 릴리스로 세면, 가리키는 대상이 조용히 바뀌는 값을
         버전 비교에 넣게 된다.
      2. 정렬은 숫자 비교다 — 문자열 정렬은 26.08.10 < 26.08.9 로 뒤집는다.
      3. 레지스트리 조회 실패는 fail-closed 다 — 못 읽었을 때 "업데이트 있음"이
         뜨면 사용자는 존재하지 않는 이미지를 받으러 간다.
      4. Docker 여부에 따라 조회 소스가 실제로 갈린다.

    네트워크를 타지 않는다(모든 레지스트리 접근을 대체한다).
"""
import sys
import types

import pytest

from aot.utils import registry_release_info as rri
from aot.utils.registry_release_info import RegistryRelease, _sort_reverse


class _FakeRegistry(RegistryRelease):
    """토큰/태그 조회만 대체한 RegistryRelease."""

    def __init__(self, tags, token='fake-token'):
        self._tags = tags
        self._token = token
        super().__init__()

    def _get_token(self):
        return self._token

    def _get_json(self, url, token):
        return {'tags': list(self._tags)}, None


def test_sort_is_numeric_not_lexical():
    """26.08.10 이 26.08.9 보다 크다고 판정해야 한다."""
    assert _sort_reverse(['26.08.9', '26.08.10', '26.08.2'])[0] == '26.08.10'


def test_moving_tags_are_not_releases():
    """latest / YY.MM / sha-* 는 릴리스가 아니다."""
    registry = _FakeRegistry(
        ['latest', '26.08', 'sha-a1b2c3d', '26.08.2', '26.09.0'])
    assert registry.releases() == ['26.09.0', '26.08.2']
    assert registry.latest_release() == '26.09.0'


def test_upgrade_detected_only_when_image_published(monkeypatch):
    """설치 버전보다 높은 '릴리스 태그'가 레지스트리에 있을 때만 업그레이드다."""
    monkeypatch.setattr(rri, 'AOT_VERSION', '26.08.2')

    # 이미지가 아직 안 올라온 상태: 움직이는 태그만 있다
    exists, _, _, latest, _ = _FakeRegistry(['latest', '26.08']).upgrade_exists()
    assert exists is False
    assert latest is None

    # 이미지 발행 후
    exists, _, _, latest, _ = _FakeRegistry(['latest', '26.08.2', '26.09.0']).upgrade_exists()
    assert exists is True
    assert latest == '26.09.0'

    # 같은 버전만 있으면 업그레이드 아님
    exists, _, _, _, _ = _FakeRegistry(['26.08.2']).upgrade_exists()
    assert exists is False


def test_registry_failure_fails_closed():
    """조회에 실패하면 '업데이트 있음'이 아니라 오류를 낸다."""
    registry = _FakeRegistry([], token=None)  # 토큰 획득 실패
    exists, _, _, _, errors = registry.upgrade_exists()
    assert exists is False
    assert errors, "실패를 조용히 넘기면 안 된다"


def test_empty_tag_list_reports_an_error():
    """태그가 하나도 없으면(비공개 패키지 등) 정상이 아니라 오류다."""
    exists, _, _, _, errors = _FakeRegistry([]).upgrade_exists()
    assert exists is False
    assert errors


def _reload_update_availability(monkeypatch, docker):
    """DOCKER_CONTAINER 값을 바꿔 모듈을 다시 읽어들인다."""
    import importlib

    from aot import config
    monkeypatch.setattr(config, 'DOCKER_CONTAINER', docker)
    module = importlib.import_module('aot.utils.update_availability')
    importlib.reload(module)
    return module


def test_source_follows_deployment_type(monkeypatch):
    """Docker 면 레지스트리, 아니면 GitHub 태그를 본다."""
    called = []

    fake_registry_mod = types.ModuleType('aot.utils.registry_release_info')
    fake_registry_mod.RegistryRelease = lambda: types.SimpleNamespace(
        upgrade_exists=lambda: (called.append('registry') or
                                (False, [], [], None, [])))
    fake_github_mod = types.ModuleType('aot.utils.github_release_info')
    fake_github_mod.AoTRelease = lambda: types.SimpleNamespace(
        github_upgrade_exists=lambda: (called.append('github') or
                                       (False, [], [], None, [])))

    monkeypatch.setitem(sys.modules, 'aot.utils.registry_release_info',
                        fake_registry_mod)
    monkeypatch.setitem(sys.modules, 'aot.utils.github_release_info',
                        fake_github_mod)

    module = _reload_update_availability(monkeypatch, docker=True)
    module.check_upgrade_exists()
    assert called == ['registry']

    called.clear()
    module = _reload_update_availability(monkeypatch, docker=False)
    module.check_upgrade_exists()
    assert called == ['github']

    # 다른 테스트가 오염된 상태를 물려받지 않도록 원상 복구
    _reload_update_availability(monkeypatch, docker=False)


def test_stale_heartbeat_means_no_updater(monkeypatch, tmp_path):
    """하트비트가 낡았으면 업데이터가 '있다'고 하면 안 된다 —
    아무도 읽지 않는 요청 파일을 쓰는 버튼이 생긴다."""
    import importlib
    import json
    import time

    from aot import config
    heartbeat = tmp_path / 'heartbeat.json'
    monkeypatch.setattr(config, 'DOCKER_CONTAINER', True)
    monkeypatch.setattr(config, 'DOCKER_UPDATE_HEARTBEAT_FILE', str(heartbeat))
    module = importlib.reload(
        importlib.import_module('aot.utils.update_availability'))

    heartbeat.write_text(json.dumps({'timestamp': time.time() - 10}))
    assert module.updater_status()['present'] is True

    heartbeat.write_text(json.dumps({'timestamp': time.time() - 10000}))
    assert module.updater_status()['present'] is False

    heartbeat.write_text(json.dumps({'state': 'idle'}))  # 날짜 없는 하트비트
    assert module.updater_status()['present'] is False

    monkeypatch.setattr(config, 'DOCKER_CONTAINER', False)
    importlib.reload(module)


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))

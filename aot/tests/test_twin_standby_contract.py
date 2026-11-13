# -*- coding: utf-8 -*-
"""디지털트윈 서버는 기본 구성에 항상 들어 있고 대기한다 — 배포 파일 계약.

일반 사용자는 설정 > 일반 토글만 볼 수 있어 서버를 따로 띄울 방법이 없다(앱에 Docker 소켓을 주지 않는다).
그래서 (1) 배포 compose 에 profile 없이 들어가고, (2) 직접 설치는 설치·업그레이드마다 설치하고, (3) 업데이터가
함께 재생성하고, (4) 잠긴 기기는 되살아나 판정을 반복하지 않아야 한다 — 직접 설치는 exit 0(systemd
`Restart=on-failure`), Docker 는 `sleep infinity`(compose 는 `unless-stopped`: docker 의 `on-failure` 는
데몬이 재시작하면 컨테이너를 다시 띄우지 않아 정전·재부팅 뒤 돌아오지 못한다).
"""
import os
import re

import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding='utf-8') as f:
        return f.read()


def _compose(name):
    return yaml.safe_load(_read('docker', name))['services']


def test_prod_compose_has_the_twin_without_a_profile_and_survives_a_daemon_restart():
    twin = _compose('docker-compose.prod.yml')['aot_twin']
    assert 'profiles' not in twin
    # on-failure 는 "데몬이 재시작하면 컨테이너를 다시 띄우지 않는다"(Docker 문서) — 재부팅 뒤 트윈이 안 돌아온다
    assert twin['restart'] == 'unless-stopped'
    # 대신 잠긴 컨테이너는 종료하지 않고 sleep infinity 로 바뀐다
    assert 'park_if_locked' in _read('aot', 'twin', '__main__.py')
    assert 'sleep", ["sleep", "infinity"]' in _read('aot', 'twin', '__main__.py')
    assert twin['command'] == 'python -m aot.twin'
    # 이미지는 aot_daemon 과 같고 호스트 소스를 덮지 않는다
    assert twin['image'] == _compose('docker-compose.prod.yml')['aot_daemon']['image']
    assert not any(str(v).startswith('../') for v in twin.get('volumes', []))


def test_dev_and_nas_compose_keep_their_profile():
    """사본 스택 메모리를 늘리지 않으려 개발용·NAS 노드 compose 는 그대로 둔다."""
    assert _compose('docker-compose.yml')['aot_twin']['profiles'] == ['twin']
    assert _compose('docker-compose.twin-nas.yml')['aot_twin']['profiles'] == ['twin']


def test_updater_recreates_the_twin_and_rollback_shares_the_variable():
    script = _read('docker', 'updater', 'aot_docker_update.sh')
    m = re.search(r'^SERVICES="\$\{AOT_UPDATE_SERVICES:-([^}]*)\}"', script, re.M)
    assert m and set(m.group(1).split()) == {'aot-app', 'aot_daemon', 'aot_mcp', 'aot_twin'}
    # 재생성과 롤백이 같은 recreate() 를 부른다 → 같은 $SERVICES
    assert script.count('compose up -d $SERVICES') == 1
    rollback = script[script.index('rollback() {'):]
    assert 'recreate ||' in rollback.split('\n}\n')[0]


def test_native_install_installs_the_twin_on_every_upgrade_and_at_setup():
    post = _read('aot', 'scripts', 'upgrade_post.sh')
    assert re.search(r'^\$\{INSTALL_CMD\} install-aottwin$', post, re.M)
    assert 'restart-aottwin' not in post
    for setup in ('setup.sh', 'setup_unattended.sh'):
        text = _read('install', setup)
        assert 'install-aottwin' in text and text.index('install-aotmcp') < text.index('install-aottwin'), setup
    cmds = _read('aot', 'scripts', 'upgrade_commands.sh')
    assert "'install-aottwin')" in cmds


def test_systemd_unit_does_not_restart_a_clean_exit_and_is_no_longer_optional():
    unit = _read('install', 'aottwin.service')
    assert re.search(r'^Restart=on-failure$', unit, re.M)
    assert '설치하지 말 것' not in unit and '기본 비활성' not in unit


def test_env_example_no_longer_asks_for_a_compose_profile():
    env = _read('docker', '.env.prod.example')
    assert 'COMPOSE_PROFILES=twin' not in env

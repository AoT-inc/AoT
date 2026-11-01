# coding=utf-8
"""네이티브(systemd) 설치용 Matter 서버 파일이 Docker 설치와 어긋나지 않게 지킨다.

docker/docker-compose.matter-native.yml 은 docker-compose.prod.yml 의 matter_server
를 그대로 옮긴 것이고, 다른 점은 소켓 중계가 없다는 것뿐이다(네이티브 AoT 는 호스트
루프백에 바로 닿는다). 한쪽만 고치면(이미지 태그, VENDOR_ID, 로그 수준…) 같은 Fabric
설정이 설치 방식에 따라 달라진다. install/aot-matter.conf 의 주소는 그 서버의 포트와
경로(/ws, 2026-10-10 실측)를 가리켜야 한다.
"""
import os
import re

import yaml

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')


def _compose(name):
    with open(os.path.join(_ROOT, 'docker', name)) as fh:
        return yaml.safe_load(fh)


def _env(service):
    return dict(item.split('=', 1) for item in service['environment'])


def test_native_server_matches_the_docker_one():
    prod = _compose('docker-compose.prod.yml')['services']['matter_server']
    native = _compose('docker-compose.matter-native.yml')['services']['matter_server']
    assert native['image'] == prod['image']
    assert native['network_mode'] == prod['network_mode'] == 'host'
    assert native['restart'] == prod['restart']
    assert _env(native) == _env(prod)
    # 네이티브는 이 파일을 쓰는 것 자체가 "켠다" 이므로 profile 이 없다.
    assert 'profiles' not in native


def test_native_server_stays_on_loopback():
    env = _env(_compose('docker-compose.matter-native.yml')['services']['matter_server'])
    assert env['LISTEN_ADDRESS'] == '127.0.0.1'   # API 에 인증이 없다


def test_native_has_no_socket_relay():
    assert set(_compose('docker-compose.matter-native.yml')['services']) == {'matter_server'}


def test_dropin_points_at_the_server():
    env = _env(_compose('docker-compose.matter-native.yml')['services']['matter_server'])
    with open(os.path.join(_ROOT, 'install', 'aot-matter.conf')) as fh:
        text = fh.read()
    assert '[Service]' in text
    match = re.search(r'^Environment=AOT_MATTER_URL=(\S+)$', text, re.M)
    assert match, 'AOT_MATTER_URL line missing'
    assert match.group(1) == 'ws://127.0.0.1:{}/ws'.format(env['PORT'])


def test_ble_override_layers_on_the_native_file():
    ble = _compose('docker-compose.matter-ble.yml')['services']
    assert set(ble) == {'matter_server'}     # 같은 서비스 이름이어야 겹쳐진다

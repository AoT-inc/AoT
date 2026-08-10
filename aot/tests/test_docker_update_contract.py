# coding=utf-8
"""앱↔업데이터 계약 회귀 가드.

앱(`aot/utils/docker_update.py`)과 업데이터 셸 스크립트
(`docker/updater/aot_docker_update.sh`)는 공유 볼륨의 파일로만 통신한다.
두 구현이 서로를 import 하지 않으므로, 한쪽이 상태 이름이나 경로나 태그
규칙을 바꿔도 **아무 에러 없이** 통신이 끊긴다 — 버튼은 요청을 쓰고
업데이터는 영원히 안 읽는다. 그 드리프트를 여기서 잡는다.

핵심 가치는 **태그 검증**이다. 요청 파일은 데이터지 명령이 아니어야 한다:
버전 번호 하나만 담고 이미지·레지스트리·셸 명령을 담을 수 없어야, 볼륨에
쓸 수 있는 누군가가 "아무 이미지나 이 호스트에서 실행"으로 승격하지 못한다.
그래서 검증은 앱과 업데이터 양쪽에 있고, 둘 다 여기서 확인한다.

네트워크도 Docker 도 쓰지 않는다.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "docker" / "updater" / "aot_docker_update.sh"
COMPOSE_PROD = REPO / "docker" / "docker-compose.prod.yml"
COMPOSE_UPDATER = REPO / "docker" / "docker-compose.updater.yml"

# 앱이 거부해야 하는 것들. 각각이 막는 사고가 다르다.
BAD_TARGETS = [
    "latest",              # 움직이는 태그 — 무엇이 설치될지 알 수 없다
    "26.08",               # 같은 이유
    "sha-a1b2c3d",
    "26.08.2; rm -rf /",   # 명령 주입
    "../../etc/passwd",    # 경로 탈출
    "evil.io/x/y:1.0.0",   # 타 레지스트리
    "sha256:deadbeef",
    "",
    "26.8.2",              # 0 패딩 없는 YY.MM (발행 태그 형식이 아니다)
]

GOOD_TARGETS = ["26.08.2", "26.09.0", "27.01.15"]


def test_app_rejects_everything_but_a_release_version():
    from aot.utils.docker_update import valid_target

    for target in GOOD_TARGETS:
        assert valid_target(target), target
    for target in BAD_TARGETS:
        assert not valid_target(target), f"허용되면 안 되는 값: {target!r}"


def _script_tag_regex():
    """업데이터 스크립트의 valid_target() 정규식을 뽑아낸다."""
    text = SCRIPT.read_text()
    match = re.search(r"valid_target\(\)\s*\{\s*\n\s*echo .*grep -Eq '([^']+)'",
                      text)
    assert match, "업데이터의 valid_target() 정규식을 찾지 못했다"
    return match.group(1)


def test_updater_applies_the_same_tag_rule():
    """같은 규칙이 업데이터에도 있어야 한다 — 앱만 막으면, 요청 파일에 직접
    쓰는 경로가 검증 없는 뒷문이 된다."""
    pattern = _script_tag_regex()
    compiled = re.compile(pattern)
    for target in GOOD_TARGETS:
        assert compiled.match(target), f"{pattern} 가 {target} 를 거부한다"
    for target in BAD_TARGETS:
        assert not compiled.match(target), f"{pattern} 가 {target} 를 통과시킨다"


def test_image_repository_never_comes_from_the_request():
    """레포지토리는 기본값이 AoT 로 못박혀 있고, 운영자 환경변수로만 바뀐다.
    요청 파일이 건드릴 수 있으면 볼륨 쓰기 권한이 '이 호스트에서 아무 이미지나
    실행'으로 승격된다."""
    text = SCRIPT.read_text()
    assert 'IMAGE_REPO="${AOT_IMAGE_REPO:-ghcr.io/aot-inc/aot}"' in text
    # 요청 파일에서 읽는 키는 id/target/requested_by 뿐이어야 한다.
    keys = set(re.findall(r'json_value "\$_body" (\w+)', text))
    assert keys <= {'id', 'target', 'requested_by'}, f"요청에서 읽는 키: {keys}"
    # 앱이 쓰는 요청에도 이미지/레지스트리 필드가 없어야 한다.
    from aot.utils import docker_update as du
    source = (REPO / 'aot' / 'utils' / 'docker_update.py').read_text()
    assert 'image' not in re.findall(r"'(\w+)':", source)
    assert du.TARGET_VERSION_RE.pattern == r'^\d{2}\.\d{2}\.\d+$'


def test_state_names_match_on_both_sides():
    """상태 이름이 어긋나면 진행 표시가 조용히 멈춘다."""
    from aot.utils import docker_update as du

    text = SCRIPT.read_text()
    script_states = set(re.findall(r'status "([a-z_]+)"', text))
    app_states = set(du.RUNNING_STATES) | set(du.TERMINAL_STATES)
    unknown = script_states - app_states
    assert not unknown, f"앱이 모르는 상태를 업데이터가 쓴다: {unknown}"
    # 종료 상태 3종은 반드시 업데이터가 실제로 쓴다(UI 가 이걸로 결과를 낸다)
    assert set(du.TERMINAL_STATES) <= script_states


def test_shared_paths_match_on_both_sides():
    """앱은 /app/aot_local/update, 업데이터는 /state/update 로 같은 곳을 본다.
    파일 이름이 어긋나면 요청이 영원히 안 읽힌다."""
    from aot.config import (DOCKER_UPDATE_HEARTBEAT_FILE,
                            DOCKER_UPDATE_LOG_FILE, DOCKER_UPDATE_REQUEST_FILE,
                            DOCKER_UPDATE_STATUS_FILE)

    text = SCRIPT.read_text()
    for app_path, script_suffix in (
            (DOCKER_UPDATE_REQUEST_FILE, 'request.json'),
            (DOCKER_UPDATE_STATUS_FILE, 'status.json'),
            (DOCKER_UPDATE_HEARTBEAT_FILE, 'heartbeat.json'),
            (DOCKER_UPDATE_LOG_FILE, 'update.log')):
        assert app_path.endswith(script_suffix), app_path
        assert f'"$STATE_DIR/{script_suffix}"' in text, script_suffix

    # 업데이터가 마운트하는 지점과 앱의 볼륨 경로가 같은 디렉터리를 가리키는지
    updater_yml = COMPOSE_UPDATER.read_text()
    assert 'aot_data:/state' in updater_yml
    assert 'AOT_UPDATE_DIR=/state/update' in updater_yml


def test_updater_is_not_in_the_base_compose_file():
    """업데이터가 기본 compose 에 있으면 업데이트 도중 자기 자신을 재생성하고
    업데이트가 반토막 난다."""
    assert 'aot_updater' not in COMPOSE_PROD.read_text()
    assert 'aot_updater' in COMPOSE_UPDATER.read_text()


def test_updater_recreates_with_the_base_file_only():
    """자기 자신을 교체 대상에서 빼는 유일한 장치다."""
    text = SCRIPT.read_text()
    assert 'AOT_COMPOSE_FILE:-docker/docker-compose.prod.yml' in text
    # 주석은 뺀다 — 헤더가 오버레이를 설명하는 것은 정상이다. 문제는 실행되는
    # 코드가 오버레이를 compose 인자로 넘기는 것이다.
    code = '\n'.join(line for line in text.splitlines()
                     if not line.lstrip().startswith('#'))
    assert 'docker-compose.updater.yml' not in code


def test_health_key_lives_in_the_base_compose_file():
    """오버레이에만 두면, 업데이터가 기본 파일로 aot-app 을 재생성하는 순간
    사라진다 — 헬스 게이트가 필요한 바로 그 순간에."""
    assert 'AOT_HEALTH_KEY=${AOT_HEALTH_KEY:-}' in COMPOSE_PROD.read_text()


def test_request_write_is_atomic_and_readable(tmp_path, monkeypatch):
    """요청은 rename 으로 게시된다 — 업데이터가 반쯤 쓰인 버전 문자열을 읽고
    행동하면 안 된다."""
    import importlib

    from aot import config
    update_dir = tmp_path / 'update'
    monkeypatch.setattr(config, 'DOCKER_UPDATE_PATH', str(update_dir))
    monkeypatch.setattr(config, 'DOCKER_UPDATE_REQUEST_FILE',
                        str(update_dir / 'request.json'))
    monkeypatch.setattr(config, 'DOCKER_UPDATE_STATUS_FILE',
                        str(update_dir / 'status.json'))
    monkeypatch.setattr(config, 'DOCKER_UPDATE_HEARTBEAT_FILE',
                        str(update_dir / 'heartbeat.json'))
    monkeypatch.setattr(config, 'DOCKER_UPDATE_LOG_FILE',
                        str(update_dir / 'update.log'))
    du = importlib.reload(importlib.import_module('aot.utils.docker_update'))

    ok, request_id = du.request_update('26.09.0', requested_by='tester')
    assert ok, request_id

    written = json.loads((update_dir / 'request.json').read_text())
    assert written['target'] == '26.09.0'
    assert written['id'] == request_id
    assert written['requested_by'] == 'tester'
    assert not (update_dir / 'request.json.partial').exists()

    # 처리 전에는 진행 중으로 보인다 (버튼이 두 번 눌리면 안 된다)
    assert du.update_in_progress() is True
    ok, message = du.request_update('26.09.1')
    assert not ok and 'in progress' in message

    # 업데이터가 같은 id 로 종료 상태를 쓰면 진행 중이 아니다
    (update_dir / 'status.json').write_text(json.dumps({
        'id': request_id, 'state': 'done', 'updated_at': time.time()}))
    assert du.update_in_progress() is False

    # 잘못된 타깃은 파일을 만들지 않는다
    (update_dir / 'request.json').unlink()
    ok, message = du.request_update('latest')
    assert not ok
    assert not (update_dir / 'request.json').exists()

    importlib.reload(du)


def test_script_passes_shell_syntax_check():
    result = subprocess.run(['sh', '-n', str(SCRIPT)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))

# coding=utf-8
"""oneshot(`--update`)이 request.json 을 정리하는 조건 — 회귀 가드.

`docker/updater/aot_docker_update.sh`의 oneshot 분기는 남아 있는
request.json 을 지우고 시작한다(2026-09-16 koat 사고: 지워지지 않은
request.json 이 status.json 의 id 드리프트 때문에 "새 요청"으로 재생됨).

그런데 그 정리가 "이미 처리된 게 확실할 때"만 지워야지, 무조건 지우면 앱이
방금 써 둔, 아직 loop 가 못 집어간 **살아있는 요청**을 조용히 버릴 수 있다
(loop 는 POLL_INTERVAL 초 동안 락을 놓고 있어 그 사이 오퍼레이터가 --update
를 수동 실행할 여지가 있다). 이 파일은 그 구분이 실제로 지켜지는지를
스크립트를 직접 실행해 확인한다.

`docker`는 진짜로 뜨지 않는다 — PATH 에 `info` 서브커맨드만 받는 가짜
바이너리를 심어 `docker info` 체크만 통과시키고, 그 뒤로는 일부러 잘못된
버전 문자열을 줘서 `run_update`가 실제 docker 호출 전에 스스로 거부하게
한다. 정리 로직 자체는 그 이전에 끝나므로 이걸로 충분하다.
"""
import json
import os
import stat
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "docker" / "updater" / "aot_docker_update.sh"


def _run_oneshot(tmp_path):
    project_dir = tmp_path / 'project'
    project_dir.mkdir()
    (project_dir / 'compose.yml').write_text('services: {}\n')

    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    docker_stub = fake_bin / 'docker'
    docker_stub.write_text(
        '#!/bin/sh\n'
        'if [ "$1" = "info" ]; then exit 0; fi\n'
        'exit 1\n')
    docker_stub.chmod(docker_stub.stat().st_mode | stat.S_IEXEC)

    env = dict(os.environ)
    env['PATH'] = f"{fake_bin}:{env.get('PATH', '')}"

    result = subprocess.run(
        ['sh', str(SCRIPT), '--update', 'not-a-real-version',
         '--project-dir', str(project_dir),
         '--compose-file', 'compose.yml',
         '--state-dir', str(tmp_path / 'state')],
        env=env, capture_output=True, text=True, timeout=30)
    return result


def test_already_handled_request_is_cleared_before_oneshot(tmp_path):
    """request.json 의 id 가 status.json 의 마지막 id 와 같으면 — 이미
    처리됐다고 확실히 말할 수 있으니 — 정리해도 된다."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (state_dir / 'request.json').write_text(json.dumps({'id': 'req-1', 'target': '26.09.0'}))
    (state_dir / 'status.json').write_text(json.dumps({'id': 'req-1', 'state': 'done'}))

    _run_oneshot(tmp_path)

    assert not (state_dir / 'request.json').exists(), (
        '이미 처리된 것으로 확인되는 request.json 은 정리돼야 한다')


def test_unconfirmed_request_survives_oneshot(tmp_path):
    """id 가 status.json 과 다르면(또는 status.json 이 아직 없으면) 아직
    처리되지 않은 살아있는 요청일 수 있다 — 지우면 안 된다.

    2026-09-16 사고의 정확한 반대 실패 모드: 그때는 "지우지 않아서" 재생이
    났는데, 이번엔 "무조건 지워서" 아직 안 처리된 진짜 요청을 잃을 수 있다.
    """
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (state_dir / 'request.json').write_text(json.dumps({'id': 'req-fresh', 'target': '26.09.0'}))
    (state_dir / 'status.json').write_text(json.dumps({'id': 'cli-1', 'state': 'done'}))

    _run_oneshot(tmp_path)

    assert (state_dir / 'request.json').exists(), (
        '아직 확인되지 않은 request.json 을 oneshot 이 조용히 지웠다')


def test_request_with_no_status_yet_survives_oneshot(tmp_path):
    """status.json 이 아예 없으면 "이미 처리됨"을 확인할 방법이 없다 —
    처리되지 않은 것으로 보고 남겨 둬야 한다."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (state_dir / 'request.json').write_text(json.dumps({'id': 'req-1', 'target': '26.09.0'}))

    _run_oneshot(tmp_path)

    assert (state_dir / 'request.json').exists()

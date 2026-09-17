# coding=utf-8
"""라우트 목록을 한 번만 덤프해 캐시한다.

`dump_routes` 는 컨테이너 안에서 `create_app()` 을 도므로 20초쯤 걸린다.
L0 와 L1 이 각각 부르면 그만큼 두 번 기다린다. 수집 시점에 필요한 쪽(L1 은
페이지마다 테스트를 하나씩 만든다)도 있어 파일 캐시로 공유한다.
"""
import json
import os
import subprocess
import tempfile
import time

COMPOSE_FILE = os.environ.get(
    'AOT_E2E_COMPOSE', 'docker/docker-compose.e2e.yml')
CACHE_PATH = os.path.join(tempfile.gettempdir(), 'aot_e2e_routes.json')
CACHE_TTL_S = 300


def _dump():
    target = '/app/aot_local/e2e_routes.json'
    subprocess.run(
        ['docker', 'compose', '-f', COMPOSE_FILE, 'exec', '-T', 'aot-app',
         'python', '-m', 'aot.tests.e2e.dump_routes', target],
        check=True, capture_output=True, timeout=300)
    out = subprocess.run(
        ['docker', 'compose', '-f', COMPOSE_FILE, 'exec', '-T', 'aot-app',
         'cat', target],
        check=True, capture_output=True, timeout=60)
    return json.loads(out.stdout)


def get_routes(force=False):
    """라우트 목록. 실패하면 빈 목록을 돌려준다(호출 쪽에서 skip 판단)."""
    if not force and os.path.exists(CACHE_PATH):
        if time.time() - os.path.getmtime(CACHE_PATH) < CACHE_TTL_S:
            try:
                with open(CACHE_PATH) as f:
                    return json.load(f)
            except (ValueError, OSError):
                pass
    try:
        routes = _dump()
    except Exception:                        # noqa: BLE001
        return []
    try:
        with open(CACHE_PATH, 'w') as f:
            json.dump(routes, f)
    except OSError:
        pass
    return routes

# coding=utf-8
"""Docker 이미지 크기 회귀 가드.

2026-08-11 실측: build-essential + libpq-dev 를 최종 이미지에서 빼는
멀티스테이지 전환으로 2.11GB -> 1.68GB(디스크), 507MB -> 405MB(레지스트리
압축 크기, 즉 실제 pull 용량). 둘 다 requirements.txt 의 어떤 패키지도
컴파일을 요구하지 않아(전부 wheel 로 해결) 제거해도 안전함을 실측으로
확인했다 — 다만 build-essential 은 안전망으로 builder 스테이지에는 남겨
멀티아치(QEMU arm64) CI 빌드가 wheel 없는 패키지를 만나도 실패하지
않게 한다.

on-demand 하드웨어 드라이버 설치 경로(routes_admin.install_dependencies ->
aot_wrapper -> /app/env venv)는 Docker 에서 실제로 동작하지만, 그 경로가
설치하는 드라이버(RPi.GPIO/pigpio/bluepy/wiringpi 등)는 전부 GPIO/I2C/SPI/
BLE 접근이 필요한데 docker-compose.yml/docker-compose.prod.yml 어디에도
`privileged:`/`devices:` 가 없다 — 하드웨어에 닿을 수 없으니 컴파일 성공
여부와 무관하게 이미 못 쓰는 경로였다. 이 검사는 그 경계가 다시 흐려지는지
(예: 최종 스테이지에 build-essential 이 도로 들어가는지)만 본다.

이미지를 빌드하진 않는다(수 분 소요) — Dockerfile 구조만 정적으로 본다.
실제 크기 재검증은 `docker build -f docker/Dockerfile . && docker images`
로 사람이 수동으로.
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "docker" / "Dockerfile"
DOCKERIGNORE = REPO / ".dockerignore"


def _stages():
    """[(stage_text, is_final)] -- FROM 절 기준으로 자른다."""
    text = DOCKERFILE.read_text()
    parts = re.split(r'(?m)^FROM\s', text)
    # parts[0]은 첫 FROM 이전(보통 비어있거나 주석)
    stages = [p for p in parts[1:]]
    return stages


def test_dockerfile_is_multi_stage():
    stages = _stages()
    assert len(stages) >= 2, (
        "단일 스테이지로 되돌아갔다 -- build-essential 제거의 전제가 "
        "멀티스테이지다. 되돌리려면 이 테스트와 함께 의도적으로 되돌릴 것.")


def test_build_essential_and_libpq_dev_absent_from_final_stage():
    """최종(마지막) 스테이지에만 이 두 패키지가 없는지 본다 -- builder
    스테이지에는 안전망으로 build-essential 이 남아있어도 된다."""
    stages = _stages()
    final_stage = stages[-1]
    assert 'build-essential' not in final_stage, (
        "build-essential 이 최종 이미지에 다시 들어갔다. 2026-08-11 실측상 "
        "필요 없다(모든 의존성이 wheel 로 해결됨) -- 정말 필요해졌다면 "
        "이 테스트를 갱신하고 그 근거(어떤 패키지가 컴파일을 요구하는지)를 "
        "주석에 남길 것.")
    assert 'libpq-dev' not in final_stage, (
        "libpq-dev 는 requirements.txt 어디에도 postgres 드라이버가 없어 "
        "죽은 의존성이었다(2026-08-11 확인). 다시 필요해졌다면 무엇이 "
        "요구하는지 주석에 남길 것.")


def test_nodejs_stays_in_final_stage():
    """node 는 빌드 도구가 아니라 런타임 의존성이다
    (aot/ai/agents/mcp_*.py 가 npx 로 MCP 서버를 실제로 띄운다) --
    최적화하다 실수로 같이 빠지면 안 된다."""
    stages = _stages()
    final_stage = stages[-1]
    assert 'nodejs' in final_stage


def test_docs_not_shipped_to_image():
    """docs/ 는 CLAUDE.md 의 배포 대상 목록에 없었고, manual_url() 이
    항상 외부 github.io 링크를 내보내 이미지 안의 로컬 docs/ 는 읽힌 적이
    없다(2026-08-11 확인, 7.8MB). .dockerignore 화이트리스트에 다시
    들어가면 이 검사가 잡는다."""
    text = DOCKERIGNORE.read_text()
    allow_lines = [l.strip() for l in text.splitlines()
                  if l.strip().startswith('!')]
    assert '!docs/' not in allow_lines


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))

# coding=utf-8
"""E2E(종단) 테스트 — 브라우저로 실제 화면을 열어 판정한다.

이 디렉터리는 기본 pytest 수집에서 **빠진다**. `conftest.py` 가 환경변수
`AOT_E2E_BASE_URL` 이 없으면 수집 자체를 건너뛰므로, `pytest aot/tests` 는
지금까지와 똑같이 6초에 수집되고 브라우저를 켜지 않는다.

실행:
    docker compose -f docker/docker-compose.e2e.yml up -d
    docker compose -f docker/docker-compose.e2e.yml exec -T aot-app \
        python -m aot.tests.e2e.seed
    AOT_E2E_BASE_URL=http://127.0.0.1:8085 python3 -m pytest aot/tests/e2e -q
"""

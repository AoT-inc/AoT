#!/usr/bin/env bash
# E2E 를 한 번에 돌린다 — 스택 기동 → 시드 → L0 → L1.
#
#   aot/scripts/run_e2e.sh              # 전부
#   aot/scripts/run_e2e.sh l0           # 라우트 스모크만 (~15초)
#   aot/scripts/run_e2e.sh l1           # 페이지 부팅 검사만 (~2분 30초)
#   aot/scripts/run_e2e.sh l1 /geo/design   # 페이지 하나만
#   AOT_E2E_HEADED=1 aot/scripts/run_e2e.sh l1 /dashboard   # 브라우저를 보면서
#
# 개발 스택(8084)은 건드리지 않는다. 이 스크립트가 쓰는 것은 8085 의 별도
# 스택과 별도 볼륨뿐이다.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

COMPOSE="docker compose -f docker/docker-compose.e2e.yml"
BASE_URL="${AOT_E2E_BASE_URL:-http://127.0.0.1:8085}"
WHAT="${1:-all}"
ONLY="${2:-}"

echo "== E2E 스택 기동 =="
$COMPOSE up -d

echo "== 앱 대기 =="
for i in $(seq 1 60); do
    if curl -sf -o /dev/null "$BASE_URL/"; then
        echo "   응답 확인 (${i}회차)"
        break
    fi
    if [ "$i" = "60" ]; then
        echo "   앱이 5분 안에 뜨지 않았습니다"
        $COMPOSE logs --tail 80
        exit 1
    fi
    sleep 5
done

echo "== 픽스처 시드 =="
$COMPOSE exec -T aot-app python -m aot.tests.e2e.seed

export AOT_E2E_BASE_URL="$BASE_URL"

run_l0() {
    echo "== L0 라우트 스모크 =="
    python3 -m pytest aot/tests/e2e/test_route_smoke.py -q -p no:cacheprovider
}

run_l1() {
    echo "== L1 페이지 부팅 검사 =="
    if [ -n "$ONLY" ]; then
        python3 -m pytest "aot/tests/e2e/test_page_boot.py::test_page_boots[$ONLY]" \
            -q -p no:cacheprovider
    else
        python3 -m pytest aot/tests/e2e/test_page_boot.py -q -p no:cacheprovider
    fi
}

case "$WHAT" in
    l0) run_l0 ;;
    l1) run_l1 ;;
    all) run_l0; run_l1 ;;
    *) echo "사용법: $0 [all|l0|l1] [경로]"; exit 2 ;;
esac

echo
echo "실패한 화면의 스크린샷은 .local/e2e-artifacts/ 에 있습니다."
echo "스택을 내리려면: $COMPOSE down -v   (-v 를 빼면 DB 가 남아 다음 실행이 빠릅니다)"
